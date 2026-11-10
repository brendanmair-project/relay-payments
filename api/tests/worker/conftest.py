"""Worker tests reuse the committing-session fixtures and a clean stream; the processor is faked with MockTransport."""

import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import PaymentEvent
from app.worker.consumer import GROUP, STREAM
from app.worker.processor import ProcessorClient
from tests.services.conftest import clean_tables, correlation, engine, factory, payment_id  # noqa: F401

APPROVED = (200, {"result": "approved", "reason": None, "latency_ms": 120})
DECLINED = (200, {"result": "declined", "reason": "do_not_honor", "latency_ms": 90})
CAPTURED = (200, {"result": "captured", "reason": None, "latency_ms": 80})
CAPTURE_FAILED = (200, {"result": "failed", "reason": "capture_failed", "latency_ms": 70})
OUTAGE = (503, {"error": {"code": "processor_outage", "message": "outage"}})
TIMEOUT = "timeout"  # the fake raises httpx.ReadTimeout


class FakeProcessor:
    """Records every request; `authorize` and `capture` are (status, json), TIMEOUT, or a callable run first."""

    def __init__(
        self, authorize: Any = APPROVED, capture: Any = CAPTURED, on_call: Callable[[str], None] | None = None
    ):
        self.script = {"authorize": authorize, "capture": capture}
        self.on_call = on_call
        self.requests: list[httpx.Request] = []
        self.client = ProcessorClient("http://sim", 5, transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        operation = request.url.path.rsplit("/", 1)[-1]
        if self.on_call is not None:
            self.on_call(operation)
        answer = self.script[operation]
        if answer == TIMEOUT:
            raise httpx.ReadTimeout("timed out", request=request)
        status, body = answer
        return httpx.Response(status, json=body)

    def operations(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[-1] for r in self.requests]


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    client.delete(STREAM)
    yield client
    client.delete(STREAM)
    client.close()


def trigger(client: Redis, pid: uuid.UUID, type_: str = "payment.received", attempt_no: int = 0) -> str:
    return str(
        client.xadd(
            STREAM,
            {
                "event_id": "1",
                "payment_id": str(pid),
                "seq": "1",
                "attempt_no": str(attempt_no),
                "type": type_,
                "correlation_id": "corr-test",
            },
        )
    )


def pending(client: Redis) -> int:
    return int(client.xpending(STREAM, GROUP)["pending"])


def timeline(sf: sessionmaker[Session], pid: uuid.UUID) -> list[PaymentEvent]:
    with sf() as session:
        return list(
            session.scalars(sa.select(PaymentEvent).where(PaymentEvent.payment_id == pid).order_by(PaymentEvent.seq))
        )


def types(sf: sessionmaker[Session], pid: uuid.UUID) -> list[str]:
    return [e.type for e in timeline(sf, pid)]
