# Relay — Roadmap

## Status
Decided with ADR-0002. Phase-ordered, without dates. The owner (Brendan) decides when each phase is done. Tasks are defined in `docs/delivery/delivery-plan.md` and tracked as GitHub Issues.

## Phase 0 — Foundation (done)
Product docs, architecture docs, ADRs 0001-0006, repository guidance, licence and ignore rules. No application code.

**Exit criteria (met):**
- Positioning, scope, event-history approach and payment fundamentals are decided and recorded as ADRs.
- Product docs, glossary and risk register are consistent with those decisions.
- The full task plan exists (`docs/delivery/delivery-plan.md`) with one GitHub issue per task.

## Phase 1 — Showcase slice
A complete vertical slice, small but end to end:

- Payments API: create, get and list payments, with idempotency (`docs/architecture/payment-lifecycle.md`).
- Two simulated processors ("Processor A" and "Processor B") and a synthetic load generator with injectable failures and outages; the generator uses only the public API.
- Per-payment event history via the transactional outbox and a relay process to Redis Streams (ADR-0003).
- Rule-based routing with failover when a processor's recent error rate crosses a threshold.
- An "explain this payment" endpoint that turns the event timeline into a plain-language explanation using a local open-source model via Ollama, with a deterministic rule-based fallback when no model is available, so tests and CI need no model (ADR-0005).
- A minimal Next.js UI: payment list, and payment detail with timeline and explanation.

**Exit criteria:**
- `docker compose up` brings up the whole system locally.
- A scripted demo injects a Processor A outage and shows failover plus an explanation.
- The pytest suite and a Playwright smoke test pass in CI (GitHub Actions).
- State machine, idempotency and money rules are covered by tests.
- Risks R1 and R5 are reassessed with implementation evidence.

## Phase 2 — Operations depth
- Incident management: structured incident records linked to affected payments and events.
- Monitoring dashboards with Prometheus and Grafana (confirm ADR-0006 at kickoff).
- Analytics: failures, recoveries and revenue impact by processor and reason.

**Exit criteria:**
- ADR-0006 is Accepted before dashboards are built.
- An incident can be created (manually or by rule) and linked to the payments and events that caused it, and its lifecycle updated end to end.
- The guardrail metrics in `metrics.md` are visible on a dashboard.
- The outcome metrics (revenue recovered, success-rate uplift) are computed from the synthetic environment against the static-routing baseline.

## Phase 3 — Integrations
- Webhooks for payment lifecycle events, with documented retry behavior.
- Developer documentation for the API.
- A client SDK.

**Exit criteria:**
- A subscriber can register for an event type and reliably receive a webhook for a payment reaching that state.
- Delivery failure and retry behavior are documented and tested.
- A developer can make a first successful API call using only the docs.

## Phase 4 — Optimization
- Adaptive routing that learns from processor behavior; AI-assisted where it adds value.

**Exit criteria:**
- Adaptive routing beats the Phase 1 rule-based routing on the synthetic environment by a stated, reproducible measure.
- Any paid dependency has an owner decision recorded as an Accepted ADR; otherwise the feature works with free and open-source tooling.

## Sequencing risk
Later phases consume the event history designed in Phase 1. If the event schema is under-designed, expect rework; tracked as R1 in `docs/delivery/risk-register.md` (Low likelihood given the transactional outbox).
