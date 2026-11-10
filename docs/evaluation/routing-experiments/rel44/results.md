# REL-44: adaptive against rules, 3 scenarios by 5 seeds

**Verdict (ADR-0016): NOT A WIN.** The mean uplift condition holds; the better-share and latency conditions do not.

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 7600 s.

## Runs

| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | rules | 200 | 86.00 | EUR 4785915, GBP 2956639, JPY 891900, USD 12644870 | 15819.5 | 123 |
| normal-day | 11 | adaptive | 200 | 91.50 | EUR 5357155, GBP 3584271, JPY 1269748, USD 12687912 | 33308.4 | 148 |
| normal-day | 12 | rules | 200 | 88.00 | EUR 4675299, GBP 3208954, JPY 865631, USD 12269335 | 47379.4 | 158 |
| normal-day | 12 | adaptive | 200 | 91.50 | EUR 4792895, GBP 2946698, JPY 754137, USD 13015930 | 38173.7 | 148 |
| normal-day | 13 | rules | 200 | 85.00 | EUR 5709139, GBP 2578938, JPY 2117064, USD 11133057 | 7955.6 | 113 |
| normal-day | 13 | adaptive | 200 | 89.50 | EUR 6317455, GBP 2758143, JPY 2227555, USD 11441169 | 40462.2 | 153 |
| normal-day | 14 | rules | 200 | 86.00 | EUR 6310456, GBP 3900542, JPY 1248208, USD 10019284 | 18490.1 | 123 |
| normal-day | 14 | adaptive | 200 | 88.00 | EUR 6619529, GBP 3424740, JPY 1248208, USD 10548466 | 44309.2 | 153 |
| normal-day | 15 | rules | 200 | 86.50 | EUR 5259742, GBP 2761870, JPY 2442780, USD 12292912 | 9434.0 | 113 |
| normal-day | 15 | adaptive | 200 | 89.00 | EUR 5111121, GBP 2849157, JPY 2272415, USD 12903243 | 24923.2 | 133 |
| processor-a-outage | 11 | rules | 300 | 87.33 | EUR 9295344, GBP 5067954, JPY 1164608, USD 17358510 | 36166.8 | 352 |
| processor-a-outage | 11 | adaptive | 300 | 86.00 | EUR 8355842, GBP 5241041, JPY 1456127, USD 17193923 | 32102.6 | 378 |
| processor-a-outage | 12 | rules | 300 | 88.33 | EUR 7903410, GBP 4673750, JPY 1656742, USD 18076526 | 36580.4 | 344 |
| processor-a-outage | 12 | adaptive | 300 | 88.00 | EUR 8400709, GBP 4334341, JPY 1708402, USD 17166769 | 29332.5 | 383 |
| processor-a-outage | 13 | rules | 300 | 90.00 | EUR 8600320, GBP 5019547, JPY 2809958, USD 17625290 | 18710.0 | 313 |
| processor-a-outage | 13 | adaptive | 300 | 89.00 | EUR 8758740, GBP 4794940, JPY 2844707, USD 17816761 | 12817.6 | 311 |
| processor-a-outage | 14 | rules | 300 | 89.67 | EUR 9527848, GBP 5551169, JPY 2072769, USD 17228124 | 31691.8 | 343 |
| processor-a-outage | 14 | adaptive | 300 | 90.67 | EUR 9611919, GBP 5567458, JPY 1989215, USD 17800234 | 29664.6 | 350 |
| processor-a-outage | 15 | rules | 300 | 91.00 | EUR 8114247, GBP 4726817, JPY 2717770, USD 20133623 | 24561.0 | 345 |
| processor-a-outage | 15 | adaptive | 300 | 88.33 | EUR 8069079, GBP 4558151, JPY 2467003, USD 19513850 | 15458.0 | 330 |
| processor-a-degraded | 11 | rules | 300 | 88.00 | EUR 8663746, GBP 5415170, JPY 1525408, USD 17396560 | 132569.7 | 305 |
| processor-a-degraded | 11 | adaptive | 300 | 88.00 | EUR 8877383, GBP 4992032, JPY 1868994, USD 17431972 | 52642.0 | 256 |
| processor-a-degraded | 12 | rules | 300 | 86.33 | EUR 8581545, GBP 4208911, JPY 1459511, USD 16902587 | 126845.9 | 318 |
| processor-a-degraded | 12 | adaptive | 300 | 92.00 | EUR 9032202, GBP 4776450, JPY 1586534, USD 17682501 | 39385.1 | 245 |
| processor-a-degraded | 13 | rules | 300 | 87.67 | EUR 8316788, GBP 5234793, JPY 2853273, USD 17329381 | 119536.8 | 309 |
| processor-a-degraded | 13 | adaptive | 300 | 89.67 | EUR 8238188, GBP 5439065, JPY 2901094, USD 17603895 | 53248.1 | 262 |
| processor-a-degraded | 14 | rules | 300 | 83.67 | EUR 8531556, GBP 4437003, JPY 1639062, USD 16323720 | 116671.0 | 319 |
| processor-a-degraded | 14 | adaptive | 300 | 85.33 | EUR 8121565, GBP 4731855, JPY 1639062, USD 17119844 | 38651.5 | 257 |
| processor-a-degraded | 15 | rules | 300 | 84.00 | EUR 7614661, GBP 4282635, JPY 2447922, USD 18455150 | 111318.4 | 293 |
| processor-a-degraded | 15 | adaptive | 300 | 88.33 | EUR 7976971, GBP 4777507, JPY 2732717, USD 18646631 | 22101.6 | 222 |

## Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | adaptive | 86.00 | 91.50 | +5.50 | yes | EUR 571240, GBP 627632, JPY 377848, USD 43042 |
| normal-day | 12 | adaptive | 88.00 | 91.50 | +3.50 | yes | EUR 117596, GBP -262256, JPY -111494, USD 746595 |
| normal-day | 13 | adaptive | 85.00 | 89.50 | +4.50 | yes | EUR 608316, GBP 179205, JPY 110491, USD 308112 |
| normal-day | 14 | adaptive | 86.00 | 88.00 | +2.00 | yes | EUR 309073, GBP -475802, JPY 0, USD 529182 |
| normal-day | 15 | adaptive | 86.50 | 89.00 | +2.50 | yes | EUR -148621, GBP 87287, JPY -170365, USD 610331 |
| processor-a-outage | 11 | adaptive | 87.33 | 86.00 | -1.33 | no | EUR -939502, GBP 173087, JPY 291519, USD -164587 |
| processor-a-outage | 12 | adaptive | 88.33 | 88.00 | -0.33 | no | EUR 497299, GBP -339409, JPY 51660, USD -909757 |
| processor-a-outage | 13 | adaptive | 90.00 | 89.00 | -1.00 | no | EUR 158420, GBP -224607, JPY 34749, USD 191471 |
| processor-a-outage | 14 | adaptive | 89.67 | 90.67 | +1.00 | yes | EUR 84071, GBP 16289, JPY -83554, USD 572110 |
| processor-a-outage | 15 | adaptive | 91.00 | 88.33 | -2.67 | no | EUR -45168, GBP -168666, JPY -250767, USD -619773 |
| processor-a-degraded | 11 | adaptive | 88.00 | 88.00 | +0.00 | no | EUR 213637, GBP -423138, JPY 343586, USD 35412 |
| processor-a-degraded | 12 | adaptive | 86.33 | 92.00 | +5.67 | yes | EUR 450657, GBP 567539, JPY 127023, USD 779914 |
| processor-a-degraded | 13 | adaptive | 87.67 | 89.67 | +2.00 | yes | EUR -78600, GBP 204272, JPY 47821, USD 274514 |
| processor-a-degraded | 14 | adaptive | 83.67 | 85.33 | +1.67 | yes | EUR -409991, GBP 294852, JPY 0, USD 796124 |
| processor-a-degraded | 15 | adaptive | 84.00 | 88.33 | +4.33 | yes | EUR 362310, GBP 494872, JPY 284795, USD 191481 |

## Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | adaptive | 5 | +3.60 | 100% | 1.829 |
| processor-a-outage | adaptive | 5 | -0.87 | 20% | 0.808 |
| processor-a-degraded | adaptive | 5 | +2.73 | 80% | 0.340 |

## Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-outage | rules | A | 500 | 446 | 89.2% | 11: 82%, 12: 89%, 13: 97%, 14: 93%, 15: 85% |
| processor-a-outage | adaptive | A | 500 | 36 | 7.2% | 11: 8%, 12: 2%, 13: 15%, 14: 9%, 15: 2% |
| processor-a-degraded | rules | A | 500 | 199 | 39.8% | 11: 39%, 12: 38%, 13: 40%, 14: 49%, 15: 33% |
| processor-a-degraded | adaptive | A | 500 | 34 | 6.8% | 11: 6%, 12: 6%, 13: 15%, 14: 5%, 15: 2% |

## Win rule (ADR-0016)

`adaptive` against `rules` over 15 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +1.82 pp | at least 1 pp | yes |
| Pairs where better | 67% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.829 | at most 1.10 | no |

## Reading the result

The ADR-0016 conditions are evaluated over all 15 pairs (the first two) and per scenario (the third):

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift, all 15 pairs | +1.82 pp | at least 1.0 pp | yes |
| Pairs where `adaptive` is better, all 15 | 10 of 15 (67%) | at least 80% (12 of 15) | no |
| p95 latency ratio, `normal-day` | 1.829 | at most 1.10 | no |
| p95 latency ratio, `processor-a-outage` | 0.808 | at most 1.10 | yes |
| p95 latency ratio, `processor-a-degraded` | 0.340 | at most 1.10 | yes |

Per scenario (mean difference, pairs better): `normal-day` +3.60 pp, 5 of 5; `processor-a-outage` -0.87 pp, 1 of 5
(it loses on success); `processor-a-degraded` +2.73 pp, 4 of 5 (seed 11 tied at +0.00 pp, which is not better).
Taken scenario by scenario, `adaptive` meets the rule only in `processor-a-degraded`. Over all pairs it fails the
better-share condition, and it fails the latency guardrail in `normal-day`. Parameters were fixed in the protocol
(`## Adaptive strategy parameters`) before any run and were not changed.

Revenue captured, summed over the five seeds (minor units; currencies are never added):

| Scenario | Strategy | EUR | GBP | JPY | USD |
|---|---|---|---|---|---|
| normal-day | rules | 26740551 | 15406943 | 7565583 | 58359458 |
| normal-day | adaptive | 28198155 | 15563009 | 7772063 | 60596720 |
| processor-a-outage | rules | 43441169 | 25039237 | 10421847 | 90422073 |
| processor-a-outage | adaptive | 43196289 | 24495931 | 10465454 | 89491537 |
| processor-a-degraded | rules | 41708296 | 23578512 | 9925176 | 86407398 |
| processor-a-degraded | adaptive | 42246309 | 24716909 | 10728401 | 88484843 |

Revenue follows success: `adaptive` is ahead in `normal-day` and `processor-a-degraded` in every currency, and behind
in `processor-a-outage` in EUR, GBP and USD.

## Exploration cost

`adaptive` sent 7.2% of initial routes to the down processor in `processor-a-outage` (36 of 500 payments created in
the fault) and 6.8% to the degraded one in `processor-a-degraded` (34 of 500). `rules` sent 89.2% and 39.8%: it keeps
Processor A until the error rate passes 0.5 within the window, and in the degradation scenario it never avoids A, which
is what that scenario is for. `normal-day` has no degraded processor. Per-seed shares are in the table above.

## What the outcomes show, and what they do not

- **Every adaptive route carried reason `adaptive`** (the first routed event of every payment in the 15 adaptive
  runs); retries carry `retry`, as in `rules`.
- **`normal-day` routing:** `rules` sent the initial route of every payment to A in the saved outcomes of all five
  seeds; `adaptive` sent 52% to 92% to B (70%, 85%, 92%, 56%, 52%). The simulator gives B a lower decline rate (0.08
  against 0.10) and a lower timeout rate (0.01 against 0.02), so a payment sent to B ends captured more often. The gain
  of +3.6 pp is what that mix of traffic predicts. What the strategy can and cannot see: its posterior counts only
  timeouts, outages and capture failures (declines are never errors, ADR-0008), so it can see B's small advantage there
  (about 0.02 against 0.03) and not the decline difference. The gain is therefore B's better outcome reached through a
  preference for B that the error counts support only weakly, and not a learned decline rate. It is a real gain on this
  synthetic data; it would not carry over to processors that differ only in latency.
- **Latency gap in `normal-day` (ratio 1.83, mean p95 about 36 s against about 20 s):**
  - *Ruled out: decision time.* Measured on a test database holding 1500 payments of events, `decide_adaptive` took
    3.4 ms and `compute_health` 2.3 ms per call, so the posterior query adds about 1 ms, not seconds.
  - *Consistent with, not proven: queueing at the single worker.* The stack runs one worker process that handles one
    payment at a time (two processor calls per payment, five seconds lost to each timeout), and payments arrive at 2 per
    second. Processor B's latency profile is slower (p50 250 ms against 120 ms; p95 800 ms against 400 ms), so a worker
    that sends 52% to 92% of the traffic to B has less spare capacity, and the backlog shows up as creation-to-final
    latency. The runs fit that: the adaptive runs with 85% and 92% on B had p50 latencies of 24.5 s and 20.1 s and the
    run with 52% had 13.1 s; but `rules`, with no traffic on B, also had a p50 of 19.4 s in seed 12 and 2.0 s in
    seed 11, which shows how large the run-to-run queueing noise is at this rate. The per-payment queue wait was not
    recorded, so the mechanism was not measured, and the latency cannot be split between the processor's own latency
    and queueing.
  - The same queueing works the other way where `rules` routes badly: in `processor-a-degraded` `rules` kept about 40%
    of initial routes on the timing-out A, and its p95 was about 120 s against about 41 s for `adaptive` (ratio 0.34).
- **`processor-a-outage` loss:** `adaptive` is 0.87 pp behind and loses 4 of 5 pairs by small margins (-0.33 to
  -2.67 pp; seed 14 is +1.00 pp). `rules` already recovers most payments there through its retry (about 89% success),
  so there is little left to gain. A likely reason is that `adaptive` pays for sampling the down processor (7% of
  initial routes) and for the first payments after the outage ends, while its posterior still holds the faulty history;
  that is an inference from the exploration cost and the per-seed numbers, not a measured breakdown. Seed 15 is the
  worst pair (-2.67 pp).
- **No seed where `adaptive` does dramatically worse;** the largest loss is -2.67 pp.

## How the run was executed

- Images were rebuilt before the runs (`docker compose build`). A first smoke run used a stale api image: its routes
  carried `initial` and `failover`, because an unknown strategy name falls back to `rules`. That smoke run was discarded
  and counts for nothing; the smoke that was kept (one scenario, one seed) is not a result either.
- The full run (`python scripts/routing_experiment.py --strategies rules,adaptive --scenarios
  normal-day,processor-a-outage,processor-a-degraded --seeds 11,12,13,14,15 --baseline rules --candidate adaptive
  --out docs/evaluation/routing-experiments/rel44/`) was cut off in run 27 of 30 by the two-hour background limit of
  the tool that ran it, not by a failure of the stack. Runs 1 to 26 had completed and saved their outcome files. The
  four runs not completed (`processor-a-degraded`, seeds 14 and 15, both strategies) were run in a second invocation
  of the same script with the same settings (output folder `rel44-part2`, files moved here afterwards). No completed
  run was redone, and no seed was selected or rerun to change a number. `results.json` and this file were then rebuilt
  from the 30 saved per-run outcome files and the run durations in the progress log (whole seconds), with the
  harness's own functions (`summarize_run`, `build_experiment`, `render_experiment_markdown`). The total in the
  header is the sum of the run durations (7600 s), without stack restarts.
- The per-run `*.outcomes.json` files are kept (small). The per-run report and recovery files were removed, as REL-43
  did, because this file does not need them. Each run's `digest` in `results.json` identifies its outcomes.
