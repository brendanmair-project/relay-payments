"""Webhook helpers: signature verification exactly as ADR-0015 defines it, and typed event parsing.

`Relay-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>" keyed with the subscription secret>`.
Several `v1` values may be present (any match accepts); the timestamp must be within the tolerance of now; the
comparison is constant-time. Mirrors `verify` in the api's `app/webhooks/signing.py`, and a test keeps the two in step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from relay_sdk.models import required_time


class SignatureVerificationError(Exception):
    """The message failed verification.

    `reason` is `malformed_header`, `timestamp_outside_tolerance` or `no_matching_signature`.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"webhook signature rejected: {reason}")
        self.reason = reason


def verify_signature(
    secret: str,
    header: str,
    body: bytes,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Return None when `header` carries a valid signature of the raw `body`; raise otherwise.

    Pass the exact bytes received, before any JSON parsing.
    """
    stamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                stamp = int(value)
            except ValueError:
                raise SignatureVerificationError("malformed_header") from None
        elif key == "v1" and value:
            candidates.append(value)
    if stamp is None or not candidates:
        raise SignatureVerificationError("malformed_header")
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance_seconds:
        raise SignatureVerificationError("timestamp_outside_tolerance")
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest().encode()
    # Compare as bytes so a non-ASCII candidate is a mismatch rather than a TypeError.
    if not any(hmac.compare_digest(expected, candidate.encode()) for candidate in candidates):
        raise SignatureVerificationError("no_matching_signature")


def is_valid_signature(
    secret: str,
    header: str,
    body: bytes,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> bool:
    """`verify_signature` as a bool, for callers that do not need the reason."""
    try:
        verify_signature(secret, header, body, tolerance_seconds, now)
    except SignatureVerificationError:
        return False
    return True


@dataclass(frozen=True)
class WebhookEvent:
    """A delivered message; `id` equals the `Relay-Event-Id` header, `data` holds the payment fields."""

    id: int
    type: str
    created_at: datetime
    data: dict[str, Any]


def parse_event(body: bytes | str) -> WebhookEvent:
    """Parse a delivery body (after verifying it) into a typed event; unknown fields are ignored."""
    raw = json.loads(body)
    return WebhookEvent(
        id=raw["id"],
        type=raw["type"],
        created_at=required_time(raw["created_at"]),
        data=raw.get("data") or {},
    )
