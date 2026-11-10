"""Rolling health from events (REL-22): window, minimum attempts, threshold boundary, error definition."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.routing.health import AVOIDED, PREFERRED, UNKNOWN, compute_health
from tests.routing.conftest import seed

Factory = sessionmaker[Session]


def health(factory: Factory) -> dict[str, tuple[int, int, float, str]]:
    with factory() as session:
        return {n: (h.attempts, h.errors, h.error_rate, h.state) for n, h in compute_health(session).items()}


def test_no_events_is_unknown_with_zero_rate(factory: Factory) -> None:
    assert health(factory) == {"A": (0, 0, 0.0, UNKNOWN), "B": (0, 0, 0.0, UNKNOWN)}


def test_below_min_attempts_is_unknown_even_when_every_attempt_failed(factory: Factory) -> None:
    seed(factory, "A", routed=4, failed=4)
    assert health(factory)["A"] == (4, 4, 1.0, UNKNOWN)


def test_exactly_min_attempts_is_classified(factory: Factory) -> None:
    seed(factory, "A", routed=5, failed=5)
    assert health(factory)["A"][3] == AVOIDED


def test_rate_equal_to_threshold_is_preferred_and_above_is_avoided(factory: Factory) -> None:
    seed(factory, "A", routed=10, failed=5)  # 0.5 is not above 0.5
    seed(factory, "B", routed=10, failed=6)
    result = health(factory)
    assert result["A"] == (10, 5, 0.5, PREFERRED)
    assert result["B"] == (10, 6, 0.6, AVOIDED)


def test_old_events_are_outside_the_window(factory: Factory) -> None:
    seed(factory, "A", routed=10, failed=10, age_seconds=120)
    assert health(factory)["A"] == (0, 0, 0.0, UNKNOWN)
    seed(factory, "A", routed=6, failed=0)
    assert health(factory)["A"] == (6, 0, 0.0, PREFERRED)  # the old failures no longer count


def test_window_follows_the_environment(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(factory, "A", routed=10, failed=10, age_seconds=120)
    monkeypatch.setenv("HEALTH_WINDOW_SECONDS", "300")
    assert health(factory)["A"][3] == AVOIDED


def test_thresholds_follow_the_environment(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(factory, "A", routed=10, failed=3)
    assert health(factory)["A"][3] == PREFERRED
    monkeypatch.setenv("HEALTH_ERROR_THRESHOLD", "0.2")
    assert health(factory)["A"][3] == AVOIDED
    monkeypatch.setenv("HEALTH_MIN_ATTEMPTS", "11")
    assert health(factory)["A"][3] == UNKNOWN


@pytest.mark.parametrize("reason", ["timeout", "outage", "capture_failed"])
def test_technical_failures_count_as_errors(factory: Factory, reason: str) -> None:
    seed(factory, "B", routed=6, failed=6, reason=reason)
    assert health(factory)["B"] == (6, 6, 1.0, AVOIDED)


def test_declines_are_never_errors(factory: Factory) -> None:
    seed(factory, "A", routed=10, declined=10)
    assert health(factory)["A"] == (10, 0, 0.0, PREFERRED)


def test_processors_are_counted_separately(factory: Factory) -> None:
    seed(factory, "A", routed=10, failed=10)
    seed(factory, "B", routed=10)
    result = health(factory)
    assert (result["A"][3], result["B"][3]) == (AVOIDED, PREFERRED)
