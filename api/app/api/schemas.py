"""Request and response models for POST /payments (docs/architecture/api-contract.md)."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

from app.domain.money import CURRENCY_DIGITS, InvalidMoneyError, Money

MAX_AMOUNT_API = 1_000_000_000_000  # tighter than Money's BIGINT bound (api-contract.md)


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: Annotated[StrictInt, Field(ge=1, le=MAX_AMOUNT_API)]
    currency: str
    description: Annotated[str, StringConstraints(max_length=200)] | None = None
    reference: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")] | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def _supported_currency(cls, value: object) -> object:
        # Money holds the one currency table; amount bounds are checked by the field constraints above.
        try:
            Money(1, value)  # type: ignore[arg-type]
        except InvalidMoneyError:
            raise ValueError("must be one of " + ", ".join(CURRENCY_DIGITS)) from None
        return value


def iso_utc(moment: datetime) -> str:
    """2026-10-01T14:03:22.418Z"""
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


class PaymentResponse(BaseModel):
    """The Payment resource; the schema documents the 201 body, the endpoint returns the stored dict as is."""

    id: str
    amount_minor: int
    currency: str
    description: str | None
    reference: str | None
    status: str
    attempt_no: int
    is_final: bool
    display_status: str
    processor: str | None
    created_at: str
    status_changed_at: str
    final_at: str | None


class EventResponse(BaseModel):
    """One timeline entry (api-contract.md "Event")."""

    seq: int
    type: str
    attempt_no: int
    from_status: str | None
    to_status: str | None
    processor: str | None
    reason: str | None
    data: dict[str, Any]
    occurred_at: str


class PaymentDetailResponse(PaymentResponse):
    """GET /payments/{id}: the Payment plus every event in seq order."""

    events: list[EventResponse]


class PaymentListResponse(BaseModel):
    """GET /payments: one page, newest first; `next_cursor` is null on the last page."""

    items: list[PaymentResponse]
    next_cursor: str | None


class ExplanationResponse(BaseModel):
    """GET and POST /payments/{id}/explanation (api-contract.md "Explanation")."""

    payment_id: str
    source: str
    model: str | None
    text: str
    cited_event_seqs: list[int]
    trigger: str
    generated_at: str
    fallback_reason: str | None
