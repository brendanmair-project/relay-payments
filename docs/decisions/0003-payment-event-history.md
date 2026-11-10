# ADR-0003: Payment event history via transactional outbox

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29  
Supersedes: None  
Superseded by: None

## Context and forces

Every downstream capability (investigation, explanation, analytics, incidents, webhooks) consumes a per-payment history. The foundation left open whether events are the source of truth (event sourcing) or a side effect of database writes (risk R1).

- Constraint: PostgreSQL is the system of record; Redis is in the fixed stack (ADR-0001).
- Quality attribute: The history must never disagree with payment state, and no state change may be lost if a process crashes.
- Evidence: `docs/architecture/system-context.md` and risk R1 in `docs/delivery/risk-register.md`.

## Decision

We will keep PostgreSQL as the source of truth and append a row to an append-only `payment_events` table in the same database transaction as every state change (a transactional outbox), with a separate relay process publishing outbox rows to Redis Streams, because a single database transaction guarantees state and history cannot diverge while avoiding the replay and projection complexity of full event sourcing.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (undecided) | No work now | Risk R1 stays high and blocks Phase 1 schema work | Schema needs the answer |
| Full event sourcing | Complete replay, events are truth | Projection consistency and replay logic; large commitment | Not justified for the showcase slice |
| Write to Postgres, then publish to Redis directly | Simple | Dual write: a crash between the two loses or duplicates events | Cannot guarantee consistency |

## Consequences

### Positive

- State and history commit atomically; the timeline is trustworthy and doubles as an audit trail.
- Redis outages delay publishing but never lose events.

### Negative and tradeoffs

- Consumers see at-least-once delivery and must be idempotent.
- An extra relay process to run and monitor.

### Follow-on work

- Define the event schema and ordering guarantees in Phase 1 (tasks REL-15, REL-16 and REL-20 in `docs/delivery/delivery-plan.md`).
- Reassess R5 (Redis capacity) at Phase 2 exit; R1 is now Low likelihood.

## Validation and review

- Validate with: tests that force a failure between state change and publish and confirm no event is lost or duplicated in the timeline.
- Revisit when: consumers need replay of the full history or Redis Streams becomes a bottleneck.
- Reversal/migration cost: Moderate; the events table can later become the log for event sourcing without changing the write path.
