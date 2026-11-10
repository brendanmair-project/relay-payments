"""ADR-0015, item 4: http(s) to a host on the allowlist, nothing else (server-side request forgery)."""

import pytest

from app.webhooks.targets import is_allowed_target, parse_allowed_hosts

ALLOWED = ["webhook-sink", "localhost", "127.0.0.1"]


def test_the_setting_is_a_comma_separated_list_of_exact_lowercase_hostnames() -> None:
    assert parse_allowed_hosts(" Webhook-Sink , localhost,,127.0.0.1 ") == {"webhook-sink", "localhost", "127.0.0.1"}


@pytest.mark.parametrize(
    "url",
    [
        "http://webhook-sink:8200/hook",
        "https://localhost/x",
        "http://127.0.0.1:9000/",
        "HTTP://WEBHOOK-SINK/hook",
    ],
)
def test_allowed_targets(url: str) -> None:
    assert is_allowed_target(url, ALLOWED)


@pytest.mark.parametrize(
    "url",
    [
        "http://postgres:5432/",
        "http://redis:6379/",
        "http://api:8000/payments",
        "http://simulator:8101/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost.evil.test/",
        "http://webhook-sink.evil.test/",
        "http://evil.test/?h=localhost",
        "http://evil.test#@localhost",
        "http://localhost@evil.test/",
        "http://user:pw@localhost/",
        "file:///etc/passwd",
        "ftp://localhost/",
        "gopher://localhost/",
        "//localhost/x",
        "localhost",
        "",
        "http://",
        "http://localhost:notaport/",
        "http://[::1]/",
    ],
)
def test_everything_else_is_rejected(url: str) -> None:
    assert not is_allowed_target(url, ALLOWED)


def test_an_empty_allowlist_rejects_everything() -> None:
    assert not is_allowed_target("http://localhost/", [])
