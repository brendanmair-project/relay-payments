"""Processor profiles: latency, decline, timeout and capture-failure rates, changeable at runtime."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

PROCESSORS = ("a", "b")


class Profile(BaseModel):
    latency_ms_p50: float = Field(gt=0)
    latency_ms_p95: float = Field(gt=0)
    decline_rate: float = Field(ge=0, le=1)
    timeout_rate: float = Field(ge=0, le=1)
    # Not in the four-field contract body; optional so a PUT without it means "captures never fail".
    capture_failure_rate: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def check_consistent(self) -> Self:
        if self.latency_ms_p95 < self.latency_ms_p50:
            raise ValueError("latency_ms_p95 must be at least latency_ms_p50")
        if self.decline_rate + self.timeout_rate > 1:
            raise ValueError("decline_rate plus timeout_rate must not exceed 1")
        if self.capture_failure_rate + self.timeout_rate > 1:
            raise ValueError("capture_failure_rate plus timeout_rate must not exceed 1")
        return self


# Synthetic defaults: A is faster but declines and times out more often than B, so routing has a real trade-off.
DEFAULT_PROFILES = {
    "a": Profile(
        latency_ms_p50=120, latency_ms_p95=400, decline_rate=0.10, timeout_rate=0.02, capture_failure_rate=0.01
    ),
    "b": Profile(
        latency_ms_p50=250, latency_ms_p95=800, decline_rate=0.08, timeout_rate=0.01, capture_failure_rate=0.01
    ),
}
