# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 304 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-degraded | 11 | rules | 300 | 88.00 | EUR 8663746, GBP 5415170, JPY 1525408, USD 17396560 | 132582.7 | 304 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|

## Determinism

Per-reference outcomes compared with the earlier run in `docs/evaluation/routing-experiments/smoke`: **IDENTICAL**.

| Run | Differing references |
|---|---|
| processor-a-degraded-11-rules | 0 |
