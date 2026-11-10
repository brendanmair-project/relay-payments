"""Analytics endpoints (REL-37, api-contract.md). The API key (401) is checked by the middleware in app.main."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy.orm import Session

from app.analytics.baseline import read_baseline
from app.analytics.figures import analytics_figures
from app.api.schemas import iso_utc
from app.config import get_settings
from app.errors import ApiError
from app.reporting.report import Window, load_fallback_reasons, load_rows

router = APIRouter()

Processor = Literal["A", "B"]
DEFAULT_RANGE = timedelta(hours=24)
MAX_RANGE = timedelta(days=31)


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def resolve_range(start: datetime | None, end: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    """Defaults: `to` is now and `from` is 24 h before it. A range must be positive and at most 31 days."""
    stop = _utc(end) if end is not None else now
    begin = _utc(start) if start is not None else stop - DEFAULT_RANGE
    if begin >= stop:
        raise ApiError(422, "validation_failed", "`from` must be before `to`")
    if stop - begin > MAX_RANGE:
        raise ApiError(422, "validation_failed", "the range must be at most 31 days")
    return begin, stop


@router.get(
    "/analytics",
    summary="Volume, success rate, latency and failure reasons by processor",
    description="Figures for payments created in [`from`, `to`) (default: the last 24 hours; at most 31 days), "
    "optionally only payments routed to one `processor`. Derived from `payment_events`; money and the handling "
    "processor are joined from `payments`.",
)
def get_analytics(
    request: Request,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    processor: Annotated[Processor | None, Query()] = None,
) -> dict[str, Any]:
    begin, stop = resolve_range(from_, to, datetime.now(UTC))
    window = Window(since=begin, until=stop, processor=processor)
    with Session(request.app.state.engine) as session:
        payments, events = load_rows(session, window)
        fallbacks = load_fallback_reasons(session, window)
    return {
        "window": {"from": iso_utc(begin), "to": iso_utc(stop), "processor": processor},
        **analytics_figures(payments, events, processor=processor, fallback_reasons=fallbacks),
    }


@router.get(
    "/analytics/baseline",
    summary="The REL-30 static-routing baseline figures",
    description="Headline figures read from the REL-30 results file. A missing or malformed file answers 200 with "
    '`{"available": false}`.',
)
def get_baseline() -> dict[str, Any]:
    return read_baseline(get_settings().baseline_results_path)
