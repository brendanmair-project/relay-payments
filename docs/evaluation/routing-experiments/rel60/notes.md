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
