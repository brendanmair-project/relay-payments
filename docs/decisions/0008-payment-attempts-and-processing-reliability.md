# ADR-0008: Payment attempts and processing reliability

Template: claude/decision@1

Status: Accepted (by the owner, 2026-10-01, in task REL-53)  
Decision owner: Brendan  
Date: 2026-09-30  
Supersedes: None  
Superseded by: None

## Context and forces

A review of the delivery plan on 2026-09-30 found that ADR-0003 and ADR-0004 guarantee a consistent history but not that every payment reaches the right final state. Specific failure paths: a payment stays `received` forever when its stream message is lost; a late processor answer for a timed-out attempt is applied to the retry on the other processor; `failed` means both "retry pending" and "finished"; a redelivered message calls a processor twice; two concurrent requests with one idempotency key both create a payment; the router's error rate lives in one process's memory. This ADR amends ADR-0004 and extends ADR-0003; it does not replace them.

- Constraint: Delivery from Redis Streams is at-least-once (ADR-0003); workers and processes can crash at any point.
- Quality attribute: Every payment reaches exactly one final outcome, with no double authorization or capture, and no silent stall.
- Evidence: Relay plan review of 2026-09-30 (gaps A1 to A9), recorded in `docs/delivery/process-log.md` (session 5).

## Decision

We will make every processing step attempt-scoped, state-guarded and recoverable, because at-least-once delivery and crashes are normal and only these rules keep the outcome exact:

1. **Attempts.** A payment has an `attempt_no` (1 or 2). Every transition and every event carries it. A processor result for an attempt that is no longer current is written as an event and changes nothing.
2. **Final outcome.** A payment also has `is_final`. It is final when captured, declined, failed from `authorized`, failed on attempt 2, or failed when retries are disabled (static baseline, ADR-0009). A `failed` payment that is not final is shown and counted as "retrying". Metrics use final payments only.
3. **State-guarded work.** The worker acts only on trigger events (payment received, retry scheduled). Before acting it locks the payment row and checks that state and attempt still match; otherwise it acknowledges the message and does nothing. No separate processed-message table is needed.
4. **Idempotent processor calls.** Authorize and capture calls carry the key `<payment_id>:<attempt_no>`; the simulator returns the first result for a repeated key without a new outcome.
5. **Recovery.** Pending stream messages of a crashed consumer are reclaimed after an idle timeout (`XAUTOCLAIM`). The sweeper also re-drives payments stalled in `received` or in retry-pending `failed` past a threshold by publishing a new trigger (not a state change), and moves `routed` or `authorized` past the processor timeout to `failed`. Redis runs with append-only persistence; the stream is trimmed with an approximate `MAXLEN`, which is safe because recovery reads from PostgreSQL.
6. **Idempotency under concurrency.** `idempotency_keys` has a unique key, a hash of the canonical request body and an in-progress state. A concurrent request with the same key receives 409 while the first is in progress, then the stored response.
7. **Shared routing health.** Each processor's rolling error rate is computed from recent attempt events in PostgreSQL, so the worker and `GET /processors/health` agree and restarts lose nothing.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (ADR-0004 rules only) | No change | Stalled payments, double processing, ambiguous `failed` | The gaps are real on the at-least-once path |
| Add a `retrying` state to the state machine | Status is explicit in one column | Changes the Accepted transition table and every consumer | `attempt_no` plus `is_final` gives the same information with fewer transitions |
| Processed-message table for deduplication | Simple duplicate check | Extra table and cleanup; still needs a state check for late results | The row-lock state and attempt check covers both cases |
| Exactly-once broker | Fewer duplicates | Outside the fixed stack (ADR-0001), still needs idempotent side effects | Not justified; risk R5 covers a later broker review |

## Consequences

### Positive

- No payment stays in a non-final state without the sweeper acting on it.
- Duplicate or late messages cannot change a payment twice or charge twice.
- Metrics and the UI can tell "retrying" from "finished".

### Negative and tradeoffs

- More columns (`attempt_no`, `is_final`, `status_changed_at`) and more tests.
- The sweeper and consumer reclaim add background work to operate and monitor.

### Follow-on work

- Update `docs/architecture/payment-lifecycle.md` (done with this ADR) and tasks REL-14 to REL-22, REL-50 and REL-53 in `docs/delivery/delivery-plan.md`.
- Validate at Phase 1 exit (REL-32) with the forced-failure and duplicate-delivery tests.

## Validation and review

- Validate with: tests that deliver a message twice, crash a consumer mid-attempt, return a late processor result after a retry, race two requests with one idempotency key, and lose a stream entry; each ends with one correct final outcome and no second processor charge.
- Revisit when: a third processor, more than one retry, or refunds are added.
- Reversal/migration cost: Low before REL-14; moderate after, since the schema and worker depend on it.
