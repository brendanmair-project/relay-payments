# Routing strategies and the experiment harness

How a routing strategy is chosen and how strategies are compared (REL-43, ADR-0016). All data is synthetic.

## Strategy registry (`api/app/routing/registry.py`)

`ROUTING_STRATEGY` names a strategy. A strategy is a `Strategy(name, decide, retries)`:

- `decide(session, payment) -> RouteDecision` picks the processor and the `payment.routed` reason for a new payment
  from the health data in PostgreSQL (`app/routing/health.py`) and the payment (an object with `reference`,
  `amount_minor` and `currency`; the worker passes its snapshot, so a later strategy can seed its draws on the
  reference);
- `retries` says whether a failed first attempt is retried on the other processor. `retries_enabled()` in
  `app/routing/config.py` is this flag of the selected strategy, and the worker and the sweeper still read only that.

Four strategies are registered (`rules` and `static` by `app/routing/router.py`, `adaptive` by `app/routing/adaptive.py`,
`hybrid` by `app/routing/hybrid.py`; the registry imports all):

| Name | Decision | Retries |
|---|---|---|
| `rules` (default) | Processor A, or B (reason `failover`) when A is `avoided` and B is not; both avoided or unknown stays on A (`initial`) | yes (`retry`, to the other processor) |
| `static` | Always A, reason `static` (the baseline of ADR-0009) | no |
| `adaptive` | Thompson sampling over recent outcomes (below), reason `adaptive` | yes, exactly as `rules` (`retry`, to the other processor) |
| `hybrid` | `rules`, except inside the degraded zone, where the `adaptive` sampler decides (below) | yes, exactly as `rules` |

An unknown or empty `ROUTING_STRATEGY` means `rules`, as before, and `rules` stays the default. The retry target
(`decide_retry`) is shared. A strategy is added by calling `registry.register(Strategy(...))` from its own module
(imported in `registry._load_built_ins`) and adding its routed reason; the worker does not change.

## The `adaptive` strategy (REL-44, ADR-0016)

`api/app/routing/adaptive.py`. Thompson sampling with a Beta-Bernoulli posterior per processor:

- **Counts from PostgreSQL at decision time**, like `compute_health`, so nothing lives in a worker's memory and every
  worker process and a restart see the same posterior (PR-6). An attempt is a `payment.routed` event, an error a
  `payment.failed` event with reason timeout, outage or capture_failed (declines are never errors), successes are
  attempts minus errors. Each event inside the health window (`HEALTH_WINDOW_SECONDS`) is weighted by
  0.5 ^ (age / half-life), the half-life being `ADAPTIVE_HALF_LIFE_SECONDS` (default 30). An error event is a little
  younger than its attempt, so the decayed successes are floored at zero.
- **Posterior** Beta(`ADAPTIVE_PRIOR` + successes, `ADAPTIVE_PRIOR` + errors), prior 1. One draw per processor with
  `random.betavariate`, A then B; the higher draw wins, a tie goes to A.
- **Seeded draws:** `random.Random(seed)`, the seed the first 8 bytes of SHA-256 of the payment `reference` (the
  payment id without one), never `hash()` or the global `random`, so a paired run repeats exactly. A payment with
  neither reference nor id (the worker's snapshot carries only the reference today) gets a fresh random seed.
- **Reason `adaptive`:** added to `RoutedReason`, to the `payment_events` reason CHECK by migration 0007, to the
  rule-based explainer (`captured_first_time_adaptive`) and to the timeline lines of the payment and incident pages
  (`(adaptive: chosen from recent processor outcomes)`). The decision's `data` carries the weighted counts.
- It never waits on a model (ADR-0012). The parameters used in the comparison are fixed in the protocol file
  (`## Adaptive strategy parameters`).

## The `hybrid` strategy (REL-60, ADR-0017)

`api/app/routing/hybrid.py`. Health is computed as `rules` does (`compute_health`: health window, the same error
counting, `HEALTH_MIN_ATTEMPTS`). A processor is in the **degraded zone** when it has at least the minimum attempts
and an error rate strictly above `HYBRID_GATE` (default 0.15) that `classify` does not call `avoided` (a rate equal to
the failover threshold stays `preferred`, so it is in the zone; a rate equal to the gate is not). In the zone and with
no `avoided` processor, the initial route is `adaptive.decide_adaptive` (unchanged sampler, seeded on the payment
reference) with reason `adaptive`; otherwise it is exactly `rules` (`initial` or `failover`). An `avoided` processor
keeps the failover rule even when the other processor is in the zone. Retries are as `rules`. The decision's `data`
adds `hybrid.gate` and `hybrid.zone`. No migration: the `adaptive` reason already exists. `HYBRID_GATE` is read from
the environment with its default; the compose file does not pass it.

## Scenarios

The generator (`simulator/generator/scenarios.py`) has three seeded scenarios: `normal-day`, `processor-a-outage`
(full outage, `ControlStep`) and `processor-a-degraded` (a `ProfileStep` raises A's `timeout_rate` to 0.35 for
payments 100 to 199 through `PUT /control/processors/a/profile`, then restores the default). The degradation level and
its reasoning are in `docs/evaluation/routing-experiments/protocol.md`.

## Harness

`scripts/routing_experiment.py` drives the real compose stack (host side, standard library only) and reuses
`scripts/outage_demo.py` (`prepare_run`, `generate_and_collect`). Per scenario, seed and strategy it restarts api and
worker with `ROUTING_STRATEGY`, resets the data and the simulator, runs the load generator on the same payment
references, waits until every payment is final and saves the outcomes and the reporting tool's JSON. Its pure logic
(run plan, per-run summary, paired differences, the ADR-0016 win rule, REL-30 agreement, results files) is in
`simulator/demo/experiment.py` and tested with fakes in `simulator/tests/test_demo_experiment.py` (the simulator
tests carry it because they already host the demo comparison and the host script imports `simulator/demo`). REL-44 adds
the exploration cost: per run, the share of initial routes (the first routed event) sent to the processor that was
degraded or down at the time, over the payments created between the scenario's control steps (`degraded_window`,
`exploration_cost`), reported per strategy and scenario. REL-60 adds `--merge` (`merge_runs`,
`build_split_experiment`, `render_split_markdown`): the parts' `results.json` files are merged into a deciding seed set
and a comparison-only seed set, and a missing run is an error.

The full comparison is a manual run (about an hour or more per strategy pair, duration recorded in the results);
the protocol, seeds and win rule are fixed in `docs/evaluation/routing-experiments/protocol.md`. Outputs:
`results.json` and `results.md` per run folder.
