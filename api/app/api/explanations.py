"""GET and POST /payments/{id}/explanation (REL-25.4, REL-25.10, api-contract.md). The API key is checked by the
middleware in app.main.

GET only reads, except that a final payment without an explanation gets one generated and stored
(`trigger=on_request`); regeneration is the POST, so prefetching or retried reads never call the model (ADR-0012).
The model is `app.state.model_client` (None: rules only); it never sees the payment description.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import ExplanationResponse, iso_utc
from app.errors import ApiError
from app.explain.store import (
    PaymentNotFinalError,
    StoredExplanation,
    explain_payment,
    latest_explanation,
)
from app.services.transitions import PaymentNotFoundError

router = APIRouter()


def _body(stored: StoredExplanation) -> dict[str, Any]:
    return {
        "payment_id": str(stored.payment_id),
        "source": stored.source,
        "model": stored.model,
        "text": stored.text,
        "cited_event_seqs": list(stored.cited_event_seqs),
        "trigger": stored.trigger,
        "generated_at": iso_utc(stored.generated_at),
        "fallback_reason": stored.fallback_reason,
    }


def _payment_id(raw: str) -> uuid.UUID:
    try:
        pid = uuid.UUID(raw)
        if len(raw) != 36:  # UUID() also accepts braces, urn: prefixes and bare hex
            raise ValueError(raw)
    except ValueError:
        raise ApiError(404, "not_found", "payment not found") from None
    return pid


def _generate(request: Request, pid: uuid.UUID, trigger: str) -> StoredExplanation:
    factory = sessionmaker(request.app.state.engine, expire_on_commit=False)
    try:
        stored = explain_payment(
            factory,
            pid,
            trigger,
            getattr(request.app.state, "model_client", None),
            correlation_id=request.state.correlation_id,
        )
    except PaymentNotFoundError:
        raise ApiError(404, "not_found", "payment not found") from None
    except PaymentNotFinalError:
        raise ApiError(409, "payment_not_final", "the payment has not reached a final state yet") from None
    assert stored is not None  # only the automatic trigger can return None
    return stored


@router.get(
    "/payments/{payment_id}/explanation",
    response_model=ExplanationResponse,
    summary="Get the latest explanation of a final payment",
    description="Returns the latest stored explanation, labelled with its source (`model` or `rules`). A final "
    "payment without one gets one generated and stored with `trigger=on_request`. 404 for an unknown payment, 409 "
    "`payment_not_final` while it is still processing or retrying.",
)
def get_explanation(payment_id: str, request: Request) -> dict[str, Any]:
    pid = _payment_id(payment_id)
    with Session(request.app.state.engine) as session:
        stored = latest_explanation(session, pid)
    return _body(stored or _generate(request, pid, "on_request"))


@router.post(
    "/payments/{payment_id}/explanation/regenerate",
    response_model=ExplanationResponse,
    status_code=201,
    summary="Generate a new explanation of a final payment now",
    description="Stores a new explanation with `trigger=regenerate` and returns it. 404 for an unknown payment, 409 "
    "`payment_not_final` for a payment that is not final.",
)
def regenerate_explanation(payment_id: str, request: Request) -> JSONResponse:
    return JSONResponse(_body(_generate(request, _payment_id(payment_id), "regenerate")), status_code=201)
