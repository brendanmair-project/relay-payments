# ADR-0002: Positioning and business problem

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29  
Supersedes: None  
Superseded by: None

## Context and forces

The foundation left audience and positioning undecided (risk R4), which blocked metrics, personas, routing scope, auth and multi-tenancy. A concrete positioning is needed before Phase 1 issues are created.

- Constraint: Synthetic data only; Relay never handles real payments or card data.
- Quality attribute: A reviewer should understand the business value and see it demonstrated end to end.
- Evidence: `docs/product/vision.md`, `docs/product/personas.md`, `docs/product/metrics.md` and `docs/delivery/risk-register.md` (R2, R4, R6) before this change.

## Decision

We will position Relay as a portfolio project that solves a concrete business problem, using synthetic data only, because a specific problem with measurable outcomes is a stronger showcase than a generic platform. The problem: an online merchant routes card payments through two payment processors; failed and stuck payments cost revenue (lost sales, false declines, processor outages), and the payment-operations team spends hours per incident rebuilding what happened across processor dashboards and logs. Relay gives every payment one timeline, explains each failure in plain language (AI-assisted), and routes around a degraded processor.

Consequences of this decision, applied across the docs:

- The domain term "transaction" becomes "payment"; the API is `/payments`.
- Personas: primary is the Payment Operations Analyst (Dana), secondary is the On-call Engineer (Marcus), later is the Integrating Developer (Sam). The Platform Engineer persona is dropped (that is the builder) and the Risk/Compliance persona is out of scope; the per-payment event history provides an audit trail.
- Single merchant, no multi-tenancy. Authentication is one static API key for that merchant, supplied by an environment variable. The former auth and multi-tenancy backlog items from the original foundation are resolved; the API key is part of task REL-17.
- Routing chooses between two simulated processors, "Processor A" and "Processor B", with different latency, decline-rate and outage profiles; outages are injectable. This resolves risk R6.
- North star metric: median time from a payment failure to an explained root cause. Outcome metrics, measured on the synthetic environment against a static-routing baseline: simulated revenue recovered by failover routing, and payment success-rate uplift.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (undecided positioning) | Flexibility | Blocks metrics, scope and every dependent decision | Risk R4 stays open indefinitely |
| Generic payment operations platform with no named problem | Broad, flexible story | No measurable outcome; hard to demo | A concrete failure-recovery problem is demonstrable |
| Multi-tenant SaaS product | Realistic product shape | Auth, tenancy and compliance work that does not serve the showcase | Out of proportion for a single-owner portfolio project |

## Consequences

### Positive

- Clear demo story: inject a Processor A outage, watch failover, read the explanation.
- Metrics can be measured on the synthetic environment against a baseline.

### Negative and tradeoffs

- Narrower than the original platform framing; Phase 3 and Phase 4 items stay conceptual until earlier phases finish.
- A static API key is not production-grade auth; this is acceptable for a synthetic single-merchant demo and is stated in the docs.

### Follow-on work

- Keep `docs/product/` docs, the glossary and the risk register consistent with this ADR.
- Create GitHub issues from the task plan (`docs/delivery/delivery-plan.md`).

## Validation and review

- Validate with: the scripted outage demo and the outcome metrics in `docs/product/metrics.md`.
- Revisit when: the owner wants real multi-merchant use, or the synthetic results do not show a meaningful uplift.
- Reversal/migration cost: Low while docs only; moderate once the API and data model exist, since tenancy would touch every table.
