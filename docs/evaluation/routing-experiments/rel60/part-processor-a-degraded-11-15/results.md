# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 2917 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-degraded | 11 | rules | 300 | 88.00 | EUR 8663746, GBP 5415170, JPY 1525408, USD 17396560 | 131614.6 | 305 |
| processor-a-degraded | 11 | hybrid | 300 | 88.00 | EUR 8834660, GBP 5298821, JPY 1525408, USD 17421895 | 92991.8 | 270 |
| processor-a-degraded | 12 | rules | 300 | 86.00 | EUR 8354051, GBP 4224323, JPY 1638115, USD 16707490 | 127180.6 | 308 |
| processor-a-degraded | 12 | hybrid | 300 | 89.00 | EUR 8667998, GBP 4365068, JPY 1463944, USD 17071992 | 79998.9 | 278 |
| processor-a-degraded | 13 | rules | 300 | 87.67 | EUR 8316788, GBP 5234793, JPY 2853273, USD 17329381 | 120645.1 | 309 |
| processor-a-degraded | 13 | hybrid | 300 | 87.67 | EUR 8393381, GBP 5248271, JPY 2853273, USD 17139505 | 95794.4 | 290 |
| processor-a-degraded | 14 | rules | 300 | 83.33 | EUR 8531556, GBP 4437003, JPY 1639062, USD 16141244 | 117399.6 | 325 |
| processor-a-degraded | 14 | hybrid | 300 | 84.67 | EUR 8681420, GBP 4760793, JPY 1639062, USD 16186384 | 79422.9 | 290 |
| processor-a-degraded | 15 | rules | 300 | 84.00 | EUR 7614661, GBP 4282635, JPY 2447922, USD 18455150 | 111107.4 | 292 |
| processor-a-degraded | 15 | hybrid | 300 | 86.00 | EUR 7614661, GBP 4402460, JPY 2692509, USD 19164985 | 68523.8 | 250 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| processor-a-degraded | 11 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 170914, GBP -116349, JPY 0, USD 25335 |
| processor-a-degraded | 12 | hybrid | 86.00 | 89.00 | +3.00 | yes | EUR 313947, GBP 140745, JPY -174171, USD 364502 |
| processor-a-degraded | 13 | hybrid | 87.67 | 87.67 | +0.00 | no | EUR 76593, GBP 13478, JPY 0, USD -189876 |
| processor-a-degraded | 14 | hybrid | 83.33 | 84.67 | +1.33 | yes | EUR 149864, GBP 323790, JPY 0, USD 45140 |
| processor-a-degraded | 15 | hybrid | 84.00 | 86.00 | +2.00 | yes | EUR 0, GBP 119825, JPY 244587, USD 709835 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| processor-a-degraded | hybrid | 5 | +1.27 | 60% | 0.685 |

## Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-degraded | rules | A | 500 | 200 | 40.0% | 11: 39%, 12: 39%, 13: 40%, 14: 49%, 15: 33% |
| processor-a-degraded | hybrid | A | 500 | 145 | 29.0% | 11: 31%, 12: 19%, 13: 32%, 14: 41%, 15: 22% |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +1.27 pp | at least 1 pp | yes |
| Pairs where better | 60% | at least 80% | no |
| Worst scenario p95 latency ratio | 0.685 | at most 1.10 | yes |
