# First runs of the routing experiment harness (REL-43)

**All data is synthetic.** Run on 2026-11-06 on one Windows 11 host (Docker Desktop, compose stack built from this
branch, host Ollama up for explanations), `static` against `rules`, under `protocol.md`. These runs prove the harness
and the new scenario end to end; they are not the Phase 4 comparison (that is REL-44 with the `adaptive` strategy over
5 seeds). Per-run outcome files were not kept; each run's `digest` in `results.json` identifies its per-reference
outcomes.

## 1. REL-30 reproduction (`rel30-reproduction/`)

`processor-a-outage`, seed 7, 300 payments, health window 120 s, 2 payments per second, the REL-30 settings.
Command: `python scripts/routing_experiment.py --strategies static,rules --scenarios processor-a-outage --seeds 7
--out docs/evaluation/routing-experiments/rel30-reproduction --rel30`. Result: `REL30_AGREEMENT=PASS`.

| Measure | REL-30 (`outage-demo/results.json`) | This run | Tolerance |
|---|---|---|---|
| Static success rate | 58.0% | 58.0% | 1.0 pp |
| Rules success rate | 89.0% | 89.0% | 1.0 pp |
| Uplift | +31.0 pp | +31.0 pp | |
| Revenue recovered EUR / GBP / JPY / USD | 3032328 / 1618218 / 902033 / 6810094 | identical | 1.0% |

Duration: 292 s (`static`) and 322 s (`rules`), 673 s wall clock for the pair including stack restarts. (This run used
the generator's own 100 s drain limit, as REL-30 did; the drain never bound.)

## 2. Smoke over the protocol (`smoke/`)

`static` against `rules`, first protocol seed (11), each scenario, drain timeout 400 s. Numbers are in
`smoke/results.md`; the paired differences are one pair per scenario, so they show the harness works, not that a
difference is reliable.

| Scenario | Static % | Rules % | Difference pp | p95 latency ratio (rules over static) |
|---|---|---|---|---|
| normal-day | 85.00 | 86.00 | +1.00 | 1.26 |
| processor-a-outage | 56.00 | 87.33 | +31.33 | 1.82 |
| processor-a-degraded | 67.67 | 88.00 | +20.33 | 0.61 |

Duration per run: 117 to 439 s (`normal-day` about 2 min, `processor-a-outage` 5 to 6 min, `processor-a-degraded` 5 to
7 min); six runs took 1795 s (about 30 min) wall clock. Extrapolation for the REL-44 matrix (2 strategies, 3
scenarios, 5 seeds, 30 runs): about 2.5 hours.

Findings worth knowing before REL-44:

- **The rule-based router never fails over in `processor-a-degraded`.** A's error rate (about 0.36) stays under the
  0.5 threshold, so all of `rules`' gain there comes from the retry on B, as designed in the protocol. That is the
  headroom an adaptive strategy has to improve on.
- **Latency is dominated by the single worker's queue under timeouts.** In `processor-a-degraded` 35% of payments
  wait out the 5 s processor timeout, so at 2 payments per second the queue grows (p95 creation-to-final latency of
  219 s for `static` and 133 s for `rules`). The guardrail compares strategies on the same load, so it still works,
  but the latency figures are queue-dominated; the generator's 100 s drain limit was too short here (see the protocol).
- In `normal-day` and `processor-a-outage`, `rules` has a higher p95 than `static` (ratios 1.26 and 1.82; and 5.13 in
  the seed-7 reproduction) because retried payments take a second attempt. A candidate is judged against `rules`, not
  `static`, so these are not guardrail failures; they show how large the retry cost in latency is.

## 3. Determinism (`determinism-rerun/`)

`processor-a-degraded`, seed 11, `rules`, rerun after the smoke run (stack restarted, data reset):
the per-reference outcomes (status, handling processor and the routed reasons in order) match exactly for all 300
references (`determinism.json`: no differing references; identical digest in both `results.json` files). Success rate
88.00% in both; p95 latency 132589 ms and 132583 ms (timing varies slightly; outcomes do not).

## Gotcha recorded

- Trigger: first smoke attempt, `processor-a-degraded`, `static`. Symptom: the generator exited 1 with a drain
  failure at the switch back (payments still `received`, attempt 0). Cause (inferred from the throughput arithmetic and
  the later run that completed once the limit was raised; the stuck payments were not otherwise inspected): the single
  worker could not keep up when 35% of payments wait 5 s. Remedy: the harness passes `--drain-timeout` (default 400 s).
  Prevention: the protocol states the limit; a new fault scenario with slow answers needs the same check.
