# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 1208 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| normal-day | 21 | rules | 200 | 87.00 | EUR 5318529, GBP 2032548, JPY 1808331, USD 11275209 | 17351.3 | 128 |
| normal-day | 21 | hybrid | 200 | 88.00 | EUR 5381261, GBP 2801585, JPY 1537656, USD 11558830 | 47686.0 | 158 |
| normal-day | 22 | rules | 200 | 89.00 | EUR 4971180, GBP 3690182, JPY 1307709, USD 13632983 | 4593.3 | 113 |
| normal-day | 22 | hybrid | 200 | 89.00 | EUR 4971180, GBP 3690182, JPY 1307709, USD 13632983 | 4593.4 | 113 |
| normal-day | 23 | rules | 200 | 88.00 | EUR 5259564, GBP 4106832, JPY 1359980, USD 12349897 | 16912.8 | 118 |
| normal-day | 23 | hybrid | 200 | 88.00 | EUR 5259564, GBP 4106832, JPY 1359980, USD 12349897 | 17239.5 | 123 |
| normal-day | 24 | rules | 200 | 86.50 | EUR 4818234, GBP 2463605, JPY 2035324, USD 12173170 | 12146.1 | 108 |
| normal-day | 24 | hybrid | 200 | 86.50 | EUR 4818234, GBP 2463605, JPY 2035324, USD 12173170 | 12470.2 | 113 |
| normal-day | 25 | rules | 200 | 87.50 | EUR 3863407, GBP 3573779, JPY 1746524, USD 14015808 | 15442.8 | 118 |
| normal-day | 25 | hybrid | 200 | 87.50 | EUR 3863407, GBP 3573779, JPY 1746524, USD 14015808 | 15914.2 | 118 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 21 | hybrid | 87.00 | 88.00 | +1.00 | yes | EUR 62732, GBP 769037, JPY -270675, USD 283621 |
| normal-day | 22 | hybrid | 89.00 | 89.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 23 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 24 | hybrid | 86.50 | 86.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 25 | hybrid | 87.50 | 87.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | hybrid | 5 | +0.20 | 20% | 1.473 |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +0.20 pp | at least 1 pp | no |
| Pairs where better | 20% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.473 | at most 1.10 | no |
