# ADR-0017: Second adaptive iteration: a gated hybrid of rules and Thompson sampling

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-11-09  
Supersedes: None (adds to ADR-0016; its objective, guardrail and win rule are unchanged)  
Superseded by: None

## Context and forces

REL-44 measured the `adaptive` strategy (Thompson sampling, ADR-0016) against `rules` on the pre-registered protocol. It did not win. Its mean paired uplift was +1.82 pp, which passes, but it was better on only 10 of 15 pairs (80% needed), and its normal-day p95 latency was 1.83 times that of `rules` (`docs/evaluation/adaptive-routing-results.md`). The costs and benefits split by scenario:

- **Calm day:** it moves most traffic to Processor B, which declines less but is slower, so latency rises.
- **Full outage:** `rules` fails over decisively at the 0.5 error threshold, while sampling keeps some traffic on the failing processor, so success falls slightly.
- **Partial degradation below the failover threshold:** it routes around the degraded processor (+2.73 pp, a third of the latency, 6.8% of fault-time routes to the faulty processor instead of 39.8%).

The owner chose a second iteration before closing Phase 4 (REL-42 follow-up decisions, 2026-11-09). Because the variant is designed after seeing results on seeds 11 to 15, a fresh set of seeds must decide it.

## Decision

1. **Strategy `hybrid`.**
   - **Normal routing:** `rules` decides as today: Processor A first, failover to the other processor when one is `avoided` (error rate above `HEALTH_ERROR_THRESHOLD`, 0.5).
   - **Degraded zone:** the initial route switches to Thompson sampling (the REL-44 sampler, unchanged, seeded on the payment reference) only while at least one processor is in the degraded zone. That means at least `HEALTH_MIN_ATTEMPTS` attempts and a recent error rate above the gate of **0.15** but not above the failover threshold.
   - **Routing reasons:** payments routed by the sampler carry the reason `adaptive`. All others keep the `rules` reasons (`initial`, `failover`). Retries stay as in `rules`.
2. **Gate value 0.15, fixed now, before any code or run.**
   - The simulator's normal error rates are about 0.03 for A and 0.02 for B (timeouts plus capture failures), and their sum stays below 0.06 even with sampling noise at the minimum attempts.
   - So 0.15 is 2.5 times the noisy calm-day ceiling: calm days stay on `rules`.
   - A raised timeout rate such as the degraded scenario's (about 0.36) enters the zone.
   - The gate uses the health window and the same error counting as `app/routing/health.py`.
3. **Protocol v2.**
   - The same three scenarios, counts, rate, health window, drain and REL-44 sampler parameters.
   - The deciding seeds are **21 to 25**, new and never run before. Seeds 11 to 15 are run as well and reported for comparison with REL-44 only; they do not decide.
   - Strategies `rules` and `hybrid`, with fresh images and a check that routed reasons appear as expected.
   - The runs are split into parts of under 2 hours (lesson L-077).
4. **Unchanged win rule (ADR-0016).**
   - On the deciding seeds against `rules`: a mean paired success-rate uplift of at least 1 percentage point; better on at least 80% of the 15 paired runs; and p95 latency no more than 10% worse in any scenario.
   - Otherwise the result is reported as not winning.
5. **Prerequisite (REL-59).** The worker's payment snapshot gains the payment id, so a payment without a reference is seeded deterministically too.

## Alternatives considered

- **Latency-aware Thompson sampling** (a success counts only within a latency budget): addresses calm-day latency but not the outage loss.
- **Faster-forgetting Thompson sampling** (a shorter half-life): the smallest change; it helps the outage recovery but not calm-day latency.
- **Reusing seeds 11 to 15:** directly comparable and half the run time. Rejected because the variant was designed after seeing results on those seeds.
- **Changing the win rule:** rejected. Moving the goalposts after a result would make any win meaningless.

## Consequences

- REL-60 owns the `hybrid` strategy, the protocol v2 section, the harness runs and the results. It adds no migration, because the `adaptive` reason already exists.
- About 5 hours of live runs (60 runs).
- REL-45 closes Phase 4 after REL-60 and reports both iterations: the verdict first, then the trade-off per scenario.
- If `hybrid` also loses, Phase 4 closes with its exit criterion not met, as measured.

## Validation and review

- Tests show `hybrid` routes exactly as `rules` when no processor is in the degraded zone.
- They show it uses the sampler inside the zone and fails over like `rules` above the failover threshold.
- They show the seed is deterministic for payments with and without a reference.
- The protocol v2 section is committed before the first comparison run, and the results record the verdict on seeds 21 to 25.
- Revisit when a third processor is added or the objective changes.

## Implementation and result

Added by REL-60 on 2026-11-09; the decisions above did not change.

- **Implemented as decided:** `api/app/routing/hybrid.py`, registered as `hybrid`, `HYBRID_GATE` default 0.15 (read
  from the environment; the compose file does not pass it). Zone: at least `HEALTH_MIN_ATTEMPTS` attempts and an
  error rate strictly above the gate that `classify` does not call `avoided` (a rate equal to the failover
  threshold stays in the zone, as `classify` keeps it `preferred`; a rate equal to the gate is outside it). Two
  readings the ADR left open: when one processor is `avoided`, the failover rule keeps priority even if the other is
  in the zone; and the decision's `data` carries `hybrid.gate` and `hybrid.zone`. Protocol v2 was committed before
  any comparison run (`62ae8c8`).
- **Result: not a win, on the fresh deciding seeds 21 to 25.** Mean paired uplift +0.58 pp (needs 1.0, fails), better
  on 8 of 15 pairs, 53% (needs 80%, fails), worst p95 latency ratio 1.473 in `normal-day` (needs 1.10; also 1.118 in
  `processor-a-outage`, 0.605 in `processor-a-degraded`). On the comparison-only seeds 11 to 15: +0.36 pp, 5 of 15
  better, worst ratio 1.004. Numbers: `docs/evaluation/routing-experiments/rel60/results.md`, summary
  `docs/evaluation/adaptive-routing-results.md`. Phase 4 closes with its exit criterion not met, as the ADR foresaw.
- **The "Decision" 2 reasoning was flawed.** The 2.5-times-the-ceiling argument held for long-run rates. The zone
  opens at 5 attempts, where one random error is a rate of 0.2, above the 0.15 gate, so a calm day can sample on
  noise: `normal-day` seed 21 had 174 adaptive routes (from payment 5) and a p95 of 47.7 s against 17.4 s. The
  implementation follows the ADR; the flaw is in the ADR's reasoning.
- **Ties under the unchanged rule.** The rule counts only strictly better pairs, and a gated hybrid ties `rules`
  exactly on a calm day (4 of 5 `normal-day` deciding pairs), which caps the better-share at 11 of 15 (73%) against
  the 80% needed. The rule was not changed.
- **For the next review:** a gate that cannot open on a single error (a larger minimum, or a confidence test) and the
  treatment of ties would be new owner decisions with a new protocol on new seeds.

