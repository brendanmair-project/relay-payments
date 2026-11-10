"""Signature verification and event parsing (REL-41, ADR-0015)."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

import pytest

from relay_sdk import SignatureVerificationError, WebhookEvent, is_valid_signature, parse_event, verify_signature

SECRET = secrets.token_hex(16)
OTHER = secrets.token_hex(16)
BODY = (
    b'{"id": 1234, "type": "payment.final", "created_at": "2026-11-05T14:03:22.418Z", "data": {"status": "captured"}}'
)
NOW = 1_793_890_000


def sign(secret: str, body: bytes, stamp: int) -> str:
    return hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()


def header(secret: str = SECRET, body: bytes = BODY, stamp: int = NOW) -> str:
    return f"t={stamp},v1={sign(secret, body, stamp)}"


def test_a_good_signature_verifies() -> None:
    assert verify_signature(SECRET, header(), BODY, now=NOW) is None
    assert is_valid_signature(SECRET, header(), BODY, now=NOW) is True


def test_a_tampered_body_is_rejected() -> None:
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(SECRET, header(), BODY + b" ", now=NOW)
    assert exc.value.reason == "no_matching_signature"
    assert is_valid_signature(SECRET, header(), BODY + b" ", now=NOW) is False


def test_the_wrong_secret_is_rejected() -> None:
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(OTHER, header(), BODY, now=NOW)
    assert exc.value.reason == "no_matching_signature"


def test_a_timestamp_outside_the_tolerance_is_rejected_either_way() -> None:
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(SECRET, header(stamp=NOW - 301), BODY, now=NOW)
    assert exc.value.reason == "timestamp_outside_tolerance"
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(SECRET, header(stamp=NOW + 301), BODY, now=NOW)
    assert exc.value.reason == "timestamp_outside_tolerance"


def test_the_tolerance_boundary_and_a_custom_tolerance() -> None:
    assert verify_signature(SECRET, header(stamp=NOW - 300), BODY, now=NOW) is None
    assert verify_signature(SECRET, header(stamp=NOW - 3000), BODY, tolerance_seconds=3600, now=NOW) is None
    with pytest.raises(SignatureVerificationError):
        verify_signature(SECRET, header(stamp=NOW - 31), BODY, tolerance_seconds=30, now=NOW)


def test_a_replayed_signature_with_a_fresh_timestamp_is_rejected() -> None:
    signature = sign(SECRET, BODY, NOW - 1000)
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(SECRET, f"t={NOW},v1={signature}", BODY, now=NOW)
    assert exc.value.reason == "no_matching_signature"


def test_several_v1_values_are_accepted_when_any_matches() -> None:
    both = f"t={NOW},v1={sign(OTHER, BODY, NOW)},v1={sign(SECRET, BODY, NOW)}"
    assert verify_signature(SECRET, both, BODY, now=NOW) is None
    assert verify_signature(OTHER, both, BODY, now=NOW) is None
    with pytest.raises(SignatureVerificationError):
        verify_signature(SECRET, f"t={NOW},v1={sign(OTHER, BODY, NOW)},v1={'0' * 64}", BODY, now=NOW)


@pytest.mark.parametrize(
    "bad",
    ["", "garbage", f"v1={'a' * 64}", f"t={NOW}", f"t={NOW},v1=", "t=abc,v1=" + "a" * 64, f"t=,v1={'a' * 64}"],
)
def test_a_malformed_header_is_rejected_with_that_reason(bad: str) -> None:
    with pytest.raises(SignatureVerificationError) as exc:
        verify_signature(SECRET, bad, BODY, now=NOW)
    assert exc.value.reason == "malformed_header"
    assert is_valid_signature(SECRET, bad, BODY, now=NOW) is False


def test_whitespace_around_parts_is_tolerated() -> None:
    spaced = f"t={NOW}, v1={sign(SECRET, BODY, NOW)}"
    assert verify_signature(SECRET, spaced, BODY, now=NOW) is None


def test_now_defaults_to_the_clock() -> None:
    assert verify_signature(SECRET, header(stamp=int(time.time())), BODY) is None
    with pytest.raises(SignatureVerificationError):
        verify_signature(SECRET, header(stamp=NOW), BODY)


def test_the_error_message_carries_the_reason() -> None:
    with pytest.raises(SignatureVerificationError, match="timestamp_outside_tolerance"):
        verify_signature(SECRET, header(stamp=NOW - 999), BODY, now=NOW)


def test_parse_event_returns_a_typed_event() -> None:
    event = parse_event(BODY)
    assert isinstance(event, WebhookEvent)
    assert event.id == 1234
    assert event.type == "payment.final"
    assert event.created_at == datetime(2026, 11, 5, 14, 3, 22, 418000, tzinfo=UTC)
    assert event.data == {"status": "captured"}


def test_parse_event_accepts_text_and_ignores_unknown_fields() -> None:
    payload = {"id": 1, "type": "payment.failed", "created_at": "2026-11-05T14:03:22Z", "data": {}, "x": 1}
    event = parse_event(json.dumps(payload))
    assert (event.id, event.type, event.data) == (1, "payment.failed", {})
