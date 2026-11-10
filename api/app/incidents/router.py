"""Incident endpoints (REL-34, api-contract.md). The API key (401) is checked by the middleware in app.main."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import iso_utc
from app.db.models import Incident, IncidentPayment
from app.errors import ApiError
from app.incidents.detector import open_incident
from app.incidents.linking import link_failures, load_facts, lookback
from app.incidents.state import TRIAGED, can_transition
from app.incidents.summary_store import (
    IncidentNotFoundError,
    StoredSummary,
    latest_summary,
    summarize_incident,
)
from app.metrics import INCIDENTS_OPENED

router = APIRouter()

Processor = Literal["A", "B"]
Status = Literal["detected", "triaged", "resolved"]
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class IncidentResponse(BaseModel):
    id: str
    processor: str | None
    source: str
    status: str
    title: str
    opened_at: str
    opened_by_event_id: int | None
    recovered_at: str | None
    triaged_at: str | None
    resolved_at: str | None
    created_at: str


class IncidentListItem(IncidentResponse):
    affected_count: int


class IncidentEvent(BaseModel):
    id: int
    type: str
    reason: str | None
    processor: str | None
    occurred_at: str


class AffectedPayment(BaseModel):
    id: str
    status: str
    amount_minor: int
    currency: str
    processor: str | None
    events: list[IncidentEvent]


class IncidentDetailResponse(IncidentListItem):
    affected_payments: list[AffectedPayment]


class SummaryResponse(BaseModel):
    incident_id: str
    source: str
    model: str | None
    text: str
    cited_event_ids: list[int]
    cause: str
    trigger: str
    generated_at: str
    fallback_reason: str | None


class IncidentListResponse(BaseModel):
    items: list[IncidentListItem]


class IncidentCreate(BaseModel):
    processor: Processor | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TransitionRequest(BaseModel):
    to: Status


def _iso(moment: datetime | None) -> str | None:
    return iso_utc(moment) if moment is not None else None


def _body(row: Incident) -> IncidentResponse:
    return IncidentResponse(
        id=str(row.id),
        processor=row.processor,
        source=row.source,
        status=row.status,
        title=row.title,
        opened_at=iso_utc(row.opened_at),
        opened_by_event_id=row.opened_by_event_id,
        recovered_at=_iso(row.recovered_at),
        triaged_at=_iso(row.triaged_at),
        resolved_at=_iso(row.resolved_at),
        created_at=iso_utc(row.created_at),
    )


def _incident_id(raw: str) -> uuid.UUID:
    try:
        value = uuid.UUID(raw)
        if len(raw) != 36:  # UUID() also accepts braces, urn: prefixes and bare hex
            raise ValueError(raw)
    except ValueError:
        raise ApiError(404, "not_found", "incident not found") from None
    return value


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    summary="List incidents, newest first",
    description="Each incident carries `affected_count`, the number of payments linked to it.",
)
def list_incidents(
    request: Request,
    status: Annotated[Status | None, Query()] = None,
    processor: Annotated[Processor | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> IncidentListResponse:
    # The count is a correlated subquery in the list query itself: one statement however many incidents (REL-57).
    affected = (
        sa.select(sa.func.count())
        .select_from(IncidentPayment)
        .where(IncidentPayment.incident_id == Incident.id)
        .scalar_subquery()
    )
    query = sa.select(Incident, affected).order_by(
        Incident.opened_at.desc(), Incident.created_at.desc(), Incident.id.desc()
    )
    if status is not None:
        query = query.where(Incident.status == status)
    if processor is not None:
        query = query.where(Incident.processor == processor)
    with Session(request.app.state.engine) as session:
        rows = session.execute(query.limit(limit)).all()
        return IncidentListResponse(
            items=[IncidentListItem(**_body(row).model_dump(), affected_count=count) for row, count in rows]
        )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetailResponse,
    summary="Get one incident with its affected payments",
    description="The Incident plus `affected_payments`: each linked payment and its incident-relevant events "
    "(failures on the incident's processor). A manual incident without a processor has none.",
)
def get_incident(incident_id: str, request: Request) -> IncidentDetailResponse:
    iid = _incident_id(incident_id)
    with Session(request.app.state.engine) as session:
        row = session.get(Incident, iid)
        if row is None:
            raise ApiError(404, "not_found", "incident not found")
        facts = load_facts(session, row)
        base = _body(row)
    events: dict[str, list[IncidentEvent]] = {}
    for e in facts.events:
        events.setdefault(e.payment_id, []).append(
            IncidentEvent(
                id=e.id, type=e.type, reason=e.reason, processor=e.processor, occurred_at=iso_utc(e.occurred_at)
            )
        )
    payments = [
        AffectedPayment(
            id=p.id,
            status=p.status,
            amount_minor=p.amount_minor,
            currency=p.currency,
            processor=p.processor,
            events=events.get(p.id, []),
        )
        for p in facts.payments
    ]
    return IncidentDetailResponse(**base.model_dump(), affected_count=len(payments), affected_payments=payments)


@router.post(
    "/incidents",
    status_code=201,
    response_model=IncidentResponse,
    summary="Open an incident by hand",
    description="`processor` is optional. A processor that already has an open incident returns 409 "
    "`incident_already_open`.",
)
def create_incident(body: IncidentCreate, request: Request) -> IncidentResponse:
    now = datetime.now(UTC)
    with Session(request.app.state.engine) as session, session.begin():
        new_id = open_incident(session, body.processor, "manual", body.title, now, None)
        if new_id is None:
            raise ApiError(409, "incident_already_open", f"processor {body.processor} already has an open incident")
        if body.processor is not None:  # the failures that preceded it, like the detector's lookback at open
            link_failures(session, new_id, body.processor, now - lookback(), now)
        row = session.get(Incident, new_id)
        assert row is not None
        response = _body(row)
    if body.processor is not None:
        INCIDENTS_OPENED.labels(body.processor, "manual").inc()
    return response


@router.post(
    "/incidents/{incident_id}/transitions",
    response_model=IncidentResponse,
    summary="Triage or resolve an incident",
    description="Only detected to triaged and triaged to resolved; anything else is 409 `invalid_incident_transition`.",
)
def transition_incident(incident_id: str, body: TransitionRequest, request: Request) -> IncidentResponse:
    iid = _incident_id(incident_id)
    with Session(request.app.state.engine) as session, session.begin():
        row = session.scalar(sa.select(Incident).where(Incident.id == iid).with_for_update())
        if row is None:
            raise ApiError(404, "not_found", "incident not found")
        if not can_transition(row.status, body.to):
            raise ApiError(409, "invalid_incident_transition", f"cannot move from {row.status} to {body.to}")
        updates: dict[str, Any] = {"status": body.to}
        updates["triaged_at" if body.to == TRIAGED else "resolved_at"] = datetime.now(UTC)
        for key, value in updates.items():
            setattr(row, key, value)
        session.flush()
        response = _body(row)
    return response


def _summary_body(stored: StoredSummary) -> dict[str, Any]:
    return {
        "incident_id": str(stored.incident_id),
        "source": stored.source,
        "model": stored.model,
        "text": stored.text,
        "cited_event_ids": list(stored.cited_event_ids),
        "cause": stored.cause,
        "trigger": stored.trigger,
        "generated_at": iso_utc(stored.generated_at),
        "fallback_reason": stored.fallback_reason,
    }


def _generate(request: Request, iid: uuid.UUID, trigger: str) -> StoredSummary:
    factory = sessionmaker(request.app.state.engine, expire_on_commit=False)
    try:
        return summarize_incident(factory, iid, trigger, getattr(request.app.state, "model_client", None))
    except IncidentNotFoundError:
        raise ApiError(404, "not_found", "incident not found") from None


@router.get(
    "/incidents/{incident_id}/summary",
    response_model=SummaryResponse,
    summary="Get the latest summary of an incident",
    description="Returns the latest stored summary, labelled with its source (`model` or `rules`). An incident "
    "without one gets one generated and stored with `trigger=on_request`; regeneration is the POST, so prefetching "
    "or retried reads never call the model again.",
)
def get_summary(incident_id: str, request: Request) -> dict[str, Any]:
    iid = _incident_id(incident_id)
    with Session(request.app.state.engine) as session:
        if session.get(Incident, iid) is None:
            raise ApiError(404, "not_found", "incident not found")
        stored = latest_summary(session, iid)
    return _summary_body(stored or _generate(request, iid, "on_request"))


@router.post(
    "/incidents/{incident_id}/summary/regenerate",
    response_model=SummaryResponse,
    status_code=201,
    summary="Generate a new summary of an incident now",
    description="Stores a new summary with `trigger=regenerate` and returns it. 404 for an unknown incident.",
)
def regenerate_summary(incident_id: str, request: Request) -> JSONResponse:
    return JSONResponse(_summary_body(_generate(request, _incident_id(incident_id), "regenerate")), status_code=201)
