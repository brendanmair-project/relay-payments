"""REL-40 (api-contract.md): GET /webhooks/deliveries/summary, the delivery success rate.

success_rate = delivered / (delivered + failed) over the window, null when no delivery is final. The window is
[since, until) applied to `updated_at` for delivered and failed rows and to `created_at` for pending ones.
"""

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.webhooks.helpers import subscribe

Factory = sessionmaker[Session]
BASE = datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC)
_event_ids = itertools.count(1000)


def seed(factory: Factory, subscription: uuid.UUID, status: str, at: datetime) -> None:
    """One delivery row with `created_at` and `updated_at` both at `at`."""
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type, attempt, status, "
                "created_at, updated_at) VALUES (:sub, :event, 'payment.final', :attempt, :status, :at, :at)"
            ),
            {"sub": subscription, "event": next(_event_ids), "attempt": 0 if status == "pending" else 1,
             "status": status, "at": at},
        )  # fmt: skip


def summary(client: TestClient, headers: dict[str, str], **params: str) -> dict[str, Any]:
    response = client.get("/webhooks/deliveries/summary", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_summary_requires_the_api_key(client: TestClient) -> None:
    for bad in ({}, {"X-API-Key": "wrong"}):
        response = client.get("/webhooks/deliveries/summary", headers=bad)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"


def test_summary_is_not_parsed_as_a_delivery_id(client: TestClient, headers: dict[str, str]) -> None:
    body = summary(client, headers)
    assert set(body) >= {"delivered", "failed", "pending", "success_rate"}


def test_an_empty_log_has_zero_counts_and_a_null_rate(client: TestClient, headers: dict[str, str]) -> None:
    body = summary(client, headers)
    assert (body["delivered"], body["failed"], body["pending"]) == (0, 0, 0)
    assert body["success_rate"] is None
    assert body["since"] is None and body["until"] is None and body["subscription_id"] is None


def test_only_pending_deliveries_give_a_null_rate(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    seed(factory, sub, "pending", BASE)
    seed(factory, sub, "pending", BASE)
    body = summary(client, headers)
    assert (body["delivered"], body["failed"], body["pending"]) == (0, 0, 2)
    assert body["success_rate"] is None


def test_mixed_counts_and_the_rate_over_final_deliveries(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    for status in ["delivered"] * 3 + ["failed"] + ["pending"] * 2:
        seed(factory, sub, status, BASE)
    body = summary(client, headers)
    assert (body["delivered"], body["failed"], body["pending"]) == (3, 1, 2)
    assert body["success_rate"] == 0.75  # pending rows are not in the denominator


def test_all_failed_is_a_rate_of_zero_not_null(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    seed(factory, sub, "failed", BASE)
    assert summary(client, headers)["success_rate"] == 0.0


def test_the_window_is_since_inclusive_until_exclusive(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    seed(factory, sub, "delivered", BASE - timedelta(seconds=1))  # before
    seed(factory, sub, "delivered", BASE)  # at since: in
    seed(factory, sub, "failed", BASE + timedelta(minutes=5))  # inside
    seed(factory, sub, "failed", BASE + timedelta(minutes=10))  # at until: out
    body = summary(client, headers, since=iso(BASE), until=iso(BASE + timedelta(minutes=10)))
    assert (body["delivered"], body["failed"]) == (1, 1)
    assert body["success_rate"] == 0.5
    assert body["since"] == "2026-11-05T12:00:00.000Z"
    assert body["until"] == "2026-11-05T12:10:00.000Z"


def test_final_rows_use_updated_at_and_pending_rows_use_created_at(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    seed(factory, sub, "delivered", BASE - timedelta(hours=1))
    seed(factory, sub, "pending", BASE - timedelta(hours=1))
    with factory.begin() as session:  # the delivery was created long ago but finished inside the window
        session.execute(
            sa.text("UPDATE webhook_deliveries SET updated_at = :at WHERE status = 'delivered'"), {"at": BASE}
        )
    body = summary(client, headers, since=iso(BASE - timedelta(minutes=1)))
    assert (body["delivered"], body["pending"]) == (1, 0)
    body = summary(client, headers, until=iso(BASE - timedelta(minutes=30)))
    assert (body["delivered"], body["pending"]) == (0, 1)


def test_the_subscription_filter(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    first, _ = subscribe(factory, ["payment.final"])
    second, _ = subscribe(factory, ["payment.final"])
    seed(factory, first, "delivered", BASE)
    seed(factory, first, "delivered", BASE)
    seed(factory, second, "failed", BASE)
    body = summary(client, headers, subscription_id=str(first))
    assert (body["delivered"], body["failed"]) == (2, 0)
    assert body["success_rate"] == 1.0
    assert body["subscription_id"] == str(first)
    assert summary(client, headers)["success_rate"] == round(2 / 3, 4)


def test_a_bad_timestamp_or_subscription_id_is_422(client: TestClient, headers: dict[str, str]) -> None:
    for params in ({"since": "yesterday"}, {"until": "not-a-time"}, {"subscription_id": "nope"}):
        response = client.get("/webhooks/deliveries/summary", params=params, headers=headers)
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "validation_failed"


def test_since_must_be_before_until(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get(
        "/webhooks/deliveries/summary", params={"since": iso(BASE), "until": iso(BASE)}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_counts_equal_a_count_from_the_delivery_log(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    for status in ["delivered", "delivered", "failed", "pending"]:
        seed(factory, sub, status, BASE)
    body = summary(client, headers)
    items = client.get("/webhooks/deliveries", headers=headers).json()["items"]
    for status in ("delivered", "failed", "pending"):
        assert body[status] == sum(1 for i in items if i["status"] == status)
