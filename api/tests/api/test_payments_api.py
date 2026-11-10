"""POST /payments: auth, check order, validation, idempotency and concurrency (REL-17, api-contract.md)."""

import threading
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

BODY: dict[str, Any] = {"amount_minor": 1999, "currency": "USD", "description": "Order 4471", "reference": "ord-17.a_b"}
JSON = {"Content-Type": "application/json"}


def headers(api_key: str, key: str | None = "key-1") -> dict[str, str]:
    result = {"X-API-Key": api_key}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())  # noqa: S608


def post(client: TestClient, api_key: str, body: Any = BODY, key: str | None = "key-1") -> Any:
    return client.post("/payments", json=body, headers=headers(api_key, key))


def sql(engine: Engine, statement: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement))


def test_creates_payment(client: TestClient, engine: Engine, api_key: str) -> None:
    response = post(client, api_key)
    assert response.status_code == 201
    body = response.json()
    assert response.headers["Location"] == f"/payments/{body['id']}"
    assert "Idempotent-Replayed" not in response.headers
    assert uuid.UUID(body["id"]).version == 4
    assert body["amount_minor"] == 1999
    assert body["currency"] == "USD"
    assert body["description"] == "Order 4471"
    assert body["reference"] == "ord-17.a_b"
    assert body["status"] == "received"
    assert body["display_status"] == "Received"
    assert body["attempt_no"] == 0
    assert body["is_final"] is False
    assert body["processor"] is None
    assert body["final_at"] is None
    assert body["created_at"].endswith("Z")
    assert len(body["created_at"]) == len("2026-10-01T14:03:22.418Z")
    assert body["status_changed_at"].endswith("Z")
    assert count(engine, "payments") == 1
    assert count(engine, "payment_events") == 1
    with engine.connect() as connection:
        row = connection.execute(text("SELECT state, response_status, payment_id::text FROM idempotency_keys")).one()
        reference = connection.execute(text("SELECT reference FROM payments")).scalar_one()
    assert tuple(row) == ("completed", 201, body["id"])
    assert reference == "ord-17.a_b"


def test_optional_fields_default_to_null(client: TestClient, api_key: str) -> None:
    response = post(client, api_key, {"amount_minor": 5, "currency": "JPY"})
    assert response.status_code == 201
    assert response.json()["description"] is None
    assert response.json()["reference"] is None


def test_correlation_id_reaches_the_payment_and_event(client: TestClient, engine: Engine, api_key: str) -> None:
    response = client.post("/payments", json=BODY, headers={**headers(api_key), "X-Correlation-ID": "cid-17"})
    assert response.status_code == 201
    with engine.connect() as connection:
        assert connection.execute(text("SELECT correlation_id FROM payment_events")).scalar_one() == "cid-17"
        assert connection.execute(text("SELECT correlation_id FROM payments")).scalar_one() == "cid-17"


@pytest.mark.parametrize("supplied", [None, "wrong"])
def test_bad_api_key_is_401(client: TestClient, engine: Engine, supplied: str | None) -> None:
    sent = {"Idempotency-Key": "key-1"}
    if supplied is not None:
        sent["X-API-Key"] = supplied
    response = client.post("/payments", json=BODY, headers=sent)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert count(engine, "idempotency_keys") == 0


@pytest.mark.parametrize("key", [None, ""])
def test_missing_idempotency_key_is_400(client: TestClient, engine: Engine, api_key: str, key: str | None) -> None:
    response = post(client, api_key, key=key)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "idempotency_key_missing"
    assert error["correlation_id"]
    assert count(engine, "idempotency_keys") == 0


@pytest.mark.parametrize("key", ["k" * 256, "has\x01control", b"caf\xc3\xa9"])
def test_invalid_idempotency_key_is_400_malformed(
    client: TestClient, engine: Engine, api_key: str, key: str | bytes
) -> None:
    sent: dict[str, Any] = {"X-API-Key": api_key, "Idempotency-Key": key}
    response = client.post("/payments", json=BODY, headers=sent)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"
    assert count(engine, "idempotency_keys") == 0


def test_longest_valid_key_is_accepted(client: TestClient, api_key: str) -> None:
    assert post(client, api_key, key="k" * 255).status_code == 201


def test_missing_header_wins_over_invalid_body(client: TestClient, api_key: str) -> None:
    response = post(client, api_key, {"amount_minor": -1, "currency": "XXX"}, key=None)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_missing"


def test_invalid_json_is_400_malformed(client: TestClient, engine: Engine, api_key: str) -> None:
    response = client.post("/payments", content=b"{not json", headers={**headers(api_key), **JSON})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_request"
    assert count(engine, "idempotency_keys") == 0


INVALID_BODIES: list[tuple[Any, str]] = [
    ({"currency": "USD"}, "amount_minor"),
    ({"amount_minor": 100}, "currency"),
    ({"amount_minor": 0, "currency": "USD"}, "amount_minor"),
    ({"amount_minor": -5, "currency": "USD"}, "amount_minor"),
    ({"amount_minor": 1_000_000_000_001, "currency": "USD"}, "amount_minor"),
    ({"amount_minor": 12.5, "currency": "USD"}, "amount_minor"),
    ({"amount_minor": "100", "currency": "USD"}, "amount_minor"),
    ({"amount_minor": True, "currency": "USD"}, "amount_minor"),
    ({"amount_minor": 100, "currency": "CAD"}, "currency"),
    ({"amount_minor": 100, "currency": "usd"}, "currency"),
    ({"amount_minor": 100, "currency": 5}, "currency"),
    ({"amount_minor": 100, "currency": "USD", "extra": 1}, "extra"),
    ({"amount_minor": 100, "currency": "USD", "description": "d" * 201}, "description"),
    ({"amount_minor": 100, "currency": "USD", "description": 5}, "description"),
    ({"amount_minor": 100, "currency": "USD", "reference": ""}, "reference"),
    ({"amount_minor": 100, "currency": "USD", "reference": "a" * 65}, "reference"),
    ({"amount_minor": 100, "currency": "USD", "reference": "has space"}, "reference"),
    ({"amount_minor": 100, "currency": "USD", "reference": "trail\n"}, "reference"),
    ({"amount_minor": 100, "currency": "USD", "reference": "café"}, "reference"),
    ([1, 2], "body"),
]


@pytest.mark.parametrize(("body", "field"), INVALID_BODIES)
def test_invalid_body_is_422_before_claim(
    client: TestClient, engine: Engine, api_key: str, body: Any, field: str
) -> None:
    response = post(client, api_key, body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert field in [d["field"] for d in error["details"]]
    assert field in error["message"]
    assert error["correlation_id"]
    assert count(engine, "idempotency_keys") == 0
    assert count(engine, "payments") == 0


def test_currency_message_is_clear(client: TestClient, api_key: str) -> None:
    error = post(client, api_key, {"amount_minor": 100, "currency": "CAD"}).json()["error"]
    assert "currency must be one of USD, EUR, GBP, JPY" in error["message"]
    assert error["details"] == [{"field": "currency", "issue": "not_supported"}]


def test_empty_body_is_422(client: TestClient, api_key: str) -> None:
    response = client.post("/payments", headers=headers(api_key))
    assert response.status_code == 422
    assert {d["field"] for d in response.json()["error"]["details"]} == {"amount_minor", "currency"}


def test_replay_returns_stored_response(client: TestClient, engine: Engine, api_key: str) -> None:
    first = post(client, api_key)
    second = post(client, api_key)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.headers["Location"] == first.headers["Location"]
    assert count(engine, "payments") == 1
    assert count(engine, "payment_events") == 1


def test_replay_is_the_stored_body_not_current_state(client: TestClient, engine: Engine, api_key: str) -> None:
    first = post(client, api_key)
    sql(engine, "UPDATE payments SET status_changed_at = now() + interval '1 hour'")
    assert post(client, api_key).json() == first.json()


def test_key_order_and_explicit_null_do_not_change_the_hash(client: TestClient, api_key: str) -> None:
    sent = {**headers(api_key), **JSON}
    first = client.post("/payments", content=b'{"currency":"USD","amount_minor":10}', headers=sent)
    second = client.post(
        "/payments",
        content=b'{ "amount_minor": 10, "description": null, "currency": "USD" }',
        headers=sent,
    )
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json() == first.json()


@pytest.mark.parametrize(
    "other",
    [
        {**BODY, "amount_minor": 2000},
        {**BODY, "currency": "EUR"},
        {**BODY, "description": "other"},
        {**BODY, "reference": "other-ref"},
        {k: v for k, v in BODY.items() if k != "reference"},
    ],
)
def test_changed_body_is_409_reused(client: TestClient, engine: Engine, api_key: str, other: dict[str, Any]) -> None:
    post(client, api_key)
    response = post(client, api_key, other)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert count(engine, "payments") == 1


def start_in_progress(engine: Engine, body: dict[str, Any] = BODY) -> None:
    """Leave key-1 claimed and unfinished, as after a crash between claim and create."""
    from app.idempotency.service import claim, request_hash

    claim(engine, "key-1", request_hash(body), ttl_hours=24, lease_seconds=30)


def test_in_progress_same_body_is_409_with_retry_after(client: TestClient, engine: Engine, api_key: str) -> None:
    start_in_progress(engine)
    response = post(client, api_key)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_request_in_progress"
    assert response.headers["Retry-After"] == "1"
    assert count(engine, "payments") == 0


def test_in_progress_different_body_is_409_reused(client: TestClient, engine: Engine, api_key: str) -> None:
    start_in_progress(engine)
    response = post(client, api_key, {**BODY, "amount_minor": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_expired_lease_same_body_is_taken_over(client: TestClient, engine: Engine, api_key: str) -> None:
    start_in_progress(engine)
    with engine.connect() as connection:
        old_token = connection.execute(text("SELECT lease_token FROM idempotency_keys")).scalar_one()
    sql(engine, "UPDATE idempotency_keys SET lease_expires_at = now() - interval '1 second'")
    response = post(client, api_key)
    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    assert count(engine, "payments") == 1
    with engine.connect() as connection:
        row = connection.execute(text("SELECT state, lease_token FROM idempotency_keys")).one()
    assert row.state == "completed"
    assert row.lease_token != old_token


def test_expired_lease_different_body_is_409_reused(client: TestClient, engine: Engine, api_key: str) -> None:
    start_in_progress(engine)
    sql(engine, "UPDATE idempotency_keys SET lease_expires_at = now() - interval '1 second'")
    response = post(client, api_key, {**BODY, "amount_minor": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert count(engine, "payments") == 0


def test_key_past_24_hours_starts_a_new_payment(client: TestClient, engine: Engine, api_key: str) -> None:
    first = post(client, api_key)
    sql(engine, "UPDATE idempotency_keys SET expires_at = now() - interval '1 second'")
    changed = post(client, api_key, {**BODY, "amount_minor": 7})
    assert changed.status_code == 201
    assert "Idempotent-Replayed" not in changed.headers
    assert changed.json()["id"] != first.json()["id"]
    assert count(engine, "payments") == 2
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT payment_id::text AS pid, response_body ->> 'amount_minor' AS amount FROM idempotency_keys")
        ).one()
    assert (row.pid, row.amount) == (changed.json()["id"], "7")
    again = post(client, api_key, {**BODY, "amount_minor": 7})
    assert again.json() == changed.json()
    assert again.headers["Idempotent-Replayed"] == "true"


def test_expiry_is_set_from_the_ttl(client: TestClient, engine: Engine, api_key: str) -> None:
    post(client, api_key)
    with engine.connect() as connection:
        hours = connection.execute(
            text("SELECT extract(epoch FROM expires_at - created_at) / 3600 FROM idempotency_keys")
        ).scalar_one()
    assert float(hours) == pytest.approx(24, abs=0.01)


def test_stalled_first_request_cannot_complete_a_taken_over_key(
    client: TestClient, engine: Engine, api_key: str
) -> None:
    from app.api.payments import payment_body
    from app.errors import ApiError
    from app.idempotency.service import Claimed, claim, create_once, request_hash

    stalled = claim(engine, "key-1", request_hash(BODY), ttl_hours=24, lease_seconds=30)
    assert isinstance(stalled, Claimed)
    sql(engine, "UPDATE idempotency_keys SET lease_expires_at = now() - interval '1 second'")
    assert post(client, api_key).status_code == 201  # the retry takes the key over and completes it
    with pytest.raises(ApiError) as caught:
        create_once(engine, "key-1", stalled.token, fields=BODY, correlation_id="cid", render=payment_body)
    assert caught.value.code == "idempotency_request_in_progress"
    assert count(engine, "payments") == 1
    assert count(engine, "payment_events") == 1


def test_concurrent_requests_create_one_payment(client: TestClient, engine: Engine, api_key: str) -> None:
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[Any] = []

    def run() -> None:
        barrier.wait()
        results.append(post(client, api_key))

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == workers
    assert count(engine, "payments") == 1
    created = [r for r in results if r.status_code == 201 and "Idempotent-Replayed" not in r.headers]
    assert len(created) == 1
    for response in results:
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "idempotency_request_in_progress"
        else:
            assert response.status_code == 201
            assert response.json() == created[0].json()
    again = post(client, api_key)
    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == created[0].json()


def test_openapi_describes_the_endpoint(client: TestClient) -> None:
    from app.main import app

    operation = app.openapi()["paths"]["/payments"]["post"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert parameters["Idempotency-Key"]["in"] == "header"
    assert parameters["Idempotency-Key"]["schema"]["maxLength"] == 255
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["properties"]) == {"amount_minor", "currency", "description", "reference"}
    assert schema["required"] == ["amount_minor", "currency"]
    assert "201" in operation["responses"]
    assert "Idempotent-Replayed" in operation["responses"]["201"]["headers"]
    assert "Location" in operation["responses"]["201"]["headers"]
    # REL-40: only the errors POST /payments can return (no 404, and 503 is /health only)
    assert {s for s in operation["responses"] if int(s) >= 400} == {"400", "401", "409", "422", "500"}
