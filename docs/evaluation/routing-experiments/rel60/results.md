# Routing experiment results

**All data is synthetic** (simulated processors, generated payments, no real card data).

Verdict on the deciding seeds [21, 22, 23, 24, 25]: `hybrid` against `rules` is **NO WIN** under the ADR-0016 win rule. Total wall-clock time of the runs: 15327 s.

## Findings to read with the verdict

Written after the runs, from the saved per-run outcomes. Facts are observed; the explanations marked (inference) are
not proven by the data.

**Verdict:** `hybrid` does not win under the unchanged ADR-0016 rule on the deciding seeds 21 to 25, and it fails
all three conditions: mean paired uplift +0.58 pp (needed 1.0), better on 8 of 15 pairs (53%; needed 80%), and worst
scenario p95 latency ratio 1.473 in `normal-day` (needed at most 1.10; `processor-a-outage` is also over, at 1.118).

### (a) The ADR-0017 gate reasoning was flawed; the implementation did what the ADR says

ADR-0017 argued that 0.15 is 2.5 times the noisy calm-day ceiling, because the simulator's calm error rates sum to
below 0.06. That holds for a long run of attempts, not at the point where the gate opens. The zone needs only
`HEALTH_MIN_ATTEMPTS` = 5 attempts, and at 5 attempts one random error is a rate of 0.2, above the 0.15 gate. So on a
calm day the hybrid can start sampling on noise. This is a flaw in the ADR's reasoning (a ceiling computed for the
long-run rate was applied to a 5-attempt window), not a bug in `app/routing/hybrid.py`, which implements the ADR
exactly (tests in `api/tests/routing/test_hybrid.py`, including a rate of 0.15 staying `rules` and 5 attempts
counting). Protocol v2 fixed the gate before any run, so it was not changed.

Counted from the saved outcomes (initial routes with reason `adaptive` among payments created outside the
scenario's fault window; `rules` has 0 everywhere; table "Adaptive routes outside the fault window" below):

- `normal-day`, deciding seeds: 174 adaptive routes of 1000 payments, all in seed 21 (seeds 22 to 25: 0). Seed 21
  went adaptive from payment 5 (the first payment with 5 attempts in the window) to payment 178; 164 of its first
  routes went to B. Its p95 was 47.7 s against 17.4 s for `rules` (+1.00 pp success), which is the whole of the
  `normal-day` latency ratio of 1.473; the other four seeds are within 3% of `rules`.
  (inference: after one noisy error opened the gate, sampling kept most traffic on the slower Processor B and A's
  few remaining attempts kept its windowed rate above the gate; the queueing was not measured.)
- `normal-day`, comparison seeds 11 to 15: 2 adaptive routes (seed 15).
- Before the fault window of `processor-a-outage` and `processor-a-degraded` (payments 0 to 99), deciding seeds:
  adaptive routes in the outage runs were 1, 26, 0, 21, 0 and in the degraded runs 8, 0, 0, 3, 0 (seeds 21 to 25);
  the smoke run (seed 21, not counted) showed the same 8 early routes at payments 6 to 15.

### (b) Exact ties count as "not better" (a property of the rule combined with a gated design)

The rule counts a pair as better only when strictly above zero. A gated hybrid routes exactly as `rules` whenever
no processor is in the zone, and the same references then give identical outcomes, so a calm day ties by design:
4 of the 5 `normal-day` deciding pairs are exact ties (seeds 22 to 25: identical success and revenue). With those
four ties the better-share cannot exceed 11 of 15 (73%) however well the other 11 pairs go, below the 80% bar of
12 of 15. The deciding pairs split 8 better, 5 tied (4 `normal-day`, 1 `processor-a-degraded`) and 2 worse (both
`processor-a-outage`). The rule was not changed (ADR-0017); this is reported as a property of the rule together
with a gated design, not as a defect of the result.

### Scenario summary on the deciding seeds

- `processor-a-degraded`: +2.00 pp mean, better on 4 of 5, p95 ratio 0.605: the case the gate targets works.
- `processor-a-outage`: -0.47 pp mean, better on 3 of 5, p95 ratio 1.118 (fails the guardrail). Exploration cost of
  the faulty processor 14.4% against 89.4% for `rules`, but the full-outage failover of `rules` is already decisive
  and the sampler's residual routes to A cost a little. The two worse pairs are seeds 21 and 24; early noise-driven
  sampling does not explain them cleanly (seed 22 had 26 such routes and was still +0.33 pp), so no cause is claimed.
- `normal-day`: +0.20 pp mean, better on 1 of 5, p95 ratio 1.473 (see (a)).
- On the comparison seeds 11 to 15 (not deciding) the hybrid also fails the rule: +0.36 pp, 5 of 15 better, but its
  worst latency ratio is 1.004; beside REL-44's `adaptive` on the same seeds (+1.82 pp, 10 of 15, 1.829) it gives
  up uplift in exchange for latency.
- Absolute p95 values in `processor-a-degraded` (80 to 200 s) are queueing at the single worker behind the 5 s
  processor timeout, as in REL-44; ratios compare like with like.

## Deciding seeds [21, 22, 23, 24, 25]

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 7793 s.

### Runs

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

### Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 21 | hybrid | 87.00 | 88.00 | +1.00 | yes | EUR 62732, GBP 769037, JPY -270675, USD 283621 |
| normal-day | 22 | hybrid | 89.00 | 89.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 23 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 24 | hybrid | 86.50 | 86.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 25 | hybrid | 87.50 | 87.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| processor-a-outage | 21 | hybrid | 89.33 | 88.00 | -1.33 | no | EUR -260948, GBP -143486, JPY 138402, USD -18779 |
| processor-a-outage | 22 | hybrid | 91.33 | 91.67 | +0.33 | yes | EUR -182865, GBP 103836, JPY 0, USD 205128 |
| processor-a-outage | 23 | hybrid | 87.67 | 88.00 | +0.33 | yes | EUR 48460, GBP 191486, JPY -6718, USD -319316 |
| processor-a-outage | 24 | hybrid | 85.67 | 83.33 | -2.33 | no | EUR 109964, GBP 92917, JPY 188379, USD -648329 |
| processor-a-outage | 25 | hybrid | 89.00 | 89.67 | +0.67 | yes | EUR 172937, GBP -119255, JPY -56813, USD 298222 |
| processor-a-degraded | 21 | hybrid | 82.00 | 86.00 | +4.00 | yes | EUR 963856, GBP -92372, JPY -335954, USD 822937 |
| processor-a-degraded | 22 | hybrid | 86.67 | 87.67 | +1.00 | yes | EUR -78636, GBP -411229, JPY 0, USD 526238 |
| processor-a-degraded | 23 | hybrid | 83.67 | 83.67 | +0.00 | no | EUR 90493, GBP 85871, JPY -261241, USD 299103 |
| processor-a-degraded | 24 | hybrid | 83.33 | 85.67 | +2.33 | yes | EUR 297151, GBP 242518, JPY 0, USD 257838 |
| processor-a-degraded | 25 | hybrid | 82.00 | 84.67 | +2.67 | yes | EUR 259005, GBP -167160, JPY 0, USD 759877 |

### Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | hybrid | 5 | +0.20 | 20% | 1.473 |
| processor-a-outage | hybrid | 5 | -0.47 | 60% | 1.118 |
| processor-a-degraded | hybrid | 5 | +2.00 | 80% | 0.605 |

### Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-outage | rules | A | 500 | 447 | 89.4% | 21: 95%, 22: 87%, 23: 81%, 24: 87%, 25: 97% |
| processor-a-outage | hybrid | A | 500 | 72 | 14.4% | 21: 19%, 22: 12%, 23: 12%, 24: 11%, 25: 18% |
| processor-a-degraded | rules | A | 500 | 278 | 55.6% | 21: 67%, 22: 32%, 23: 68%, 24: 36%, 25: 75% |
| processor-a-degraded | hybrid | A | 500 | 141 | 28.2% | 21: 25%, 22: 21%, 23: 48%, 24: 23%, 25: 24% |

### Win rule (ADR-0016)

`hybrid` against `rules` over 15 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +0.58 pp | at least 1 pp | no |
| Pairs where better | 53% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.473 | at most 1.10 | no |

## Comparison seeds [11, 12, 13, 14, 15] (comparison only, not deciding)

**All data is synthetic** (simulated processors, generated payments, no real card data).

Objective: Success rate: payments that ended captured over final payments (declines count as not captured), compared per seed on identical payment references. Revenue captured per currency is reported alongside; p95 creation-to-final latency is a guardrail (ADR-0016).

Baseline strategy: `rules`. Total wall-clock time of the runs: 7535 s.

### Runs

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

### Paired differences (candidate minus baseline, same seed and references)

| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |
|---|---|---|---|---|---|---|---|
| normal-day | 11 | hybrid | 86.00 | 86.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 12 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 13 | hybrid | 85.00 | 85.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 14 | hybrid | 86.00 | 86.00 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| normal-day | 15 | hybrid | 86.50 | 86.50 | +0.00 | no | EUR 0, GBP 0, JPY 0, USD 0 |
| processor-a-outage | 11 | hybrid | 87.33 | 87.33 | +0.00 | no | EUR -69911, GBP 173087, JPY 10956, USD -188349 |
| processor-a-outage | 12 | hybrid | 88.33 | 88.67 | +0.33 | yes | EUR 58874, GBP 118465, JPY 4433, USD -562319 |
| processor-a-outage | 13 | hybrid | 90.00 | 89.33 | -0.67 | no | EUR -61533, GBP -65834, JPY 34749, USD 170294 |
| processor-a-outage | 14 | hybrid | 89.67 | 91.33 | +1.67 | yes | EUR 143837, GBP 189187, JPY 0, USD 325186 |
| processor-a-outage | 15 | hybrid | 91.00 | 88.67 | -2.33 | no | EUR -135749, GBP -87287, JPY -474450, USD -252104 |
| processor-a-degraded | 11 | hybrid | 88.00 | 88.00 | +0.00 | no | EUR 170914, GBP -116349, JPY 0, USD 25335 |
| processor-a-degraded | 12 | hybrid | 86.00 | 89.00 | +3.00 | yes | EUR 313947, GBP 140745, JPY -174171, USD 364502 |
| processor-a-degraded | 13 | hybrid | 87.67 | 87.67 | +0.00 | no | EUR 76593, GBP 13478, JPY 0, USD -189876 |
| processor-a-degraded | 14 | hybrid | 83.33 | 84.67 | +1.33 | yes | EUR 149864, GBP 323790, JPY 0, USD 45140 |
| processor-a-degraded | 15 | hybrid | 84.00 | 86.00 | +2.00 | yes | EUR 0, GBP 119825, JPY 244587, USD 709835 |

### Per scenario

| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |
|---|---|---|---|---|---|
| normal-day | hybrid | 5 | +0.00 | 0% | 1.004 |
| processor-a-outage | hybrid | 5 | -0.20 | 40% | 0.655 |
| processor-a-degraded | hybrid | 5 | +1.27 | 60% | 0.685 |

### Exploration cost

Share of initial routes (the first routed event, not the retry) sent to the processor that was degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.

| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |
|---|---|---|---|---|---|---|
| processor-a-outage | rules | A | 500 | 444 | 88.8% | 11: 81%, 12: 89%, 13: 97%, 14: 93%, 15: 84% |
| processor-a-outage | hybrid | A | 500 | 67 | 13.4% | 11: 12%, 12: 13%, 13: 16%, 14: 14%, 15: 12% |
| processor-a-degraded | rules | A | 500 | 200 | 40.0% | 11: 39%, 12: 39%, 13: 40%, 14: 49%, 15: 33% |
| processor-a-degraded | hybrid | A | 500 | 145 | 29.0% | 11: 31%, 12: 19%, 13: 32%, 14: 41%, 15: 22% |

### Win rule (ADR-0016)

`hybrid` against `rules` over 15 pairs: **NO WIN**.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +0.36 pp | at least 1 pp | no |
| Pairs where better | 33% | at least 80% | no |
| Worst scenario p95 latency ratio | 1.004 | at most 1.10 | yes |

## Adaptive routes outside the fault window

Initial routes with reason `adaptive` among payments created outside the scenario's fault window (a calm scenario has none), counted from the saved per-run outcomes. Under `rules` this is always 0.

| Set | Scenario | Strategy | Payments outside | Adaptive routes | Per seed |
|---|---|---|---|---|---|
| deciding | normal-day | rules | 1000 | 0 | 21: 0, 22: 0, 23: 0, 24: 0, 25: 0 |
| deciding | normal-day | hybrid | 1000 | 174 | 21: 174, 22: 0, 23: 0, 24: 0, 25: 0 |
| deciding | processor-a-outage | rules | 1000 | 0 | 21: 0, 22: 0, 23: 0, 24: 0, 25: 0 |
| deciding | processor-a-outage | hybrid | 1000 | 52 | 21: 3, 22: 26, 23: 0, 24: 21, 25: 2 |
| deciding | processor-a-degraded | rules | 1000 | 0 | 21: 0, 22: 0, 23: 0, 24: 0, 25: 0 |
| deciding | processor-a-degraded | hybrid | 1000 | 232 | 21: 53, 22: 28, 23: 72, 24: 45, 25: 34 |
| comparison | normal-day | rules | 1000 | 0 | 11: 0, 12: 0, 13: 0, 14: 0, 15: 0 |
| comparison | normal-day | hybrid | 1000 | 2 | 11: 0, 12: 0, 13: 0, 14: 0, 15: 2 |
| comparison | processor-a-outage | rules | 1000 | 0 | 11: 0, 12: 0, 13: 0, 14: 0, 15: 0 |
| comparison | processor-a-outage | hybrid | 1000 | 44 | 11: 10, 12: 24, 13: 3, 14: 4, 15: 3 |
| comparison | processor-a-degraded | rules | 1000 | 0 | 11: 0, 12: 0, 13: 0, 14: 0, 15: 0 |
| comparison | processor-a-degraded | hybrid | 1000 | 167 | 11: 82, 12: 14, 13: 11, 14: 42, 15: 18 |

## Beside the earlier iteration (same seeds)

| Strategy | Mean paired uplift pp | Pairs better | Worst scenario latency ratio |
|---|---|---|---|
| adaptive (earlier) | +1.82 | 67% | 1.829 |
| hybrid (comparison set) | +0.36 | 33% | 1.004 |

| Scenario | Earlier mean pp | Earlier latency ratio | Now mean pp | Now latency ratio |
|---|---|---|---|---|
| normal-day | +3.60 | 1.829 | +0.00 | 1.004 |
| processor-a-outage | -0.87 | 0.808 | -0.20 | 0.655 |
| processor-a-degraded | +2.73 | 0.340 | +1.27 | 0.685 |

