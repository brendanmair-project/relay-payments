# Phase 1 exit review (REL-32, evidence half)

Date: 2026-11-02. Reviewed commit: `b880d26` (worktree `rel32`, branch `rel-32-phase-1-exit-review-and-phase-2-r`). All data is synthetic. This file records evidence only; the `plan-review` run, the Phase 2 refinement, issue re-sync, process log, README status and handoff are done separately by the primary session.

Verdict key: Met, Partly met, Not met. Evidence is a command and what it printed, a test as `file::name`, a CI run URL, or a file link. Test paths are under `api/tests/` unless stated.

## Summary

Phase 1 is met on every roadmap exit criterion. Three items are Partly met and are explained, none blocks Phase 2: the PR #351 e2e job was skipped by the path filter (the e2e evidence comes from PR #350 and #347), the docker kill method in the suggested ADR-0003 run does not trigger the restart policy (so restart-after-crash was not exercised live), and the billing API could not be read (CI minutes are an estimate). The forced-failure run lost no event and duplicated none in the timeline; the stream carried 140 expected duplicate entries (at-least-once), all harmless.

## 1. Roadmap exit criteria (`docs/product/roadmap.md`, Phase 1)

| Criterion | Verdict | Evidence |
|---|---|---|
| `docker compose up` brings up the whole system locally | Met | `RELAY_API_KEY=<plain value> docker compose up -d --build --wait` in the worktree (no env file, only the key in the shell): exit 0, all of `api`, `explainer`, `frontend`, `postgres`, `publisher`, `redis`, `simulator`, `worker` reported `Healthy`, `migrate` `Exited` (0). Caveat: a worktree of the repository, not a fresh `git clone`; it has no env file and no cached data volumes, so it behaves as a clean clone, and the images were built from source. Also `test_compose_stack.py` and `test_compose_explainer.py` (compose file checks) |
| A scripted demo injects a Processor A outage and shows failover plus an explanation | Met | [`outage-demo/results.md`](outage-demo/results.md): `python scripts/outage_demo.py --seed 7 --runs 3`; baseline 58% vs Relay 89% success (+31.0 pp), 93 of 300 references improved and none got worse, 89 rescued by retry and 4 by failover, median time to explanation 1033.5 ms; reproducibility PASS (spread 0 over three runs, tolerance 1 pp and 1%). Explanations stored per failure (section 3, ADR-0009 item 3) |
| pytest and a Playwright smoke test pass in CI | Met, with a note | Latest `main` run in which the backend job executed: <https://github.com/brendanmair-project/relay/actions/runs/41455186538> (REL-30 merge, `Backend lint, types, tests` and `Simulator lint and tests` success). Later `main` runs (the REL-31 merge and the docs commits, latest <https://github.com/brendanmair-project/relay/actions/runs/41473221625>) are green but documentation-only, so path filters skipped the code jobs (run `gh run view <id> --json jobs`). e2e: PR #351 (README only) skipped `Stack smoke and e2e (pull requests)` (`gh pr checks 351`); the job passed in PR #350, <https://github.com/brendanmair-project/relay/actions/runs/41454484563> (4m37s), and PR #347 (REL-29, 6m56s). Playwright spec `frontend/tests/e2e/smoke.spec.ts`: create a payment and see timeline and explanation, axe accessibility, no API key in browser traffic, foreign Host 403, cross-site POST 403 |
| State machine, idempotency and money rules covered by tests | Met | State machine: `domain/test_lifecycle.py` (16 tests, including `test_result_for_non_current_attempt_is_stale`, `test_late_answer_from_processor_a_after_retry`, `test_stale_takes_precedence_over_after_timeout`), `services/test_transitions.py` (18, including `test_concurrent_writers_get_gapless_unique_seqs`, `test_stale_attempt_is_recorded_as_late_result`), `db/test_constraints.py` (17). Idempotency: `api/test_payments_api.py` (`test_replay_returns_stored_response`, `test_changed_body_is_409_reused`, `test_concurrent_requests_create_one_payment`, `test_key_past_24_hours_starts_a_new_payment`), `api/test_idempotency_service.py`, `jobs/test_key_cleanup.py`. Money: `domain/test_money.py` (7, `test_currency_table_matches_adr_0009`), `db/test_constraints.py::test_unknown_currency_is_rejected`, `api/test_payments_api.py::test_currency_message_is_clear` |
| R1 and R5 reassessed with implementation evidence | Met | Section 4; rows updated in [`../delivery/risk-register.md`](../delivery/risk-register.md) |

## 2. ADR-0003 validation, run live (no lost or duplicated event)

Verdict: Met. Method: stack up as in section 1; the publisher is the only writer to the stream. Three runs on one stack (60 s of setup each):

1. `docker compose stop publisher`; 200 payments created through `POST /payments` (script outside the repository, unique `Idempotency-Key` and `reference`); counted `payment_events`: 200 rows, 0 published, `XLEN relay:payment-events` 0, all payments `received` (the worker reads only the stream).
2. To make the crash window wide, a second session took `LOCK TABLE payment_events IN SHARE MODE` for 25 s: the publisher's `SELECT ... FOR UPDATE SKIP LOCKED` and its `XADD` calls run, but its `UPDATE ... SET published_at` waits. `docker compose start publisher`, then after 8 s: `XLEN` 100 and 200 events unpublished (`pg_stat_activity` showed the publisher's `UPDATE` waiting on a relation lock): the exact window between "added to the stream" and "marked published". `docker compose kill -s SIGKILL publisher` there (exit 137).
3. Lock released, publisher started again by `docker compose start`. Runs 2 and 3 repeated the procedure with 60 and 40 payments (run 2's in-container `kill -9 1` was ignored, PID 1 cannot be killed from inside its namespace, so it was a clean publish; run 3 killed in the window again).

Final counts (all three runs, 300 payments):

| Measure | Value |
|---|---|
| Payments / final | 300 / 300 (captured 268, declined 25, failed 7); none stuck |
| `payment_events` rows / marked `published_at` / unpublished | 2,869 / 2,869 / 0 |
| Distinct `(payment_id, seq)` / payments with a gap in `seq` | 2,869 / 0 (no duplicate or missing event in any timeline) |
| Stream entries / distinct `event_id` / events missing from stream / entries not in the database | 3,009 / 2,869 / 0 / 0 |
| Duplicate stream entries (the republished batches) | 140 = 100 (run 1) + 40 (run 3), each `event_id` at most twice |
| Duplicates with an effect: payments with two `payment.routed` for one attempt, two `payment.captured`, two `payment.final` | 0, 0, 0 |
| Explanations / `payment.explained` events / failed or declined finals | 32 / 32 / 32 |
| Consumer groups `processing` and `explanations` after the run | lag 0, pending 0, entries-read 3,009 |
| `payment.redriven` events (the sweeper during the 3-minute outage, 30 s threshold) | 767 across 199 payments; consumed with no effect on final state |

Reading: a crash between `XADD` and the commit re-sends the batch, never loses it (ADR-0003 consequence "at-least-once"); the duplicate entries are triggers and the state-guarded worker ignored them (`dup_*` counts 0). The unit equivalent is `outbox/test_publisher.py::test_crash_after_xadd_before_mark_republishes_without_loss`, and `outbox/test_publisher.py::test_concurrent_publishers_skip_rows_locked_by_each_other` covers two publishers.

Not proven live (stated honestly): (a) restart by the restart policy. `docker kill` and `docker compose kill` count as a manual stop in this Docker (state `exited`, exit 137, `RestartCount` 0, also on a freshly recreated container), so the suggested "let the restart policy bring it back" does not work with kill; I restarted by hand. A real crash (non-zero exit) needs a host-level kill, which was refused by the sandbox classifier and not attempted again. Primary's note: restart after a real crash was proven in REL-48 (process log, session 18): the worker process killed with SIGKILL from outside the Docker API came back through the restart policy (RestartCount 1, healthy); every long-running service has the same `restart: unless-stopped`, checked by `api/tests/test_compose_stack.py`. (b) Trimming at `MAXLEN ~ 10000` was never reached (3,009 entries).

Observation, open question 5: the minimum gap between two `payment.redriven` events of one payment was 26.3 s by event time although the threshold is 30 s. The sweeper compares `last_driven_at`, set to the sweep pass's database `now()` (taken at the start of the pass), while the event's `occurred_at` is the transaction's own time, so with a slow pass (here one blocked by my table lock) event times drift by seconds. Gaps measured on `last_driven_at` cannot be shorter than the threshold; `worker/test_sweeper.py::test_stalled_received_payment_is_redriven_once_per_threshold` proves it with a controlled clock. No double re-drive happened.

## 3. ADR-0008 and ADR-0009 validation

### ADR-0008 (validation line: duplicate delivery, consumer crash, late result, concurrent idempotency, lost stream entry; plus lease takeover and sweeper)

| Case | Verdict | Tests (all in `api/tests/`) | Live check |
|---|---|---|---|
| Duplicate delivery | Met | `worker/test_worker.py::test_duplicate_trigger_changes_nothing`; `routing/test_worker_routing.py::test_retry_also_runs_on_a_redriven_trigger`; `explainer/test_consumer.py::test_redelivered_final_entry_changes_nothing`; `explainer/test_store.py::test_redelivered_final_creates_no_second_row_or_event_and_no_model_call`; no second charge: `simulator/tests/test_processors.py::test_repeated_key_returns_the_first_result_without_waiting_again` | Section 2: 140 duplicate entries plus 767 re-drive triggers, no second `payment.routed` per attempt, no second capture |
| Consumer crash | Met | `worker/test_worker.py::test_pending_message_of_crashed_consumer_is_reclaimed_once`, `::test_failure_before_commit_leaves_message_pending`; `worker/test_shutdown.py::test_stop_during_an_entry_finishes_it_and_leaves_the_rest_pending_for_reclaim` | Not run (a test covers it); a publisher crash was run live |
| Late result | Met | `worker/test_worker.py::test_late_authorize_after_timeout_is_recorded_only`, `::test_late_authorize_for_old_attempt_is_stale`, `::test_late_capture_after_timeout_is_recorded_only`; `worker/test_sweeper.py::test_result_after_the_sweeper_failed_the_attempt_is_a_late_result`; `services/test_transitions.py::test_stale_attempt_is_recorded_as_late_result`, `::test_after_timeout_is_recorded_as_late_result`; `domain/test_lifecycle.py::test_late_answer_from_processor_a_after_retry` | Not run live (the simulator never answers a timed-out key late, see the REL-19 note); 0 `attempt.late_result` in the live data |
| Concurrent idempotency | Met | `api/test_payments_api.py::test_concurrent_requests_create_one_payment`, `::test_in_progress_same_body_is_409_with_retry_after` | Not run (a test covers it) |
| Lost stream entry | Met | `worker/test_sweeper.py::test_lost_stream_entry_still_ends_with_a_final_payment` | Live: during the publisher outage the payments had no stream entry for up to 3 minutes and all 100 stalled payments still reached a final state after the stream was fed again (the sweeper had re-driven them 767 times) |
| Idempotency lease takeover | Met | `api/test_idempotency_service.py::test_expired_lease_is_taken_over_with_a_new_token`, `::test_takeover_of_a_completed_expired_key_clears_the_response`, `::test_lost_takeover_race_rereads_and_decides_again`, `::test_create_once_rolls_back_when_the_lease_is_lost`; `api/test_payments_api.py::test_expired_lease_same_body_is_taken_over`, `::test_expired_lease_different_body_is_409_reused`, `::test_stalled_first_request_cannot_complete_a_taken_over_key` | Not run (tests cover it) |
| Sweeper re-drives a stalled payment once per threshold | Met | `worker/test_sweeper.py::test_stalled_received_payment_is_redriven_once_per_threshold`, `::test_stalled_retrying_payment_is_redriven_without_a_state_change`, `::test_final_payments_are_never_redriven`, `::test_repeated_sweeps_produce_one_timeout_transition`, `::test_two_concurrent_sweepers_produce_one_move_per_payment` | Live: 767 re-drives, 199 payments, spacing about 31 s (see the 26.3 s observation in section 2) |

ADR-0008 decisions 1 to 7 are all backed by the code that the tests above exercise; decision 7 (shared routing health) by `routing/test_health_endpoint.py` and the live `GET /processors/health` (`{"strategy": "rules", ...}`, computed from events). Verdict: ADR-0008 validated, Accepted stays.

### ADR-0009 decisions

| Decision | Verdict | Evidence |
|---|---|---|
| 1 Currencies USD, EUR, GBP, JPY, other code 422 | Met | `domain/test_money.py::test_currency_table_matches_adr_0009`; live `POST /payments` with `XXX` returned 422 `validation_failed` "currency must be one of USD, EUR, GBP, JPY"; database `ck_payments_currency` |
| 2 `X-API-Key` on every endpoint, browser never holds it | Met | `api/test_read_payments.py::test_both_endpoints_require_api_key`, `api/test_payments_api.py::test_bad_api_key_is_401`; live: `GET /health` without a key returned 401; `frontend/app/secrets.test.ts` and e2e `the API key never appears in browser requests or page source` |
| 3 Stored explanations with source, model and time | Met | `api/test_explanation_api.py::test_get_does_not_regenerate_on_repeat`, `::test_regenerate_adds_a_row_returns_201_and_becomes_the_latest`; live: 32 failed or declined payments gave 32 `final_failure` rows and 32 `payment.explained` events (partial unique index `uq_payment_explanations_final_failure`) |
| 4 2-hour manual baseline stated as an assumption | Met | [`outage-demo/results.md`](outage-demo/results.md) ("assumption"), README |
| 5 Static baseline, no failover or retry | Met | `routing/test_worker_routing.py::test_static_strategy_sends_everything_to_a_without_failover_or_retry`, `routing/test_router.py::test_static_always_a_with_reason_static`, `worker/test_sweeper.py::test_routed_timeout_is_final_when_routing_is_static`; baseline run in the outage demo |
| 6 Reproducibility within tolerance | Met | `simulator/tests/test_processors.py::test_same_seed_gives_the_same_outcomes_in_a_different_arrival_order`, `simulator/tests/test_demo_compare.py::test_reproducibility_spread_and_tolerance`; demo table: spread 0 over three runs |

Verdict: ADR-0009 validated, Accepted stays.

## 4. Risks R1 and R5

### R1 event schema against the Phase 2 consumers

Fields available in `payment_events` today: `id`, `payment_id`, `seq`, `attempt_no`, `type`, `from_status`, `to_status`, `processor` (only on `payment.routed`, `payment.failed`, `attempt.*`), `reason`, `data`, `correlation_id`, `occurred_at`, `published_at`. Data keys seen live: `latency_ms` and `result` on `attempt.*_result`, `outcome` on `payment.final`, `health` on `payment.routed`, explanation ids on `payment.explained`. Stream entries carry only `event_id`, `payment_id`, `seq`, `attempt_no`, `type`, `correlation_id`.

| Consumer | Event types and fields it needs | Present? |
|---|---|---|
| REL-34 incident detection and lifecycle | `payment.routed` (attempts) and `payment.failed` (errors) with `processor`, `reason` in `timeout`, `outage`, `capture_failed`, `occurred_at`; the same series `GET /processors/health` already computes, served by index `(type, processor, occurred_at)` | Yes, nothing missing |
| REL-35 link incidents to payments and events, grounded summary | `payment_id`, `seq`, `type`, `reason`, `processor`, `attempt_no`, `occurred_at` of failed, declined and final events inside the incident window; the rules explainer already builds timelines from these | Yes; the link table (incident id to payment id and seq) is the incident service's own |
| REL-37 analytics by processor, time and reason | Volume: `payment.received`; success rate: `payment.final` `data.outcome`; latency: `data.latency_ms` of `attempt.*_result`, and `payment.received` to `payment.final` times; failure reasons: `payment.failed` and `payment.declined` `reason`; revenue: amounts | Partly. Amount and currency are not in any event (live `payment.received.data` is `{}`) and terminal events (`payment.captured`, `payment.declined`, `payment.final`) have `processor` null. Both are resolved by a join (`payments` for money; the latest `payment.routed`, equal to `payments.processor`, for the processor). REL-37's wording "derive figures from `payment_events` only" cannot hold for revenue as written: decide to allow the join to `payments`, or put `amount_minor` and `currency` in `payment.received.data` going forward (no migration, older rows would lack it) |
| REL-39 webhooks (state changes, filter by event type, signed payload, retries) | `type` in the six `payment.*` state events, `event_id` as the delivery id, `payment_id`, `seq` for per-payment ordering, `to_status`, `occurred_at`; amount and currency for the body | Yes for identification and ordering. Payload money comes from `payments` (immutable, so the join is safe). The consumer must read missed events from `payment_events` by `id` and `published_at`, not from the trimmed stream |

Proposal: R1 stays Low likelihood, High impact, status Mitigated, reviewed. The three gaps (money join, processor of terminal events, paging from PostgreSQL) are doc-level facts, now written in [`../architecture/data-model.md`](../architecture/data-model.md); the money decision belongs in the REL-37 refinement. Row updated.

### R5 stream server

| Observation | Evidence |
|---|---|
| Size | `valkey-cli INFO memory`: 1.51 MB used with 3,009 entries; `INFO persistence`: append-only on, 2.9 MB file; no `maxmemory` set |
| Lag | Both groups ended at lag 0 and 0 pending (`XINFO GROUPS`), 3,009 entries read; demo `results.md`: largest backlog 3 (Relay) and 14 (baseline) entries |
| Reclaim | Covered by `worker/test_worker.py::test_pending_message_of_crashed_consumer_is_reclaimed_once`; no consumer crashed live |
| Trimming | `MAXLEN ~ 10000` never reached; about 9.5 events per payment means roughly 1,000 payments of history in the stream; trimming is safe for the worker because the sweeper reads PostgreSQL |
| Outage of the publisher | 3 minutes without publishing: nothing lost, the backlog drained in about one minute once it returned |

Proposal: R5 stays Low. Do not swap the broker. The risk that rises in Phase 2 and 3 is a new consumer group that falls more than 10,000 entries behind; each must recover from `payment_events`. Re-evaluate at Phase 2 exit with the real Phase 2 load. Row updated. R12 also updated (section 6).

Other register rows that look stale (not in my allowed files, for the primary): R3 still says ADR-0005 is Proposed (it is Accepted); R11 can move from "Mitigated (design)" to validated by the tests in section 3; R14 can cite the three reproducible runs.

## 5. Documents reconciled with the code

Method: `GET /openapi.json` from the running api (paths, parameters, schemas) with live requests for status codes; `api/app/db/models.py`, `api/migrations/versions/0001_initial_schema.py` and `0002_payment_explanations.py` plus `\d` of every table in the running database; `docker-compose.yml` and the three Dockerfiles. No code was changed. Full tables are in the last section of each document.

| Document | Differences found | Resolved how |
|---|---|---|
| [`api-contract.md`](../architecture/api-contract.md) | No `securitySchemes` in the OpenAPI; `Idempotency-Key` declared optional (handler enforces 400); `currency`, status values and `source`/`trigger` plain strings; path parameter `payment_id` against `{id}`; every endpoint lists the shared error codes; two endpoints have no description | New section "Differences from the generated OpenAPI" and a reconciliation line in Status; document stays the authority. All field lists, status codes (checked live: 401, 400, 422, 404 for a non-UUID, 400 for a malformed cursor, 404 for an unknown path), filters and the processor health shape matched |
| [`data-model.md`](../architecture/data-model.md) | `fallback_reason` list lacked `model_error`; event `data` contents undocumented (`payment.routed.data.health`, `outcome`, `latency_ms`, explanation ids); not stated which events carry `processor` or money | All three added; tables, constraints, indexes, trigger, stream keys and groups matched exactly |
| [`containers.md`](../architecture/containers.md) | Status said only part of the stack was built; `reporting` (profile `tools`) missing; volumes, `./reports` bind mount, log cap and the postgres init script undocumented; `worker` start order omitted its wait for the simulator; `reporting` missing from "Used by" of `PROCESSOR_TIMEOUT_SECONDS` | Fixed in place; images, pins, ports, restart policies, health checks and variable defaults matched |

Code questions found (none changed): whether to declare an API-key security scheme in the OpenAPI (helps the SDK and developer docs, REL-40), and whether `Idempotency-Key` should be declared required while keeping the 400 order of checks.

## 6. Hygiene and CI

| Item | Verdict | Evidence |
|---|---|---|
| Project hygiene | Met | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <workspace>\maintenance\test-project-hygiene.ps1 -ProjectRoot <worktree>` printed `PROJECT_HYGIENE=PASS CHECKED=2`, exit 0 |
| Template validation | see the file list at the end | `validate-template-system.ps1 -Mode Managed` run after the edits |
| CI minutes against ADR-0007 | Partly met (estimate) | `gh run list --limit 200` returned 101 runs (earliest 2026-10-26); `gh run view <id> --json jobs` job durations, skipped jobs counted as zero: 2026-10 (from the 26th) 69 runs, 308 jobs, 184.2 raw minutes, about 402 billed (each job rounded up to a minute); 2026-11 (to the 2nd) 32 runs, 152 jobs, 119.5 raw, about 221 billed. Budget: Relay 600 a month (workspace `projects/README.md`), ADR-0007 estimate 465. `gh api users/<login>/settings/billing/...` returned 404 because the token lacks the `user` scope (not changed), so the account-wide total over the seven private repositories is unknown |
| Merge gate (R12) | Met as designed | Free private plan, no branch protection; merging stays manual after `gh pr checks` (`task-finish.ps1` waits for CI); PR #350 had all checks passing |

Reading: the pace of the last eight days (about 623 billed minutes) is above the monthly 600 if it continued, though it covers the densest build period; docs-only pushes cost about two job minutes. Keep path filters and PR-only e2e.

## 7. ADR statuses

| ADR | Status in file and in `docs/decisions/README.md` | Phase 1 evidence supports it? |
|---|---|---|
| 0001 stack | Accepted | Yes: the stack runs end to end (amended by 0011, 0012) |
| 0002 positioning | Accepted | Yes: README and demo |
| 0003 outbox | Accepted | Yes: section 2 |
| 0004 payment fundamentals | Accepted | Yes: lifecycle, money and idempotency tests (section 1) |
| 0005 explanation provider | Accepted | Yes: stored explanations with rules fallback, quality check 10/10 citations (`results.md`) |
| 0006 observability | Proposed (Phase 2, to be accepted in REL-33) | Not applicable yet; stays Proposed |
| 0007 tooling and CI | Accepted | Yes: CI green; minutes see section 6 |
| 0008 attempts and reliability | Accepted | Yes: section 3 |
| 0009 Phase 1 owner decisions | Accepted | Yes: section 3 |
| 0010 local model | Accepted | Yes: `granite3.3:2b` in the demo |
| 0011 build decisions | Accepted | Yes: clean-clone start with only `RELAY_API_KEY` |
| 0012 review decisions | Accepted | Yes: Valkey pins, `explainer` container, reproducible paired runs |
| 0013 rules text on cause mismatch | Accepted | Yes: `cause_mismatch` rows in the demo (3 of 33 Relay, 103 of 126 baseline explanations) |

Every status in the README table matches the file header, so `docs/decisions/README.md` is unchanged. A newer ADR may exist on `main` (the plan commit `f6c5d96` mentions ADR-0014 decisions); it was not in this worktree.

## 8. Open questions for the owner

1. Declare an API-key security scheme and mark `Idempotency-Key` required in the generated OpenAPI? (Helps REL-40 developer docs; no behaviour change.)
2. REL-37 says analytics are derived from `payment_events` only, but money is not in events. Allow a join to `payments`, or add `amount_minor` and `currency` to `payment.received.data` from now on?
3. CI minutes: the last eight days ran at about 623 billed minutes against Relay's 600 a month. Accept, or tighten (for example e2e only when the frontend or api changes, fewer docs-only runs)? The account total needs the `user` scope on the token (`gh auth refresh -h github.com -s user`) or a look at the billing page.
4. The restart policy does not restart a container stopped with `docker kill`; a real crash restart was not exercised live here. Resolved by the primary: the REL-48 crash test (process log, session 18) proved restart after a real SIGKILL, and the compose contract test keeps the policy on every long-running service; no drill added.
5. Re-drive spacing by event time can read below 30 s on a slow sweep pass (26.3 s observed); the guarantee holds on `last_driven_at`. Accept, or stamp the event and `last_driven_at` with the same time?
6. In the baseline run 103 of 126 explanations show `cause_mismatch` (cause not analysed here). It is within ADR-0013, but worth stating in the README results so the number is not misread.
7. R3, R11 and R14 rows in the risk register are stale (section 4); the primary refreshes them with the process log.

Owner review (2026-11-02): approved. CI minutes: keep CI as is and check usage at REL-38; tighten path filters if a month passes 1,000 minutes (R12). The REL-37 money join and the OpenAPI gaps were moved into the plan (REL-37, REL-40).
