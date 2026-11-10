"""Write real `payment.routed` events through the transition service and push their stream entries."""

import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.db.models import PaymentEvent
from app.domain.lifecycle import Event, PaymentState
from app.outbox.publisher import STREAM
from app.services.transitions import apply_transition, create_payment

Factory = sessionmaker[Session]


def health(a: str = "preferred", b: str = "preferred") -> dict[str, dict[str, object]]:
    return {"A": {"state": a, "errors": 0, "attempts": 10}, "B": {"state": b, "errors": 0, "attempts": 10}}


def routed(factory: Factory, a: str = "preferred", b: str = "preferred", processor: str = "A") -> int:
    """Create a payment routed with the given health snapshot; return the id of its `payment.routed` event."""
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=1250, currency="USD", description=None)
        apply_transition(
            session,
            pid,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=False,
            processor=processor,
            reason="initial",
            data={"health": health(a, b)},
        )
        return int(
            session.scalar(
                sa.select(PaymentEvent.id).where(PaymentEvent.payment_id == pid, PaymentEvent.type == "payment.routed")
            )
            or 0
        )


def push(client: Redis, factory: Factory, event_id: int) -> str:
    """XADD the entry the publisher would write for this event (ids, not data)."""
    with factory() as session:
        event = session.get(PaymentEvent, event_id)
        assert event is not None
        fields = {
            "event_id": str(event.id),
            "payment_id": str(event.payment_id),
            "seq": str(event.seq),
            "attempt_no": str(event.attempt_no),
            "type": event.type,
            "correlation_id": event.correlation_id,
        }
    return str(client.xadd(STREAM, fields))


def routed_entry(client: Redis, factory: Factory, a: str = "preferred", b: str = "preferred") -> int:
    event_id = routed(factory, a, b)
    push(client, factory, event_id)
    return event_id


def occurred_at(factory: Factory, event_id: int) -> datetime:
    with factory() as session:
        event = session.get(PaymentEvent, event_id)
        assert event is not None
        return event.occurred_at


def incidents(factory: Factory) -> list[dict[str, object]]:
    with factory() as session:
        rows = session.execute(sa.text("SELECT * FROM incidents ORDER BY created_at, id")).mappings().all()
    return [dict(row) for row in rows]


SENTINEL = "relay-test-sentinel-description"


def seed_failure(
    factory: Factory,
    processor: str = "A",
    reason: str = "timeout",
    age_seconds: float = 0,
    kind: str = "payment.failed",
    amount_minor: int = 1250,
) -> tuple[uuid.UUID, int]:
    """One throwaway payment routed to `processor` with one failed-attempt event, `age_seconds` old.

    `kind` is `payment.failed` or an `attempt.*_result` type. Returns the payment id and the failure event's id.
    """
    at = sa.func.now() - timedelta(seconds=age_seconds)
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=amount_minor, currency="USD", description=SENTINEL)
        for seq, (type_, why) in enumerate([("payment.routed", "initial"), (kind, reason)], start=2):
            event_id = session.execute(
                sa.insert(PaymentEvent)
                .values(
                    payment_id=pid,
                    seq=seq,
                    attempt_no=1,
                    type=type_,
                    processor=processor,
                    reason=why,
                    correlation_id="seed",
                    occurred_at=at,
                )
                .returning(PaymentEvent.id)
            ).scalar_one()
    return pid, int(event_id)


def rescue(factory: Factory, pid: uuid.UUID) -> None:
    """The payment failed over to B and was captured there."""
    with factory.begin() as session:
        session.execute(
            sa.insert(PaymentEvent).values(
                payment_id=pid,
                seq=4,
                attempt_no=2,
                type="payment.routed",
                processor="B",
                reason="failover",
                correlation_id="seed",
            )
        )
        session.execute(
            sa.text(
                "UPDATE payments SET status = 'captured', attempt_no = 2, processor = 'B', is_final = true,"
                " final_at = now() WHERE id = :p"
            ),
            {"p": pid},
        )


def links(factory: Factory, incident_id: uuid.UUID | None = None) -> set[uuid.UUID]:
    """The payment ids linked to `incident_id` (the only incident when omitted)."""
    with factory() as session:
        rows = session.execute(sa.text("SELECT incident_id, payment_id FROM incident_payments")).all()
    if incident_id is None:
        assert len({r[0] for r in rows}) <= 1
        return {r[1] for r in rows}
    return {r[1] for r in rows if r[0] == incident_id}


def the_incident(factory: Factory) -> uuid.UUID:
    rows = incidents(factory)
    assert len(rows) == 1
    return uuid.UUID(str(rows[0]["id"]))
