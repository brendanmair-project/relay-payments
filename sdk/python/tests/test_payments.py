"""Payments: headers, idempotency keys, parsing, paging (REL-41)."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from conftest import API_KEY, EVENT, PAYMENT, Handler, Recorder, body_of, json_response

from relay_sdk import Payment, PaymentEvent, PaymentPage, RelayClient


def created(request: httpx.Request) -> httpx.Response:
    return json_response(PAYMENT, 201, {"Location": f"/payments/{PAYMENT['id']}"})


def test_every_request_carries_the_api_key(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    rec.client.create_payment(1999, "USD")
    assert len(rec.requests) == 1
    assert rec.last.headers["X-API-Key"] == API_KEY
    assert rec.last.url == httpx.URL("http://relay.test/payments")


def test_create_sends_the_body_and_only_the_fields_given(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    rec.client.create_payment(1999, "USD")
    assert len(rec.requests) == 1
    assert rec.last.method == "POST"
    assert body_of(rec.last) == {"amount_minor": 1999, "currency": "USD"}
    rec.client.create_payment(500, "EUR", description="Order 4471", reference="order-4471")
    assert body_of(rec.last) == {
        "amount_minor": 500,
        "currency": "EUR",
        "description": "Order 4471",
        "reference": "order-4471",
    }


def test_create_generates_a_uuid4_idempotency_key_when_none_is_given(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    rec.client.create_payment(1999, "USD")
    rec.client.create_payment(1999, "USD")
    assert len(rec.requests) == 2
    keys = [r.headers["Idempotency-Key"] for r in rec.requests]
    assert all(uuid.UUID(k).version == 4 for k in keys)
    assert keys[0] != keys[1]


def test_create_uses_the_idempotency_key_it_is_given(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    rec.client.create_payment(1999, "USD", idempotency_key="order-4471-attempt-1")
    assert len(rec.requests) == 1
    assert rec.last.headers["Idempotency-Key"] == "order-4471-attempt-1"


def test_create_returns_the_payment_and_not_replayed_for_a_first_request(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    result = rec.client.create_payment(1999, "USD")
    assert len(rec.requests) == 1
    assert result.replayed is False
    assert result.payment.id == PAYMENT["id"]
    assert result.payment.amount_minor == 1999


def test_create_reports_a_replay_from_the_header(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(PAYMENT, 201, {"Idempotent-Replayed": "true"}))
    result = rec.client.create_payment(1999, "USD", idempotency_key="k")
    assert len(rec.requests) == 1
    assert result.replayed is True


def test_payment_fields_are_parsed_into_typed_values(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    payment = rec.client.create_payment(1999, "USD").payment
    assert len(rec.requests) == 1
    assert isinstance(payment, Payment)
    assert payment.currency == "USD"
    assert payment.description == "Order 4471"
    assert payment.reference == "order-4471"
    assert payment.status == "captured"
    assert payment.attempt_no == 1
    assert payment.is_final is True
    assert payment.display_status == "Captured"
    assert payment.processor == "A"
    assert payment.created_at == datetime(2026, 11, 5, 14, 3, 22, 418000, tzinfo=UTC)
    assert payment.final_at == datetime(2026, 11, 5, 14, 3, 23, 1000, tzinfo=UTC)


def test_null_fields_parse_as_none(make: Callable[[Handler], Recorder]) -> None:
    body = {**PAYMENT, "description": None, "reference": None, "processor": None, "final_at": None, "is_final": False}
    rec = make(lambda request: json_response(body, 201))
    payment = rec.client.create_payment(1, "USD").payment
    assert len(rec.requests) == 1
    assert (payment.description, payment.reference, payment.processor, payment.final_at) == (None, None, None, None)


def test_unknown_response_fields_do_not_break_parsing(make: Callable[[Handler], Recorder]) -> None:
    body = {**PAYMENT, "brand_new_field": {"nested": 1}, "events": [{**EVENT, "also_new": True}]}
    rec = make(lambda request: json_response(body))
    payment = rec.client.get_payment(PAYMENT["id"])
    assert len(rec.requests) == 1
    assert payment.id == PAYMENT["id"]
    assert len(payment.events) == 1


def test_get_payment_requests_the_id_and_parses_events(make: Callable[[Handler], Recorder]) -> None:
    events = [EVENT, {**EVENT, "seq": 2, "data": {"latency_ms": 812}}]
    rec = make(lambda request: json_response({**PAYMENT, "events": events}))
    payment = rec.client.get_payment(PAYMENT["id"])
    assert len(rec.requests) == 1
    assert rec.last.method == "GET"
    assert rec.last.url.path == f"/payments/{PAYMENT['id']}"
    assert [e.seq for e in payment.events] == [1, 2]
    first = payment.events[0]
    assert isinstance(first, PaymentEvent)
    assert (first.type, first.from_status, first.to_status) == ("payment.received", None, "received")
    assert payment.events[1].data == {"latency_ms": 812}
    assert first.occurred_at == datetime(2026, 11, 5, 14, 3, 22, 418000, tzinfo=UTC)


def test_a_payment_without_events_has_an_empty_list(make: Callable[[Handler], Recorder]) -> None:
    rec = make(created)
    assert rec.client.create_payment(1, "USD").payment.events == []
    assert len(rec.requests) == 1


def test_get_payment_quotes_the_id_in_the_path(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(PAYMENT))
    rec.client.get_payment("../health")
    assert len(rec.requests) == 1
    assert rec.last.url.raw_path == b"/payments/..%2Fhealth"


def page(items: list[dict[str, object]], cursor: str | None) -> httpx.Response:
    return json_response({"items": items, "next_cursor": cursor})


def test_list_sends_filters_limit_and_cursor_as_query(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: page([PAYMENT], "abc"))
    result = rec.client.list_payments(
        status=["failed", "declined"], processor="B", limit=5, cursor="xyz", is_final=True
    )
    assert len(rec.requests) == 1
    params = rec.last.url.params
    assert params.get_list("status") == ["failed", "declined"]
    assert params["processor"] == "B"
    assert params["limit"] == "5"
    assert params["cursor"] == "xyz"
    assert params["is_final"] == "true"
    assert isinstance(result, PaymentPage)
    assert result.next_cursor == "abc"
    assert [p.id for p in result.items] == [PAYMENT["id"]]


def test_list_sends_no_query_when_nothing_is_given_and_accepts_one_status(
    make: Callable[[Handler], Recorder],
) -> None:
    rec = make(lambda request: page([], None))
    result = rec.client.list_payments()
    assert len(rec.requests) == 1
    assert rec.last.url.query == b""
    assert result.items == []
    assert result.next_cursor is None
    rec.client.list_payments(status="failed")
    assert rec.last.url.params.get_list("status") == ["failed"]


def test_iter_payments_follows_cursors_and_stops_at_the_last_page(make: Callable[[Handler], Recorder]) -> None:
    pages = {
        None: ([{**PAYMENT, "id": "p1"}, {**PAYMENT, "id": "p2"}], "c1"),
        "c1": ([{**PAYMENT, "id": "p3"}], None),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        items, cursor = pages[request.url.params.get("cursor")]
        return page(items, cursor)

    rec = make(handler)
    ids = [p.id for p in rec.client.iter_payments(limit=2, processor="A")]
    assert len(rec.requests) == 2
    assert ids == ["p1", "p2", "p3"]
    assert [r.url.params.get("cursor") for r in rec.requests] == [None, "c1"]
    assert all(r.url.params["limit"] == "2" and r.url.params["processor"] == "A" for r in rec.requests)


def test_iter_payments_is_lazy(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: page([PAYMENT], "more"))
    iterator = rec.client.iter_payments()
    assert rec.requests == []
    assert next(iterator).id == PAYMENT["id"]
    assert len(rec.requests) == 1


def test_context_manager_closes_the_client() -> None:
    with RelayClient("http://relay.test", "k", transport=httpx.MockTransport(created)) as client:
        client.create_payment(1, "USD")
    with pytest.raises(RuntimeError):
        client.create_payment(1, "USD")
