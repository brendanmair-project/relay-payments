# Outage demo results

**All data is synthetic** (simulated processors, generated payments, no real card data). The baseline is **static routing: ROUTING_STRATEGY=static, every payment to Processor A, no failover, no retry (ADR-0009)**.

Scenario `processor-a-outage`, seed 7, 3 run(s). Command: `python scripts/outage_demo.py --seed 7 --runs 3`. Each run resets the system first, runs the baseline and then Relay routing over the same deterministic payment references, and saves each mode's per-reference outcomes before the next reset.

## Method

- Reset before every mode: `python -m app.demo.reset` (TRUNCATE ... RESTART IDENTITY CASCADE, stream and groups recreated, request log truncated) and the simulator's outages and profiles restored.
- Same references in both modes (`<scenario>-<seed>-<index>`); the simulator draws its outcomes from the reference, so a payment meets the same processor behaviour in both modes.
- Drain: before each outage switch the load generator waits until every earlier payment is final (it polls `GET /payments/{id}` on the public API, 60 s limit, `--no-drain` turns it off). Without it the outage switch raced the worker: the payment sent just before the switch could meet the outage or not by a few milliseconds, which moved one EUR payment between runs. The drain makes the outage window exactly payments 100 to 199.
- The generator waits one health window after an outage ends: the router's health state still holds the outage failures, so the generator waits one health window (`window_seconds` from `GET /processors/health`) plus 5 s from the switch before the next payment, and polls the health once a second to record the recovery lag. Recovery therefore starts from a clean state.
- Both modes use a health window of 120 s (`HEALTH_WINDOW_SECONDS`; the default configuration stays 60 s). The scripted outage lasts 100 payments, so the window is set well above it: the health state never ages out during the outage, and the post-outage wait is one window plus 5 s.
- The model is warmed with one request before each mode; payments are sent at a rate the worker keeps up with (2 per second).

## Headline (run 1)

| Measure | Value |
|---|---|
| Success rate, static routing baseline | 58% |
| Success rate, Relay routing | 89% |
| Uplift | +31.0 percentage points |
| Recovery lag (Relay) | processor A: 105.9 s after the outage ended |
| Median time to explanation (Relay) | 1033.5 ms, 6966.3 times faster than the 2-hour manual baseline (assumption) |

### Revenue recovered per currency (minor units)

| Currency | Revenue recovered |
|---|---|
| EUR | 3032328 |
| GBP | 1618218 |
| JPY | 902033 |
| USD | 6810094 |

### Revenue of rescued payments by rescue path (Relay run, minor units)

| Rescue path | Payments | Amount by currency |
|---|---|---|
| retry | 89 | EUR 2832363, GBP 1446165, JPY 902033, USD 6713460 |
| failover | 4 | EUR 199965, GBP 172053, USD 96634 |
| redrive | 0 | - |

### Paired comparison by reference

300 references were compared payment by payment: 93 improved to captured (93 from failed), 0 got worse, 207 unchanged.

### Time to explanation per source (run 1, after warming the model)

| Run | Source | Count | P50 ms | P95 ms | Fallback rate (by reason) | Largest backlog |
|---|---|---|---|---|---|---|
| Relay | model | 30 | 1033.5 | 1945.1 |  |  |
| Relay | rules | 3 | 984.6 | 1729.9 |  |  |
| Relay | all | 33 | 1033.5 | 1945.1 | 0.1 (cause_mismatch 3) | 3 |
| Baseline | model | 23 | 953.7 | 1984.5 |  |  |
| Baseline | rules | 103 | 4760.9 | 7298.4 |  |  |
| Baseline | all | 126 | 3957.5 | 7272.6 | 0.8 (cause_mismatch 103) | 14 |

## Runs

| Run | Baseline success % | Relay success % | Uplift pp | Revenue recovered | Median explanation ms | Recovery lag (Relay) |
|---|---|---|---|---|---|---|
| 1 | 58 | 89 | +31.0 | EUR 3032328, GBP 1618218, JPY 902033, USD 6810094 | 1033.5 | processor A: 105.9 s after the outage ended |
| 2 | 58 | 89 | +31.0 | EUR 3032328, GBP 1618218, JPY 902033, USD 6810094 | 1093.9 | processor A: 100.8 s after the outage ended |
| 3 | 58 | 89 | +31.0 | EUR 3032328, GBP 1618218, JPY 902033, USD 6810094 | 1053.0 | processor A: 105.9 s after the outage ended |

## Reproducibility

Tolerance: 1 percentage point on success rate and 1% on revenue recovered (spread over runs, per currency).

| Measure | Values per run | Spread | Verdict |
|---|---|---|---|
| Success rate, Relay (pp) | 89, 89, 89 | 0 | PASS |
| Success rate, baseline (pp) | 58, 58, 58 | 0 | PASS |
| Revenue recovered EUR (%) | 3032328, 3032328, 3032328 | 0 | PASS |
| Revenue recovered GBP (%) | 1618218, 1618218, 1618218 | 0 | PASS |
| Revenue recovered JPY (%) | 902033, 902033, 902033 | 0 | PASS |
| Revenue recovered USD (%) | 6810094, 6810094, 6810094 | 0 | PASS |

Overall: **PASS** over 3 runs.

### Differing references

No reference differs in status, handling processor or routing between the runs.


## Metric definitions

- Success rate: payments that ended `captured` divided by all payments of the run. Declines are cardholder outcomes and count as not captured in both modes alike.
- Uplift: Relay success rate minus baseline success rate, in percentage points.
- Revenue recovered: per currency, the amount captured in the Relay run minus the amount captured in the baseline run over the same references, in minor units (cents; whole yen for JPY). Currencies are never added together. It can differ from the rescue-path split, which sums only payments whose capturing attempt was routed with reason `retry` or `failover` (or a sweeper re-drive).
- Median time to explanation: the median of the time from a payment's final failure to its stored automatic explanation, over every declined or failed payment of the Relay run. P95 is the nearest-rank 95th percentile. The model is warmed with one request before the Relay run.
- Fallback rate: the share of those explanations that used the rules text. Fallbacks are counted per reason: `cause_mismatch` (the model answered with another cause than the rules, ADR-0013) apart from model failures (`model_timeout`, `model_unreachable`, `model_error`, citation failures).
- Recovery lag: seconds from the generator switching an outage off until the router's health state for that processor is no longer `avoided`, polled once a second; measured per run for the Relay mode (the baseline does not route by health).
- Largest backlog: the most declined or failed payments waiting for an explanation at once.

## Assumptions

- Manual reconstruction baseline (assumption, ADR-0009): 2 hours (7200 s) for an analyst to reconstruct why one payment failed. It is an assumption, not a measurement.
- The baseline is static routing, not an industry benchmark: every payment goes to Processor A with no failover and no retry (ADR-0009, risk R10). The uplift is the benefit of Relay's rules over that baseline on synthetic data only.
