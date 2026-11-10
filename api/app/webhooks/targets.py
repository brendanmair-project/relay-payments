"""The target allowlist against server-side request forgery (ADR-0015, item 4).

A subscription URL is fetched by Relay itself, so only `http` or `https` URLs whose host is exactly one of the allowed
hostnames pass. The host is the one the HTTP client will connect to (`urlsplit(...).hostname`), so tricks such as
`http://localhost@evil.test/` or a fragment do not help; URLs with credentials are refused outright.
"""

from collections.abc import Iterable
from urllib.parse import urlsplit


def parse_allowed_hosts(value: str) -> frozenset[str]:
    """The comma-separated setting as a set of lowercase hostnames (blanks dropped)."""
    return frozenset(part.strip().lower() for part in value.split(",") if part.strip())


def is_allowed_target(url: str, allowed: Iterable[str]) -> bool:
    """True for an http or https URL whose host is exactly one of `allowed`."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    return host.lower() in {a.lower() for a in allowed}
