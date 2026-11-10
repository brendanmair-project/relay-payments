"""REL-35 (api-contract.md): `GET /incidents/{id}` lists affected payments and events; `GET` and `POST regenerate` on
`/incidents/{id}/summary` keep stored summaries; the model sees no description and no database transaction is open
during its call."""

import json
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.incidents.consumer import IncidentConsumer
from tests.explain.fakes import FakeModel
from tests.incidents.helpers import SENTINEL, rescue, routed_entry, seed_failure, the_incident

Factory = sessionmaker[Session]
SUMMARY_FIELDS = {
    "incident_id",
    "source",
    "model",
    "text",
    "cited_event_ids",
    "cause",
    "trigger",
    "generated_at",
    "fallback_reason",
}


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def use(client: TestClient, model: Any) -> Any:
    client.app.state.model_client = model  # type: ignore[attr-defined]
    return model


def open_incident(factory: Factory, redis_client: Redis) -> tuple[str, list[tuple[uuid.UUID, int]]]:
    """An incident on A with three outage payments (one rescued by failover) linked at open."""
    failures = [seed_failure(factory, "A", "outage", age_seconds=10 + i, kind="payment.failed") for i in range(3)]
    rescue(factory, failures[0][0])
    consumer = IncidentConsumer(factory, redis_client, "i1")
    consumer.ensure_group()
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    return str(the_incident(factory)), failures


def good(ids: list[int]) -> FakeModel:
    return FakeModel(json.dumps({"text": "Processor A had an outage.", "cited_event_ids": ids, "cause": "outage"}))


def summary_rows(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT source, trigger FROM incident_summaries ORDER BY id")).all()
    return [(r[0], r[1]) for r in rows]


def test_the_detail_lists_affected_payments_and_their_events(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    body = client.get(f"/incidents/{incident_id}", headers=headers).json()
    assert body["id"] == incident_id and body["processor"] == "A"
    by_id = {p["id"]: p for p in body["affected_payments"]}
    assert set(by_id) == {str(pid) for pid, _ in failures}
    first = by_id[str(failures[0][0])]
    assert {"id", "status", "amount_minor", "currency", "processor", "events"} <= set(first)
    assert (first["status"], first["amount_minor"], first["currency"], first["processor"]) == (
        "captured",
        1250,
        "USD",
        "B",
    )
    assert "description" not in first
    events = first["events"]
    assert [e["id"] for e in events] == [failures[0][1]]
    assert set(events[0]) == {"id", "type", "reason", "processor", "occurred_at"}
    assert (events[0]["type"], events[0]["reason"], events[0]["processor"]) == ("payment.failed", "outage", "A")
    assert events[0]["occurred_at"].endswith("Z")


def test_a_manual_incident_without_a_processor_has_no_payments(client: TestClient, headers: dict[str, str]) -> None:
    created = client.post("/incidents", json={"title": "Reports look wrong"}, headers=headers).json()
    detail = client.get(f"/incidents/{created['id']}", headers=headers).json()
    assert detail["affected_payments"] == []
    assert {k: detail[k] for k in created} == created


@pytest.mark.parametrize(("method", "suffix"), [("GET", "/summary"), ("POST", "/summary/regenerate")])
def test_the_summary_endpoints_require_the_api_key(client: TestClient, method: str, suffix: str) -> None:
    path = f"/incidents/{uuid.uuid4()}{suffix}"
    for bad in ({}, {"X-API-Key": "wrong"}):
        response = client.request(method, path, headers=bad)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "suffix"), [("GET", "/summary"), ("POST", "/summary/regenerate")])
def test_the_summary_of_an_unknown_incident_is_404(
    client: TestClient, headers: dict[str, str], method: str, suffix: str
) -> None:
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        response = client.request(method, f"/incidents/{bad}{suffix}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_get_generates_once_then_returns_the_stored_summary(
    client: TestClient, factory: Factory, redis_client: Redis, engine: Engine, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    ids = [failures[0][1], failures[1][1]]
    model = use(client, good(ids))
    first = client.get(f"/incidents/{incident_id}/summary", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert set(body) == SUMMARY_FIELDS
    assert (body["source"], body["model"], body["trigger"], body["fallback_reason"]) == (
        "model",
        "granite3.3:2b",
        "on_request",
        None,
    )
    assert body["cited_event_ids"] == sorted(ids) and body["cause"] == "outage"
    assert body["incident_id"] == incident_id and body["generated_at"].endswith("Z")
    second = client.get(f"/incidents/{incident_id}/summary", headers=headers)
    assert second.json() == body
    assert len(model.prompts) == 1
    assert summary_rows(engine) == [("model", "on_request")]


def test_regenerate_stores_a_new_summary_and_get_returns_the_latest(
    client: TestClient, factory: Factory, redis_client: Redis, engine: Engine, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    use(client, good([failures[0][1]]))
    client.get(f"/incidents/{incident_id}/summary", headers=headers)
    use(client, FakeModel(unavailable="model_timeout"))
    response = client.post(f"/incidents/{incident_id}/summary/regenerate", headers=headers)
    assert response.status_code == 201
    body = response.json()
    assert (body["source"], body["trigger"], body["fallback_reason"], body["model"]) == (
        "rules",
        "regenerate",
        "model_timeout",
        None,
    )
    assert client.get(f"/incidents/{incident_id}/summary", headers=headers).json() == body
    assert summary_rows(engine) == [("model", "on_request"), ("rules", "regenerate")]


def test_a_citation_outside_the_linked_events_is_stored_as_a_rules_fallback(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    incident_id, _ = open_incident(factory, redis_client)
    _, unlinked = seed_failure(factory, "B", "outage")  # a real event, but not linked to this incident
    use(client, good([unlinked]))
    body = client.get(f"/incidents/{incident_id}/summary", headers=headers).json()
    assert (body["source"], body["fallback_reason"]) == ("rules", "citation_check_failed")
    assert unlinked not in body["cited_event_ids"]


def test_a_cause_mismatch_is_stored_as_a_rules_fallback(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    wrong = FakeModel(json.dumps({"text": "Slow.", "cited_event_ids": [failures[0][1]], "cause": "timeouts"}))
    use(client, wrong)
    body = client.get(f"/incidents/{incident_id}/summary", headers=headers).json()
    assert (body["source"], body["fallback_reason"], body["cause"]) == ("rules", "cause_mismatch", "outage")


def test_the_model_never_sees_a_description(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    model = use(client, good([failures[0][1]]))
    client.get(f"/incidents/{incident_id}/summary", headers=headers)
    assert model.prompts and all(SENTINEL not in p for p in model.prompts)


def test_no_database_transaction_is_open_during_the_model_call(
    client: TestClient, factory: Factory, redis_client: Redis, engine: Engine, headers: dict[str, str]
) -> None:
    incident_id, failures = open_incident(factory, redis_client)
    seen: list[int] = []

    class Spy(FakeModel):
        def generate(self, prompt: str) -> str:
            with engine.connect() as connection:
                seen.append(
                    int(
                        connection.execute(
                            sa.text(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                                " AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                            )
                        ).scalar_one()
                    )
                )
            return super().generate(prompt)

    use(client, Spy(json.dumps({"text": "t", "cited_event_ids": [failures[0][1]], "cause": "outage"})))
    assert client.get(f"/incidents/{incident_id}/summary", headers=headers).status_code == 200
    assert seen == [0]


def test_an_incident_without_linked_events_gets_a_rules_summary_without_a_model_call(
    client: TestClient, headers: dict[str, str]
) -> None:
    created = client.post("/incidents", json={"title": "Reports look wrong"}, headers=headers).json()
    model = use(client, good([1]))
    body = client.get(f"/incidents/{created['id']}/summary", headers=headers).json()
    assert (body["source"], body["fallback_reason"], body["cause"], body["cited_event_ids"]) == (
        "rules",
        "no_linked_events",
        "none",
        [],
    )
    assert model.prompts == []


def test_a_manual_incident_with_a_processor_links_the_recent_failures(
    client: TestClient, factory: Factory, headers: dict[str, str]
) -> None:
    recent, event_id = seed_failure(factory, "B", "timeout", age_seconds=10)
    seed_failure(factory, "B", "timeout", age_seconds=900)
    seed_failure(factory, "A", "timeout", age_seconds=10)
    created = client.post("/incidents", json={"processor": "B", "title": "B is slow"}, headers=headers).json()
    detail = client.get(f"/incidents/{created['id']}", headers=headers).json()
    assert [p["id"] for p in detail["affected_payments"]] == [str(recent)]
    assert [e["id"] for e in detail["affected_payments"][0]["events"]] == [event_id]
