"""Detection rule (ADR-0014): open an incident when the router starts avoiding a processor, record recovery.

The rule reads `payment.routed.data.health`, the snapshot the router itself used, so an incident always agrees with
routing and the routing threshold is not copied. Everything for one stream entry happens in one database transaction:
the change and the per-processor bookkeeping (`incident_detector_state.last_event_id`). An entry whose event id is not
newer than the last one applied for that processor is ignored, so a duplicate, redelivered or late entry can neither
reopen a resolved incident nor move `recovered_at`. The row lock on the bookkeeping row serialises two detectors, and
the unique partial index on open incidents is the last guard against a second open incident.
"""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import OPEN_INCIDENT, Incident, IncidentDetectorState, PaymentEvent
from app.domain.reasons import EventType
from app.incidents.linking import link_failures, lookback
from app.incidents.state import DETECTED, RESOLVED
from app.routing.health import AVOIDED, PREFERRED, PROCESSORS


def open_incident(
    session: Session, processor: str | None, source: str, title: str, opened_at: datetime, event_id: int | None
) -> uuid.UUID | None:
    """Insert a `detected` incident; None when the processor already has an open one (the unique index decides)."""
    statement = (
        insert(Incident)
        .values(
            id=uuid.uuid4(),
            processor=processor,
            source=source,
            status=DETECTED,
            title=title,
            opened_at=opened_at,
            opened_by_event_id=event_id,
        )
        .on_conflict_do_nothing(index_elements=[Incident.processor], index_where=OPEN_INCIDENT)
        .returning(Incident.id)
    )
    return session.execute(statement).scalar_one_or_none()


def _lock_state(session: Session, processor: str) -> int:
    """Create the bookkeeping row if needed, lock it and return the last event id applied."""
    session.execute(
        insert(IncidentDetectorState)
        .values(processor=processor, last_event_id=0)
        .on_conflict_do_nothing(index_elements=[IncidentDetectorState.processor])
    )
    return int(
        session.execute(
            sa.select(IncidentDetectorState.last_event_id)
            .where(IncidentDetectorState.processor == processor)
            .with_for_update()
        ).scalar_one()
    )


def _health_states(event: PaymentEvent) -> dict[str, str]:
    health: Any = (event.data or {}).get("health")
    if not isinstance(health, dict):
        return {}
    states: dict[str, str] = {}
    for processor in PROCESSORS:
        entry = health.get(processor)
        if isinstance(entry, dict) and isinstance(entry.get("state"), str):
            states[processor] = entry["state"]
    return states


def apply_routed_event(factory: sessionmaker[Session], event_id: int) -> list[str]:
    """Apply one `payment.routed` event in one transaction; return the processors that got a new incident."""
    opened: list[str] = []
    with factory.begin() as session:
        event = session.get(PaymentEvent, event_id)
        if event is None or event.type != EventType.PAYMENT_ROUTED.value:
            return opened
        for processor, state in _health_states(event).items():  # A then B: one lock order for every detector
            if event_id <= _lock_state(session, processor):
                continue
            if state == AVOIDED:
                title = f"Processor {processor} is being avoided by routing"
                if open_incident(session, processor, "rule", title, event.occurred_at, event_id) is not None:
                    opened.append(processor)
            # Every failure up to this event belongs to each open, unrecovered incident of the processor; the primary
            # key makes a repeat a no-op, and the recovery event itself still links before `recovered_at` is set.
            for incident_id, opened_at in session.execute(
                sa.select(Incident.id, Incident.opened_at).where(
                    Incident.processor == processor, Incident.status != RESOLVED, Incident.recovered_at.is_(None)
                )
            ).all():
                link_failures(session, incident_id, processor, opened_at - lookback(), event.occurred_at)
            if state == PREFERRED:
                # `unknown` is not recovery: an avoided processor gets no traffic, so its failures age out even while
                # it is still down. Only fresh successful attempts (`preferred`) show that health returned.
                session.execute(
                    sa.update(Incident)
                    .where(
                        Incident.processor == processor,
                        Incident.source == "rule",
                        Incident.status != RESOLVED,
                        Incident.recovered_at.is_(None),
                    )
                    .values(recovered_at=event.occurred_at)
                )
            session.execute(
                sa.update(IncidentDetectorState)
                .where(IncidentDetectorState.processor == processor)
                .values(last_event_id=event_id)
            )
    return opened
