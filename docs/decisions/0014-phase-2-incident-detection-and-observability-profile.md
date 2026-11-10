# ADR-0014: Phase 2 incident detection in its own consumer, and observability as an optional profile

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-11-02  
Supersedes: None (refines REL-33 and REL-34; ADR-0006 stays Proposed until REL-33)  
Superseded by: None

## Context and forces

The Phase 2 plan said only that "a processor error-rate spike opens an incident" (REL-34) and that Prometheus and Grafana join the stack (REL-33). The REL-32 plan review (workspace `evaluations/relay-plan-review-2026-11-02-phase2.md`) found that both choices change the schema, the API, the containers and CI cost, so they need a decision.

- Constraint: nothing may delay payment processing (ADR-0012 put model calls in the `explainer` container for this reason). The stream is at-least-once, so it can deliver duplicate and late entries (ADR-0003, confirmed live in `docs/evaluation/phase-1-exit-review.md`).
- Quality attribute: an incident should agree with what the router did. Analysts should not see a processor "in an incident" that routing still prefers, or the reverse.
- Cost: CI runs on the free private plan with a shared minute budget (R12, ADR-0007), and the clean-clone run should stay small.

## Decision

1. **Incident detection.** We will detect incidents in their own consumer, an `incidents` container reading the event stream. The rule reuses the routing health threshold: an incident opens when the router starts avoiding a processor. At most one incident per processor is open at a time, enforced by a unique partial index. When health returns, the detector records `recovered` on the incident, but only an analyst resolves it. This keeps detection off the payment path and in step with routing, and gives one place to handle duplicate and late stream entries. The owner chose this on 2026-11-02.
2. **Observability profile.** We will run Prometheus and Grafana under the compose profile `observability` (`docker compose --profile observability up -d --wait`). The default stack, the clean-clone run and the CI e2e job stay as they are. The owner chose this on 2026-11-02.

## Alternatives considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Own consumer, health-based (one open per processor) | Off the payment path; agrees with routing; one duplicate-handling point | One more container | Chosen |
| Detection inside the worker | No new container | Incident logic on the payment path, against ADR-0012 | Rejected |
| Separate rule and threshold | Tunable independently | Two thresholds; incidents can disagree with routing | Rejected |
| Observability under a profile | Default stack and CI unchanged; no extra minutes | Dashboards need the flag | Chosen |
| Observability always on | Dashboards without a flag | Slower `up`, larger clean clone, more CI minutes | Rejected |

## Consequences

Positive:

- A slow or crashed detector never delays a payment, and an incident always matches a routing decision.
- CI cost and the clean-clone run do not grow in Phase 2.

Negative and tradeoffs:

- Incident timing inherits the routing health window's wall-clock dependence, so REL-36's MTTD/MTTR must pin it or state a tolerance (lesson L-068).
- Dashboards are not visible on a default `up`; the README and `containers.md` must name the profile.

Operational impact:

- REL-34 adds the `incidents` container (restart policy, health check, per-service variables, covered by `api/tests/test_compose_stack.py`) and the unique partial index, with tests for concurrency, duplicates, late entries and a crash. REL-33 adds the profile with pinned, licence-checked images.

## Validation and review

- Validate with: REL-34 tests (one incident per processor under concurrent and duplicate entries; a crash opens no second incident), and the compose contract test asserting that the observability services are profile-only.
- Revisit when: analysts need incidents for conditions routing does not track (for example capture failures), or dashboards must run in CI.
- Owner: Brendan.
