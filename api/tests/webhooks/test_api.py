"""REL-39 (api-contract.md): the keyed subscription API, the delivery log and the secret shown once."""

import logging
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.webhooks.helpers import HOOK_URL, subscribe

Factory = sessionmaker[Session]


def create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    payload = {"url": HOOK_URL, "event_types": ["payment.final"]} | body
    response = client.post("/webhooks/subscriptions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/webhooks/subscriptions"),
        ("GET", "/webhooks/subscriptions"),
        ("GET", f"/webhooks/subscriptions/{uuid.uuid4()}"),
        ("DELETE", f"/webhooks/subscriptions/{uuid.uuid4()}"),
        ("GET", "/webhooks/deliveries"),
        ("GET", "/webhooks/deliveries/1"),
    ],
)
def test_every_webhook_endpoint_requires_the_api_key(client: TestClient, method: str, path: str) -> None:
    body = {"url": HOOK_URL, "event_types": ["payment.final"]} if method == "POST" else None
    for bad in ({}, {"X-API-Key": "wrong"}):
        response = client.request(method, path, json=body, headers=bad)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


def test_create_returns_201_with_the_subscription_and_a_generated_secret(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    body = create(client, headers, event_types=["payment.final", "payment.declined"])
    uuid.UUID(body["id"])
    assert body["url"] == HOOK_URL
    assert body["event_types"] == ["payment.final", "payment.declined"]
    assert body["active"] is True
    assert body["created_at"].endswith("Z")
    assert isinstance(body["secret"], str) and len(body["secret"]) >= 32
    with factory() as session:
        stored = session.execute(sa.text("SELECT secret FROM webhook_subscriptions")).scalar_one()
    assert stored == body["secret"]


def test_each_subscription_gets_its_own_random_secret(client: TestClient, headers: dict[str, str]) -> None:
    assert create(client, headers)["secret"] != create(client, headers)["secret"]


def test_the_secret_cannot_be_chosen_by_the_caller(client: TestClient, headers: dict[str, str]) -> None:
    chosen = "a-subscriber-supplied-value-that-must-be-ignored"
    body = create(client, headers, secret=chosen)
    assert body["secret"] != chosen


def test_the_secret_is_returned_only_by_the_create_response(client: TestClient, headers: dict[str, str]) -> None:
    created = create(client, headers)
    secret = created["secret"]
    listed = client.get("/webhooks/subscriptions", headers=headers)
    one = client.get(f"/webhooks/subscriptions/{created['id']}", headers=headers)
    deleted = client.delete(f"/webhooks/subscriptions/{created['id']}", headers=headers)
    for response in (listed, one, deleted):
        assert response.status_code == 200
        assert secret not in response.text
        assert "secret" not in response.text
    assert listed.json()["items"][0]["id"] == created["id"]
    assert one.json()["id"] == created["id"]


def test_the_secret_never_appears_in_a_log(
    client: TestClient, headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    created = create(client, headers)
    client.get("/webhooks/subscriptions", headers=headers)
    client.get(f"/webhooks/subscriptions/{created['id']}", headers=headers)
    client.delete(f"/webhooks/subscriptions/{created['id']}", headers=headers)
    assert len(created["secret"]) >= 32
    assert created["secret"] not in caplog.text
    assert created["secret"] not in "".join(str(r.__dict__) for r in caplog.records)


@pytest.mark.parametrize(
    "url",
    [
        "http://postgres:5432/",
        "http://api:8000/payments",
        "http://169.254.169.254/",
        "http://localhost.evil.test/",
        "file:///etc/passwd",
        "ftp://localhost/",
        "http://user:pw@localhost/",
    ],
)
def test_a_target_off_the_allowlist_is_422_and_nothing_is_stored(
    client: TestClient, headers: dict[str, str], factory: Factory, url: str
) -> None:
    response = client.post(
        "/webhooks/subscriptions", json={"url": url, "event_types": ["payment.final"]}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "webhook_target_not_allowed"
    with factory() as session:
        assert session.execute(sa.text("SELECT count(*) FROM webhook_subscriptions")).scalar_one() == 0


def test_the_allowlist_comes_from_the_environment(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "other.test")
    refused = client.post(
        "/webhooks/subscriptions", json={"url": HOOK_URL, "event_types": ["payment.final"]}, headers=headers
    )
    assert refused.status_code == 422
    accepted = client.post(
        "/webhooks/subscriptions",
        json={"url": "http://other.test/in", "event_types": ["payment.final"]},
        headers=headers,
    )
    assert accepted.status_code == 201


@pytest.mark.parametrize(
    "event_types",
    [[], ["payment.routed"], ["attempt.authorize_result"], ["payment.explained"], ["nonsense"], ["payment.final", "x"]],
)
def test_only_the_six_lifecycle_types_can_be_subscribed(
    client: TestClient, headers: dict[str, str], event_types: list[str]
) -> None:
    response = client.post(
        "/webhooks/subscriptions", json={"url": HOOK_URL, "event_types": event_types}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_all_six_lifecycle_types_are_accepted_and_repeats_are_stored_once(
    client: TestClient, headers: dict[str, str]
) -> None:
    six = ["payment.received", "payment.authorized", "payment.captured", "payment.declined", "payment.failed"]
    body = create(client, headers, event_types=[*six, "payment.final", "payment.final"])
    assert body["event_types"] == [*six, "payment.final"]


def test_a_missing_or_blank_url_is_422(client: TestClient, headers: dict[str, str]) -> None:
    for payload in ({"event_types": ["payment.final"]}, {"url": "", "event_types": ["payment.final"]}):
        response = client.post("/webhooks/subscriptions", json=payload, headers=headers)
        assert response.status_code == 422


def test_list_is_newest_first_and_get_returns_one(client: TestClient, headers: dict[str, str]) -> None:
    first = create(client, headers)
    second = create(client, headers, event_types=["payment.captured"])
    items = client.get("/webhooks/subscriptions", headers=headers).json()["items"]
    assert [i["id"] for i in items] == [second["id"], first["id"]]
    one = client.get(f"/webhooks/subscriptions/{second['id']}", headers=headers).json()
    assert one["event_types"] == ["payment.captured"]


def test_delete_deactivates_and_is_repeatable_but_unknown_ids_are_404(
    client: TestClient, headers: dict[str, str]
) -> None:
    created = create(client, headers)
    for _ in range(2):
        response = client.delete(f"/webhooks/subscriptions/{created['id']}", headers=headers)
        assert response.status_code == 200
        assert response.json()["active"] is False
    assert client.get(f"/webhooks/subscriptions/{created['id']}", headers=headers).json()["active"] is False
    for bad in (str(uuid.uuid4()), "not-a-uuid"):
        for method in ("GET", "DELETE"):
            response = client.request(method, f"/webhooks/subscriptions/{bad}", headers=headers)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"


def add_delivery(factory: Factory, subscription_id: uuid.UUID, event_id: int, status: str, attempt: int) -> None:
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type, attempt, status,"
                " last_status_code, last_error, created_at) VALUES (:s, :e, 'payment.final', :a, :st,"
                " :code, :err, now() + make_interval(secs => :e))"
            ),
            {
                "s": subscription_id,
                "e": event_id,
                "a": attempt,
                "st": status,
                "code": 500 if status != "delivered" else 200,
                "err": None if status == "delivered" else "HTTP 500",
            },
        )


def test_the_delivery_log_is_newest_first_with_each_deliverys_attempts_and_last_response(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _secret = subscribe(factory, ["payment.final"])
    add_delivery(factory, sub, 1, "delivered", 1)
    add_delivery(factory, sub, 2, "pending", 3)
    add_delivery(factory, sub, 3, "failed", 8)
    items = client.get("/webhooks/deliveries", headers=headers).json()["items"]
    assert [i["event_id"] for i in items] == [3, 2, 1]
    newest = items[0]
    assert newest["subscription_id"] == str(sub)
    assert newest["event_type"] == "payment.final"
    assert (newest["status"], newest["attempt"], newest["last_status_code"], newest["last_error"]) == (
        "failed",
        8,
        500,
        "HTTP 500",
    )
    for key in ("id", "next_attempt_at", "created_at", "updated_at"):
        assert key in newest
    assert "secret" not in str(items)


def test_the_delivery_log_filters_by_subscription_and_status_and_limits(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    one, _ = subscribe(factory, ["payment.final"])
    two, _ = subscribe(factory, ["payment.final"])
    add_delivery(factory, one, 1, "delivered", 1)
    add_delivery(factory, one, 2, "failed", 8)
    add_delivery(factory, two, 3, "delivered", 1)

    def ids(query: str) -> list[int]:
        response = client.get(f"/webhooks/deliveries{query}", headers=headers)
        assert response.status_code == 200
        return [i["event_id"] for i in response.json()["items"]]

    assert ids(f"?subscription_id={one}") == [2, 1]
    assert ids("?status=delivered") == [3, 1]
    assert ids(f"?subscription_id={one}&status=failed") == [2]
    assert ids("?limit=1") == [3]
    for bad in ("?status=nope", "?subscription_id=nope", "?limit=0", "?limit=1000"):
        assert client.get(f"/webhooks/deliveries{bad}", headers=headers).status_code == 422


def test_the_delivery_detail_lists_every_attempt_in_order(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    add_delivery(factory, sub, 1, "delivered", 4)
    add_delivery(factory, sub, 2, "delivered", 1)
    with factory.begin() as session:
        delivery = session.execute(sa.text("SELECT id FROM webhook_deliveries WHERE event_id = 1")).scalar_one()
        for number, code, error in [
            (1, 503, "HTTP 503"),
            (2, None, "ReadTimeout"),
            (3, 503, "HTTP 503"),
            (4, 200, None),
        ]:
            session.execute(
                sa.text(
                    "INSERT INTO webhook_delivery_attempts (delivery_id, attempt, status_code, error, duration_ms)"
                    " VALUES (:d, :n, :c, :e, :n * 10)"
                ),
                {"d": delivery, "n": number, "c": code, "e": error},
            )
    body = client.get(f"/webhooks/deliveries/{delivery}", headers=headers).json()
    assert body["id"] == delivery and body["event_id"] == 1 and body["status"] == "delivered" and body["attempt"] == 4
    attempts = body["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2, 3, 4]
    assert [a["status_code"] for a in attempts] == [503, None, 503, 200]
    assert [a["error"] for a in attempts] == ["HTTP 503", "ReadTimeout", "HTTP 503", None]
    assert [a["duration_ms"] for a in attempts] == [10, 20, 30, 40]
    assert all(a["attempted_at"].endswith("Z") for a in attempts)
    assert "secret" not in str(body)
    summary = client.get("/webhooks/deliveries", headers=headers).json()["items"]
    assert all("attempts" not in item for item in summary)  # the list stays a summary


def test_the_delivery_detail_of_an_unknown_or_malformed_id(client: TestClient, headers: dict[str, str]) -> None:
    missing = client.get("/webhooks/deliveries/999999", headers=headers)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.get("/webhooks/deliveries/abc", headers=headers).status_code == 422


def add_many_deliveries(factory: Factory, subscription_id: uuid.UUID, count: int, status: str = "delivered") -> None:
    """`count` deliveries with event ids 1..count; created_at is shared by groups of 3, so the id breaks ties."""
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type, attempt, status, created_at)"
                " SELECT :s, g, 'payment.final', 1, :st, now() + make_interval(secs => g / 3)"
                " FROM generate_series(1, :n) AS g ORDER BY g"
            ),
            {"s": subscription_id, "st": status, "n": count},
        )


def read_all(client: TestClient, headers: dict[str, str], query: str = "") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100):
        params = "&".join(part for part in (query, f"cursor={cursor}" if cursor else "") if part)
        response = client.get(f"/webhooks/deliveries?{params}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("the cursor never ended")


def test_the_delivery_log_pages_with_a_cursor_newest_first_with_no_gap_or_duplicate(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    add_many_deliveries(factory, sub, 25)
    first = client.get("/webhooks/deliveries?limit=10", headers=headers).json()
    assert len(first["items"]) == 10
    assert isinstance(first["next_cursor"], str)
    items = read_all(client, headers, "limit=10")
    assert [i["event_id"] for i in items] == list(range(25, 0, -1))
    assert len({i["id"] for i in items}) == 25
    last = client.get(f"/webhooks/deliveries?limit=10&cursor={first['next_cursor']}", headers=headers).json()
    assert len(last["items"]) == 10
    final = client.get(f"/webhooks/deliveries?limit=10&cursor={last['next_cursor']}", headers=headers).json()
    assert len(final["items"]) == 5
    assert final["next_cursor"] is None


def test_the_delivery_log_is_no_longer_capped_at_100_rows(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    add_many_deliveries(factory, sub, 130)
    items = read_all(client, headers, "limit=100")
    assert len(items) == 130
    assert len({i["id"] for i in items}) == 130


def test_an_exact_page_boundary_has_no_trailing_empty_page(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    add_many_deliveries(factory, sub, 6)
    body = client.get("/webhooks/deliveries?limit=6", headers=headers).json()
    assert len(body["items"]) == 6
    assert body["next_cursor"] is None
    assert client.get("/webhooks/deliveries", headers=headers).json()["next_cursor"] is None


def test_filters_apply_across_pages(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    one, _ = subscribe(factory, ["payment.final"])
    two, _ = subscribe(factory, ["payment.final"])
    add_many_deliveries(factory, one, 12, "delivered")
    add_many_deliveries(factory, two, 7, "failed")
    assert len(read_all(client, headers, f"subscription_id={one}&limit=5")) == 12
    assert len(read_all(client, headers, "status=failed&limit=3")) == 7
    assert len(read_all(client, headers, f"subscription_id={two}&status=delivered&limit=3")) == 0
    assert len(read_all(client, headers, "limit=4")) == 19


def test_a_malformed_cursor_is_400_malformed_request(client: TestClient, headers: dict[str, str]) -> None:
    for bad in ("garbage", "e30", "!!!", "eyJjIjoiMjAyNi0wMS0wMVQwMDowMDowMCIsImkiOiIxIn0"):
        response = client.get(f"/webhooks/deliveries?cursor={bad}", headers=headers)
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "malformed_request"
