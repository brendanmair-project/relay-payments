# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 3460 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 21 | rules | 300 | 89.33 | EUR 9003473, GBP 4553866, JPY 2138195, USD 18114993 | 19679.9 | 329 |
| processor-a-outage | 21 | hybrid | 300 | 88.00 | EUR 8742525, GBP 4410380, JPY 2276597, USD 18096214 | 32058.5 | 338 |
| processor-a-outage | 22 | rules | 300 | 91.33 | EUR 8023651, GBP 5752917, JPY 1406290, USD 19817277 | 24748.4 | 352 |
| processor-a-outage | 22 | hybrid | 300 | 91.67 | EUR 7840786, GBP 5856753, JPY 1406290, USD 20022405 | 25245.8 | 353 |
| processor-a-outage | 23 | rules | 300 | 87.67 | EUR 7819834, GBP 5435519, JPY 1785536, USD 18197431 | 32476.9 | 365 |
| processor-a-outage | 23 | hybrid | 300 | 88.00 | EUR 7868294, GBP 5627005, JPY 1778818, USD 17878115 | 26623.9 | 361 |
| processor-a-outage | 24 | rules | 300 | 85.67 | EUR 6681454, GBP 4535912, JPY 3628306, USD 18264400 | 24292.3 | 352 |
| processor-a-outage | 24 | hybrid | 300 | 83.33 | EUR 6791418, GBP 4628829, JPY 3816685, USD 17616071 | 36002.9 | 367 |
| processor-a-outage | 25 | rules | 300 | 89.00 | EUR 6570227, GBP 5538967, JPY 2433111, USD 19286865 | 21725.2 | 323 |
| processor-a-outage | 25 | hybrid | 300 | 89.67 | EUR 6743164, GBP 5419712, JPY 2376298, USD 19585087 | 17512.6 | 320 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 21 | hybrid | 89.33 | 88.00 | -1.33 | no | EUR -260948, GBP -143486, JPY 138402, USD -18779 |
| processor-a-outage | 22 | hybrid | 91.33 | 91.67 | +0.33 | yes | EUR -182865, GBP 103836, JPY 0, USD 205128 |
| processor-a-outage | 23 | hybrid | 87.67 | 88.00 | +0.33 | yes | EUR 48460, GBP 191486, JPY -6718, USD -319316 |
| processor-a-outage | 24 | hybrid | 85.67 | 83.33 | -2.33 | no | EUR 109964, GBP 92917, JPY 188379, USD -648329 |
| processor-a-outage | 25 | hybrid | 89.00 | 89.67 | +0.67 | yes | EUR 172937, GBP -119255, JPY -56813, USD 298222 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| processor-a-outage | hybrid | 5 | -0.47 | 60% | 1.118 |

## Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-outage | rules | A | 500 | 447 | 89.4% | 21: 95%, 22: 87%, 23: 81%, 24: 87%, 25: 97% |
| processor-a-outage | hybrid | A | 500 | 72 | 14.4% | 21: 19%, 22: 12%, 23: 12%, 24: 11%, 25: 18% |

## Win rule (ADR-0016)

`hybrid` against `rules` over 5 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | -0.47 pp | at least 1 pp | no |
| Pairs where better | 60% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.118 | at most 1.10 | no |
