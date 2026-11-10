"""HTTP client for the simulated processors (docs/architecture/api-contract.md "Simulator APIs").

A call ends in one of these ways: a `ProcessorResult` (HTTP 200), `ProcessorTimeout` (the client timeout, or a 504) or
`ProcessorOutage` (a 503, or the processor could not be reached). Anything else is a `ProcessorProtocolError`: the
caller does not guess an outcome from it.
"""

import time
import uuid
from dataclasses import dataclass

import httpx


class ProcessorError(Exception):
    """A processor call did not produce a result; `elapsed_ms` is how long it took."""

    def __init__(self, message: str, elapsed_ms: int = 0) -> None:
        super().__init__(message)
        self.elapsed_ms = elapsed_ms


class ProcessorTimeout(ProcessorError):
    pass


class ProcessorOutage(ProcessorError):
    pass


class ProcessorProtocolError(ProcessorError):
    pass


@dataclass(frozen=True)
class ProcessorResult:
    result: str
    reason: str | None
    latency_ms: int


class ProcessorClient:
    def __init__(self, base_url: str, timeout_seconds: float, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._http.close()

    def authorize(
        self,
        processor: str,
        *,
        payment_id: uuid.UUID,
        attempt_no: int,
        amount_minor: int,
        currency: str,
        reference: str | None,
    ) -> ProcessorResult:
        return self._call(processor, "authorize", payment_id, attempt_no, amount_minor, currency, reference)

    def capture(
        self,
        processor: str,
        *,
        payment_id: uuid.UUID,
        attempt_no: int,
        amount_minor: int,
        currency: str,
        reference: str | None,
    ) -> ProcessorResult:
        return self._call(processor, "capture", payment_id, attempt_no, amount_minor, currency, reference)

    def _call(
        self,
        processor: str,
        operation: str,
        payment_id: uuid.UUID,
        attempt_no: int,
        amount_minor: int,
        currency: str,
        reference: str | None,
    ) -> ProcessorResult:
        body: dict[str, object] = {
            "payment_id": str(payment_id),
            "attempt_no": attempt_no,
            "amount_minor": amount_minor,
            "currency": currency,
        }
        if reference is not None:
            body["reference"] = reference
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        try:
            response = self._http.post(
                f"/processors/{processor.lower()}/{operation}",
                json=body,
                headers={"Idempotency-Key": f"{payment_id}:{attempt_no}"},
            )
        except httpx.TimeoutException as error:
            raise ProcessorTimeout(f"{operation} timed out", elapsed()) from error
        except httpx.TransportError as error:  # connection refused, DNS failure: the processor is unreachable
            raise ProcessorOutage(f"{operation} failed: {error}", elapsed()) from error
        if response.status_code == 503:
            raise ProcessorOutage(f"{operation} answered 503", elapsed())
        if response.status_code == 504:
            raise ProcessorTimeout(f"{operation} answered 504", elapsed())
        if response.status_code != 200:
            raise ProcessorProtocolError(f"{operation} answered {response.status_code}", elapsed())
        try:
            data = response.json()
            return ProcessorResult(str(data["result"]), data.get("reason"), int(data["latency_ms"]))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ProcessorProtocolError(f"{operation} answered an unreadable body", elapsed()) from error
