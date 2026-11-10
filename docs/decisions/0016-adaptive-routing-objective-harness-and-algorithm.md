# ADR-0016: Adaptive routing objective, experiment harness and algorithm

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-11-06  
Supersedes: None (refines REL-43 and REL-44)  
Superseded by: None

## Context and forces

Phase 4 must show that adaptive routing "beats the Phase 1 rule-based routing on the synthetic environment by a stated, reproducible measure" (`docs/product/roadmap.md`). The REL-42 plan review (workspace `evaluations/relay-plan-review-2026-11-06-phase4.md`) found that the plan named neither the measure, the way to run the comparison, the algorithm, nor what counts as a win. Each of these changes reported results, so each is an owner decision (checklist PR-17, PR-18).

- Reproducibility: the simulator seeds its draws on the payment `reference`, which the load generator sets deterministically (ADR-0012), so two strategies can be run on identical draws. REL-30 already compared `static` with `rules` this way, with `scripts/outage_demo.py` on the real stack.
- Constraints: free and open source only, no dependency outside the fixed stack without an ADR (ADR-0011); processing never waits on a model (ADR-0012); state several processes need lives in shared storage (PR-6).
- Today: `ROUTING_STRATEGY` selects `rules` (default) or `static`; routing reasons are a closed set guarded by a database CHECK; only two generator scenarios exist (`normal-day`, `processor-a-outage`).

## Decision

1. **Objective.** The primary measure is the success rate as defined in REL-57: captured over final payments, declines included. It is compared per seed on identical payment references (paired runs).
   - **Reported alongside:** revenue captured per currency.
   - **Guardrail:** p95 creation-to-final latency must not be worse than the rule-based router's by more than 10% in any scenario.
   - The 10% margin was confirmed by the owner in the REL-42 review (2026-11-06).
2. **Harness: the real stack.** REL-43 extends `scripts/outage_demo.py` (or a sibling script that reuses it).
   - **Runs:** every strategy on every scenario and seed, against the compose stack, through the load generator, on the same references.
   - **Fresh start:** routing services restart between runs.
   - **Strategy selection:** `ROUTING_STRATEGY` through a small registry in `api/app/routing/`.
   - **Testing:** CI tests the harness logic with fakes. The full comparison is a documented manual run, with its duration recorded.
   - **Scenarios:** a third scenario with a partial degradation of one processor (a raised error rate, not a full outage) joins the two existing ones.
   - **First run:** `static` against `rules`. It must agree with the REL-30 results within their tolerance.
3. **Algorithm: Thompson sampling.** REL-44 adds an `adaptive` strategy: a Beta-Bernoulli posterior per processor over a recent, decaying window of outcomes.
   - **Standard library only:** `random.betavariate`.
   - **Shared state:** the posterior is computed from recent `payment_events` in PostgreSQL, as `app/routing/health.py` computes health, so every worker process and a restart see the same state.
   - **Seeded draws:** the sampler's random draws are seeded from the payment `reference`, so a paired run repeats exactly.
   - **Routing reason:** such payments carry a new routed reason, `adaptive`.
   - **Defaults:** `rules` stays the default.
4. **Win rule.** Across 3 scenarios × 5 seeds, measured against `rules`, the adaptive strategy wins only when all of these hold:
   - the mean paired success-rate uplift is at least 1 percentage point;
   - it is better on at least 80% of the paired runs;
   - the latency guardrail holds.

   Otherwise the result is reported honestly as not winning, with the same numbers. The exploration cost is reported too: the share of payments sent to the processor that was degraded at the time.

## Alternatives considered

- **Revenue as the primary measure:** closer to the business story, but the currency mix adds noise to a paired comparison; kept as a reported figure.
- **A composite score:** one weighted number of success, revenue and latency is harder to explain and to defend.
- **An offline simulation harness:** fast and runnable in CI, but its results describe a model of the processors, not the running system.
- **Epsilon-greedy:** simpler, but its fixed exploration keeps sending traffic to a degraded processor.
- **Smarter sliding-window rules:** easy to explain, but weaker as evidence of adaptive routing.
- **A looser or stricter win rule:** any positive mean is weak evidence. Requiring a win on every pair is likely to fail on noise in calm scenarios, where both strategies are equal.

## Consequences

- REL-43 owns the harness script, the routing registry, the generator and simulator for the new scenario, tests and `docs/evaluation/routing-experiments/`.
- REL-44 owns the routing code, a migration for the new reason, the domain enum, the explainer's texts, UI reason labels and the results.
- A full comparison takes roughly an hour or more of wall time per strategy pair, so it runs by hand, not in CI. The CI minute budget (R12) is unaffected.
- The adaptive strategy can lose; the plan and REL-45 report that result honestly.

## Validation and review

- REL-43: the harness test with fakes passes in CI. The `static` against `rules` run agrees with REL-30 within tolerance. Two runs with the same seed match.
- REL-44: running the same references twice routes the same way. The full 3 × 5 comparison is recorded in `docs/evaluation/` with the win rule evaluated.
- Revisit when a third processor is added, when the objective changes (for example to cost), or when the latency margin proves too tight or too loose.

## Implementation and result

Added by REL-44 on 2026-11-07; none of the decisions above changed.

- **Implemented as decided:** `api/app/routing/adaptive.py` (Thompson sampling, `random.betavariate`, standard library
  only; posterior from decayed `payment_events` counts in PostgreSQL; draws seeded from the SHA-256 of the payment
  `reference`; routed reason `adaptive`, migration 0007; `rules` stays the default; retries as `rules`). Parameters,
  fixed before the comparison in `docs/evaluation/routing-experiments/protocol.md`: window 120 s, half-life 30 s,
  prior Beta(1, 1).
- **Result: not a win.** Over 3 scenarios by 5 seeds against `rules`: mean paired uplift +1.82 pp (holds), better on
  10 of 15 pairs, 67% against 80% required (fails), worst p95 latency ratio 1.829 in `normal-day` against 1.10
  allowed (fails; 0.808 in `processor-a-outage`, 0.340 in `processor-a-degraded`). Exploration cost: 7.2% (outage) and
  6.8% (degradation) of initial routes in the fault went to the faulty processor, against 89.2% and 39.8% for `rules`.
  Numbers and notes: `docs/evaluation/routing-experiments/rel44/results.md`, summary
  `docs/evaluation/adaptive-routing-results.md`.
- **For the next review:** the guardrail failure in `normal-day` came with a shift of traffic to the slower Processor
  B; its cause (queueing at the single worker is consistent with the data, not measured) is open. A second objective
  such as latency, or other parameters, would be a new decision and a new protocol.
