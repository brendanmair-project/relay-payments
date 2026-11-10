# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 3352 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 11 | rules | 300 | 87.33 | EUR 9295344, GBP 5067954, JPY 1164608, USD 17358510 | 35263.9 | 350 |
| processor-a-outage | 11 | hybrid | 300 | 87.33 | EUR 9225433, GBP 5241041, JPY 1175564, USD 17170161 | 29026.4 | 354 |
| processor-a-outage | 12 | rules | 300 | 88.33 | EUR 7903410, GBP 4673750, JPY 1656742, USD 18076526 | 37585.8 | 347 |
| processor-a-outage | 12 | hybrid | 300 | 88.67 | EUR 7962284, GBP 4792215, JPY 1661175, USD 17514207 | 25265.8 | 335 |
| processor-a-outage | 13 | rules | 300 | 90.00 | EUR 8600320, GBP 5019547, JPY 2809958, USD 17625290 | 18961.3 | 314 |
| processor-a-outage | 13 | hybrid | 300 | 89.33 | EUR 8538787, GBP 4953713, JPY 2844707, USD 17795584 | 8957.8 | 306 |
| processor-a-outage | 14 | rules | 300 | 89.67 | EUR 9527848, GBP 5551169, JPY 2072769, USD 17228124 | 31585.8 | 343 |
| processor-a-outage | 14 | hybrid | 300 | 91.33 | EUR 9671685, GBP 5740356, JPY 2072769, USD 17553310 | 20138.4 | 331 |
| processor-a-outage | 15 | rules | 300 | 91.00 | EUR 8114247, GBP 4726817, JPY 2717770, USD 20133623 | 24736.8 | 345 |
| processor-a-outage | 15 | hybrid | 300 | 88.67 | EUR 7978498, GBP 4639530, JPY 2243320, USD 19881519 | 13686.4 | 325 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 11 | hybrid | 87.33 | 87.33 | +0.00 | no | EUR -69911, GBP 173087, JPY 10956, USD -188349 |
| processor-a-outage | 12 | hybrid | 88.33 | 88.67 | +0.33 | yes | EUR 58874, GBP 118465, JPY 4433, USD -562319 |
| processor-a-outage | 13 | hybrid | 90.00 | 89.33 | -0.67 | no | EUR -61533, GBP -65834, JPY 34749, USD 170294 |
| processor-a-outage | 14 | hybrid | 89.67 | 91.33 | +1.67 | yes | EUR 143837, GBP 189187, JPY 0, USD 325186 |
| processor-a-outage | 15 | hybrid | 91.00 | 88.67 | -2.33 | no | EUR -135749, GBP -87287, JPY -474450, USD -252104 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| processor-a-outage | hybrid | 5 | -0.20 | 40% | 0.655 |

## Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-outage | rules | A | 500 | 444 | 88.8% | 11: 81%, 12: 89%, 13: 97%, 14: 93%, 15: 84% |
| processor-a-outage | hybrid | A | 500 | 67 | 13.4% | 11: 12%, 12: 13%, 13: 16%, 14: 14%, 15: 12% |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | -0.20 pp | at least 1 pp | no |
| Pairs where better | 40% | at least 80% | no |
| Worst scenario p95 latency ratio | 0.655 | at most 1.10 | yes |
