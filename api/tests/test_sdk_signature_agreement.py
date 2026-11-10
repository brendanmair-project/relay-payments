"""REL-41 (ADR-0015): the Python SDK's `verify_signature` agrees with `app.webhooks.signing` on every case.

The SDK is imported from its source (`sdk/python/src`), added to the path in this test only. It is not part of the api
image (the image is built from `api/`), so the test skips there with a reason. CI runs it in the `backend` job, which
checks out the whole repository and runs pytest from `api/`; locally it runs on the host the same way, or in the image
with the source mounted read-only at /sdk/python/src (`docker run -v <repo>/sdk/python/src:/sdk/python/src:ro`).
"""

import hashlib
import hmac
import secrets
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.webhooks import signing

SDK_SRC = Path(__file__).resolve().parents[2] / "sdk" / "python" / "src"
TOLERANCE = 300
BODY = b'{"id": 7, "type": "payment.final", "data": {"status": "captured"}}'


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Any:
    if not (SDK_SRC / "relay_sdk").exists():
        pytest.skip("sdk/python/src is not part of the api image; CI runs this test from the repository checkout")
    monkeypatch.syspath_prepend(str(SDK_SRC))
    for name in [n for n in sys.modules if n == "relay_sdk" or n.startswith("relay_sdk.")]:
        monkeypatch.delitem(sys.modules, name)
    import relay_sdk.webhooks as module

    return module


def sdk_accepts(sdk: Any, secret: str, body: bytes, header: str, now: float) -> bool:
    try:
        sdk.verify_signature(secret, header, body, tolerance_seconds=TOLERANCE, now=now)
    except sdk.SignatureVerificationError:
        return False
    return True


def digest(secret: str, stamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()


def cases() -> list[tuple[str, Callable[[str, str, int], tuple[str, bytes, str]]]]:
    """Each case maps (secret, other secret, now) to (the secret to verify with, the body, the header)."""

    def header(secret: str, stamp: int, body: bytes = BODY) -> str:
        return f"t={stamp},v1={digest(secret, stamp, body)}"

    return [
        ("good", lambda s, o, now: (s, BODY, header(s, now))),
        ("signed_by_relay", lambda s, o, now: (s, BODY, signing.sign(s, BODY, now))),
        ("tampered_body", lambda s, o, now: (s, BODY + b" ", header(s, now))),
        ("wrong_secret", lambda s, o, now: (o, BODY, header(s, now))),
        ("old_timestamp", lambda s, o, now: (s, BODY, header(s, now - TOLERANCE - 1))),
        ("future_timestamp", lambda s, o, now: (s, BODY, header(s, now + TOLERANCE + 1))),
        ("edge_of_tolerance", lambda s, o, now: (s, BODY, header(s, now - TOLERANCE))),
        ("replayed_signature_new_timestamp", lambda s, o, now: (s, BODY, f"t={now},v1={digest(s, now - 5, BODY)}")),
        (
            "two_v1_second_matches",
            lambda s, o, now: (s, BODY, f"t={now},v1={digest(o, now, BODY)},v1={digest(s, now, BODY)}"),
        ),
        ("two_v1_none_match", lambda s, o, now: (s, BODY, f"t={now},v1={digest(o, now, BODY)},v1={'0' * 64}")),
        ("spaces_between_parts", lambda s, o, now: (s, BODY, f"t={now}, v1={digest(s, now, BODY)}")),
        ("empty_header", lambda s, o, now: (s, BODY, "")),
        ("no_timestamp", lambda s, o, now: (s, BODY, f"v1={digest(s, now, BODY)}")),
        ("no_v1", lambda s, o, now: (s, BODY, f"t={now}")),
        ("empty_v1", lambda s, o, now: (s, BODY, f"t={now},v1=")),
        ("bad_timestamp", lambda s, o, now: (s, BODY, f"t=abc,v1={digest(s, now, BODY)}")),
        ("non_ascii_v1", lambda s, o, now: (s, BODY, f"t={now},v1={chr(0xE9)}{digest(s, now, BODY)[1:]}")),
        ("non_ascii_v1_then_good", lambda s, o, now: (s, BODY, f"t={now},v1={chr(0xE9)},v1={digest(s, now, BODY)}")),
        ("uppercase_digest", lambda s, o, now: (s, BODY, f"t={now},v1={digest(s, now, BODY).upper()}")),
    ]


@pytest.mark.parametrize(("name", "build"), cases(), ids=[name for name, _ in cases()])
def test_the_sdk_and_relay_agree(sdk: Any, name: str, build: Callable[[str, str, int], tuple[str, bytes, str]]) -> None:
    secret, other = secrets.token_hex(16), secrets.token_hex(16)
    now = int(time.time())
    verify_with, body, header = build(secret, other, now)
    relay = signing.verify(verify_with, header, body, TOLERANCE, now=now)
    assert sdk_accepts(sdk, verify_with, body, header, now) is relay, name
    assert sdk.is_valid_signature(verify_with, header, body, tolerance_seconds=TOLERANCE, now=now) is relay, name


def test_the_expected_outcomes_are_not_all_the_same(sdk: Any) -> None:
    """Guards the matrix itself: it must contain both accepted and rejected messages."""
    secret, other = secrets.token_hex(16), secrets.token_hex(16)
    now = int(time.time())
    outcomes = {name: sdk_accepts(sdk, *build(secret, other, now), now) for name, build in cases()}
    assert outcomes["good"] and outcomes["signed_by_relay"] and outcomes["two_v1_second_matches"]
    assert not outcomes["tampered_body"] and not outcomes["wrong_secret"] and not outcomes["old_timestamp"]
    assert not outcomes["non_ascii_v1"] and outcomes["non_ascii_v1_then_good"]
