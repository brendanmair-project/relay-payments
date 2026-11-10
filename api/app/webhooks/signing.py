"""Signing and verification of webhook messages (ADR-0015); REL-41's SDK mirrors `verify`.

`Relay-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>" keyed with the subscription secret>`. The
timestamp is inside the signed text, so a captured message cannot be replayed with a fresh timestamp; `verify` also
rejects a timestamp further than `tolerance_seconds` from now. Comparison is constant-time, on bytes, and a malformed
`v1` (non-ASCII, empty, any length) is a mismatch: `verify` returns False and never raises.
"""

import hashlib
import hmac
import time


def _digest(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """The `Relay-Signature` header value: `t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">`."""
    stamp = int(time.time()) if timestamp is None else timestamp
    return f"t={stamp},v1={_digest(secret, stamp, body)}"


def verify(secret: str, header: str, body: bytes, tolerance_seconds: int, now: float | None = None) -> bool:
    """True when the header carries a valid signature of `body` made at most `tolerance_seconds` from `now`."""
    stamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                stamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:  # several v1 values are allowed, so a later secret rotation can overlap
            candidates.append(value)
    if stamp is None or not candidates:
        return False
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance_seconds:
        return False
    expected = _digest(secret, stamp, body).encode()
    # surrogatepass: a lone surrogate (from a decoded header) must still become bytes and mismatch, not raise.
    return any(hmac.compare_digest(expected, candidate.encode("utf-8", "surrogatepass")) for candidate in candidates)
