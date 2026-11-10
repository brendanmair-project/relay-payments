# Relay — Product Strategy

## Status
Accepted positioning ([ADR-0002](../decisions/0002-positioning-and-business-problem.md)). The owner (Brendan) is the sole decision-maker.

## Positioning
Relay is a portfolio project that solves a concrete business problem: recovering revenue lost to failed and stuck card payments for a merchant using two payment processors, and cutting the time the payment-operations team spends explaining each failure. It uses synthetic data only. The audience is a reviewer who wants to see engineering quality and product thinking demonstrated end to end.

## Strategic principles

1. **Local-first, cloud-optional.** Every capability works fully via Docker Compose. Any cloud demo is an optional thin layer on free tiers.
2. **Synthetic before real.** Everything is built and measured against the simulated processors. No real payments, card data or processor integrations.
3. **Observable by construction.** The per-payment event history exists from the first slice, so explanation, analytics, monitoring and incidents share one consistent log.
4. **Thin vertical slices.** Phase 1 delivers one complete path: a payment is created, routed, fails over when a processor degrades, and is explained in the UI. Depth comes after.
5. **Free and open source; paid dependencies need an owner decision.** A paid dependency (including a paid tier of a freemium service or a hosted AI API) requires an explicit owner decision recorded as an Accepted ADR.
6. **Decisions are recorded.** Significant decisions are ADRs under `docs/decisions/`; tasks are GitHub Issues.

## Resolved strategic questions
- **Audience and positioning:** portfolio project on a business problem (ADR-0002).
- **AI approach:** local open-source model via Ollama with a deterministic fallback (ADR-0005, Proposed).
- **Tenancy and auth:** single merchant; one static API key from an environment variable (ADR-0002).

## Sequencing
Phase 0 Foundation (done), Phase 1 Showcase slice, Phase 2 Operations depth, Phase 3 Integrations, Phase 4 Optimization. See `roadmap.md` for scope and exit criteria.

## Out of scope for this document
Specific stories and their acceptance criteria — see `../docs/delivery-plan.md`.
