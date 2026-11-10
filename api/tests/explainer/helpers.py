"""Build final and non-final payments through the transition service (the only way events are written)."""

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.domain.lifecycle import Event, PaymentState
from app.services.transitions import apply_transition, create_payment

SENTINEL = "relay-test-sentinel-description"
Step = tuple[Event, PaymentState, int, dict[str, Any]]
ROUTE_A: Step = (Event.ROUTE, PaymentState.RECEIVED, 0, {"processor": "A", "reason": "initial"})
DECLINE: Step = (Event.DECLINE, PaymentState.ROUTED, 1, {"reason": "insufficient_funds"})
FAIL_TIMEOUT: Step = (Event.FAIL, PaymentState.ROUTED, 1, {"reason": "timeout"})


def build(factory: sessionmaker[Session], steps: list[Step], **kw: Any) -> uuid.UUID:
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=1250, currency="USD", description=SENTINEL, **kw)
        for event, expected, attempt, extra in steps:
            apply_transition(
                session, pid, event, expected_status=expected, expected_attempt=attempt, retries_enabled=False, **extra
            )
    return pid


def declined(factory: sessionmaker[Session]) -> uuid.UUID:
    return build(factory, [ROUTE_A, DECLINE])


def failed_final(factory: sessionmaker[Session]) -> uuid.UUID:
    return build(factory, [ROUTE_A, FAIL_TIMEOUT])


def retrying(factory: sessionmaker[Session]) -> uuid.UUID:
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=1250, currency="USD", description=SENTINEL)
        for event, expected, attempt, extra in [ROUTE_A, FAIL_TIMEOUT]:
            apply_transition(
                session, pid, event, expected_status=expected, expected_attempt=attempt, retries_enabled=True, **extra
            )
    return pid


def captured(factory: sessionmaker[Session]) -> uuid.UUID:
    return build(
        factory,
        [
            ROUTE_A,
            (Event.AUTHORIZE, PaymentState.ROUTED, 1, {}),
            (Event.CAPTURE, PaymentState.AUTHORIZED, 1, {}),
        ],
    )
