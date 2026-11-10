"""REL-57: `GET /incidents` carries `affected_count` per incident, computed in the list query (no query per row)."""

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.incidents.consumer import IncidentConsumer
from tests.incidents.helpers import rescue, routed_entry, seed_failure, the_incident

Factory = sessionmaker[Session]


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def open_incident(factory: Factory, redis_client: Redis, failures: int) -> str:
    seeded = [seed_failure(factory, "A", "outage", age_seconds=10 + i, kind="payment.failed") for i in range(failures)]
    rescue(factory, seeded[0][0])
    consumer = IncidentConsumer(factory, redis_client, "i1")
    consumer.ensure_group()
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    return str(the_incident(factory))


def test_each_listed_incident_carries_the_number_of_payments_linked_to_it(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    rule_id = open_incident(factory, redis_client, 3)
    manual = client.post("/incidents", json={"title": "Reports look wrong"}, headers=headers).json()
    items = {i["id"]: i for i in client.get("/incidents", headers=headers).json()["items"]}
    assert items[rule_id]["affected_count"] == 3
    assert items[manual["id"]]["affected_count"] == 0
    detail = client.get(f"/incidents/{rule_id}", headers=headers).json()
    assert detail["affected_count"] == len(detail["affected_payments"]) == 3


def test_the_count_comes_from_the_list_query_not_one_query_per_incident(
    client: TestClient, factory: Factory, redis_client: Redis, headers: dict[str, str]
) -> None:
    open_incident(factory, redis_client, 2)
    statements: list[str] = []

    def record(_conn: object, _cur: object, statement: str, *_rest: object) -> None:
        statements.append(statement)

    def selects_for_list() -> int:
        statements.clear()
        assert client.get("/incidents", headers=headers).status_code == 200
        return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])

    engine = client.app.state.engine  # type: ignore[attr-defined]
    event.listen(engine, "before_cursor_execute", record)
    try:
        one = selects_for_list()
        for index in range(4):
            client.post("/incidents", json={"title": f"manual {index}"}, headers=headers)
        many = selects_for_list()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert one == many, (one, many)
    assert many <= 2
