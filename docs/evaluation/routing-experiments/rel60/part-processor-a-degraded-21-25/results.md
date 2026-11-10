# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 3124 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-degraded | 21 | rules | 300 | 82.00 | EUR 7328808, GBP 4249763, JPY 2405583, USD 16740058 | 169826.3 | 344 |
| processor-a-degraded | 21 | hybrid | 300 | 86.00 | EUR 8292664, GBP 4157391, JPY 2069629, USD 17562995 | 89624.1 | 265 |
| processor-a-degraded | 22 | rules | 300 | 86.67 | EUR 7672341, GBP 5225296, JPY 1406290, USD 18539631 | 117910.7 | 304 |
| processor-a-degraded | 22 | hybrid | 300 | 87.67 | EUR 7593705, GBP 4814067, JPY 1406290, USD 19065869 | 85280.3 | 276 |
| processor-a-degraded | 23 | rules | 300 | 83.67 | EUR 7903413, GBP 5288886, JPY 2079123, USD 17268952 | 144462.5 | 315 |
| processor-a-degraded | 23 | hybrid | 300 | 83.67 | EUR 7993906, GBP 5374757, JPY 1817882, USD 17568055 | 108519.4 | 308 |
| processor-a-degraded | 24 | rules | 300 | 83.33 | EUR 6749607, GBP 4520795, JPY 3545183, USD 17813792 | 132188.9 | 337 |
| processor-a-degraded | 24 | hybrid | 300 | 85.67 | EUR 7046758, GBP 4763313, JPY 3545183, USD 18071630 | 97339.2 | 307 |
| processor-a-degraded | 25 | rules | 300 | 82.00 | EUR 6383851, GBP 5338271, JPY 2226678, USD 18232225 | 202740.6 | 388 |
| processor-a-degraded | 25 | hybrid | 300 | 84.67 | EUR 6642856, GBP 5171111, JPY 2226678, USD 18992102 | 83264.5 | 281 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| processor-a-degraded | 21 | hybrid | 82.00 | 86.00 | +4.00 | yes | EUR 963856, GBP -92372, JPY -335954, USD 822937 |
| processor-a-degraded | 22 | hybrid | 86.67 | 87.67 | +1.00 | yes | EUR -78636, GBP -411229, JPY 0, USD 526238 |
| processor-a-degraded | 23 | hybrid | 83.67 | 83.67 | +0.00 | no | EUR 90493, GBP 85871, JPY -261241, USD 299103 |
| processor-a-degraded | 24 | hybrid | 83.33 | 85.67 | +2.33 | yes | EUR 297151, GBP 242518, JPY 0, USD 257838 |
| processor-a-degraded | 25 | hybrid | 82.00 | 84.67 | +2.67 | yes | EUR 259005, GBP -167160, JPY 0, USD 759877 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| processor-a-degraded | hybrid | 5 | +2.00 | 80% | 0.605 |

## Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-degraded | rules | A | 500 | 278 | 55.6% | 21: 67%, 22: 32%, 23: 68%, 24: 36%, 25: 75% |
| processor-a-degraded | hybrid | A | 500 | 141 | 28.2% | 21: 25%, 22: 21%, 23: 48%, 24: 23%, 25: 24% |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +2.00 pp | at least 1 pp | yes |
| Pairs where better | 80% | at least 80% | yes |
| Worst scenario p95 latency ratio | 0.605 | at most 1.10 | yes |
