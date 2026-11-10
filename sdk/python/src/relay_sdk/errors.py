"""The one exception type for API errors."""

from typing import Any


class RelayError(Exception):
    """A non-2xx answer from the Relay API.

    `status` is the HTTP status; `code`, `message` and `details` come from the shared error body
    (`{"error": {"code", "message", "details", "correlation_id"}}`); `correlation_id` falls back to the
    `X-Correlation-ID` header. A body that is not that shape gives `code == "http_error"` and the raw text as message.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        correlation_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {message} (correlation id {correlation_id})")
        self.status = status
        self.code = code
        self.message = message
        self.correlation_id = correlation_id
        self.details = details
