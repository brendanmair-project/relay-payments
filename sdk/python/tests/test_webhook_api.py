"""Webhook endpoints: subscriptions, delivery log, summary (REL-41)."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from conftest import ATTEMPT, DELIVERY, SUBSCRIPTION, Handler, Recorder, body_of, json_response

from relay_sdk import Delivery, DeliveryDetail, DeliverySummary, Subscription, SubscriptionCreated

SECRET = "shape-only-" + "x" * 8  # Relay generates real secrets; this one is never used for signing


def test_create_subscription_posts_the_body_and_returns_the_secret(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({**SUBSCRIPTION, "secret": SECRET}, 201))
    sub = rec.client.create_subscription("http://webhook-sink:8200/hook", ["payment.final", "payment.failed"])
    assert len(rec.requests) == 1
    assert rec.last.method == "POST"
    assert rec.last.url.path == "/webhooks/subscriptions"
    assert body_of(rec.last) == {
        "url": "http://webhook-sink:8200/hook",
        "event_types": ["payment.final", "payment.failed"],
    }
    assert isinstance(sub, SubscriptionCreated)
    assert sub.secret == SECRET
    assert sub.id == SUBSCRIPTION["id"]
    assert sub.active is True
    assert sub.created_at == datetime(2026, 11, 5, 14, 0, tzinfo=UTC)


def test_the_secret_is_not_in_the_repr(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({**SUBSCRIPTION, "secret": SECRET}, 201))
    sub = rec.client.create_subscription("http://webhook-sink:8200/hook", ["payment.final"])
    assert len(rec.requests) == 1
    assert SECRET not in repr(sub)


def test_list_subscriptions(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({"items": [SUBSCRIPTION, {**SUBSCRIPTION, "id": "second", "new": 1}]}))
    subs = rec.client.list_subscriptions()
    assert len(rec.requests) == 1
    assert (rec.last.method, rec.last.url.path) == ("GET", "/webhooks/subscriptions")
    assert [s.id for s in subs] == [SUBSCRIPTION["id"], "second"]
    assert isinstance(subs[0], Subscription)
    assert subs[0].event_types == ["payment.final"]


def test_get_subscription(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(SUBSCRIPTION))
    sub = rec.client.get_subscription(SUBSCRIPTION["id"])
    assert len(rec.requests) == 1
    assert (rec.last.method, rec.last.url.path) == ("GET", f"/webhooks/subscriptions/{SUBSCRIPTION['id']}")
    assert sub.url == SUBSCRIPTION["url"]


def test_delete_subscription_returns_the_deactivated_subscription(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({**SUBSCRIPTION, "active": False}))
    sub = rec.client.delete_subscription(SUBSCRIPTION["id"])
    assert len(rec.requests) == 1
    assert (rec.last.method, rec.last.url.path) == ("DELETE", f"/webhooks/subscriptions/{SUBSCRIPTION['id']}")
    assert sub.active is False


def test_list_deliveries_sends_filters_and_cursor_and_parses_a_page(make: Callable[[Handler], Recorder]) -> None:
    body = {"items": [DELIVERY, {**DELIVERY, "id": 18, "status": "pending"}], "next_cursor": "c1"}
    rec = make(lambda request: json_response(body))
    result = rec.client.list_deliveries(subscription_id=SUBSCRIPTION["id"], status="delivered", limit=10, cursor="c0")
    assert len(rec.requests) == 1
    assert rec.last.url.path == "/webhooks/deliveries"
    assert dict(rec.last.url.params) == {
        "subscription_id": SUBSCRIPTION["id"],
        "status": "delivered",
        "limit": "10",
        "cursor": "c0",
    }
    assert type(result).__name__ == "DeliveryPage"
    assert result.next_cursor == "c1"
    assert [d.id for d in result.items] == [17, 18]
    first = result.items[0]
    assert isinstance(first, Delivery)
    assert (first.event_id, first.event_type, first.attempt, first.last_status_code) == (1234, "payment.final", 2, 200)
    assert first.next_attempt_at is None
    assert first.updated_at == datetime(2026, 11, 5, 14, 3, 26, tzinfo=UTC)


def test_list_deliveries_without_filters_sends_no_query_and_the_last_page_has_no_cursor(
    make: Callable[[Handler], Recorder],
) -> None:
    rec = make(lambda request: json_response({"items": [], "next_cursor": None}))
    result = rec.client.list_deliveries()
    assert not isinstance(result, list)
    assert (result.items, result.next_cursor) == ([], None)
    assert len(rec.requests) == 1
    assert rec.last.url.query == b""


def test_a_page_without_next_cursor_key_is_the_last_page(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({"items": [DELIVERY]}))
    result = rec.client.list_deliveries()
    assert not isinstance(result, list)
    assert result.next_cursor is None


def test_iter_deliveries_follows_cursors_and_keeps_the_filters(make: Callable[[Handler], Recorder]) -> None:
    pages = {
        None: ([{**DELIVERY, "id": 3}, {**DELIVERY, "id": 2}], "c1"),
        "c1": ([{**DELIVERY, "id": 1}], None),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        items, cursor = pages[request.url.params.get("cursor")]
        return json_response({"items": items, "next_cursor": cursor})

    rec = make(handler)
    ids = [d.id for d in rec.client.iter_deliveries(status="failed", limit=2)]
    assert ids == [3, 2, 1]
    assert [r.url.params.get("cursor") for r in rec.requests] == [None, "c1"]
    assert all(r.url.params["status"] == "failed" and r.url.params["limit"] == "2" for r in rec.requests)


def test_iter_deliveries_is_lazy(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({"items": [DELIVERY], "next_cursor": "more"}))
    iterator = rec.client.iter_deliveries()
    assert rec.requests == []
    assert next(iterator).id == DELIVERY["id"]
    assert len(rec.requests) == 1


def test_get_delivery_includes_the_attempts(make: Callable[[Handler], Recorder]) -> None:
    body = {**DELIVERY, "attempts": [ATTEMPT, {**ATTEMPT, "attempt": 2, "status_code": 200, "extra": 1}]}
    rec = make(lambda request: json_response(body))
    detail = rec.client.get_delivery(17)
    assert len(rec.requests) == 1
    assert rec.last.url.path == "/webhooks/deliveries/17"
    assert isinstance(detail, DeliveryDetail)
    assert [a.attempt for a in detail.attempts] == [1, 2]
    assert (detail.attempts[0].status_code, detail.attempts[0].duration_ms) == (503, 12)
    assert detail.attempts[0].attempted_at == datetime(2026, 11, 5, 14, 3, 24, 100000, tzinfo=UTC)


SUMMARY = {
    "delivered": 18,
    "failed": 2,
    "pending": 1,
    "success_rate": 0.9,
    "since": "2026-11-05T00:00:00.000Z",
    "until": None,
    "subscription_id": None,
}


def test_delivery_summary_sends_the_window_and_parses(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(SUMMARY))
    since = datetime(2026, 11, 5, tzinfo=UTC)
    summary = rec.client.delivery_summary(since=since, until="2026-11-06T00:00:00Z", subscription_id=SUBSCRIPTION["id"])
    assert len(rec.requests) == 1
    assert rec.last.url.path == "/webhooks/deliveries/summary"
    params = rec.last.url.params
    assert datetime.fromisoformat(params["since"]) == since
    assert params["until"] == "2026-11-06T00:00:00Z"
    assert params["subscription_id"] == SUBSCRIPTION["id"]
    assert isinstance(summary, DeliverySummary)
    assert (summary.delivered, summary.failed, summary.pending, summary.success_rate) == (18, 2, 1, 0.9)
    assert summary.since == since
    assert summary.until is None


def test_delivery_summary_with_no_final_deliveries_has_a_null_rate(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response({**SUMMARY, "delivered": 0, "failed": 0, "success_rate": None}))
    summary = rec.client.delivery_summary()
    assert len(rec.requests) == 1
    assert rec.last.url.query == b""
    assert summary.success_rate is None


def test_a_missing_optional_field_in_a_response_does_not_break_parsing(make: Callable[[Handler], Recorder]) -> None:
    body = {key: value for key, value in SUBSCRIPTION.items() if key != "active"}
    rec = make(lambda request: httpx.Response(200, json=body))
    sub = rec.client.get_subscription("x")
    assert len(rec.requests) == 1
    assert sub.id == SUBSCRIPTION["id"]
