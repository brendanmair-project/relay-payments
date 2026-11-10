"""Rule-based payment explainer (REL-24): the always-available fallback of ADR-0005.

A pure function from a payment's ordered events to one `Explanation`. The same events always give the same output.
Only event types, reasons, attempt numbers and `data.result` / `data.outcome` / `data.operation` are read; the
payment `description` and any other free text never reach the output (ADR-0012). Every pattern is listed once in
`PATTERNS` (pattern -> cause, next step) so a test can prove each has a case.

The payment's final state comes from the `payment.final` event (`data.outcome`); a timeline without one is still in
progress.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.reasons import DeclinedReason, EventType, FailedReason, LateResultReason, RoutedReason

SOURCE = "rules"

# pattern -> (cause, next step). Plain language, one or two sentences each.
PATTERNS: dict[str, tuple[str, str]] = {
    "decline_insufficient_funds": (
        "The customer's card was declined because there was not enough money available.",
        "Ask the customer to use another payment method or add funds, then try again.",
    ),
    "decline_do_not_honor": (
        "The customer's bank refused the payment without giving a specific reason.",
        "Ask the customer to contact their bank or use another payment method.",
    ),
    "decline_card_expired": (
        "The customer's card has expired, so the bank declined the payment.",
        "Ask the customer to try again with an updated card.",
    ),
    "authorize_timeout": (
        "The processor did not answer in time when Relay asked it to approve the payment.",
        "Check the processor's status, then ask the customer to try the payment again.",
    ),
    "authorize_outage": (
        "The processor was down when Relay asked it to approve the payment.",
        "Check the processor's status and try the payment again once it is back up.",
    ),
    "capture_failed": (
        "The processor approved the payment but then refused to collect the money.",
        "Release the held approval at the processor to free the customer's funds, then try the payment again.",
    ),
    "capture_timeout": (
        "The processor approved the payment but did not answer in time when Relay asked it to collect the money.",
        "Release the held approval at the processor if it is still open, then try the payment again.",
    ),
    "capture_outage": (
        "The processor approved the payment but went down while collecting the money.",
        "Release the held approval at the processor if it is still open, then try again once the processor is back up.",
    ),
    "failed_after_retry": (
        "Both attempts failed, first on one processor and then on the other, so the payment could not be completed.",
        "Check the status of both processors and ask the customer to try again later.",
    ),
    "captured_after_retry": (
        "The first attempt failed on a technical problem, but Relay retried on the other processor and the payment was "
        "captured.",
        "No action is needed.",
    ),
    "captured_first_time_adaptive": (
        "The payment was approved and captured on the first attempt, on the processor that Relay's adaptive routing "
        "chose from recent outcomes.",
        "No action is needed.",
    ),
    "captured_first_time": (
        "The payment was approved and captured on the first attempt.",
        "No action is needed.",
    ),
    "late_result_after_retry": (
        "An earlier attempt answered after Relay had moved on to a retry, so that late answer was ignored.",
        "Check that the earlier processor holds no approval for this payment; otherwise no action is needed.",
    ),
    "orphaned_authorization": (
        "The processor approved the payment after Relay had already marked it failed, leaving an orphaned "
        "authorization that may still be held on the customer's card.",
        "Void or release the authorization at the processor so the customer's funds are not tied up.",
    ),
    "late_capture_after_timeout": (
        "After Relay marked the payment failed, the processor reported that the money was collected.",
        "Refund the customer at the processor, or confirm with them that the charge should stand.",
    ),
    "stalled_and_redriven": (
        "The payment stalled before it finished, so Relay's recovery job restarted it and it was then captured.",
        "No action is needed.",
    ),
    "static_no_retry": (
        "The first attempt failed and was not retried, because this payment used fixed routing with no retries.",
        "Turn on automatic routing, which retries on the other processor, or try the payment again by hand.",
    ),
    "in_progress": (
        "The payment is still in progress and has not reached a final result yet.",
        "Check again in a few moments. The timeline shows the latest step.",
    ),
    "unknown": (
        "Relay could not match this payment's timeline to a known pattern.",
        "Read the timeline entries to see what happened.",
    ),
}

_DECLINE_PATTERNS = {
    DeclinedReason.INSUFFICIENT_FUNDS.value: "decline_insufficient_funds",
    DeclinedReason.DO_NOT_HONOR.value: "decline_do_not_honor",
    DeclinedReason.CARD_EXPIRED.value: "decline_card_expired",
}
_CAPTURE_STAGE_PATTERNS = {
    FailedReason.CAPTURE_FAILED.value: "capture_failed",
    FailedReason.TIMEOUT.value: "capture_timeout",
    FailedReason.OUTAGE.value: "capture_outage",
}
_AUTHORIZE_STAGE_PATTERNS = {
    FailedReason.TIMEOUT.value: "authorize_timeout",
    FailedReason.OUTAGE.value: "authorize_outage",
}


@dataclass(frozen=True)
class ExplainEvent:
    """The fields of a timeline event the explainer reads (the read endpoint's Event shape)."""

    seq: int
    type: str
    attempt_no: int | None = None
    processor: str | None = None
    reason: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    to_status: str | None = None
    occurred_at: str | None = None

    @classmethod
    def of(cls, raw: "ExplainEvent | Mapping[str, Any]") -> "ExplainEvent":
        if isinstance(raw, ExplainEvent):
            return raw
        return cls(
            seq=int(raw["seq"]),
            type=str(raw["type"]),
            attempt_no=raw.get("attempt_no"),
            processor=raw.get("processor"),
            reason=raw.get("reason"),
            data=raw.get("data") or {},
            to_status=raw.get("to_status"),
            occurred_at=raw.get("occurred_at"),
        )


@dataclass(frozen=True)
class Explanation:
    pattern: str
    cause: str
    next_step: str
    cited_event_seqs: tuple[int, ...]
    source: str = SOURCE


def _make(pattern: str, *cited: ExplainEvent | None) -> Explanation:
    cause, next_step = PATTERNS[pattern]
    seqs = tuple(sorted({e.seq for e in cited if e is not None}))
    return Explanation(pattern, cause, next_step, seqs)


def explain(events: Sequence[ExplainEvent | Mapping[str, Any]]) -> Explanation:
    """Explain a payment from its events (any order; they are sorted by `seq`)."""
    timeline = sorted((ExplainEvent.of(e) for e in events), key=lambda e: e.seq)
    if not timeline:
        raise ValueError("cannot explain a payment with no events")

    def of_type(*types: EventType) -> list[ExplainEvent]:
        names = {t.value for t in types}
        return [e for e in timeline if e.type in names]

    def last_of(type_: EventType, attempt: int | None = None) -> ExplainEvent | None:
        found = [e for e in of_type(type_) if attempt is None or e.attempt_no == attempt]
        return found[-1] if found else None

    late_results = of_type(EventType.ATTEMPT_LATE_RESULT)

    # A late result is the most important fact: it can leave money held or collected.
    for late in late_results:
        if late.reason != LateResultReason.AFTER_TIMEOUT.value:
            continue
        failed = last_of(EventType.PAYMENT_FAILED, late.attempt_no)
        if late.data.get("result") == "approved":
            return _make("orphaned_authorization", failed, late)
        if late.data.get("result") == "captured":
            return _make("late_capture_after_timeout", failed, late)
    for late in late_results:
        if late.reason == LateResultReason.STALE_ATTEMPT.value:
            return _make("late_result_after_retry", last_of(EventType.PAYMENT_FAILED, late.attempt_no), late)

    final = last_of(EventType.PAYMENT_FINAL)
    if final is None:
        return _make("in_progress", timeline[-1])
    outcome = final.data.get("outcome")
    failures = of_type(EventType.PAYMENT_FAILED)

    if outcome == "declined":
        declined = last_of(EventType.PAYMENT_DECLINED)
        pattern = _DECLINE_PATTERNS.get(declined.reason or "") if declined else None
        if declined and pattern:
            return _make(pattern, last_of(EventType.ATTEMPT_AUTHORIZE_RESULT, declined.attempt_no), declined)

    elif outcome == "captured":
        captured = last_of(EventType.PAYMENT_CAPTURED)
        redriven = last_of(EventType.PAYMENT_REDRIVEN)
        if captured and redriven:
            return _make("stalled_and_redriven", redriven, captured)
        if captured and failures:
            retry_route = last_of(EventType.PAYMENT_ROUTED)
            return _make("captured_after_retry", failures[0], retry_route, captured)
        if captured:
            routes = of_type(EventType.PAYMENT_ROUTED)
            first_route = routes[0] if routes else None
            if first_route and first_route.reason == RoutedReason.ADAPTIVE.value:
                return _make("captured_first_time_adaptive", first_route, captured)
            return _make("captured_first_time", captured)

    elif outcome == "failed" and failures:
        if len(failures) >= 2:
            return _make("failed_after_retry", failures[0], failures[-1])
        failure = failures[0]
        attempt = failure.attempt_no
        authorized = last_of(EventType.PAYMENT_AUTHORIZED, attempt)
        if authorized:  # failed after approval: the capture step
            pattern = _CAPTURE_STAGE_PATTERNS.get(failure.reason or "")
            if pattern:
                return _make(pattern, authorized, last_of(EventType.ATTEMPT_CAPTURE_RESULT, attempt), failure)
        else:
            routed = last_of(EventType.PAYMENT_ROUTED, attempt)
            result = last_of(EventType.ATTEMPT_AUTHORIZE_RESULT, attempt)
            if routed and routed.reason == RoutedReason.STATIC.value:
                return _make("static_no_retry", routed, result, failure)
            pattern = _AUTHORIZE_STAGE_PATTERNS.get(failure.reason or "")
            if pattern:
                return _make(pattern, result, failure)

    return _make("unknown", final)
