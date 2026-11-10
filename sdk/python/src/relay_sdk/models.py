"""Typed, forward-compatible models: unknown response fields are ignored, field names follow openapi.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def parse_time(value: str | None) -> datetime | None:
    """ISO 8601 with a `Z` suffix (or an offset) to an aware datetime; None stays None."""
    return None if value is None else datetime.fromisoformat(value)


def required_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class PaymentEvent:
    """One entry of a payment's timeline."""

    seq: int
    type: str
    attempt_no: int
    from_status: str | None
    to_status: str | None
    processor: str | None
    reason: str | None
    data: dict[str, Any]
    occurred_at: datetime

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PaymentEvent:
        return cls(
            seq=raw["seq"],
            type=raw["type"],
            attempt_no=raw["attempt_no"],
            from_status=raw.get("from_status"),
            to_status=raw.get("to_status"),
            processor=raw.get("processor"),
            reason=raw.get("reason"),
            data=raw.get("data") or {},
            occurred_at=required_time(raw["occurred_at"]),
        )


@dataclass(frozen=True)
class Payment:
    """A payment; `events` is filled by `get_payment` only."""

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
    created_at: datetime
    status_changed_at: datetime
    final_at: datetime | None
    events: list[PaymentEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Payment:
        return cls(
            id=raw["id"],
            amount_minor=raw["amount_minor"],
            currency=raw["currency"],
            description=raw.get("description"),
            reference=raw.get("reference"),
            status=raw["status"],
            attempt_no=raw["attempt_no"],
            is_final=raw["is_final"],
            display_status=raw["display_status"],
            processor=raw.get("processor"),
            created_at=required_time(raw["created_at"]),
            status_changed_at=required_time(raw["status_changed_at"]),
            final_at=parse_time(raw.get("final_at")),
            events=[PaymentEvent.from_dict(e) for e in raw.get("events") or []],
        )


@dataclass(frozen=True)
class PaymentCreated:
    """The result of `create_payment`: `replayed` is true when the Idempotency-Key matched an earlier request."""

    payment: Payment
    replayed: bool


@dataclass(frozen=True)
class PaymentPage:
    """One page of payments, newest first; `next_cursor` is None on the last page."""

    items: list[Payment]
    next_cursor: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PaymentPage:
        return cls(items=[Payment.from_dict(p) for p in raw["items"]], next_cursor=raw.get("next_cursor"))


@dataclass(frozen=True)
class Subscription:
    """A webhook subscription (never carries the secret)."""

    id: str
    url: str
    event_types: list[str]
    active: bool
    created_at: datetime

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Subscription:
        return cls(
            id=raw["id"],
            url=raw["url"],
            event_types=list(raw.get("event_types") or []),
            active=raw.get("active", True),
            created_at=required_time(raw["created_at"]),
        )


@dataclass(frozen=True)
class SubscriptionCreated(Subscription):
    """The create response: the only place the signing `secret` is ever returned (kept out of `repr`)."""

    secret: str = field(default="", repr=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SubscriptionCreated:
        base = Subscription.from_dict(raw)
        return cls(
            id=base.id,
            url=base.url,
            event_types=base.event_types,
            active=base.active,
            created_at=base.created_at,
            secret=raw["secret"],
        )


@dataclass(frozen=True)
class DeliveryAttempt:
    """One send attempt of a delivery."""

    attempt: int
    status_code: int | None
    error: str | None
    duration_ms: int
    attempted_at: datetime

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeliveryAttempt:
        return cls(
            attempt=raw["attempt"],
            status_code=raw.get("status_code"),
            error=raw.get("error"),
            duration_ms=raw["duration_ms"],
            attempted_at=required_time(raw["attempted_at"]),
        )


@dataclass(frozen=True)
class Delivery:
    """A row of the delivery log; `status` is `pending`, `delivered` or `failed`."""

    id: int
    subscription_id: str
    event_id: int
    event_type: str
    attempt: int
    status: str
    next_attempt_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Delivery:
        return cls(
            id=raw["id"],
            subscription_id=raw["subscription_id"],
            event_id=raw["event_id"],
            event_type=raw["event_type"],
            attempt=raw["attempt"],
            status=raw["status"],
            next_attempt_at=parse_time(raw.get("next_attempt_at")),
            last_status_code=raw.get("last_status_code"),
            last_error=raw.get("last_error"),
            created_at=required_time(raw["created_at"]),
            updated_at=required_time(raw["updated_at"]),
        )


@dataclass(frozen=True)
class DeliveryPage:
    """One page of the delivery log, newest first; `next_cursor` is None on the last page."""

    items: list[Delivery]
    next_cursor: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeliveryPage:
        return cls(items=[Delivery.from_dict(d) for d in raw["items"]], next_cursor=raw.get("next_cursor"))


@dataclass(frozen=True)
class DeliveryDetail(Delivery):
    """A delivery with every attempt."""

    attempts: list[DeliveryAttempt] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeliveryDetail:
        base = Delivery.from_dict(raw)
        return cls(
            id=base.id,
            subscription_id=base.subscription_id,
            event_id=base.event_id,
            event_type=base.event_type,
            attempt=base.attempt,
            status=base.status,
            next_attempt_at=base.next_attempt_at,
            last_status_code=base.last_status_code,
            last_error=base.last_error,
            created_at=base.created_at,
            updated_at=base.updated_at,
            attempts=[DeliveryAttempt.from_dict(a) for a in raw.get("attempts") or []],
        )


@dataclass(frozen=True)
class DeliverySummary:
    """Delivery counts in a window; `success_rate` is None when no delivery is final."""

    delivered: int
    failed: int
    pending: int
    success_rate: float | None
    since: datetime | None
    until: datetime | None
    subscription_id: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DeliverySummary:
        return cls(
            delivered=raw["delivered"],
            failed=raw["failed"],
            pending=raw["pending"],
            success_rate=raw.get("success_rate"),
            since=parse_time(raw.get("since")),
            until=parse_time(raw.get("until")),
            subscription_id=raw.get("subscription_id"),
        )
