# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 1266 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | rules | 200 | 86.00 | EUR 4785915, GBP 2956639, JPY 891900, USD 12644870 | 16089.1 | 123 |
| normal-day | 11 | hybrid | 200 | 86.00 | EUR 4785915, GBP 2956639, JPY 891900, USD 12644870 | 15648.5 | 123 |
| normal-day | 12 | rules | 200 | 88.00 | EUR 4675299, GBP 3208954, JPY 865631, USD 12269335 | 47555.5 | 163 |
| normal-day | 12 | hybrid | 200 | 88.00 | EUR 4675299, GBP 3208954, JPY 865631, USD 12269335 | 47595.6 | 163 |
| normal-day | 13 | rules | 200 | 85.00 | EUR 5709139, GBP 2578938, JPY 2117064, USD 11133057 | 7549.7 | 113 |
| normal-day | 13 | hybrid | 200 | 85.00 | EUR 5709139, GBP 2578938, JPY 2117064, USD 11133057 | 7798.6 | 112 |
| normal-day | 14 | rules | 200 | 86.00 | EUR 6310456, GBP 3900542, JPY 1248208, USD 10019284 | 18438.6 | 123 |
| normal-day | 14 | hybrid | 200 | 86.00 | EUR 6310456, GBP 3900542, JPY 1248208, USD 10019284 | 18164.2 | 123 |
| normal-day | 15 | rules | 200 | 86.50 | EUR 5259742, GBP 2761870, JPY 2442780, USD 12292912 | 9370.9 | 112 |
| normal-day | 15 | hybrid | 200 | 86.50 | EUR 5259742, GBP 2761870, JPY 2442780, USD 12292912 | 10157.0 | 113 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | hybrid | 86.00 | 86.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 12 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 13 | hybrid | 85.00 | 85.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 14 | hybrid | 86.00 | 86.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 15 | hybrid | 86.50 | 86.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | hybrid | 5 | +0.00 | 0% | 1.004 |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +0.00 pp | at least 1 pp | no |
| Pairs where better | 0% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.004 | at most 1.10 | yes |
