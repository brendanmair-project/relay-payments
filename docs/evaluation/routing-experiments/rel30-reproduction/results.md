# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `static`. Total wall-clock time of the runs: 614 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 7 | static | 300 | 58.00 | EUR 5207559, GBP 4550101, JPY 1216178, USD 9883575 | 4821.1 | 292 |
| processor-a-outage | 7 | rules | 300 | 89.00 | EUR 8239887, GBP 6168319, JPY 2118211, USD 16693669 | 24752.4 | 322 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| processor-a-outage | 7 | rules | 58.00 | 89.00 | +31.00 | yes | EUR 3032328, GBP 1618218, JPY 902033, USD 6810094 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| processor-a-outage | rules | 1 | +31.00 | 100% | 5.134 |

## Agreement with REL-30 (processor-a-outage, seed 7)

Overall: **PASS** (tolerance 1.0 pp on success rates, 1.0% on revenue recovered).

| Measure | REL-30 | This run | Spread | Holds |
|---|---|---|---|---|
| Static success % | 58.0 | 58.0 | 0.0 | yes |
| Rules success % | 89.0 | 89.0 | 0.0 | yes |
| Revenue recovered EUR | 3032328 | 3032328 | 0.0% | yes |
| Revenue recovered GBP | 1618218 | 1618218 | 0.0% | yes |
| Revenue recovered JPY | 902033 | 902033 | 0.0% | yes |
| Revenue recovered USD | 6810094 | 6810094 | 0.0% | yes |
