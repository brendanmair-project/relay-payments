"""The correlation ID: read or generated per request, held in a context variable, carried into logs and events."""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_VALID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_current: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def resolve_correlation_id(supplied: str | None) -> str:
    """Return the supplied ID when it is valid (api-contract.md); otherwise a new one. Never rejects."""
    if supplied is not None and _VALID.fullmatch(supplied):
        return supplied
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    return _current.get()


@contextmanager
def bind_correlation_id(correlation_id: str) -> Iterator[None]:
    """Bind an ID for the enclosed work. The worker and publisher use it with the ID stored on an event."""
    token = _current.set(correlation_id)
    try:
        yield
    finally:
        _current.reset(token)
