"""Keyset cursor shared by the list endpoints that page on `(created_at, id)` descending (payments, webhook deliveries).

The cursor is opaque to clients: URL-safe base64 of `{"c": <created_at ISO 8601 with zone>, "i": <id as text>}`. A
cursor that does not decode is 400 `malformed_request`.
"""

import base64
import binascii
import json
from datetime import datetime

from app.errors import ApiError


def encode_cursor(created_at: datetime, key: str) -> str:
    # Microsecond precision: the ISO strings in responses are truncated to milliseconds and would skip rows.
    raw = json.dumps({"c": created_at.isoformat(), "i": key}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """The `(created_at, id text)` of the last row of the previous page; callers convert the id to their type."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        created_at = datetime.fromisoformat(data["c"])
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        key = data["i"]
        if not isinstance(key, str):
            raise TypeError("id is not text")
        return created_at, key
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise ApiError(400, "malformed_request", "cursor is malformed") from None
