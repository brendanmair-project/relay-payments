"""Processor API on 8100 (compose network only) and control API on 8101 (X-API-Key), sharing one Simulator.

Contract: docs/architecture/api-contract.md, "Simulator APIs". Outcomes come from processors/ (REL-19).
"""

import asyncio
import hmac
import os
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from processors.profiles import PROCESSORS, Profile
from processors.simulator import ChargeRequest, Simulator

Sleep = Callable[[float], Awaitable[None]]


class ChargeBody(BaseModel):
    payment_id: str = Field(min_length=1, max_length=64)
    attempt_no: int = Field(ge=1, le=2)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reference: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")


class OutageBody(BaseModel):
    enabled: bool


def error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def unknown(processor: str) -> JSONResponse:
    return error(404, "unknown_processor", f"no processor {processor!r}; use a or b")


async def validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()))
    return error(422, "validation_error", f"{where}: {first.get('msg', 'invalid')}")


def create_apps(sim: Simulator, sleep: Sleep = asyncio.sleep, api_key: str | None = None) -> tuple[FastAPI, FastAPI]:
    processor_app = FastAPI(title="Relay simulator - processor API")
    control_app = FastAPI(title="Relay simulator - control API")
    for app in (processor_app, control_app):
        app.add_exception_handler(RequestValidationError, validation_error)

    @processor_app.get("/health")
    def processor_health() -> dict[str, str]:
        return {"status": "ok"}

    async def charge(processor: str, operation: str, key: str, body: ChargeBody) -> JSONResponse:
        if processor not in PROCESSORS:
            return unknown(processor)
        if key != f"{body.payment_id}:{body.attempt_no}":
            return error(422, "idempotency_key_mismatch", "Idempotency-Key must be <payment_id>:<attempt_no>")
        decision = sim.handle(processor, operation, key, ChargeRequest(**body.model_dump()))
        if decision.status == "conflict":
            return error(409, "idempotency_key_reused", "this Idempotency-Key was first used with a different body")
        if decision.status == "not_authorized":
            return error(409, "not_authorized", f"no approved authorize on processor {processor} for this key")
        if decision.status == "outage":
            return error(503, "processor_outage", f"processor {processor} is in an outage")
        outcome = decision.outcome
        assert outcome is not None
        if decision.status == "timeout":
            # Answer only after the worker has given up, so the worker sees a timeout, not a response; a replayed
            # key times out again.
            await sleep(sim.timeout_seconds + 1)
            return error(504, "processor_timeout", f"processor {processor} did not answer in time")
        if not decision.replayed:
            await sleep(outcome.latency_ms / 1000)
        return JSONResponse({"result": outcome.result, "reason": outcome.reason, "latency_ms": outcome.latency_ms})

    @processor_app.post("/processors/{processor}/authorize")
    async def authorize(processor: str, body: ChargeBody, idempotency_key: Annotated[str, Header()]) -> JSONResponse:
        return await charge(processor, "authorize", idempotency_key, body)

    @processor_app.post("/processors/{processor}/capture")
    async def capture(processor: str, body: ChargeBody, idempotency_key: Annotated[str, Header()]) -> JSONResponse:
        return await charge(processor, "capture", idempotency_key, body)

    @control_app.middleware("http")
    async def require_api_key(request: Request, call_next):  # type: ignore[no-untyped-def]
        expected = api_key if api_key is not None else os.environ["RELAY_API_KEY"]
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return error(401, "unauthorized", "missing or invalid X-API-Key")
        return await call_next(request)

    @control_app.get("/health")
    def control_health() -> dict[str, str]:
        return {"status": "ok"}

    def snapshot() -> dict[str, dict[str, dict[str, object]]]:
        return {
            "processors": {
                name: {"profile": profile.model_dump(), "outage": sim.outages[name]}
                for name, profile in sim.profiles.items()
            }
        }

    @control_app.get("/control/processors")
    def list_processors() -> dict[str, dict[str, dict[str, object]]]:
        return snapshot()

    @control_app.put("/control/processors/{processor}/profile", response_model=None)
    def set_profile(processor: str, profile: Profile) -> dict[str, dict[str, dict[str, object]]] | JSONResponse:
        if processor not in PROCESSORS:
            return unknown(processor)
        sim.profiles[processor] = profile
        return snapshot()

    @control_app.post("/control/processors/{processor}/outage", response_model=None)
    def set_outage(processor: str, body: OutageBody) -> dict[str, dict[str, dict[str, object]]] | JSONResponse:
        if processor not in PROCESSORS:
            return unknown(processor)
        sim.outages[processor] = body.enabled
        return snapshot()

    return processor_app, control_app


def from_environment() -> tuple[FastAPI, FastAPI]:
    sim = Simulator(
        seed=int(os.environ.get("SIM_SEED", "42")),
        timeout_seconds=float(os.environ.get("PROCESSOR_TIMEOUT_SECONDS", "5")),
    )
    return create_apps(sim)


processor_app, control_app = from_environment()
