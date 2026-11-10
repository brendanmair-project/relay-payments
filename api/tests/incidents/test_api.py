"""REL-34.3/34.5 (api-contract.md): the incident endpoints, the state machine and the API key on every route."""

import threading
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.incidents.state import can_transition

Factory = sessionmaker[Session]


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    response = client.post("/incidents", json=body, headers=headers)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def move(client: TestClient, headers: dict[str, str], incident_id: str, to: str) -> Any:
    return client.post(f"/incidents/{incident_id}/transitions", json={"to": to}, headers=headers)


def test_the_state_machine_allows_only_detected_triaged_resolved() -> None:
    allowed = {("detected", "triaged"), ("triaged", "resolved")}
    states = ("detected", "triaged", "resolved")
    for current in states:
        for target in states:
            assert can_transition(current, target) == ((current, target) in allowed), (current, target)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/incidents"),
        ("GET", f"/incidents/{uuid.uuid4()}"),
        ("POST", "/incidents"),
        ("POST", f"/incidents/{uuid.uuid4()}/transitions"),
    ],
)
def test_every_incident_endpoint_requires_the_api_key(client: TestClient, method: str, path: str) -> None:
    body = {"title": "t"} if path == "/incidents" else {"to": "triaged"}
    for bad in ({}, {"X-API-Key": "wrong"}):
        response = client.request(method, path, json=body if method == "POST" else None, headers=bad)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


def test_manual_create_returns_a_detected_manual_incident(client: TestClient, headers: dict[str, str]) -> None:
    incident = create(client, headers, processor="B", title="Processor B slow")
    assert incident["processor"] == "B"
    assert incident["source"] == "manual"
    assert incident["status"] == "detected"
    assert incident["title"] == "Processor B slow"
    assert incident["opened_by_event_id"] is None
    assert incident["recovered_at"] is None and incident["triaged_at"] is None and incident["resolved_at"] is None
    assert incident["opened_at"].endswith("Z") and incident["created_at"].endswith("Z")
    uuid.UUID(incident["id"])


def test_manual_create_without_a_processor_can_repeat(client: TestClient, headers: dict[str, str]) -> None:
    first = create(client, headers, title="Checkout reports are wrong")
    second = create(client, headers, title="Checkout reports are wrong again")
    assert first["processor"] is None
    assert first["id"] != second["id"]


def test_manual_create_for_a_processor_with_an_open_incident_is_409(
    client: TestClient, headers: dict[str, str]
) -> None:
    create(client, headers, processor="A", title="first")
    response = client.post("/incidents", json={"processor": "A", "title": "second"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "incident_already_open"
    assert create(client, headers, processor="B", title="other processor")["processor"] == "B"


def test_a_processor_can_have_a_new_incident_after_the_old_one_is_resolved(
    client: TestClient, headers: dict[str, str]
) -> None:
    first = create(client, headers, processor="A", title="first")
    assert move(client, headers, first["id"], "triaged").status_code == 200
    assert move(client, headers, first["id"], "resolved").status_code == 200
    assert create(client, headers, processor="A", title="second")["status"] == "detected"


@pytest.mark.parametrize(
    "body",
    [{}, {"title": ""}, {"title": "   "}, {"title": "x" * 201}, {"title": "t", "processor": "C"}, {"title": 5}],
)
def test_manual_create_validates_the_body(client: TestClient, headers: dict[str, str], body: dict[str, Any]) -> None:
    response = client.post("/incidents", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_concurrent_manual_creates_for_one_processor_open_exactly_one(
    client: TestClient, headers: dict[str, str]
) -> None:
    barrier = threading.Barrier(6)
    statuses: list[int] = []

    def post() -> None:
        barrier.wait()
        response = client.post("/incidents", json={"processor": "A", "title": "race"}, headers=headers)
        statuses.append(response.status_code)

    threads = [threading.Thread(target=post) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [201, 409, 409, 409, 409, 409]


def test_get_one_incident_and_unknown_ids(client: TestClient, headers: dict[str, str]) -> None:
    incident = create(client, headers, processor="A", title="t")
    detail = client.get(f"/incidents/{incident['id']}", headers=headers).json()
    assert {key: detail[key] for key in incident} == incident
    assert detail["affected_payments"] == []
    for bad in (str(uuid.uuid4()), "not-a-uuid", "{" + str(uuid.uuid4()) + "}"):
        response = client.get(f"/incidents/{bad}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_list_is_newest_first_and_filters_by_status_and_processor(client: TestClient, headers: dict[str, str]) -> None:
    first = create(client, headers, processor="A", title="one")
    second = create(client, headers, processor="B", title="two")
    third = create(client, headers, title="three")
    move(client, headers, first["id"], "triaged")
    listed = client.get("/incidents", headers=headers).json()["items"]
    assert [i["id"] for i in listed] == [third["id"], second["id"], first["id"]]
    only_triaged = client.get("/incidents?status=triaged", headers=headers).json()["items"]
    assert [i["id"] for i in only_triaged] == [first["id"]]
    only_b = client.get("/incidents?processor=B", headers=headers).json()["items"]
    assert [i["id"] for i in only_b] == [second["id"]]
    both = client.get("/incidents?status=detected&processor=A", headers=headers).json()["items"]
    assert both == []
    assert client.get("/incidents?limit=1", headers=headers).json()["items"][0]["id"] == third["id"]


@pytest.mark.parametrize("query", ["status=open", "processor=C", "limit=0", "limit=101"])
def test_list_rejects_bad_filters(client: TestClient, headers: dict[str, str], query: str) -> None:
    assert client.get(f"/incidents?{query}", headers=headers).status_code == 422


def test_valid_transitions_stamp_their_times(client: TestClient, headers: dict[str, str]) -> None:
    incident = create(client, headers, processor="A", title="t")
    triaged = move(client, headers, incident["id"], "triaged")
    assert triaged.status_code == 200
    assert triaged.json()["status"] == "triaged"
    assert triaged.json()["triaged_at"] is not None and triaged.json()["resolved_at"] is None
    resolved = move(client, headers, incident["id"], "resolved")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"] is not None
    assert resolved.json()["triaged_at"] == triaged.json()["triaged_at"]


@pytest.mark.parametrize(
    ("path", "to"),
    [
        ([], "resolved"),  # detected -> resolved skips triage
        ([], "detected"),
        (["triaged"], "triaged"),
        (["triaged"], "detected"),
        (["triaged", "resolved"], "triaged"),
        (["triaged", "resolved"], "resolved"),
        (["triaged", "resolved"], "detected"),
    ],
)
def test_invalid_transitions_are_rejected_and_change_nothing(
    client: TestClient, headers: dict[str, str], path: list[str], to: str
) -> None:
    incident = create(client, headers, processor="A", title="t")
    for step in path:
        assert move(client, headers, incident["id"], step).status_code == 200
    before = client.get(f"/incidents/{incident['id']}", headers=headers).json()
    response = move(client, headers, incident["id"], to)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_incident_transition"
    assert client.get(f"/incidents/{incident['id']}", headers=headers).json() == before


def test_transition_validates_the_body_and_the_id(client: TestClient, headers: dict[str, str]) -> None:
    incident = create(client, headers, processor="A", title="t")
    for body in ({}, {"to": "closed"}, {"to": 3}):
        response = client.post(f"/incidents/{incident['id']}/transitions", json=body, headers=headers)
        assert response.status_code == 422
    assert move(client, headers, str(uuid.uuid4()), "triaged").status_code == 404
    assert move(client, headers, "nope", "triaged").status_code == 404


def test_an_analyst_resolving_a_rule_incident_frees_the_processor(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    incident_id = uuid.uuid4()
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO incidents (id, processor, source, status, title, opened_at, opened_by_event_id)"
                " VALUES (:i, 'A', 'rule', 'detected', 'Processor A is being avoided', now(), 7)"
            ),
            {"i": incident_id},
        )
    assert client.post("/incidents", json={"processor": "A", "title": "x"}, headers=headers).status_code == 409
    assert move(client, headers, str(incident_id), "triaged").status_code == 200
    assert move(client, headers, str(incident_id), "resolved").status_code == 200
    assert client.post("/incidents", json={"processor": "A", "title": "x"}, headers=headers).status_code == 201
