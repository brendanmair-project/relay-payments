# Phase 2 exit review (REL-38, evidence half)

Date: 2026-11-04. Reviewed commit: `02d58f5` (worktree `rel38`, branch `rel-38-phase-2-exit-review-and-phase-3-r`). All data is synthetic. This file records evidence only; the `plan-review` run, the Phase 3 refinement, issue re-sync, process log, README status and handoff are done separately by the primary session.

Verdict key: Met, Partly met, Not met. Evidence is a command and what it printed, a test as `file::name`, a CI run URL, or a file link. Test paths are under `api/tests/` unless stated. Live runs used a shell-only `RELAY_API_KEY` (no env file), Docker Compose in the worktree, and each ended with `down -v`.

## Summary

Phase 2 is met on every roadmap exit criterion, with two guardrail metrics that have no dashboard panel (section 1, third row) and one that has only a nearby proxy. Nothing blocks Phase 3. Highlights:

- ADR-0006 was Accepted about 23 minutes before the first dashboard commit in the same pull request (#355).
- A seeded Processor A outage opened a rule incident that linked 94 payments; manual incidents were created, triaged and resolved through the API; the UI lifecycle passed the Playwright spec (10 of 10).
- All 21 dashboard queries return data from Prometheus on the live stack (the 5xx panel returns a series that is correctly all zero).
- On the live stack the Relay run captured 268 of 300 payments (89.3%); the stored REL-30 baseline reads 58% static against 89% Relay (+31.0 pp).
- Clean clone: the default stack (9 long-running services plus `migrate`) is healthy and `scripts/smoke_stack.py` passes, with one caveat about the script (section 2).
- CI minutes: about 406 billed for 26 to 31 October and 419 for 1 to 4 November. Neither month is near 1,000, so no tightening is triggered; November is on a pace to reach it (section 4).
- R5 stays Low; R12 text updated with the figures.

## 1. Roadmap exit criteria (`docs/product/roadmap.md`, Phase 2)

| Criterion | Verdict | Evidence |
|---|---|---|
| ADR-0006 was Accepted before dashboards were built | Met | `git log --follow docs/decisions/0006-observability-stack.md`: the accepting commit is the first commit of PR #355 (REL-33), `1645b17` "REL-33: accept ADR-0006 (Prometheus v3.15.1, Grafana 13.3.0 OSS, ...)", committed 2026-11-02T19:24:37Z (it changed only `docs/decisions/0006-observability-stack.md` and `docs/decisions/README.md`; verified with `gh api repos/brendanmair-project/relay/commits/1645b17`). The first commit that adds `observability/` (and the metrics code, compose services and `docs/architecture` pages) is `ca127f3` at 19:47:30Z, 23 minutes later; a third commit `3e986e1` (19:57:31Z) only touched metric initialisation. `git show 4808f69~1:docs/decisions/0006-observability-stack.md` has `Status: Proposed`, `git show 4808f69:...` has `Status: Accepted` and "accepted 2026-11-02". The pull request was squash-merged as `4808f69` (2026-11-02T20:07:26Z), so on `main` the order is only visible through the PR's commit list (`gh pr view 355 --json commits`); the history of the ADR file and of `observability/` in `main` shows both changes in one commit. `docs/decisions/README.md` and the file header agree (Accepted) |
| An incident is created manually and by rule, linked to the payments and events that caused it, and its lifecycle is updated end to end | Met | See the live run below. Tests: `incidents/test_detector.py`, `incidents/test_linking.py`, `incidents/test_api.py`, `incidents/test_detail_and_summary_api.py`, `incidents/test_summary.py` and the compose check `test_compose_incidents.py` (they ran in the REL-34 to REL-36 merges, not re-run here); e2e `frontend/tests/e2e/incidents.spec.ts` |
| The guardrail metrics in `docs/product/metrics.md` are visible on a dashboard | Partly met | Table below: 3 of the 5 reliability guardrails have a panel, 1 has a proxy (processor call latency and API latency, not creation to final) and 1 has no metric or panel (payments not final after the sweeper threshold). The engineering-health guardrails (CI pass rate, coverage, clean-clone start, paid dependencies) are not runtime metrics and are not on a dashboard; the dashboard spec does not claim them |
| The outcome metrics (revenue recovered, success-rate uplift) are computed against the static-routing baseline | Met | Live `GET /analytics` and `GET /analytics/baseline` below, plus the REL-30 results in [`outage-demo/results.md`](outage-demo/results.md); tests `analytics/test_api.py`, `analytics/test_baseline.py`, `analytics/test_figures.py` (REL-37, not re-run here) and e2e `frontend/tests/e2e/analytics.spec.ts` |

### Live run (stack with the observability profile)

Commands, from the worktree root with only `RELAY_API_KEY` in the shell:

1. `docker compose --profile observability up -d --build --wait`: exit 0 in 54 s; `api`, `explainer`, `frontend`, `grafana`, `incidents`, `postgres`, `prometheus`, `publisher`, `redis`, `simulator` and `worker` Healthy, `migrate` Exited (0). Prometheus targets `relay-api`, `relay-worker`, `relay-publisher` and `relay-incidents` all `up`.
2. `python scripts/incident_timing.py --runs 1 --seed 21 --out <scratch dir, deleted afterwards>`: the seeded `processor-a-outage` scenario (300 payments, 2 per second, outage on before payment 100 and off before payment 200, `ROUTING_STRATEGY=rules`, `HEALTH_WINDOW_SECONDS=120`), exit 0 after 5 m 38 s. Run 1 printed detect 61.4 s, recovery 132.6 s, scripted resolve 191.7 s, triage to resolve 0.02 s (earlier REL-36 results: mean detect 57.1 s over three runs, [`incident-timing/results.md`](incident-timing/results.md)). The script also triages and resolves the rule incident through the public API.
3. Manual calls with `curl` and the key header against `http://127.0.0.1:8000`, then `npm --prefix frontend run e2e -- incidents.spec.ts analytics.spec.ts` against `http://localhost:3000` (Chromium installed with `npx --prefix frontend playwright install chromium`).

Incidents:

| Check | Result |
|---|---|
| Rule incident | `GET /incidents`: id `ca83592f-eb2d-4cab-9a0e-338b97ee0a05`, `source: rule`, processor A, title "Processor A is being avoided by routing", opened 2026-11-05T00:49:43Z, `recovered_at` 00:52:11Z, triaged and resolved 00:52:54Z (the script) |
| Linked payments and events | `GET /incidents/{id}`: 94 `affected_payments` (82 captured, 10 declined, 2 failed), 188 linked events (186 `outage`, 2 `timeout`); 37,445 bytes of JSON. `incident_payments` holds 101 rows (94 plus 7 of the manual incident below) |
| Grounded summary | `GET /incidents/{id}/summary`: `source: rules`, `cause: mixed`, `fallback_reason: cause_mismatch` (ADR-0013 in action), text "94 payments were affected. Failures by kind: 93 outage, 1 timeout, 0 capture_failed ... 82 of the affected payments were rescued by failover or retry", cited event ids 723 and 1790 |
| Manual incident, no processor | `POST /incidents {"processor": null, "title": ...}` returned 201, `source: manual`, `status: detected`; transitions: `resolved` first returned 409 (`invalid_incident_transition`), `triaged` 200, `triaged` again 409, `resolved` 200; detail then showed `resolved` and 0 linked payments (as documented) |
| Manual incident with processor A, after the outage | `POST /incidents {"processor": "A", ...}` 201 and linked 7 payments (the lookback window); a second `POST` for A returned 409 `incident_already_open`; triaged 200 and resolved 200 |
| UI lifecycle | `incidents.spec.ts::open the list and detail, triage, then resolve and see the status change` passed (1.0 s); the same run passed the axe checks on the list and detail pages, no key in browser traffic, cross-site POST 403 and foreign Host rejection. All 10 tests of `incidents.spec.ts` and `analytics.spec.ts` passed (10 passed, 16.8 s). The UI spec exercises a manual incident on Processor B; the rule incident was not opened in the browser |
| Metrics | `relay_incidents_opened_total`: rule A 1, manual A 1, manual B 1 (the e2e spec) |

Data volume at the end of the run: 303 payments created (300 scenario plus 3 e2e), `payments` captured 268, declined 28, failed 4; 2,484 `payment_events`, none unpublished; 0 HTTP 5xx.

### Guardrail metrics against Grafana panels

Dashboards are provisioned from `observability/grafana/dashboards/*.json`; panel titles and queries below are copied from them. Verified through the Prometheus HTTP API: `GET /api/v1/query_range` for each query over the last hour at 15 s steps, run by a script outside the repository after the demo (the `[1m]` and `[5m]` windows have already decayed to zero when read with an instant query some minutes after the load, so a range query is the honest check). "Data" means at least one series with values; "nonzero" counts points different from zero.

| Guardrail (`metrics.md`) | Dashboard and panel | Query | Result |
|---|---|---|---|
| Payment success rate by processor | `success-rate`: Success rate by processor | `sum by (processor) (increase(relay_payments_final_total{outcome="captured"}[5m])) / sum by (processor) (increase(relay_payments_final_total[5m]))` | 2 series, 49 points, all nonzero |
| (same) | `success-rate`: Final payments by processor and outcome | `sum by (processor, outcome) (increase(relay_payments_final_total[5m]))` | 6 series, 121 nonzero of 174 |
| (same) | `success-rate`: Final payments per second | `sum(rate(relay_payments_final_total[1m]))` | 1 series, 20 nonzero of 29 |
| (same) | `success-rate`: Failure share by processor | `sum by (processor) (increase(relay_payments_final_total{outcome="failed"}[5m])) / sum by (processor) (increase(relay_payments_final_total[5m])) or ... * 0` | 2 series, 27 nonzero of 49 |
| P50/P95/P99 payment processing latency (creation to final) | none for creation to final. Nearest: `latency`: API request latency P50/P95/P99, Processor call latency P50/P95/P99 by processor, API request latency P95 by route | `histogram_quantile(0.5\|0.95\|0.99, sum by (le) (rate(relay_http_request_duration_seconds_bucket[1m])))`, the same on `relay_processor_call_duration_seconds_bucket` by `processor`, and `... by (le, route)` | All 7 queries return data (1, 1, 1, 2, 2, 2 and 11 series). These measure the API request and the processor call, not the payment. The creation-to-final percentiles are available only in `GET /analytics` (`latency`: p50 8,788 ms, p95 20,154 ms, p99 28,510 ms in this run) and the guardrail report |
| API 5xx rate | `throughput`: API 5xx rate | `sum(rate(relay_http_requests_total{status=~"5.."}[1m])) or vector(0)` and the ratio form | 1 series each; all points 0 (no 5xx occurred; `sum(relay_http_requests_total{status=~"5.."})` is empty) |
| Event publishing lag | `throughput`: Publish lag P95 (and P50) | `histogram_quantile(0.95, sum by (le) (rate(relay_outbox_publish_lag_seconds_bucket[1m])))` | 1 series, 20 nonzero points; highest P95 over the run 0.875 s |
| Payments not final after the sweeper threshold (target zero) | none; no metric exists | none | Gap: neither a counter nor a gauge, so no panel. Evidence of the value today comes only from the database (`final` 300 of 300 payments in `GET /analytics` volume) |
| Other panels (not guardrails) | `throughput`: Payments created per second, API requests per second by route, Events published per second; `processor-errors`: Processor error rate, errors per second by kind, calls per second by outcome | see `observability/grafana/dashboards/` | all return data |

Counters at the end: `relay_payments_created_total` 303; `relay_payments_final_total` A captured 174, declined 19, failed 3, B captured 96, declined 10, failed 1. File checks that keep the dashboards honest: `test_observability_files.py`.

### Outcome metrics against the static-routing baseline

| Figure | Value | Source |
|---|---|---|
| Live Relay run success rate | 268 captured of 300 = 89.3% | `payments` table after the seeded run (this run's seed 21, different from the REL-30 seed 7) |
| Baseline | 58.0% static, 89.0% Relay, uplift +31.0 pp | `GET /analytics/baseline`: `available: true`, label "synthetic data, static-routing baseline", seed 7, scenario `processor-a-outage` (`docs/evaluation/outage-demo/results.json`); `run_date` is null because the results file has no date |
| Revenue recovered (minor units) | EUR 3,032,328, GBP 1,618,218, JPY 902,033, USD 6,810,094 | the same endpoint |
| Revenue of rescued payments by path, this live run | retry 91 payments (EUR 3,311,761, GBP 1,626,432, JPY 709,531, USD 6,257,522), failover 5 (EUR 214,350, GBP 115,568, USD 191,741), redrive 0 | `GET /analytics?from=...&to=...`, `revenue_recovered_by_rescue_path` |
| Per processor, this run | A: 295 routed, 172 captured, 105 failed, 18 declined, success rate 0.6209, reasons outage 95, timeout 8, card_expired 8, do_not_honor 5, insufficient_funds 5, capture_failed 2; B: 107 routed, 96 captured, 1 failed, 10 declined, success rate 0.9897 | same endpoint |
| Time to explanation, this run | model 31 explanations (P50 1,017 ms, P95 1,946 ms), rules 1 (715 ms), fallback rate 0.0312 (one `cause_mismatch`) | same endpoint |
| Reproducibility (REL-30) | three runs identical, spread 0, tolerance 1 pp and 1% | [`outage-demo/results.md`](outage-demo/results.md) |

Reading: the live run is a different seed from the stored baseline, so the live figures show the endpoints work and the Relay rate is in the REL-30 range; the uplift claim rests on the paired REL-30 run, not on this run. Per-processor volumes add to 402 for 300 payments because the processor filter counts a retried payment under both (follow-up 4).

## 2. Clean clone

Verdict: Met, with a caveat on the smoke script. Method: `git clone --branch rel-38-phase-2-exit-review-and-phase-3-r <workspace>\.local\relay-wt\rel38 <workspace>\.local\rel38-clean` (commit `02d58f5`; the clone has no env file, only the tracked `.env.example`), then with only `RELAY_API_KEY` in the shell:

- `docker compose -p rel38clean up -d --build --wait`: exit 0 in 28 s (layers cached from the earlier build, so the time is not a cold-build time). `docker compose -p rel38clean ps`: `api`, `explainer`, `frontend`, `incidents`, `postgres`, `publisher`, `redis`, `simulator` and `worker` all `(healthy)`; `migrate` Exited (0); `prometheus` and `grafana` not started (the default stack leaves the observability profile off, ADR-0014).
- `python scripts/smoke_stack.py`: first run `SMOKE_STACK=FAIL FAILURES=7` because the script calls plain `docker compose`, which does not see the project name `rel38clean` (the 7 failures were the container and `migrate` checks, "not running"); the HTTP checks passed. Rerun with `COMPOSE_PROJECT_NAME=rel38clean` in the environment: all 13 checks `PASS`, `SMOKE_STACK=PASS`, exit 0 (health, 401 without key, simulator control, frontend, `POST /payments` 201, payment reaches a final state).
- `docker compose -p rel38clean down -v`: exit 0; clone deleted; no `rel38clean` container or volume left (`docker ps -a`, `docker volume ls`).

Caveat: `smoke_stack.py` checks only `postgres`, `redis`, `api`, `worker`, `simulator`, `frontend` and `migrate`, so `publisher`, `explainer` and `incidents` health is not covered by the script (follow-up 6); I confirmed them from `docker compose ps` and `--wait`.

## 3. Risk R5 (stream server) with Phase 2 evidence

| Observation | Evidence |
|---|---|
| Consumer groups | Three groups on `relay:payment-events`, not four: `processing` (worker), `explanations` (explainer) and `incidents` (detector); `XINFO GROUPS` at the end of the seeded run: each 1 consumer, 0 pending, `entries-read` 2,484, lag 0. A fourth group arrives with the webhook consumer (REL-39, ADR-0015) |
| Reclaim | All three consumers call `XAUTOCLAIM` (`app/worker/consumer.py`, `app/explainer/consumer.py`, `app/incidents/consumer.py`). Tests: `worker/test_worker.py::test_pending_message_of_crashed_consumer_is_reclaimed_once`, `worker/test_shutdown.py::test_stop_during_an_entry_finishes_it_and_leaves_the_rest_pending_for_reclaim`, `explainer/test_shutdown.py::test_stop_during_an_entry_finishes_it_and_leaves_the_rest_pending`, `incidents/test_detector.py::test_a_crash_after_commit_and_before_ack_is_harmless_on_redelivery`. No consumer crashed live in this run, so reclaim was not exercised live (same as Phase 1). The reclaim of the incidents and explainer groups has no named test as direct as the worker's (follow-up 8) |
| Lag and pending | End of run: 0 and 0 for all three groups. Not sampled during the run (no metric for stream lag or pending exists, and none is on a dashboard); publish lag P95 peaked at 0.875 s, so the publisher kept up with the 2 per second load. The largest backlog is therefore unmeasured in Phase 2 |
| Memory | `valkey-cli INFO memory`: 1.41 MB used with 2,484 entries (about 0.57 KB per entry; Phase 1 was 1.51 MB for 3,009); `maxmemory` 0; append-only on, file 3.3 MB; `XLEN` 2,484, below the `MAXLEN ~ 10000` trim |
| Load | One seeded run at 2 payments per second and 300 payments: about 8.3 events per payment. Well below a rate that stresses Valkey |

Proposal: R5 likelihood stays Low, impact Medium, status "Open (monitor)", reviewed at Phase 2 exit. Do not swap the broker. The Phase 3 trigger is the fourth group (webhook delivery): it must read missed events from `payment_events`, not the trimmed stream, and a lag and pending metric per group would make that visible on a dashboard (follow-up 7). Row updated in [`../delivery/risk-register.md`](../delivery/risk-register.md).

Other open rows reviewed (factual status text only updated in the register):

| Row | Finding |
|---|---|
| R1 | Reviewed against the actual Phase 2 consumers: incidents (detector, links, summary) and analytics used `payment_events` plus the `payments` money join; no schema change was needed. Text updated |
| R2 | No change; still one static key. The UI routes added in Phase 2 keep the key on the server (e2e: no key in browser traffic) |
| R3 | Still accurate; incident summaries use the same local model and rules fallback. Text extended with the incident summary |
| R7 | Clean-clone start verified at this exit (section 2). Text updated with the date |
| R8 | Revisit-at-Phase-2-kickoff note replaced by what the synthetic environment now varies: outage, timeout, capture_failed, declines by reason, rescued payments. Status stays Open |
| R9 | Live local model figures: P50 1.0 s, P95 1.9 s for 31 explanations, 1 rules fallback of 32 (`cause_mismatch`). Text updated |
| R10 | `GET /analytics/baseline` carries the label "synthetic data, static-routing baseline" and the analytics page shows a baseline section. Text updated |
| R11, R14, R18 | Still accurate; ADR-0013 (R18) was exercised live (incident summary `cause_mismatch`). R18 text updated |
| R12 | Updated with the October and November figures (section 4) |
| R15 | Hygiene passes with the two new images (Prometheus and Grafana, exact pins). Text updated |
| R16 | Updated with the Relay total so far |
| R17 | Mitigated by design; the incident and analytics routes have e2e checks for cross-site POST 403 and foreign Host. Text updated |

## 4. CI minutes (R12)

Verdict: Met against the 1,000-minute trigger (no month has passed it); the pace needs watching. Method as in REL-32: `gh run list --limit 400 --json databaseId,createdAt,event,...` returned 129 runs (earliest 2026-10-26T12:41:33Z, so October covers the 26th to the 31st); `gh run view <id> --json jobs` for each; a job's duration is `completedAt` minus `startedAt`, rounded up to a whole minute as the billed estimate, skipped jobs counted as zero. Linux runners, so the multiplier is 1. The billing API was not tried again (REL-32: HTTP 404 for lack of the `user` scope), so this is an estimate of Relay only, not the account total of seven private repositories.

| Period | Runs | Jobs run (skipped) | Raw minutes | Billed estimate | Against 1,000 |
|---|---|---|---|---|---|
| October (26 to 31) | 69 | 312 (180) | 184.1 | 406 | 41% |
| November (1 to 4) | 60 | 285 (195) | 234.5 | 419 | 42% after four days |
| Both | 129 | 597 | 418.6 | 825 | |

Details: by event, October push 195 and pull_request 211; November push 251, pull_request 165, schedule 3 (the Monday audit). Billed minutes per day: 26 Oct 120, 27 Oct 105, 28 Oct 99, 29 Oct 24, 30 Oct 58, 2 Nov 281, 3 Nov 138 (no run on 31 Oct and 1 Nov). Largest November jobs: Dependency audit 108, Semgrep 60, Detect changed areas 60, Secret scan 59, Stack smoke and e2e (pull requests) 52, Backend 39. The audit, Semgrep, secret scan and change detection run on every push and pull request (the audit by the ADR-0007 amendment of 2026-10-26), so a docs-only push costs about four job minutes and the four jobs make 287 of the November 419 (69%).

Reading: neither month passed 1,000, so the REL-32 owner decision (tighten path filters if a month passes 1,000) is not triggered and no workflow was changed. At the 2 and 3 November pace (about 210 billed minutes per active day) November would pass 1,000 after about five more active days, which is the case if Phase 3 (REL-39 to REL-42) continues at the Phase 2 rate, so the owner may want to tighten before then. Candidates, none applied: skip Semgrep and the secret scan on pushes that touch only `docs/` (saves about 2 minutes per docs-only push), run the audit on lock-file changes plus the weekly schedule (reverses the ADR-0007 amendment, so the owner decides), run `task-finish` docs commits as one push instead of three (the REL-37 merge produced three `main` pushes in an hour). The R12 row is updated with these figures.

## 5. Hygiene

| Item | Verdict | Evidence |
|---|---|---|
| Project hygiene | Met | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <workspace>\maintenance\test-project-hygiene.ps1 -ProjectRoot <workspace>\.local\relay-wt\rel38` printed `PROJECT_HYGIENE=PASS CHECKED=2`, exit 0 |
| Template validation | see the end of this file | `validate-template-system.ps1 -Mode Managed` |
| No code changes | Met | `git status` shows only `docs/evaluation/phase-2-exit-review.md` and `docs/delivery/risk-register.md` from this review. The untracked `docs/decisions/0015-webhook-delivery-signing-and-target-allowlist.md` and the modified `docs/decisions/README.md` in the same worktree were written by the primary session, not by this review, and are not committed by it |

## 6. ADR statuses

| ADR | Status in the file and in `docs/decisions/README.md` | Phase 2 evidence |
|---|---|---|
| 0001 stack | Accepted | Yes: Prometheus, Grafana and Next.js analytics pages run in the same stack |
| 0002 positioning | Accepted | Yes |
| 0003 outbox | Accepted | Yes: incidents and analytics consume `payment_events`; 0 unpublished events after the live run |
| 0004 payment fundamentals | Accepted | Yes |
| 0005 explanation provider | Accepted | Yes: 31 model and 1 rules explanation in the live run |
| 0006 observability | Accepted (2026-11-02) | Yes: Prometheus v3.15.1 and Grafana 13.3.0 ran under the `observability` profile; four targets `up`; all 21 panel queries return data; the metrics ports are internal only. Accepted before dashboards were built (section 1) |
| 0007 tooling and CI | Accepted | Yes: CI green on every merge; minutes in section 4 |
| 0008 attempts and reliability | Accepted | Yes: the incident detector reuses the same health series |
| 0009 Phase 1 owner decisions | Accepted | Yes: baseline label and 2-hour assumption shown |
| 0010 local model | Accepted | Yes |
| 0011 build decisions | Accepted | Yes: clean-clone start with only `RELAY_API_KEY` (section 2) |
| 0012 review decisions | Accepted | Yes: reference-seeded paired runs; image pins checked by hygiene |
| 0013 rules text on cause mismatch | Accepted | Yes: live incident summary `fallback_reason: cause_mismatch` stored the rules text; analytics `fallback_reasons {cause_mismatch: 1}` |
| 0014 incident detection in its own consumer, observability as an optional profile | Accepted | Yes: the `incidents` container is healthy and opened the rule incident; the default `up` starts no Prometheus or Grafana; the profile adds them |

All 14 ADRs have status Accepted in their files and in the log of `docs/decisions/README.md` at the reviewed commit (headers of 0007, 0008 and 0012 carry an explanatory suffix; the log shows Accepted). A fifteenth ADR (0015, webhooks) is being added in the working tree by the primary and is outside this review.

## 7. Phase 2 follow-ups (for the owner and the primary to place; none fixed here)

1. The incident list fetches each incident's detail to count its affected payments (`frontend/app/IncidentsList.tsx` reads `affected_payments`): N+1 calls, each up to 37 KB for the 94-payment incident. Fix: return a `affected_payment_count` on the list endpoint.
2. The incident detail page lists every payment and event in full (94 payments and 188 events, 37 KB in one response, no paging or cap). Fix: a cap or paging and a count.
3. The incident timing depends on the 120 s demo window: detect 61.4 s and recovery 132.6 s here are mostly the window (the default is 60 s), as the README states for the recovery lag. A figure for the default window would be needed before quoting a time to detect.
4. The analytics processor filter counts a retried payment under both processors (volumes A 295 plus B 107 for 300 payments); documented in the API contract, but the page shows the sum as if distinct.
5. No panel and no metric for "payments not final after the sweeper threshold" (target zero), and no panel for payment processing latency from creation to final: both are listed guardrails in `docs/product/metrics.md`. Either add them or amend the document to say where they are read.
6. `scripts/smoke_stack.py` checks only 6 services and `migrate`: `publisher`, `explainer` and `incidents` are not checked, and the script cannot target a compose project name other than the default (it needs `COMPOSE_PROJECT_NAME` in the environment).
7. No metric for consumer group lag or pending count (R5): the review had to read `XINFO GROUPS` by hand and could not report a peak backlog. A gauge per group would also cover the REL-39 webhook group.
8. Reclaim of the explainer and incidents groups has no test as direct as the worker's `test_pending_message_of_crashed_consumer_is_reclaimed_once`; nothing crashed live either.
9. Three success-rate definitions coexist: the Grafana panel (captured over all final, declines in the denominator), `GET /analytics` (captured over captured plus failed, declines apart) and `metrics.md` (final captured over created). The figures differ for the same payments (panel for A about 0.89 over the run, analytics for A 0.62 because it counts the retried payments that failed on A). Label them or align them.
10. `GET /analytics/baseline` has `run_date: null`: the results file records no date, so the UI cannot say when the baseline was run.
11. The e2e spec exercises the UI lifecycle only on a manual incident for Processor B; the UI for a rule-opened incident (with linked payments) has no browser test.
12. The stack leaves the rule incident open after recovery until an analyst resolves it, so a second outage on the same processor is blocked by `incident_already_open` for manual creation; documented, but the detector's behaviour on a second outage while one is open is not shown in a run.

## 8. Open questions for the owner

1. CI minutes: no month has passed 1,000 (406 for 26 to 31 October, 419 for 1 to 4 November). Tighten now or when a month passes (the REL-32 rule)? The pace suggests November will pass it during Phase 3; which candidate in section 4 do you prefer, and may the always-on audit change (ADR-0007 amendment)?
2. The two guardrails without a panel (follow-up 5): add a metric and panel, or amend `metrics.md` to say they are read from `GET /analytics` and the database? This affects whether the exit criterion "guardrail metrics visible on a dashboard" is rated Met or Partly met.
3. The task text for R5 mentions four consumer groups; today there are three (the fourth is REL-39). Confirm that the wording should follow the code.
4. Do you want a stream lag and pending gauge per consumer group in Phase 3 (follow-up 7)?
5. Should the success-rate definitions be unified (follow-up 9) before the Phase 3 SDK documents the analytics response?

## Owner review (2026-11-04)

Approved. Decisions on the open questions:

- The two guardrail metrics without a panel (creation-to-final payment latency, payments not final after the sweeper threshold) and a lag and pending gauge per consumer group are added to REL-57, the small follow-up task before webhooks. The dashboard criterion stays Partly met here, with the fix scheduled.
- The success-rate definitions are unified in REL-57 on captured over final payments (as `metrics.md` states), for the Grafana panel and `/analytics`, before the developer docs and SDK depend on them.
- CI stays as decided at REL-32: tighten path filters only when a month passes 1,000 billed minutes (about 406 in October, 419 in November so far).
- R5 follows the code: three consumer groups today (`processing`, `explanations`, `incidents`); the webhook group arrives with REL-39.
