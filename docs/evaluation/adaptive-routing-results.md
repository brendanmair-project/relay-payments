# Adaptive routing results (REL-44 and REL-60)

**All data is synthetic** (simulated processors, generated payments, no real card data).

**Verdict (ADR-0016, both iterations): neither strategy wins.** The second iteration, `hybrid` (ADR-0017), was judged
on fresh seeds 21 to 25 under the unchanged win rule and fails all three conditions. Phase 4's exit criterion is not
met, as measured. Full tables, per-seed pairs and the findings are in
[`routing-experiments/rel60/results.md`](routing-experiments/rel60/results.md); the protocol (v1 and v2) is in
[`routing-experiments/protocol.md`](routing-experiments/protocol.md).

## Second iteration: `hybrid` on seeds 21 to 25 (REL-60)

60 runs, 3 scenarios by 5 deciding seeds (15 pairs), `hybrid` against `rules`, same references per pair. `hybrid` lets
`rules` decide and hands the initial route to the REL-44 sampler only while a processor has at least 5 recent attempts
and an error rate above the gate 0.15 that `rules` does not yet treat as failing (above 0.5).

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired success-rate uplift | +0.58 pp | at least 1.0 pp | no |
| Pairs where `hybrid` is better | 8 of 15 (53%) | at least 80% | no |
| p95 latency ratio, worst scenario | 1.473 (`normal-day`) | at most 1.10 in every scenario | no |

| Scenario | Mean difference | Pairs better | p95 latency ratio | Exploration cost (`rules` / `hybrid`) |
|---|---|---|---|---|
| `normal-day` | +0.20 pp | 1 of 5 | 1.473 (fails) | no degraded processor |
| `processor-a-outage` | -0.47 pp | 3 of 5 | 1.118 (fails) | 89.4% / 14.4% |
| `processor-a-degraded` | +2.00 pp | 4 of 5 | 0.605 | 55.6% / 28.2% |

The seeds 11 to 15, run only for comparison with REL-44 (they do not decide): `hybrid` +0.36 pp, better on 5 of 15,
worst latency ratio 1.004, against `adaptive` on the same seeds +1.82 pp, 10 of 15, 1.829.

Two findings, stated plainly:

- **The ADR-0017 gate reasoning was flawed.** The gate opens at `HEALTH_MIN_ATTEMPTS` = 5 attempts, where a single
  random error is a rate of 0.2, above the 0.15 gate. The ADR's "2.5 times the noisy calm-day ceiling" held for a long
  run of attempts, not for a 5-attempt window, so on a calm day `hybrid` can sample on noise. This is a flaw in the
  ADR's reasoning; the implementation does what the ADR says. Counted from the outcomes, `normal-day` deciding seed 21
  had 174 adaptive routes of 200 payments (from payment 5 on) and a p95 of 47.7 s against 17.4 s for `rules`; the
  other four seeds had none; before their fault windows the outage and degraded runs had 0 to 26 each.
- **Exact ties count as "not better".** A gated hybrid routes exactly like `rules` on a calm day, so 4 of the 5
  `normal-day` deciding pairs are exact ties by design. That caps the better-share at 11 of 15 (73%) whatever the other
  pairs do, below the 80% the rule needs. The deciding pairs were 8 better, 5 tied and 2 worse. The rule was not
  changed; this is a property of the rule combined with a gated design.

What it does well: in the partial degradation `hybrid` gained +2.00 pp with p95 at 0.605 of `rules` (better on 4 of 5
pairs). A later iteration would need a gate that cannot open on one noisy error (a longer minimum than 5 attempts, or a
confidence test) and a rule that does not penalise a deliberate tie; either is a new owner decision, an ADR and a new
protocol on new seeds.

How it was run: protocol v2 was committed before any comparison run (commit `62ae8c8`); images rebuilt first and a
smoke run (`processor-a-degraded`, seed 21, not counted) checked the routed reasons; six parts of 10 runs, each under
2 hours (about 20 to 60 minutes), 2026-11-09. No run was repeated. The merge is `scripts/routing_experiment.py
--merge`.

## First iteration: `adaptive` on seeds 11 to 15 (REL-44)

**First iteration verdict (ADR-0016): the adaptive strategy does not win.** Thompson sampling beat `rules` on average success but not
reliably enough, and it failed the latency guardrail in `normal-day`. Full tables, per-seed pairs and the run notes are
in [`routing-experiments/rel44/results.md`](routing-experiments/rel44/results.md); the protocol and the fixed adaptive
parameters (window 120 s, half-life 30 s, prior Beta(1, 1)) are in
[`routing-experiments/protocol.md`](routing-experiments/protocol.md).

### Result against the win rule

3 scenarios by 5 seeds (15 pairs), `adaptive` against `rules`, same payment references per pair.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired success-rate uplift | +1.82 pp | at least 1.0 pp | yes |
| Pairs where `adaptive` is better | 10 of 15 (67%) | at least 80% | no |
| p95 latency ratio, worst scenario | 1.829 (`normal-day`) | at most 1.10 in every scenario | no |

| Scenario | Mean difference | Pairs better | p95 latency ratio | Exploration cost (`rules` / `adaptive`) |
|---|---|---|---|---|
| `normal-day` | +3.60 pp | 5 of 5 | 1.829 (fails) | no degraded processor |
| `processor-a-outage` | -0.87 pp | 1 of 5 | 0.808 | 89.2% / 7.2% |
| `processor-a-degraded` | +2.73 pp | 4 of 5 | 0.340 | 39.8% / 6.8% |

Exploration cost is the share of initial routes sent to the processor that was down or degraded at the time.

### What to take from it

- `adaptive` learns to avoid a faulty processor: it sent about 7% of the payments created during a fault to the faulty
  processor, against 89% (outage) and 40% (degradation) for `rules`. In the degradation scenario, which the 0.5 error
  threshold of `rules` cannot see, it gained +2.7 pp and cut p95 latency by about two thirds.
- On `normal-day` it gained +3.6 pp because it sent 52% to 92% of payments to Processor B, whose simulated decline and
  timeout rates are lower. Its latency was worse (ratio 1.83); the cause is not established. Decision time is ruled out
  (about 1 ms more per payment) and queueing at the single worker behind the slower Processor B fits the data, but the
  queue wait was not measured.
- In the full outage it did slightly worse than `rules` (-0.87 pp, 1 of 5 pairs better): `rules` already rescues most
  payments with its retry, and sampling the down processor costs `adaptive` a little.
- A retune of the parameters or a second processor-latency-aware objective would be a new owner decision and a new
  protocol; nothing was tuned after a result was seen.

### How it was run

30 runs on one Windows 11 host with the real compose stack, 2026-11-06 to 2026-11-07, seeds 11 to 15. The first
invocation was cut off in run 27 by the tool's two-hour background limit; the four unfinished runs were completed in a
second invocation and the results rebuilt from the saved per-run files (no completed run was redone; details in
`routing-experiments/rel44/results.md`).
