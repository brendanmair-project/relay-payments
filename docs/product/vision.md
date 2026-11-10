# Relay — Product Vision

## Status
Accepted positioning ([ADR-0002](../decisions/0002-positioning-and-business-problem.md)). Relay is a portfolio project that solves a concrete business problem using synthetic data only.

## One-line description
Relay is a payment operations platform for a merchant that routes card payments through two processors: it gives every payment one timeline, explains each failure in plain language (AI-assisted), and routes around a degraded processor.

## Problem statement
An online merchant routes card payments through two payment processors. Failed and stuck payments cost revenue: lost sales, false declines and processor outages. When something goes wrong, the payment-operations team spends hours per incident rebuilding what happened across processor dashboards and logs, and meanwhile payments keep failing on the degraded processor.

Three compounding problems:

1. **Fragmented visibility** — payment state, processor responses and routing decisions live in different tools.
2. **Manual investigation load** — a human reconstructs the history of each failed or stuck payment.
3. **Reactive operations** — traffic keeps flowing to a degraded processor until someone notices.

> All data in Relay is synthetic. Relay never handles real payments or card data.

## Product concept
Relay is a payment operations platform (payments, events, investigation, routing, incidents, webhooks, and SDKs later) built in layers:

1. **Payments API** — create, get and list payments with idempotency; a strict payment lifecycle (`docs/architecture/payment-lifecycle.md`).
2. **Synthetic environment** — two simulated processors ("Processor A" and "Processor B") with different latency, decline-rate and outage profiles, plus a load generator with injectable failures. The generator uses only the public API.
3. **Per-payment event history** — PostgreSQL is the source of truth; every state change also appends to an append-only `payment_events` table in the same database transaction, and a relay process publishes those rows to Redis Streams.
4. **Routing with failover** — rule-based routing that moves traffic to the other processor when a processor's recent error rate crosses a threshold.
5. **Explanation** — an "explain this payment" endpoint turns the event timeline into a plain-language explanation using a local open-source model via Ollama, with a deterministic rule-based fallback.
6. **UI** — a minimal Next.js payment list and payment detail with timeline and explanation.
7. Later phases: incident management, monitoring dashboards, analytics (Phase 2); webhooks, developer docs and an SDK (Phase 3); adaptive and AI-assisted routing (Phase 4). See `roadmap.md`.

## Why "intelligent"
AI assists investigation and, later, routing. It never replaces the correctness-critical logic or the raw event history: an explanation is always shown alongside the timeline it came from.

## Non-goals
- Relay is not a real payment processor, money mover, or regulated financial institution.
- No real card data, banking rails or card networks.
- No multi-tenancy: one merchant, one static API key.
- No compliance or risk-team tooling; the per-payment event history gives an audit trail, and that is the extent of it.

## Guiding constraint
The product must remain fully functional using free and open-source software, with local development as the canonical full environment. Cloud services are optional demo infrastructure limited to free tiers. See `docs/architecture/constraints.md`.
