"""POST /payments (api-contract.md). The API key (401) is checked by the middleware in app.main.

The order of checks is fixed by the contract: Idempotency-Key header (400), then body validation (422), then the
key is claimed. The body is validated here rather than by FastAPI so that the header check really comes first and
so that errors use the shared 422 shape with a readable message.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.cursor import decode_cursor, encode_cursor
from app.api.schemas import (
    PaymentCreate,
    PaymentDetailResponse,
    PaymentListResponse,
    PaymentResponse,
    iso_utc,
)
from app.config import get_settings
from app.db.models import Payment, PaymentEvent
from app.errors import ApiError, error_response
from app.idempotency.service import Claimed, claim, create_once, request_hash

router = APIRouter()

DISPLAY_STATUS = {
    "received": "Received",
    "routed": "Processing",
    "authorized": "Processing",
    "captured": "Captured",
    "declined": "Declined",
}
IDEMPOTENCY_KEY_MAX = 255
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def payment_body(payment: Payment) -> dict[str, Any]:
    """The Payment resource as stored for replays: JSON-native values only."""
    if payment.status == "failed":
        display = "Failed" if payment.is_final else "Retrying"
    else:
        display = DISPLAY_STATUS[payment.status]
    return {
        "id": str(payment.id),
        "amount_minor": payment.amount_minor,
        "currency": payment.currency,
        "description": payment.description,
        "reference": payment.reference,
        "status": payment.status,
        "attempt_no": payment.attempt_no,
        "is_final": payment.is_final,
        "display_status": display,
        "processor": payment.processor,
        "created_at": iso_utc(payment.created_at),
        "status_changed_at": iso_utc(payment.status_changed_at),
        "final_at": iso_utc(payment.final_at) if payment.final_at else None,
    }


def _validated_key(value: str | None) -> str:
    if not value:
        raise ApiError(400, "idempotency_key_missing", "the Idempotency-Key header is required")
    if len(value) > IDEMPOTENCY_KEY_MAX or not all(" " <= char <= "~" for char in value):
        raise ApiError(400, "malformed_request", "Idempotency-Key must be 1 to 255 printable ASCII characters")
    return value


def _invalid_body(request: Request, exc: ValidationError) -> JSONResponse:
    details: list[dict[str, str]] = []
    parts: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "body"
        if error["type"] == "value_error":  # the currency table check
            details.append({"field": field, "issue": "not_supported"})
            parts.append(f"{field} {str(error['msg']).removeprefix('Value error, ')}")
        else:
            details.append({"field": field, "issue": error["type"]})
            parts.append(f"{field}: {error['msg']}")
    return error_response(request, 422, "validation_failed", "; ".join(parts), details=details)


def _stored(status: int, body: dict[str, Any], replayed: bool) -> JSONResponse:
    headers = {"Location": f"/payments/{body['id']}"}
    if replayed:
        headers["Idempotent-Replayed"] = "true"
    return JSONResponse(body, status_code=status, headers=headers)


@router.post(
    "/payments",
    status_code=201,
    response_model=PaymentResponse,
    summary="Create a payment",
    description="Creates a payment in `received`. A repeat with the same Idempotency-Key and body returns the "
    "stored first response with `Idempotent-Replayed: true`.",
    responses={
        201: {
            "description": "Created, or a replay of the first response",
            "headers": {
                "Location": {"description": "/payments/{id}", "schema": {"type": "string"}},
                "Idempotent-Replayed": {
                    "description": "`true` when this is the stored first response of a repeated request",
                    "schema": {"type": "string"},
                },
            },
        }
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": PaymentCreate.model_json_schema()}},
        }
    },
)
async def create_payment_endpoint(
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="1 to 255 printable ASCII characters",
            json_schema_extra={"minLength": 1, "maxLength": IDEMPOTENCY_KEY_MAX},
        ),
    ] = None,
    body: Annotated[Any, Body()] = None,
) -> Response:
    key = _validated_key(idempotency_key)
    try:
        fields = PaymentCreate.model_validate({} if body is None else body).model_dump()
    except ValidationError as exc:
        return _invalid_body(request, exc)

    settings = get_settings()
    engine = request.app.state.engine
    claimed = await run_in_threadpool(
        claim,
        engine,
        key,
        request_hash(fields),
        ttl_hours=settings.idempotency_ttl_hours,
        lease_seconds=settings.idempotency_lease_seconds,
    )
    if not isinstance(claimed, Claimed):
        return _stored(claimed.status, claimed.body, replayed=True)
    created = await run_in_threadpool(
        create_once,
        engine,
        key,
        claimed.token,
        fields=fields,
        correlation_id=request.state.correlation_id,
        render=payment_body,
    )
    return _stored(201, created, replayed=False)


def _event_body(event: PaymentEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "type": event.type,
        "attempt_no": event.attempt_no,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "processor": event.processor,
        "reason": event.reason,
        "data": event.data,
        "occurred_at": iso_utc(event.occurred_at),
    }


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "payment not found")


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentDetailResponse,
    summary="Get a payment with its event timeline",
    description="Returns the payment and every event in `seq` order. 404 for an unknown id and for an id that is "
    "not a UUID.",
)
def get_payment(payment_id: str, request: Request) -> dict[str, Any]:
    try:
        pid = uuid.UUID(payment_id)
        if len(payment_id) != 36:  # UUID() also accepts braces, urn: prefixes and bare hex
            raise ValueError(payment_id)
    except ValueError:
        raise _not_found() from None
    with Session(request.app.state.engine) as session:
        payment = session.get(Payment, pid)
        if payment is None:
            raise _not_found()
        events = session.scalars(
            sa.select(PaymentEvent).where(PaymentEvent.payment_id == pid).order_by(PaymentEvent.seq)
        ).all()
        return {**payment_body(payment), "events": [_event_body(e) for e in events]}


def _encode_cursor(payment: Payment) -> str:
    return encode_cursor(payment.created_at, str(payment.id))


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    created_at, key = decode_cursor(cursor)
    try:
        return created_at, uuid.UUID(key)
    except ValueError:
        raise ApiError(400, "malformed_request", "cursor is malformed") from None


@router.get(
    "/payments",
    response_model=PaymentListResponse,
    summary="List payments, newest first",
    description="Keyset pagination on `(created_at, id)` descending. Pass `next_cursor` as `cursor` for the next "
    "page; it is null on the last page.",
)
def list_payments(
    request: Request,
    status: Annotated[
        list[Literal["received", "routed", "authorized", "captured", "declined", "failed"]] | None, Query()
    ] = None,
    processor: Annotated[Literal["A", "B"] | None, Query()] = None,
    is_final: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(description="The opaque `next_cursor` of the previous page")] = None,
) -> dict[str, Any]:
    after = _decode_cursor(cursor) if cursor is not None else None
    query = sa.select(Payment).order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit + 1)
    if status:
        query = query.where(Payment.status.in_(status))
    if processor is not None:
        query = query.where(Payment.processor == processor)
    if is_final is not None:
        query = query.where(Payment.is_final == is_final)
    if after is not None:
        query = query.where(sa.tuple_(Payment.created_at, Payment.id) < sa.tuple_(*after))
    with Session(request.app.state.engine) as session:
        rows = list(session.scalars(query))
    page = rows[:limit]
    return {
        "items": [payment_body(p) for p in page],
        "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None,
    }
