import dataclasses
import itertools

import pytest

from app.domain.lifecycle import (
    Event,
    InvalidTransitionError,
    LateResultError,
    PaymentState,
    PaymentStatus,
    StaleAttemptError,
    new_payment,
    transition,
)
from app.domain.reasons import LateResultReason

S = PaymentState
E = Event


def st(state: PaymentState, attempt: int, final: bool = False) -> PaymentStatus:
    return PaymentStatus(state, attempt, final)


# (current status, event, expected state, expected attempt, expected is_final); retries enabled
ALLOWED = [
    (st(S.RECEIVED, 0), E.ROUTE, S.ROUTED, 1, False),
    (st(S.ROUTED, 1), E.AUTHORIZE, S.AUTHORIZED, 1, False),
    (st(S.ROUTED, 2), E.AUTHORIZE, S.AUTHORIZED, 2, False),
    (st(S.ROUTED, 1), E.DECLINE, S.DECLINED, 1, True),
    (st(S.ROUTED, 2), E.DECLINE, S.DECLINED, 2, True),
    (st(S.ROUTED, 1), E.FAIL, S.FAILED, 1, False),  # retry-eligible
    (st(S.ROUTED, 2), E.FAIL, S.FAILED, 2, True),
    (st(S.AUTHORIZED, 1), E.CAPTURE, S.CAPTURED, 1, True),
    (st(S.AUTHORIZED, 2), E.CAPTURE, S.CAPTURED, 2, True),
    (st(S.AUTHORIZED, 1), E.FAIL, S.FAILED, 1, True),  # the authorization belongs to the first processor
    (st(S.AUTHORIZED, 2), E.FAIL, S.FAILED, 2, True),
    (st(S.FAILED, 1, False), E.ROUTE, S.ROUTED, 2, False),  # the single retry
]


def test_new_payment() -> None:
    assert new_payment() == st(S.RECEIVED, 0, False)


@pytest.mark.parametrize(("current", "event", "state", "attempt", "final"), ALLOWED)
def test_allowed_transitions(
    current: PaymentStatus, event: Event, state: PaymentState, attempt: int, final: bool
) -> None:
    before = dataclasses.replace(current)
    result = transition(current, event, retries_enabled=True)
    assert result == PaymentStatus(state, attempt, final)
    assert current == before


def _all_pairs() -> list[tuple[PaymentStatus, Event]]:
    # Reachable shapes only: received is attempt 0, every other state has attempt 1 or 2.
    shapes = [(s, a) for s in PaymentState for a in ((0,) if s is S.RECEIVED else (1, 2))]
    statuses = [st(s, a, final) for s, a in shapes for final in (False, True)]
    return list(itertools.product(statuses, Event))


def _is_allowed(current: PaymentStatus, event: Event) -> bool:
    return any(c == current and e == event for c, e, *_ in ALLOWED)


REJECTED = [(c, e) for c, e in _all_pairs() if not _is_allowed(c, e)]


@pytest.mark.parametrize(("current", "event"), REJECTED)
def test_every_other_pair_is_rejected_and_changes_nothing(current: PaymentStatus, event: Event) -> None:
    before = dataclasses.replace(current)
    with pytest.raises(InvalidTransitionError):
        transition(current, event, retries_enabled=True)
    assert current == before


def test_rejected_set_is_not_vacuous() -> None:
    assert len(REJECTED) > 90
    assert len(ALLOWED) == 12


def test_second_retry_is_rejected() -> None:
    final = transition(st(S.ROUTED, 2), E.FAIL, retries_enabled=True)
    assert final.is_final
    with pytest.raises(InvalidTransitionError):
        transition(final, E.ROUTE, retries_enabled=True)


def test_retry_after_failed_from_authorized_rejected() -> None:
    failed = transition(st(S.AUTHORIZED, 1), E.FAIL, retries_enabled=True)
    assert failed.is_final
    with pytest.raises(InvalidTransitionError):
        transition(failed, E.ROUTE, retries_enabled=True)


def test_full_retry_path_captures_on_attempt_2() -> None:
    status = new_payment()
    for event in (E.ROUTE, E.FAIL, E.ROUTE, E.AUTHORIZE, E.CAPTURE):
        status = transition(status, event, retries_enabled=True)
    assert status == PaymentStatus(S.CAPTURED, 2, True)


def test_retries_disabled_makes_failure_final_and_blocks_retry() -> None:
    failed = transition(st(S.ROUTED, 1), E.FAIL, retries_enabled=False)
    assert failed == PaymentStatus(S.FAILED, 1, True)
    with pytest.raises(InvalidTransitionError):
        transition(failed, E.ROUTE, retries_enabled=False)


def test_retries_disabled_blocks_retry_even_for_non_final_failed() -> None:
    with pytest.raises(InvalidTransitionError):
        transition(st(S.FAILED, 1, False), E.ROUTE, retries_enabled=False)


@pytest.mark.parametrize(
    ("current", "event", "final"),
    [
        (st(S.ROUTED, 1), E.AUTHORIZE, False),
        (st(S.ROUTED, 1), E.DECLINE, True),
        (st(S.AUTHORIZED, 1), E.CAPTURE, True),
        (st(S.AUTHORIZED, 1), E.FAIL, True),
        (st(S.ROUTED, 2), E.FAIL, True),
        (st(S.ROUTED, 1), E.FAIL, False),
    ],
)
def test_is_final_rule(current: PaymentStatus, event: Event, final: bool) -> None:
    assert transition(current, event, retries_enabled=True).is_final is final


@pytest.mark.parametrize("event", [E.AUTHORIZE, E.DECLINE, E.FAIL, E.CAPTURE])
@pytest.mark.parametrize("event_attempt", [1, 3])
def test_result_for_non_current_attempt_is_stale(event: Event, event_attempt: int) -> None:
    current = st(S.ROUTED, 2) if event in (E.AUTHORIZE, E.DECLINE, E.FAIL) else st(S.AUTHORIZED, 2)
    before = dataclasses.replace(current)
    with pytest.raises(StaleAttemptError) as info:
        transition(current, event, retries_enabled=True, event_attempt=event_attempt)
    assert info.value.reason is LateResultReason.STALE_ATTEMPT
    assert current == before


def test_late_answer_from_processor_a_after_retry() -> None:
    routed_b = transition(st(S.FAILED, 1, False), E.ROUTE, retries_enabled=True)
    with pytest.raises(StaleAttemptError):
        transition(routed_b, E.AUTHORIZE, retries_enabled=True, event_attempt=1)


def test_matching_attempt_is_accepted() -> None:
    result = transition(st(S.ROUTED, 2), E.AUTHORIZE, retries_enabled=True, event_attempt=2)
    assert result.state is S.AUTHORIZED


@pytest.mark.parametrize("event", [E.AUTHORIZE, E.DECLINE, E.CAPTURE])
def test_result_after_sweeper_failed_the_attempt_is_after_timeout(event: Event) -> None:
    current = st(S.FAILED, 1, True)
    with pytest.raises(LateResultError) as info:
        transition(current, event, retries_enabled=True, event_attempt=1)
    assert info.value.reason is LateResultReason.AFTER_TIMEOUT
    assert not isinstance(info.value, StaleAttemptError)
    assert current == st(S.FAILED, 1, True)


def test_stale_takes_precedence_over_after_timeout() -> None:
    with pytest.raises(StaleAttemptError):
        transition(st(S.FAILED, 2, True), E.AUTHORIZE, retries_enabled=True, event_attempt=1)


def test_error_hierarchy() -> None:
    assert issubclass(StaleAttemptError, LateResultError)
    assert issubclass(LateResultError, InvalidTransitionError)
