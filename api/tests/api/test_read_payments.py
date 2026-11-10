"""GET /payments/{id} and GET /payments (REL-18, api-contract.md). Test data goes through the transition service."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.domain.lifecycle import Event, PaymentState
from app.services.transitions import apply_transition, create_payment

BASE = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
R = PaymentState.RECEIVED
Step = tuple[Event, PaymentState, int, dict[str, Any]]
ROUTE_A: Step = (Event.ROUTE, R, 0, {"processor": "A", "reason": "initial"})


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def make(
    factory: sessionmaker[Session],
    engine: Engine,
    *,
    minutes: int = 0,
    steps: list[Step] | None = None,
    **kw: Any,
) -> uuid.UUID:
    """Create a payment, apply the steps, then place created_at at BASE + minutes."""
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=500, currency="EUR", **kw)
        for event, expected, attempt, extra in steps or []:
            apply_transition(
                session, pid, event, expected_status=expected, expected_attempt=attempt, retries_enabled=True, **extra
            )
    with engine.begin() as connection:  # payments rows may be updated; only events are append-only
        connection.execute(
            text("UPDATE payments SET created_at = :t WHERE id = :id"),
            {"t": BASE + timedelta(minutes=minutes), "id": pid},
        )
    return pid


def captured(factory: sessionmaker[Session], engine: Engine, **kw: Any) -> uuid.UUID:
    steps: list[Step] = [
        ROUTE_A,
        (Event.AUTHORIZE, PaymentState.ROUTED, 1, {}),
        (Event.CAPTURE, PaymentState.AUTHORIZED, 1, {}),
    ]
    return make(factory, engine, steps=steps, **kw)


def retrying(factory: sessionmaker[Session], engine: Engine, **kw: Any) -> uuid.UUID:
    steps: list[Step] = [ROUTE_A, (Event.FAIL, PaymentState.ROUTED, 1, {"reason": "timeout"})]
    return make(factory, engine, steps=steps, **kw)


def routed_b(factory: sessionmaker[Session], engine: Engine, **kw: Any) -> uuid.UUID:
    steps: list[Step] = [(Event.ROUTE, R, 0, {"processor": "B", "reason": "failover"})]
    return make(factory, engine, steps=steps, **kw)


def ids(response: Any) -> list[str]:
    return [item["id"] for item in response.json()["items"]]


# --- GET /payments/{id} ---


def test_detail_with_timeline(client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str) -> None:
    pid = captured(factory, engine, reference="ord-1", description="Order")
    response = client.get(f"/payments/{pid}", headers=auth(api_key))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(pid)
    assert body["reference"] == "ord-1"
    assert body["status"] == "captured"
    assert body["display_status"] == "Captured"
    assert body["attempt_no"] == 1
    assert body["is_final"] is True
    assert body["processor"] == "A"
    assert body["final_at"].endswith("Z")
    assert body["status_changed_at"].endswith("Z")
    events = body["events"]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["type"] for e in events] == [
        "payment.received",
        "payment.routed",
        "payment.authorized",
        "payment.captured",
        "payment.final",
    ]
    first, routed = events[0], events[1]
    assert set(first) == {
        "seq",
        "type",
        "attempt_no",
        "from_status",
        "to_status",
        "processor",
        "reason",
        "data",
        "occurred_at",
    }
    assert first["from_status"] is None and first["to_status"] == "received"
    assert routed["from_status"] == "received" and routed["to_status"] == "routed"
    assert routed["processor"] == "A" and routed["reason"] == "initial"
    assert first["data"] == {}
    stamps = [e["occurred_at"] for e in events]
    assert all(s.endswith("Z") and len(s) == len("2026-10-01T14:03:22.418Z") for s in stamps)
    assert stamps == sorted(stamps)


def test_detail_reference_null_and_retrying(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    pid = retrying(factory, engine)
    body = client.get(f"/payments/{pid}", headers=auth(api_key)).json()
    assert body["reference"] is None
    assert body["status"] == "failed" and body["is_final"] is False
    assert body["display_status"] == "Retrying"
    assert body["final_at"] is None
    assert body["events"][-1]["type"] == "payment.retry_scheduled"


def test_detail_unknown_id_is_404(client: TestClient, api_key: str) -> None:
    response = client.get(f"/payments/{uuid.uuid4()}", headers=auth(api_key))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["correlation_id"]


@pytest.mark.parametrize("bad", ["abc", "123", "not-a-uuid", "00000000-0000-0000-0000-00000000000g"])
def test_detail_non_uuid_is_404(client: TestClient, api_key: str, bad: str) -> None:
    response = client.get(f"/payments/{bad}", headers=auth(api_key))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- GET /payments ---


def test_list_newest_first_with_fields(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    old = make(factory, engine, minutes=0)
    new = captured(factory, engine, minutes=5, reference="r")
    response = client.get("/payments", headers=auth(api_key))
    assert response.status_code == 200
    assert ids(response) == [str(new), str(old)]
    assert response.json()["next_cursor"] is None
    item = response.json()["items"][0]
    assert set(item) == {
        "id",
        "amount_minor",
        "currency",
        "description",
        "reference",
        "status",
        "display_status",
        "attempt_no",
        "is_final",
        "processor",
        "created_at",
        "status_changed_at",
        "final_at",
    }
    assert item["display_status"] == "Captured" and item["reference"] == "r"
    assert response.json()["items"][1]["reference"] is None


def test_list_empty(client: TestClient, api_key: str) -> None:
    assert client.get("/payments", headers=auth(api_key)).json() == {"items": [], "next_cursor": None}


def test_pagination_walks_all_pages_with_ties(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    created = [make(factory, engine, minutes=i // 2) for i in range(7)]  # pairs share created_at: id breaks ties
    seen: list[str] = []
    params: dict[str, Any] = {"limit": 3}
    pages = 0
    while True:
        body = client.get("/payments", params=params, headers=auth(api_key)).json()
        seen += [i["id"] for i in body["items"]]
        pages += 1
        if body["next_cursor"] is None:
            break
        assert len(body["items"]) == 3
        params["cursor"] = body["next_cursor"]
    assert pages == 3
    assert len(seen) == 7 and set(seen) == {str(p) for p in created}
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id FROM payments ORDER BY created_at DESC, id DESC"))
        expected = [str(r[0]) for r in rows]
    assert seen == expected


def test_exact_multiple_has_no_trailing_cursor(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    for i in range(4):
        make(factory, engine, minutes=i)
    first = client.get("/payments", params={"limit": 2}, headers=auth(api_key)).json()
    assert first["next_cursor"]
    second = client.get("/payments", params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth(api_key)).json()
    assert len(second["items"]) == 2 and second["next_cursor"] is None


def test_pages_stable_when_newer_payment_arrives(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    for i in range(6):
        make(factory, engine, minutes=i)
    first = client.get("/payments", params={"limit": 2}, headers=auth(api_key)).json()
    newer = make(factory, engine, minutes=100)  # arrives between page fetches
    rest: list[str] = []
    cursor = first["next_cursor"]
    while cursor:
        page = client.get("/payments", params={"limit": 2, "cursor": cursor}, headers=auth(api_key)).json()
        rest += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
    all_ids = [i["id"] for i in first["items"]] + rest
    assert str(newer) not in all_ids
    assert len(all_ids) == 6 and len(set(all_ids)) == 6
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id FROM payments WHERE id <> :n ORDER BY created_at DESC, id DESC"), {"n": newer}
        )
        older = [str(r[0]) for r in rows]
    assert all_ids == older


def test_filters(client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str) -> None:
    received = make(factory, engine, minutes=1)
    done = captured(factory, engine, minutes=2)
    retry = retrying(factory, engine, minutes=3)
    on_b = routed_b(factory, engine, minutes=4)

    def get(**params: Any) -> set[str]:
        response = client.get("/payments", params=params, headers=auth(api_key))
        assert response.status_code == 200
        return set(ids(response))

    assert get(status="received") == {str(received)}
    assert get(status=["received", "captured"]) == {str(received), str(done)}
    assert get(status="failed") == {str(retry)}
    assert get(processor="B") == {str(on_b)}
    assert get(processor="A") == {str(done), str(retry)}
    assert get(is_final="true") == {str(done)}
    assert get(is_final="false") == {str(received), str(retry), str(on_b)}
    assert get(status="failed", is_final="false", processor="A") == {str(retry)}
    assert get(status="failed", processor="B") == set()


def test_filters_apply_across_pages(
    client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str
) -> None:
    for i in range(5):
        make(factory, engine, minutes=2 * i)
        captured(factory, engine, minutes=2 * i + 1)
    params: dict[str, Any] = {"status": "captured", "limit": 2}
    seen: list[str] = []
    while True:
        body = client.get("/payments", params=params, headers=auth(api_key)).json()
        seen += [i["id"] for i in body["items"]]
        assert all(i["status"] == "captured" for i in body["items"])
        if not body["next_cursor"]:
            break
        params["cursor"] = body["next_cursor"]
    assert len(seen) == 5


@pytest.mark.parametrize("cursor", ["!!!", "abc", "e30", "bm90LWpzb24", "eyJjIjoiMjAyNiIsImkiOiJ4In0"])
def test_malformed_cursor_is_400(client: TestClient, api_key: str, cursor: str) -> None:
    response = client.get("/payments", params={"cursor": cursor}, headers=auth(api_key))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "x"},
        {"processor": "C"},
        {"status": "bogus"},
        {"is_final": "maybe"},
    ],
)
def test_invalid_query_values_are_422(client: TestClient, api_key: str, params: dict[str, Any]) -> None:
    response = client.get("/payments", params=params, headers=auth(api_key))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert response.json()["error"]["details"]


def test_limit_bounds_accepted(client: TestClient, api_key: str) -> None:
    for limit in (1, 100):
        assert client.get("/payments", params={"limit": limit}, headers=auth(api_key)).status_code == 200


def test_default_limit_is_20(client: TestClient, factory: sessionmaker[Session], engine: Engine, api_key: str) -> None:
    for i in range(21):
        make(factory, engine, minutes=i)
    body = client.get("/payments", headers=auth(api_key)).json()
    assert len(body["items"]) == 20 and body["next_cursor"]


# --- auth and OpenAPI ---


def test_both_endpoints_require_api_key(client: TestClient) -> None:
    for path in ("/payments", f"/payments/{uuid.uuid4()}"):
        for headers in ({}, {"X-API-Key": "wrong"}):
            response = client.get(path, headers=headers)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "unauthorized"


def test_openapi_documents_responses(client: TestClient, api_key: str) -> None:
    spec = client.get("/openapi.json", headers=auth(api_key)).json()
    schemas = spec["components"]["schemas"]

    def ref(path: str) -> str:
        return spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]

    assert ref("/payments").endswith("/PaymentListResponse")
    assert ref("/payments/{payment_id}").endswith("/PaymentDetailResponse")
    assert set(schemas["PaymentListResponse"]["properties"]) == {"items", "next_cursor"}
    assert "events" in schemas["PaymentDetailResponse"]["properties"]
    assert {"seq", "type", "occurred_at", "data"} <= set(schemas["EventResponse"]["properties"])
    params = {p["name"] for p in spec["paths"]["/payments"]["get"]["parameters"]}
    assert params == {"status", "processor", "is_final", "limit", "cursor"}
