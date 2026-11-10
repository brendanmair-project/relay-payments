"""ADR-0015, item 2: `Relay-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>">`."""

import hashlib
import hmac

from app.webhooks.signing import sign, verify
from tests.webhooks.helpers import random_secret

BODY = b'{"id":7,"type":"payment.final"}'


def test_the_header_has_the_timestamp_and_the_hmac_of_t_dot_body() -> None:
    secret = random_secret()
    header = sign(secret, BODY, timestamp=1_700_000_000)
    expected = hmac.new(secret.encode(), b"1700000000." + BODY, hashlib.sha256).hexdigest()
    assert header == f"t=1700000000,v1={expected}"


def test_a_good_signature_verifies() -> None:
    secret = random_secret()
    header = sign(secret, BODY, timestamp=1_700_000_000)
    assert verify(secret, header, BODY, tolerance_seconds=300, now=1_700_000_100)


def test_the_timestamp_defaults_to_now() -> None:
    secret = random_secret()
    assert verify(secret, sign(secret, BODY), BODY, tolerance_seconds=300)


def test_a_tampered_body_is_rejected() -> None:
    secret = random_secret()
    header = sign(secret, BODY, timestamp=1_700_000_000)
    assert not verify(secret, header, BODY + b" ", tolerance_seconds=300, now=1_700_000_000)


def test_the_wrong_secret_is_rejected() -> None:
    header = sign(random_secret(), BODY, timestamp=1_700_000_000)
    assert not verify(random_secret(), header, BODY, tolerance_seconds=300, now=1_700_000_000)


def test_an_old_or_future_timestamp_is_rejected_but_the_edge_of_the_tolerance_is_not() -> None:
    secret = random_secret()
    header = sign(secret, BODY, timestamp=1_700_000_000)
    assert verify(secret, header, BODY, tolerance_seconds=300, now=1_700_000_300)
    assert not verify(secret, header, BODY, tolerance_seconds=300, now=1_700_000_301)
    assert not verify(secret, header, BODY, tolerance_seconds=300, now=1_699_999_699)


def test_a_replayed_timestamp_cannot_be_swapped_in() -> None:
    secret = random_secret()
    header = sign(secret, BODY, timestamp=1_700_000_000)
    forged = header.replace("t=1700000000", "t=1700000200")
    assert not verify(secret, forged, BODY, tolerance_seconds=300, now=1_700_000_200)


def test_malformed_headers_are_rejected_without_an_error() -> None:
    secret = random_secret()
    good = sign(secret, BODY, timestamp=1_700_000_000)
    v1 = good.split("v1=")[1]
    for bad in ("", "garbage", "t=abc,v1=" + v1, "t=1700000000", "v1=" + v1, "t=1700000000,v1=", "t=,v1=" + v1):
        assert not verify(secret, bad, BODY, tolerance_seconds=300, now=1_700_000_000), bad
    assert verify(secret, good, BODY, tolerance_seconds=300, now=1_700_000_000)


def test_a_non_ascii_empty_or_very_long_v1_is_false_never_an_error() -> None:
    secret = random_secret()
    good = sign(secret, BODY, timestamp=1_700_000_000).split("v1=")[1]
    accent = chr(0xE9)
    lone_surrogate = chr(0xD83D)
    for bad in (accent, accent * 64, lone_surrogate, good[:-1] + accent, "", "a" * 100_000, good + accent):
        candidate = f"t=1700000000,v1={bad}"
        assert verify(secret, candidate, BODY, tolerance_seconds=300, now=1_700_000_000) is False, bad[:10]
    # a bad value beside a good one does not hide the good one
    mixed = f"t=1700000000,v1={accent},v1={good}"
    assert verify(secret, mixed, BODY, tolerance_seconds=300, now=1_700_000_000) is True
