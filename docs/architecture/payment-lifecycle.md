# Relay - Payment Lifecycle

## Status
Accepted design ([ADR-0004](../decisions/0004-payment-fundamentals.md)), with attempt and reliability rules from [ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md) (Accepted 2026-10-01), currencies from [ADR-0009](../decisions/0009-phase-1-owner-decisions.md), and the payment reference and late-result rules from [ADR-0012](../decisions/0012-phase-1-review-decisions.md). The payment code arrives in REL-14 onward; this document is the single source for the rules below and for the transition table. Storage is in [data-model.md](data-model.md) and the endpoints in [api-contract.md](api-contract.md).

## Money

- Amounts are integers in minor units: `amount_minor` (BIGINT), for example 1999 for 19.99 USD. Amounts must be positive.
- `currency` is one of the supported ISO 4217 codes below; any other code is rejected with 422 (ADR-0009).

| Currency | Minor-unit digits |
|---|---|
| USD | 2 |
| EUR | 2 |
| GBP | 2 |
| JPY | 0 |

- Floats and decimals are never used for money, in storage, API or code.
- All timestamps are stored as `timestamptz` in UTC.

## Idempotency

- `POST /payments` requires an `Idempotency-Key` header; a missing key is rejected with 400.
- The same key with the same body returns the original response (same status and payment). Bodies are compared by a hash of their canonical JSON.
- The same key with a different body returns 409.
- A second request with a key whose first request is still in progress returns 409; once the first completes, repeats get the stored response (ADR-0008).
- Keys are unique in storage and retained for 24 hours; after that the key may be reused.
- Idempotency applies to creation only. Every other request in Phase 1 is a read.

## Access

Every endpoint requires the `X-API-Key` header; a missing or wrong key returns 401. The UI reaches the API only through Next.js server routes that add the key (ADR-0009).

## State machine

States: `received`, `routed`, `authorized`, `captured`, `declined`, `failed`.

- `received`: the payment was accepted by the API and stored.
- `routed`: a processor (Processor A or B) was chosen for an attempt.
- `authorized`: the processor approved the payment.
- `captured`: the funds were captured; this is the success end state.
- `declined`: the processor refused the payment (for example insufficient funds). Final, no retry.
- `failed`: the attempt failed for a technical reason (timeout, processor outage, failed capture). It may be retried once on the other processor, see below.

### Attempts and final outcome

- Each payment has an `attempt_no`: 1 for the first processor, 2 for the single retry. Every transition and event carries the attempt number.
- A processor result whose attempt or expected state no longer matches is recorded as an `attempt.late_result` event and changes nothing: reason `stale_attempt` when the attempt is no longer current (for example a late answer from Processor A after the payment was retried on Processor B), `after_timeout` when the sweeper already failed the current attempt. No result is ever dropped; a late approval means the processor holds an authorization Relay will not capture (an orphaned authorization), and the explanation says so (ADR-0012).
- Each payment has `is_final`. A payment is final when it is `captured`, `declined`, `failed` from `authorized`, `failed` on attempt 2, or `failed` while retries are disabled (the static-routing baseline, ADR-0009).
- A `failed` payment that is not final is **retrying**: the worker schedules the retry on the other processor. The UI shows it as "Retrying" and metrics count only final payments.

### Transition table

| From | To | Allowed | Notes |
|---|---|---|---|
| (none) | received | Yes | Creation, attempt 0 |
| received | routed | Yes | Routing decision recorded; attempt becomes 1 |
| routed | authorized | Yes | Processor approved |
| routed | declined | Yes | Processor refused; final |
| routed | failed | Yes | Timeout or outage; retry-eligible on attempt 1 |
| authorized | captured | Yes | Success end state; final |
| authorized | failed | Yes | Capture failed for a technical reason; final, because the authorization belongs to the first processor |
| failed | routed | Yes, once | Only when not final; attempt becomes 2 on the other processor |
| declined | any | No | Final |
| captured | any | No | Final |
| failed | any other | No | Except the single retry to routed |
| any other pair | any | No | Rejected as an invalid transition |

An invalid transition is rejected and does not change state; the rejection itself is not written as a state change.

### Timeouts and stalled work

The sweeper in the worker (ADR-0008):

- moves a payment that stays in `routed` or `authorized` longer than the processor timeout plus a grace period (ADR-0011) to `failed` (a timeout from `routed` on attempt 1 remains retry-eligible);
- re-drives a payment that stays in `received`, or in a retrying `failed`, longer than a threshold by publishing a new trigger; this is not a state change.

So no payment is stuck silently, even if a stream message is lost.

### Processor calls

Authorize and capture calls carry the idempotency key `<payment_id>:<attempt_no>` and the payment's optional `reference`. The simulator returns the first result for a repeated key, so a redelivered message never authorizes or captures twice, and it seeds its draws on the reference when there is one, so runs with one seed repeat per payment (ADR-0012).

## Event history

Every allowed transition also appends a row to the append-only `payment_events` table in the same database transaction as the state change ([ADR-0003](../decisions/0003-payment-event-history.md)), with a per-payment sequence number and the attempt number. Routing decisions (including failover), processor calls and late results are recorded as events with the processor and the reason. A relay process publishes these rows to a Valkey stream (Redis-compatible, ADR-0012). The worker acts only on trigger events and checks the payment's current state and attempt under a row lock before acting.

## Out of scope in Phase 1

Refunds, partial captures, voiding an authorization after a failed capture, chargebacks, multi-currency conversion and settlement. Adding any of them needs a new ADR.
