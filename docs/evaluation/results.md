# Evaluation results

Measured results with the commit, data and command that produced them. All data is synthetic.

## Explanation quality check (REL-25.8, 2026-10-30)

- What: the model explains 10 fixed synthetic timelines (`api/app/explain/quality.py`, one per rules cause). Pass rule (ADR-0011 item 6): every citation in all ten is a valid event `seq` of that timeline. Also reported (ADR-0012 item 7): whether the model's stated cause matches the rules explainer's cause, and whether any amount it states is wrong.
- Model: `granite3.3:2b` on the host's Ollama 0.40.11, structured output (JSON schema), timeout 120 s.
- Command (from `projects/professional/relay`, after `docker compose build api`): `docker run --rm --add-host host.docker.internal:host-gateway -v "$PWD/api:/app" -w /app relay/api:local python -m app.explain.quality`
- Commit: branch `rel-25-llm-explainer-via-local-ollama-wi` at `99ed619` (squash-merged as REL-25).

| Run | Prompt | Citations valid | Cause match | Wrong amount |
|---|---|---|---|---|
| 1 | JSON mode, amount in minor units, `seq=` lines | 6/10 (fail) | 3/10 | not measured; one answer said "$1250 USD" for 12.50 USD |
| 2 | JSON schema, formatted amount, bracketed seqs | 10/10 (pass) | 6/10 | 0 |
| 3 (REL-27, 2026-11-01, host Ollama 0.40.13, same prompt) | JSON schema, formatted amount, bracketed seqs | 10/10 (pass) | 7/10 | 0 |

- Result: run 2 passes, so `granite3.3:2b` stays (ADR-0010); `granite3.3:8b` is not needed.
- Cause mismatches in run 2: capture timeout (model said authorize timeout), both processors failed (said authorize outage), captured after failover (said authorize outage), static routing without retry (said authorize outage). The model names the first failure in the timeline, not the final outcome, on the retry and failover paths.
- Effect: every model explanation is labelled with its source and shown next to the raw timeline (REL-27), so an analyst can check it. Settled by ADR-0013 (REL-27): when the causes disagree the rules text is stored with `fallback_reason = cause_mismatch`. In run 3 that applies to 3 of 10 timelines (capture timeout, captured after failover, static routing without retry); the other 7 keep the model text.

## Incident summary quality check (REL-35.8, 2026-11-03)

- What: the model summarises 6 fixed synthetic incidents (`api/app/incidents/quality.py`: pure outage, pure timeouts, mixed, outage with failover rescues, a small incident, recovery without resolution) through the same path as the API (`generate_summary`): structured output, citations checked against the linked events, cause compared with the rules cause (ADR-0005, ADR-0013). Reported per run: citation validity, cause match and the fallback count per reason. Pass rule: every citation valid (a cause mismatch is a counted fallback, not a failure).
- Model: `granite3.3:2b` on the host's Ollama 0.40.13, JSON schema output, timeout 120 s.
- Command (from the worktree after the api image is built): `docker run --rm --add-host host.docker.internal:host-gateway -e OLLAMA_URL=http://host.docker.internal:11434 -v "<worktree>/api:/app" -w /app <api image> python -m app.incidents.quality`
- Commit: branch `rel-35-link-incidents-to-affected-paymen`, on top of `4ceabf8`.

| Run | Citations valid | Cause match | Fallback rate | Fallbacks by reason |
|---|---|---|---|---|
| 1 | 6/6 (pass) | 4/6 | 2/6 | `cause_mismatch` 2 |
| 2 (same prompt, same day) | 6/6 (pass) | 5/6 | 1/6 | `cause_mismatch` 1 |

- Result: no citation outside the linked events and no model failure in 12 answers; no `citation_check_failed`, `model_timeout`, `model_unreachable` or `model_error`. The only fallback is `cause_mismatch`: in run 1 on pure timeouts and on the small incident (the model named another cause than `timeouts`), in run 2 on one of them. Each is stored as the rules summary, so an analyst never sees a model-stated cause that contradicts the rules (ADR-0013).
- Limit: 6 incidents and two runs show the pattern, not a rate; the model is not deterministic across runs, so the fallback rate moves between runs.

## Incident timing (REL-36, 2026-11-03)

- What: how fast the detector opens an incident for an injected outage, how long recovery takes to show, and how long the API path to resolution takes. One seeded outage scenario (`processor-a-outage`, 300 payments, Processor A down from payment 100 to 199) with Relay routing (`ROUTING_STRATEGY=rules`), repeated 3 times with fresh seeds (11, 12, 13), each after `python -m app.demo.reset` and a simulator reset. All data is synthetic.
- Command (from `projects/professional/relay`, `RELAY_API_KEY` set, `OLLAMA_URL=http://127.0.0.1:9` as in CI so summaries are rules text): `python scripts/incident_timing.py --runs 3`. It leaves the stack running (`docker compose down -v` to remove it) and writes `docs/evaluation/incident-timing/results.json` (every timestamp) and `results.md`.
- Definitions, all from saved or stored timestamps, never from sleeps:
  - **Time to detect (MTTD)** = incident `opened_at` minus the outage-on switch time. `opened_at` is the time of the `payment.routed` event whose health snapshot first showed Processor A avoided (ADR-0014), not the time the detector process ran. The switch time is printed by the generator (`switch time processor a outage on at ...Z`, UTC, taken right after the control call returned).
  - **Time to recovery** = `recovered_at` minus the outage-off switch time.
  - **Time to resolve (MTTR)** = `resolved_at` minus `opened_at`. Triage and resolve are scripted analyst steps (API calls), made after the incident recorded its recovery. So this MTTR includes the rest of the scenario and is not a human response time. The last column, `resolved_at` minus `triaged_at`, is the scripted triage-to-resolve step alone: it measures the API path, not an analyst.
- Pinned (L-068): payment rate 2 per second (so the router's attempts per window are fixed), `HEALTH_WINDOW_SECONDS=120` (the REL-30 value; default 60), the other health settings at their defaults (`HEALTH_MIN_ATTEMPTS=5`, `HEALTH_ERROR_THRESHOLD=0.5`), the generator's drain (every earlier payment final before each switch) and its wait of one health window after the outage ends. What stays free is the simulator's seeded draws, so the spread below is the tolerance to quote.

| Run | Seed | Detect (s) | Recovery (s) | Resolve, scripted (s) | Triage to resolve (s) |
|---|---|---|---|---|---|
| 1 | 11 | 52.674 | 128.45 | 204.725 | 0.012 |
| 2 | 12 | 55.791 | 128.294 | 204.449 | 0.015 |
| 3 | 13 | 62.787 | 132.518 | 186.063 | 0.031 |
| Mean | | 57.084 | 129.754 | 198.412 | 0.019 |
| Min | | 52.674 | 128.294 | 186.063 | 0.012 |
| Max | | 62.787 | 132.518 | 204.725 | 0.031 |
| Std dev | | 5.179 | 2.395 | 10.696 | 0.01 |

- Result: with a 120 s window and 2 payments per second, an outage was detected in 53 to 63 s (mean 57 s) after it began, and the incident recorded recovery 128 to 133 s (mean 130 s) after it ended, just over the 120 s window, as expected, because recovery needs the old failures to leave the window. Quote MTTD as about 57 s with a spread of 53 to 63 s (3 runs). With the default 60 s window detection and recovery would be faster; the numbers move with the window and the payment rate, so they are a demo-scale measurement, not a production figure.
- Limit: 3 runs show the spread, not a distribution; the scripted resolve measures the API, not an analyst. The resolve column includes waiting for recovery, so do not read it as a response time.
- Drain fix (REL-34 open item): the generator's drain limit is now 100 s by default (two sweeper re-drive cycles of 30 s + 5 s, plus 30 s), and a drain timeout lists each unfinished payment. No drain timeout occurred in these 3 runs.

## Outage demo against a static-routing baseline (REL-30)

- What: one seeded outage scenario (`processor-a-outage`, seed 7, 300 payments, Processor A down for payments 100 to 199) run once with `ROUTING_STRATEGY=static` (the baseline: Processor A only, no failover, no retry) and once with Relay routing, from the same reset state and the same payment references. All data is synthetic.
- Command (from `projects/professional/relay`, with `RELAY_API_KEY` set and the host Ollama running): `python scripts/outage_demo.py --seed 7 --runs 3`; it runs `python -m app.demo.reset` in the api image between runs and leaves the stack up (`docker compose down -v` to remove it).
- Results, metric definitions, the 2-hour manual-reconstruction assumption, the reproducibility table and per-run raw outcomes: `docs/evaluation/outage-demo/` (`results.md`, `results.json`, `run<N>-<mode>.outcomes.json`, `run<N>-<mode>.report.json`).
