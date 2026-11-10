"""GET /processors/health (api-contract.md). The API key (401) is checked by the middleware in app.main."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.schemas import iso_utc
from app.routing.config import health_settings, strategy
from app.routing.health import compute_health

router = APIRouter()


class ProcessorHealthItem(BaseModel):
    name: str
    attempts: int
    errors: int
    error_rate: float
    state: str


class ProcessorHealthResponse(BaseModel):
    strategy: str
    window_seconds: int
    error_threshold: float
    processors: list[ProcessorHealthItem]
    computed_at: str


@router.get("/processors/health", response_model=ProcessorHealthResponse, summary="Recent health per processor")
async def processors_health(request: Request) -> ProcessorHealthResponse:
    settings = health_settings()

    def read() -> list[ProcessorHealthItem]:
        with Session(request.app.state.engine) as session:
            health = compute_health(session, settings)
        return [ProcessorHealthItem(**vars(h)) for h in health.values()]

    return ProcessorHealthResponse(
        strategy=strategy(),
        window_seconds=settings.window_seconds,
        error_threshold=settings.error_threshold,
        processors=await run_in_threadpool(read),
        computed_at=iso_utc(datetime.now(UTC)),
    )
