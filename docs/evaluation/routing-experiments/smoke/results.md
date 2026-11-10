# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `static`. Total wall-clock time of the runs: 1648 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | static | 200 | 85.00 | EUR 4785915, GBP 2956639, JPY 891900, USD 12442471 | 12437.1 | 117 |
| normal-day | 11 | rules | 200 | 86.00 | EUR 4785915, GBP 2956639, JPY 891900, USD 12644870 | 15720.7 | 123 |
| processor-a-outage | 11 | static | 300 | 56.00 | EUR 6111568, GBP 3456992, JPY 793164, USD 11310563 | 13992.6 | 313 |
| processor-a-outage | 11 | rules | 300 | 87.33 | EUR 9295344, GBP 5067954, JPY 1164608, USD 17358510 | 25420.1 | 350 |
| processor-a-degraded | 11 | static | 300 | 67.67 | EUR 7542101, GBP 4001181, JPY 1221184, USD 12996639 | 219258.0 | 439 |
| processor-a-degraded | 11 | rules | 300 | 88.00 | EUR 8663746, GBP 5415170, JPY 1525408, USD 17396560 | 132589.4 | 305 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | rules | 85.00 | 86.00 | +1.00 | yes | EUR 0, GBP 0, JPY 0, USD 202399 |
| processor-a-outage | 11 | rules | 56.00 | 87.33 | +31.33 | yes | EUR 3183776, GBP 1610962, JPY 371444, USD 6047947 |
| processor-a-degraded | 11 | rules | 67.67 | 88.00 | +20.33 | yes | EUR 1121645, GBP 1413989, JPY 304224, USD 4399921 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | rules | 1 | +1.00 | 100% | 1.264 |
| processor-a-outage | rules | 1 | +31.33 | 100% | 1.817 |
| processor-a-degraded | rules | 1 | +20.33 | 100% | 0.605 |
