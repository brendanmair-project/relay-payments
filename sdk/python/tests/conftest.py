"""Shared helpers: a client on httpx.MockTransport that records every request it sends (no network)."""

import json
import secrets
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from relay_sdk import RelayClient

Handler = Callable[[httpx.Request], httpx.Response]

BASE_URL = "http://relay.test"
API_KEY = "test-" + secrets.token_hex(8)  # generated at run time: no fixed key-like constant

PAYMENT: dict[str, Any] = {
    "id": "6f1d3c2a-0b6e-4a53-9a58-2f6d3b1a7c10",
    "amount_minor": 1999,
    "currency": "USD",
    "description": "Order 4471",
    "reference": "order-4471",
    "status": "captured",
    "attempt_no": 1,
    "is_final": True,
    "display_status": "Captured",
    "processor": "A",
    "created_at": "2026-11-05T14:03:22.418Z",
    "status_changed_at": "2026-11-05T14:03:23.001Z",
    "final_at": "2026-11-05T14:03:23.001Z",
}
EVENT: dict[str, Any] = {
    "seq": 1,
    "type": "payment.received",
    "attempt_no": 0,
    "from_status": None,
    "to_status": "received",
    "processor": None,
    "reason": None,
    "data": {},
    "occurred_at": "2026-11-05T14:03:22.418Z",
}
SUBSCRIPTION: dict[str, Any] = {
    "id": "0a8f1c34-76a1-4c09-8d57-1f1b0f3b9a21",
    "url": "http://webhook-sink:8200/hook",
    "event_types": ["payment.final"],
    "active": True,
    "created_at": "2026-11-05T14:00:00.000Z",
}
DELIVERY: dict[str, Any] = {
    "id": 17,
    "subscription_id": SUBSCRIPTION["id"],
    "event_id": 1234,
    "event_type": "payment.final",
    "attempt": 2,
    "status": "delivered",
    "next_attempt_at": None,
    "last_status_code": 200,
    "last_error": None,
    "created_at": "2026-11-05T14:03:24.000Z",
    "updated_at": "2026-11-05T14:03:26.000Z",
}
ATTEMPT: dict[str, Any] = {
    "attempt": 1,
    "status_code": 503,
    "error": None,
    "duration_ms": 12,
    "attempted_at": "2026-11-05T14:03:24.100Z",
}


def json_response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def body_of(request: httpx.Request) -> Any:
    return json.loads(request.content)


class Recorder:
    """A client plus the list of requests it sent."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        self.client = RelayClient(BASE_URL, API_KEY, transport=httpx.MockTransport(record))

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "the client sent no request"
        return self.requests[-1]


@pytest.fixture
def make() -> Callable[[Handler], Recorder]:
    return Recorder
