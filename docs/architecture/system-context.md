# Relay — System Context

## Status
Design intent for Phase 1 and beyond. Built so far: the compose stack and the simulated processors (REL-12, REL-19); the payment code arrives in REL-14 onward.

## Purpose
This document describes Relay at the system-context level: who and what interacts with it, and why. Component-level design is in [containers.md](containers.md), [api-contract.md](api-contract.md) and [data-model.md](data-model.md) (REL-53).

## External actors

| Actor | Relationship to Relay |
|---|---|
| Payment Operations Analyst (Dana) | Views payments, timelines and explanations in the UI |
| On-call Engineer (Marcus) | Investigates degraded processing; later manages incidents |
| Integrating Developer (Sam), later | Calls the REST API, receives webhooks, uses the SDK |
| Synthetic load generator | An external client that creates payments through the public payment API and switches outages through the simulator's control API; it has no database, stream (Valkey) or other internal access; every payment it creates carries a deterministic `reference`, so demo runs repeat (ADR-0012) |
| Processor A and Processor B | Simulated payment processors with different latency, decline-rate and outage profiles; outages are switched through a control API protected by the API key |
| Ollama (optional) | Local model server used for explanations; by default the host installation, reached at `host.docker.internal:11434`; a rule-based fallback runs when it is absent |

The generator being an external client forces the public API to be complete and realistic, as an integrator would experience it. The simulator control API is part of the synthetic environment, not of Relay.

## High-level system boundary

```
 Load generator ──▶  ┌─────────────────────────────────────────────┐
 (payment API +      │                    Relay                    │
  simulator control) │                                             │
                     │  Next.js UI ──▶ server routes (add API key) │
 Ops Analyst /  ───▶ │                     │                       │
 On-call Engineer    │                     ▼                       │
                     │  Payments API (FastAPI)                     │
                     │     │                                       │
                     │     ▼                                       │
                     │  PostgreSQL (source of truth)               │
                     │   payments + payment_events (outbox)        │
                     │     │                                       │
                     │     ▼                                       │
                     │  Publisher ──▶ Redis Streams ──▶ Worker     │ ──▶ Processor A (simulated)
                     │                  (routing, failover,        │ ──▶ Processor B (simulated)
                     │                   retry, sweeper)           │
                     │                                             │
                     │  Explainer ──▶ Ollama or rule fallback      │
                     └─────────────────────────────────────────────┘
```

A one-off migrate service applies database migrations before the API, worker and publisher start. This is deliberately coarse; see [containers.md](containers.md) for every container and flow.

## Data flow
PostgreSQL is the system of record ([ADR-0003](../decisions/0003-payment-event-history.md)). Every payment state change also appends a row to the append-only `payment_events` table in the same database transaction (a transactional outbox). A publisher process reads unpublished rows and publishes them to Redis Streams, giving at-least-once delivery. The worker consumes trigger events, checks the payment's state and attempt under a row lock, calls the processors with an idempotency key, and records every result as an event; a sweeper re-drives stalled payments ([ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md)). Redis is never a source of truth. Payment rules (idempotency, minor-unit money, attempts, state machine) are in [payment-lifecycle.md](payment-lifecycle.md).

## Access control
One merchant and one static API key supplied by an environment variable ([ADR-0002](../decisions/0002-positioning-and-business-problem.md)). Every API endpoint requires the key; the UI calls the API only through server routes, so the browser never holds it ([ADR-0009](../decisions/0009-phase-1-owner-decisions.md)). The UI in Phase 1 is for local demo use.

## Out of scope for this document
Component-level design, API contracts and database schema: see [containers.md](containers.md), [api-contract.md](api-contract.md) and [data-model.md](data-model.md).
