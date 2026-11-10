"""REL-40: the verification snippet in docs/guides/webhooks.md agrees with `app.webhooks.signing.verify`."""

import re
import secrets
import time
from pathlib import Path
from typing import Any

import pytest

from app.webhooks import signing

ROOT = Path(__file__).resolve().parents[3]
WEBHOOKS_GUIDE = ROOT / "docs" / "guides" / "webhooks.md"
TOLERANCE = 300


@pytest.fixture
def snippet() -> Any:
    if not (ROOT / "docs").exists():
        pytest.skip("docs/ is not part of the api image")
    assert WEBHOOKS_GUIDE.exists(), "docs/guides/webhooks.md is missing"
    blocks = re.findall(r"```python\n(.*?)```", WEBHOOKS_GUIDE.read_text(encoding="utf-8"), re.S)
    verifying = [b for b in blocks if "def verify_signature" in b]
    assert len(verifying) == 1, "webhooks.md needs exactly one python block defining verify_signature"
    namespace: dict[str, Any] = {}
    exec(compile(verifying[0], "webhooks.md", "exec"), namespace)  # noqa: S102  # our own committed documentation
    return namespace["verify_signature"]


def test_a_good_message_verifies(snippet: Any) -> None:
    secret, body = secrets.token_urlsafe(24), b'{"id": 1, "type": "payment.final"}'
    header = signing.sign(secret, body)
    assert snippet(secret, header, body, TOLERANCE) is True
    assert signing.verify(secret, header, body, TOLERANCE) is True


def test_a_tampered_body_or_wrong_secret_is_rejected_by_both(snippet: Any) -> None:
    secret, body = secrets.token_urlsafe(24), b'{"id": 1, "type": "payment.final"}'
    header = signing.sign(secret, body)
    for args in ((secret, header, body + b" "), (secrets.token_urlsafe(24), header, body), (secret, "garbage", body)):
        assert snippet(*args, TOLERANCE) is False
        assert signing.verify(*args, TOLERANCE) is False


def test_an_old_timestamp_is_rejected_by_both(snippet: Any) -> None:
    secret, body = secrets.token_urlsafe(24), b"{}"
    header = signing.sign(secret, body, timestamp=int(time.time()) - TOLERANCE - 60)
    assert snippet(secret, header, body, TOLERANCE) is False
    assert signing.verify(secret, header, body, TOLERANCE) is False


def test_several_v1_values_are_accepted_by_both(snippet: Any) -> None:
    secret, body = secrets.token_urlsafe(24), b"{}"
    header = signing.sign(secret, body) + ",v1=" + "0" * 64
    assert snippet(secret, header, body, TOLERANCE) is True
    assert signing.verify(secret, header, body, TOLERANCE) is True
