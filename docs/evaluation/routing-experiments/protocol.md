# Routing experiment protocol (pre-registered)

**All data is synthetic** (simulated processors, generated payments, no real card data).

This protocol was written before any strategy comparison ran (REL-43, ADR-0016). REL-44 and every later Phase 4
comparison use exactly this protocol. Nothing below changes after results are seen; a change needs a new ADR and a
new protocol file, and earlier results are not re-judged against it.

## Objective, guardrail and win rule (ADR-0016)

- **Objective:** the success rate, payments that ended `captured` over final payments (the REL-57 definition;
  declines count as not captured), compared per seed on identical payment references (`<scenario>-<seed>-<index>`).
- **Reported alongside:** revenue captured per currency (minor units; currencies are never added together).
- **Guardrail:** p95 creation-to-final latency (the reporting tool's `latency.p95_ms`) must not be worse than the
  rule-based router's by more than 10% in any scenario. The scenario ratio is the candidate's mean p95 over the
  baseline's mean p95 across the five seeds, and exactly 1.10 passes.
- **Pair:** candidate minus baseline on the same scenario and seed, in percentage points. `better` means strictly
  above zero.
- **Win rule:** across 3 scenarios by 5 seeds (15 pairs), against `rules`, a candidate wins only when all hold:
  1. the mean paired success-rate uplift is at least 1.0 percentage point (exactly 1.0 passes);
  2. it is better on at least 80% of the pairs (12 of 15; exactly 80% passes);
  3. the latency guardrail holds in every scenario.

  Otherwise the result is reported as not winning, with the same numbers. For `adaptive` the exploration cost is
  reported too: the share of payments sent to the processor that was degraded at the time.
- Comparisons are exact (fractions, not rounded rates); the code is `simulator/demo/experiment.py`, tested in
  `simulator/tests/test_demo_experiment.py`.

## Scenarios

| Scenario | Payments | What happens |
|---|---|---|
| `normal-day` (calm) | 200 | Steady traffic, default profiles, no injected fault. |
| `processor-a-outage` | 300 | Processor A is in a full outage for payments 100 to 199 (switched on before 100, off before 200). The generator drains (waits until every earlier payment is final) before each switch and, after the outage, waits one health window plus 5 s. |
| `processor-a-degraded` | 300 | Processor A's `timeout_rate` is raised from 0.02 to 0.35 for payments 100 to 199, then its default profile returns. Partial degradation, not an outage; the same drain applies before each switch. |

Default simulator profiles (A: p50 120 ms, p95 400 ms, decline 0.10, timeout 0.02, capture failure 0.01; B: p50
250 ms, p95 800 ms, decline 0.08, timeout 0.01, capture failure 0.01) are restored through the control API before
every run.

### Degradation level (chosen once)

`timeout_rate` 0.35 on Processor A. The rule-based router (`HealthSettings`) marks a processor `avoided` when its
error rate (timeout, outage and capture-failed events over routed attempts in the window) is strictly above
`HEALTH_ERROR_THRESHOLD` 0.5 with at least 5 attempts. At 0.35 (about 0.36 with capture failures) Processor A is
clearly worse than B (about 0.02) but stays under that threshold, so the rule-based router keeps it `preferred`: the
degradation is the case the threshold rule cannot see, which is what a "raised error rate rather than a full
outage" scenario is for. It is also well above A's normal rate, so the degradation is real and visible. The level
was fixed from this reasoning, not tuned against any strategy's results; there is no calibration run.

## Seeds, counts and timing

- **Seeds, every scenario:** 11, 12, 13, 14, 15. (Seed 7 is REL-30's and is used only to reproduce REL-30.)
- **Strategies:** the baseline `rules`, the candidate `adaptive` (REL-44); `static` is reported where it was run.
- **Payment counts:** the scenario defaults above (200, 300, 300), sent at 2 payments per second (as REL-30).
- **Drain timeout:** the generator waits up to 400 s for earlier payments to be final before each fault switch
  (`--drain-timeout`, harness default). This was fixed after a first attempt at `processor-a-degraded` failed at the
  generator's own 100 s limit: with 35% of payments waiting out the 5 s processor timeout on a single worker, the
  queue needs about 150 s longer to drain than it takes to send, and the switch must not race the worker. The limit
  only waits longer; it changes no outcome. No comparison result had been produced when it was set.
- **Health window:** `HEALTH_WINDOW_SECONDS` 120 (other health settings at their defaults: minimum 5 attempts,
  error threshold 0.5), for api and worker, as in REL-30.
- **Fresh start per run:** api and worker restart with `ROUTING_STRATEGY` set, every table is truncated, the stream
  and its groups are recreated, and the simulator's outages and profiles are reset (`outage_demo.prepare_run`).
- **Order:** scenario, then seed, then strategy (strategies run back to back).
- **Completion:** a run ends when every payment is final and every declined or failed one has its automatic
  explanation; routing results never depend on the model (explanations fall back to rules when Ollama is down).

## Adaptive strategy parameters

Fixed on 2026-11-06 by REL-44, before any `adaptive` comparison run, from the reasoning below and not from any
result. They do not change after a comparison result is seen; a retune would be a new owner decision and a new
protocol file.

- **Algorithm:** Thompson sampling (ADR-0016). For each processor the posterior is Beta(1 + successes, 1 + errors);
  one draw per processor, the highest draw wins, a tie goes to A. Retries are exactly `rules` (the other processor,
  `decide_retry`), so the comparison isolates the initial choice.
- **Outcomes counted:** the same events `app/routing/health.py` counts: an attempt is a `payment.routed` event, an
  error a `payment.failed` event with reason timeout, outage or capture_failed; successes are attempts minus errors,
  so declines are never errors.
- **Window:** `HEALTH_WINDOW_SECONDS`, 120 s in this protocol (the health window above): events older than that count
  for nothing.
- **Decay:** exponential with a half-life of 30 s (`ADAPTIVE_HALF_LIFE_SECONDS`), so an event's weight is
  0.5 ^ (age / 30 s), measured against the database clock. Reasoning: at 2 payments per second the faults last about
  50 s of sending, so evidence must lose half its weight well inside one fault, or a recovered processor would stay
  shunned; a half-life of 30 s keeps about 87 weighted events per processor in steady state at that rate (enough to
  tell a 35% error rate from 2%) and leaves 6% of an event's weight at the window edge, where it is cut off.
- **Prior:** Beta(1, 1) (`ADAPTIVE_PRIOR`), uniform: no processor is assumed good or bad before evidence, and a
  processor with no recent traffic has a wide posterior, so it is sampled and its health is re-learned.
- **Seeding:** `random.Random(seed)` with the seed the first 8 bytes of SHA-256 of the payment `reference` as an
  integer (the payment id when there is no reference); one fresh generator per decision, draws for A then B.
- **Shared state:** none in the process; the weighted counts come from `payment_events` in PostgreSQL at decision time.
- **Exploration cost:** the share of initial routes (first routed event of each payment) sent to the processor that
  was degraded or down at the time, over the payments created between the scenario's control steps (indexes 100 to
  199 of `processor-a-outage` and `processor-a-degraded`, Processor A). Reported per strategy and scenario;
  `normal-day` has no degraded processor, so no figure.

## Command

```
python scripts/routing_experiment.py --strategies rules,adaptive \
    --scenarios normal-day,processor-a-outage,processor-a-degraded --seeds 11,12,13,14,15 \
    --baseline rules --candidate adaptive --out docs/evaluation/routing-experiments/<run-name>/
```

The run is manual (ADR-0016); the harness logic is tested in CI with fakes. Results go to `results.json` and
`results.md` in the run's folder, with the duration of every run and in total.

## Protocol v2 (REL-60, ADR-0017)

Written and committed on 2026-11-09, before any REL-60 comparison run (the commit time proves the order). Protocol v1
above is unchanged and stays the protocol of REL-43 and REL-44; v2 is the protocol of the second iteration only. The
`hybrid` strategy was designed after the REL-44 results on seeds 11 to 15, so those seeds cannot decide it.

- **Deciding seeds:** 21, 22, 23, 24, 25, every scenario. New: never run before. The ADR-0016 verdict is judged on
  these 15 pairs only.
- **Comparison-only seeds:** 11, 12, 13, 14, 15, every scenario. Run and reported beside REL-44's numbers for the
  same seeds; they do not decide.
- **Strategies:** the baseline `rules` and the candidate `hybrid` (`--baseline rules --candidate hybrid`).
- **Gate:** `HYBRID_GATE` 0.15, fixed in ADR-0017 before any code or run (2.5 times the noisy calm-day ceiling). A
  processor is in the degraded zone with at least `HEALTH_MIN_ATTEMPTS` (5) attempts and an error rate strictly above
  0.15 that `rules` does not treat as `avoided` (error rate above 0.5 with the same counting); only then the sampler
  routes the initial payment, with reason `adaptive`. Failover and retries are as `rules`.
- **Win rule:** unchanged (ADR-0016): mean paired uplift at least 1.0 pp; better on at least 80% of the 15 deciding
  pairs (12 of 15); p95 latency ratio at most 1.10 in every scenario. Otherwise reported as not winning.
- **Everything else as v1:** the three scenarios and their payment counts (200, 300, 300), 2 payments per second,
  health window 120 s (`HEALTH_WINDOW_SECONDS`), drain timeout 400 s, fresh start per run, order scenario then seed
  then strategy, sampler parameters (Beta(1, 1) prior, half-life 30 s, seeded on the payment `reference`).
- **Parts (lesson L-077):** six separate runs of the harness, each under 2 hours: for each scenario (`normal-day`,
  `processor-a-outage`, `processor-a-degraded`) the seeds 21 to 25 and the seeds 11 to 15, into
  `docs/evaluation/routing-experiments/rel60/part-<scenario>-<seed set>/`. Images are rebuilt first; a short smoke
  (`processor-a-degraded`, seed 21, both strategies) checks the routed reasons and does not count. A run that fails
  technically is rerun alone and the reason recorded; a completed run is never rerun.
- **Merge:** `python scripts/routing_experiment.py --merge <part dirs> --deciding-seeds 21,22,23,24,25
  --comparison-seeds 11,12,13,14,15 --baseline rules --candidate hybrid --out
  docs/evaluation/routing-experiments/rel60/` (the harness's own functions, `simulator/demo/experiment.py`).
- **Exploration cost:** reported as in v1 for both strategies (share of initial routes in the fault window sent to
  the degraded processor).

### Command (one part)

```
python scripts/routing_experiment.py --strategies rules,hybrid --scenarios processor-a-degraded \
    --seeds 21,22,23,24,25 --baseline rules --candidate hybrid \
    --out docs/evaluation/routing-experiments/rel60/part-processor-a-degraded-21-25/
```
