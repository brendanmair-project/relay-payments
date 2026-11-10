"""HTTP client behind one small transport function; only the public API and the simulator control API are called."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

# transport(method, url, headers, body) -> (HTTP status, response text); status 0 means unreachable.
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, str]]


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, str]:
    if not url.startswith("http://"):
        raise ValueError("only http:// URLs are supported")
    request = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError as error:
        return 0, type(error).__name__


class RelayClient:
    def __init__(self, api_url: str, control_url: str, api_key: str, transport: Transport = urllib_transport) -> None:
        self.api_url = api_url.rstrip("/")
        self.control_url = control_url.rstrip("/")
        self._key = api_key
        self._transport = transport
        # Last (status, attempt_no) read for each payment id by is_final, for the drain-timeout report.
        self.last_seen: dict[str, tuple[str, int | None]] = {}

    def create_payment(self, idempotency_key: str, body: dict) -> int:
        return self.create_payment_with_id(idempotency_key, body)[0]

    def create_payment_with_id(self, idempotency_key: str, body: dict) -> tuple[int, str | None]:
        """POST /payments; returns the HTTP status and the payment id from the response (None when absent)."""
        headers = {"X-API-Key": self._key, "Idempotency-Key": idempotency_key, "Content-Type": "application/json"}
        payload = json.dumps(body, sort_keys=True).encode("utf-8")
        status, text = self._transport("POST", f"{self.api_url}/payments", headers, payload)
        try:
            payment_id = json.loads(text).get("id") if status in (200, 201) else None
        except (ValueError, AttributeError):
            payment_id = None
        return status, payment_id if isinstance(payment_id, str) else None

    def is_final(self, payment_id: str) -> bool:
        """GET /payments/{id} on the public API; False when it is not final or cannot be read."""
        status, text = self._transport("GET", f"{self.api_url}/payments/{payment_id}", {"X-API-Key": self._key}, None)
        if status != 200:
            return False
        try:
            data = json.loads(text)
            attempt = data.get("attempt_no")
            status_text = str(data.get("status", "unknown"))
            self.last_seen[payment_id] = (status_text, attempt if isinstance(attempt, int) else None)
            return data.get("is_final") is True
        except (ValueError, AttributeError):
            return False

    def set_outage(self, processor: str, enabled: bool) -> int:
        headers = {"X-API-Key": self._key, "Content-Type": "application/json"}
        payload = json.dumps({"enabled": enabled}).encode("utf-8")
        url = f"{self.control_url}/control/processors/{processor}/outage"
        status, _ = self._transport("POST", url, headers, payload)
        return status

    def set_profile(self, processor: str, profile: dict) -> int:
        """PUT the runtime profile of a processor through the simulator control API."""
        headers = {"X-API-Key": self._key, "Content-Type": "application/json"}
        url = f"{self.control_url}/control/processors/{processor}/profile"
        status, _ = self._transport("PUT", url, headers, json.dumps(profile).encode("utf-8"))
        return status

    def processor_health(self) -> dict:
        """GET /processors/health on the public API; {} when it cannot be read."""
        status, text = self._transport("GET", f"{self.api_url}/processors/health", {"X-API-Key": self._key}, None)
        if status != 200:
            return {}
        try:
            body = json.loads(text)
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}
