# ADR-0004: Payment fundamentals

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29  
Supersedes: None  
Superseded by: None

## Context and forces

A payments API needs agreed rules for duplicate requests, money representation and lifecycle before any schema or endpoint is written. Full detail is in [payment-lifecycle.md](../architecture/payment-lifecycle.md).

- Constraint: Synthetic data only; correctness matters even so, because the project is judged on engineering quality.
- Quality attribute: Safe retries by clients and no rounding errors.
- Evidence: Standard industry practice for payment APIs; the lifecycle document.

## Decision

We will require an `Idempotency-Key` header on `POST /payments` (same key and body returns the original response, same key with a different body returns 409, keys retained 24 hours), represent money as an integer `amount_minor` (BIGINT) plus an ISO 4217 `currency` and never as floats, and enforce the state machine received -> routed -> authorized -> captured, with declined and failed terminal for the attempt and one retry allowed from failed to routed on the other processor, rejecting invalid transitions, because these rules make retries safe, avoid float errors and keep the timeline unambiguous.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (undefined) | No work now | Schema and API cannot be written | Blocks Phase 1 |
| Optional idempotency key | Easier for clients | Duplicate payments on retry | Defeats the purpose |
| Decimal or float amounts | Familiar | Rounding errors, currency-exponent ambiguity | Integers in minor units are exact |
| Free-form status field | Flexible | Invalid states and untestable behavior | A strict state machine is testable |

## Consequences

### Positive

- Retries are safe; amounts are exact; every transition is testable and appears in the event history.

### Negative and tradeoffs

- Idempotency needs storage and a 24-hour cleanup job.
- Clients must supply keys and handle 409.

### Follow-on work

- Implement in tasks REL-14 to REL-18 in `docs/delivery/delivery-plan.md`.
- Keep `docs/architecture/payment-lifecycle.md` the single source for the transition table.

## Validation and review

- Validate with: pytest cases for every row of the transition table, duplicate-key replay, conflicting-key 409 and currency minor-unit handling.
- Revisit when: partial captures, refunds or multi-currency conversion are added.
- Reversal/migration cost: Low before code; high after clients depend on the API.
