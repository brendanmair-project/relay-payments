"""Generate and store incident summaries (REL-35, mirrors app.explain.store).

The model call runs with no database transaction open: the facts are read in a session that is closed first, the
summary is generated, then one short transaction inserts the row. Rows are append-only; the endpoint reads the latest.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Incident, IncidentSummary
from app.explain.model import ModelClient
from app.incidents.linking import load_facts
from app.incidents.summary import IncidentFacts, generate_summary

TRIGGERS = ("on_request", "regenerate")


class IncidentNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class StoredSummary:
    incident_id: uuid.UUID
    source: str
    model: str | None
    text: str
    cited_event_ids: tuple[int, ...]
    cause: str
    trigger: str
    fallback_reason: str | None
    generated_at: datetime

    @classmethod
    def of(cls, row: IncidentSummary) -> "StoredSummary":
        return cls(
            row.incident_id,
            row.source,
            row.model,
            row.text,
            tuple(row.cited_event_ids),
            row.cause,
            row.trigger,
            row.fallback_reason,
            row.generated_at,
        )


def read_facts(factory: sessionmaker[Session], incident_id: uuid.UUID) -> IncidentFacts:
    """The incident's linked payments and events, read and released before any model call."""
    with factory() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise IncidentNotFoundError(str(incident_id))
        return load_facts(session, incident)


def latest_summary(session: Session, incident_id: uuid.UUID) -> StoredSummary | None:
    row = session.scalars(
        sa.select(IncidentSummary)
        .where(IncidentSummary.incident_id == incident_id)
        .order_by(IncidentSummary.generated_at.desc(), IncidentSummary.id.desc())
        .limit(1)
    ).first()
    return StoredSummary.of(row) if row else None


def summarize_incident(
    factory: sessionmaker[Session], incident_id: uuid.UUID, trigger: str, model: ModelClient | None
) -> StoredSummary:
    """Generate and store one summary. Raises IncidentNotFoundError for an unknown incident."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    facts = read_facts(factory, incident_id)
    generated = generate_summary(facts, model)
    with factory.begin() as session:
        row = IncidentSummary(
            incident_id=incident_id,
            source=generated.source,
            model=generated.model,
            text=generated.text,
            cited_event_ids=list(generated.cited_event_ids),
            cause=generated.cause,
            fallback_reason=generated.fallback_reason,
            generated_at=sa.func.clock_timestamp(),
            trigger=trigger,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        return StoredSummary.of(row)
