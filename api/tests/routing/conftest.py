"""Routing tests: real Postgres and Valkey, a processor faked with httpx MockTransport (as in tests/worker)."""

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import PaymentEvent
from app.services.transitions import create_payment
from app.worker.processor import ProcessorClient
from tests.services.conftest import clean_tables, correlation, engine, factory, payment_id  # noqa: F401
from tests.worker.conftest import redis_client  # noqa: F401

Answer = tuple[int, dict[str, Any]] | str


@pytest.fixture(autouse=True)
def default_routing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ROUTING_STRATEGY", "HEALTH_WINDOW_SECONDS", "HEALTH_MIN_ATTEMPTS", "HEALTH_ERROR_THRESHOLD"):
        monkeypatch.delenv(name, raising=False)


def seed(
    sf: sessionmaker[Session],
    processor: str,
    *,
    routed: int = 0,
    failed: int = 0,
    reason: str = "outage",
    declined: int = 0,
    age_seconds: int = 0,
) -> None:
    """Insert history events directly, `age_seconds` old, for health tests (one throwaway payment per call)."""
    with sf.begin() as session:
        pid = create_payment(session, amount_minor=100, currency="USD", correlation_id="seed")
        seq = 1
        rows = (
            [("payment.routed", "initial")] * routed
            + [("payment.failed", reason)] * failed
            + [("payment.declined", "do_not_honor")] * declined
        )
        for type_, why in rows:
            seq += 1
            session.execute(
                sa.insert(PaymentEvent).values(
                    payment_id=pid,
                    seq=seq,
                    attempt_no=1,
                    type=type_,
                    processor=processor,
                    reason=why,
                    correlation_id="seed",
                    occurred_at=sa.func.now() - timedelta(seconds=age_seconds),
                )
            )


class PerProcessorFake:
    """Answers per (processor, operation); the default is approve then capture."""

    def __init__(self, script: dict[tuple[str, str], Answer] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []
        self.client = ProcessorClient("http://sim", 5, transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        _, _, processor, operation = request.url.path.split("/")
        self.calls.append((processor.upper(), operation))
        default: Answer = (
            (200, {"result": "approved", "reason": None, "latency_ms": 10})
            if operation == "authorize"
            else (200, {"result": "captured", "reason": None, "latency_ms": 10})
        )
        answer = self.script.get((processor.upper(), operation), default)
        if isinstance(answer, str):
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(answer[0], json=answer[1])


Seed = Callable[..., None]


@pytest.fixture
def seeder(request: pytest.FixtureRequest) -> Iterator[Seed]:
    sf = request.getfixturevalue("factory")

    def run(processor: str, **kw: Any) -> None:
        seed(sf, processor, **kw)

    yield run
