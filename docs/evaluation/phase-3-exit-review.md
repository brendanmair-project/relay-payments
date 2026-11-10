# Phase 3 exit review (REL-42, evidence half)

Date: 2026-11-06. Reviewed commit: `a1a7b7d` (worktree `rel42`, branch `rel-42-phase-3-exit-review-and-phase-4-r`). All data is synthetic. This file records evidence only; the `plan-review` run, the Phase 4 refinement, issue re-sync, handoff and the owner's decision are done separately by the primary session. Nothing in the code was changed by this review: the findings in section 7 are recorded, not fixed.

Verdict key: Met, Partly met, Not met. Evidence is a command and what it printed, a test as `file::name`, a CI run, or a file link. Test paths are under `api/tests/` unless stated. Live runs used a shell-only `RELAY_API_KEY` (a plain value, no env file), Docker Compose in the worktree (project `rel42`), and each ended with `down -v`.

## Summary

Phase 3 is met on all three roadmap exit criteria. Nothing blocks Phase 4. Highlights:

- Seeded run, 60 payments, one subscription on `payment.final` and `payment.received`: 120 matching events in the database, 120 deliveries, 120 deliveries at the sink, every signature valid, 120 distinct event ids, and the keyed summary (`delivered` 120, `failed` 0, `pending` 0, rate 1.0) equal to the database count. A second fresh run gave the same 120.
- A live retry sequence on a single in-flight delivery: attempts 503, 503, 503, 200 with gaps of 2.0, 4.1 and 8.4 seconds (the documented 2, 4, 8).
- The SDK example ran from a fresh venv following only `docs/guides/sdk.md`; the quickstart's clean-room run reached `201 Created` 43 seconds after the clone.
- Clean clone: `docker compose up -d --wait --build` took 28 s (warm layer cache), all 10 long-running services healthy including the new `webhooks`, `scripts/smoke_stack.py` passes 13 of 13.
- Two carried findings are reproduced with evidence and one more is reproduced as a consequence: `GET /analytics?since=garbage` answers 200 because the handler has no `since` parameter at all, and `signing.verify` raises `TypeError` on a non-ASCII `v1`, which makes the demo sink answer 500.
- CI minutes: about 601 billed for 1 to 6 November (60% of 1,000 after six days). The R12 trigger (a month past 1,000) has not fired, but at the observed pace it fires within about three more active days.
- CI on `main`: success. Hygiene: `PROJECT_HYGIENE=PASS CHECKED=2`.

## 1. Roadmap exit criteria (`docs/product/roadmap.md`, Phase 3)

| Criterion | Verdict | Evidence |
|---|---|---|
| A subscriber can register for an event type and reliably receive a webhook for a payment reaching that state | Met | Live run below (120 of 120 matching events delivered once, all signature-valid, no duplicates). Supporting: `webhooks/test_fan_out.py`, `webhooks/test_sender.py`, `webhooks/test_api.py` (REL-39, PR #370) |
| Delivery failure and retry behavior are documented and tested | Met | Tests and guide sections in the table of section 1.2, plus one live retry sequence |
| A developer can make a first successful API call using only the docs | Met | The quickstart's recorded clean-room run (43 s) and this review's SDK example run from a fresh venv (section 1.3) |

### 1.1 Reliable delivery (live)

Commands, from the worktree root with only `RELAY_API_KEY` in the shell:

1. `docker compose --profile webhooks-demo up -d --wait --build`: exit 0 in 30 s (warm cache); `api`, `explainer`, `frontend`, `incidents`, `postgres`, `publisher`, `redis`, `simulator`, `webhook-sink`, `webhooks` and `worker` Healthy, `migrate` Exited (0).
2. `POST /webhooks/subscriptions` with `{"url": "http://webhook-sink:8200/hook", "event_types": ["payment.final", "payment.received"]}`: 201 with a secret; then `POST http://127.0.0.1:8200/config` with that secret. (I first created one subscription by mistake with its secret lost, deactivated it with `DELETE` before any payment existed; it shows as `active: false` in the list and received nothing.)
3. `docker compose run --rm simulator python -m generator --scenario processor-a-outage --seed 41 --count 60 --rate 4 --api-url http://api:8000 --control-url http://simulator:8101`: `sent 60 payments (201: 60)`, 17 s.
4. Counts after 20 s:

| Check | Result |
|---|---|
| Payments | 60: 56 captured, 4 declined, 0 failed (`select status, count(*) from payments`) |
| Matching events in the database | `payment_events` of type `payment.received` 60 plus `payment.final` 60 = 120 (`select count(*) from payment_events where type in (...)`) |
| Deliveries | `webhook_deliveries`: 120 rows, all `delivered`, 120 distinct `(subscription_id, event_id)` pairs (one delivery per matching event), maximum attempt 1 |
| At the sink | `GET http://127.0.0.1:8200/received`: 120 entries, all `signature_valid: true`, all HTTP 200, 120 distinct `event_id` values (no duplicate), 60 `payment.received` and 60 `payment.final` |
| Summary against the log | `GET /webhooks/deliveries/summary`: `{"delivered":120,"failed":0,"pending":0,"success_rate":1.0}`. `GET /webhooks/deliveries?status=failed` and `?status=pending` return 0 items (equal to `failed` 0 and `pending` 0). The `delivered` count cannot be read from the list: `limit` is capped at 100 (`limit=500` is a 422), there is no paging, so the list returned 100 of the 120 (follow-up 3). The 120 comes from the table instead, which equals the summary |
| Repeat | `down -v`, then the same stack and command again: summary again `delivered` 120, `failed` 0, `pending` 0; Valkey stream 416 entries; consumer groups `explanations`, `incidents`, `processing` and `webhooks` each 1 consumer, 0 pending, `entries-read` 416, lag 0 |

Caveat: with `--count 60` the outage window of the `processor-a-outage` scenario (payments 100 to 199) is never reached, so no payment failed or was retried and `payment.failed` never fired; the run exercises `payment.received` and `payment.final` with captured and declined outcomes only. The guide's own demo command (`--count 20`) has the same property.

### 1.2 Failure and retry: tests, guide sections and one live sequence

| Behaviour | Tests | Guide |
|---|---|---|
| Retry on a non-2xx answer with the first backoff step | `webhooks/test_sender.py::test_a_non_2xx_answer_schedules_a_retry_with_the_first_backoff_step`, `::test_a_delivery_that_succeeds_after_failures_is_delivered_with_its_attempt_count`, `::test_a_timeout_or_connection_error_is_retried_and_logged_without_a_status`, `::test_a_redirect_is_never_followed_and_counts_as_a_failure` | [Retries](../guides/webhooks.md#retries) |
| Backoff exponential with a cap, and fresh signature with the same body on each retry | `::test_the_backoff_function_is_exponential_with_a_cap`, `::test_the_body_is_the_same_on_every_retry_but_the_signature_is_fresh`, `::test_the_settings_defaults_are_demo_friendly_and_name_the_environment_variables` | [Retries](../guides/webhooks.md#retries), [The message](../guides/webhooks.md#the-message) |
| Final `failed` after 8 attempts | `::test_eight_failed_attempts_back_off_exponentially_and_then_the_delivery_is_failed` | [Retries](../guides/webhooks.md#retries) |
| Every attempt logged | `::test_every_attempt_has_its_own_row_with_the_status_code_and_a_later_time`, `::test_a_timeout_attempt_is_recorded_with_its_error_and_no_status`, `webhooks/test_api.py::test_the_delivery_detail_lists_every_attempt_in_order` | [The delivery log](../guides/webhooks.md#the-delivery-log-and-the-success-rate) |
| Allowlist at creation | `webhooks/test_targets.py::test_allowed_targets`, `::test_everything_else_is_rejected`, `::test_an_empty_allowlist_rejects_everything`, `webhooks/test_api.py::test_a_target_off_the_allowlist_is_422_and_nothing_is_stored`, `::test_the_allowlist_comes_from_the_environment` | [Subscribe](../guides/webhooks.md#subscribe) (target allowlist paragraph) |
| Allowlist at send time | `webhooks/test_sender.py::test_a_host_no_longer_allowed_is_failed_at_send_time_without_a_request`, `::test_the_allowlist_at_send_time_comes_from_the_settings` | the same paragraph |
| Duplicates | one delivery per event and subscription: `webhooks/test_fan_out.py::test_a_duplicate_stream_entry_produces_one_delivery`, `::test_a_crash_after_the_commit_but_before_the_ack_is_harmless_on_redelivery`, `::test_a_crash_before_the_commit_loses_nothing`; the subscriber's side is documented | [Duplicates](../guides/webhooks.md#duplicates) |
| Signature verification | `webhooks/test_signing.py` (8 tests), `webhooks/test_verify_snippet.py`, `test_sdk_signature_agreement.py::test_the_sdk_and_relay_agree` | [Verify the signature](../guides/webhooks.md#verify-the-signature) |

These ran at the REL-39 and REL-41 merges (api CHECK=PASS, 995 passed); the final check of this review is at the end of this file. The full api suite is the proof for the tests above, not an individual rerun of each.

Live retry sequence (sink `fail_next` set to 3 before one payment, with a subscription on `payment.final` only so that exactly one delivery is in flight, as the REL-39 lesson requires): `GET /webhooks/deliveries/123` returned `status: delivered`, `attempt: 4` and attempts

| Attempt | Status code | Gap from the previous attempt |
|---|---|---|
| 1 | 503 | |
| 2 | 503 | 2.0 s |
| 3 | 503 | 4.1 s |
| 4 | 200 | 8.4 s |

The gaps follow 2, 4, 8 s (plus the one-second poll of the sender). An earlier attempt with two events in flight (`payment.received` and `payment.final` of one payment, `fail_next` 3) spread the three failures over two deliveries, so one retried twice (gap 2.2 s) and the other three times (2.2 s, then 4.4 s): the failures count per request at the sink, not per delivery. The eight-attempt failure was not run live (it takes about 3 minutes of waits: 2, 4, 8, 16, 32, 60, 60 s); the test above proves it.

### 1.3 First call using only the docs

| Evidence | Result |
|---|---|
| Recorded clean-room run | [quickstart, Clean-room run](../guides/quickstart.md#clean-room-run) (2026-11-05, REL-40): a fresh agent that read only the quickstart cloned the repository, followed the bash steps and got `201 Created` on `POST /payments` 43 s after the clone (Docker build cache warm; the cold build time was not measured). Cited as supporting; not repeated here |
| SDK example from a fresh venv, following `docs/guides/sdk.md` only | `python -m venv` (Python 3.12.10), `pip install ./sdk/python` (11.7 s; installed `relay-sdk 0.1.0` with `httpx 0.28.1`), then with the stack up and `RELAY_API_KEY` set `python sdk/python/examples/create_and_list.py`: exit 0 in 1.9 s; printed `created dba16a65-... (Received), replayed=False`, `final state: Declined on processor A`, the five-event timeline (`payment.received`, `payment.routed initial`, `attempt.authorize_result do_not_honor`, `payment.declined do_not_honor`, `payment.final`) and the five most recent payments. The venv was deleted afterwards |
| Guide tests | `test_docs_export.py` and `test_openapi_schema.py` keep the reference and `openapi.json` in step with the code (drift test); they skip in the api image and run with the repository mounted or in CI (REL-40 lesson) |

## 2. Clean clone

Verdict: Met. Method: `git clone --branch rel-42-phase-3-exit-review-and-phase-4-r <workspace>\.local\relay-wt\rel42 <workspace>\.local\rel42-clean` (commit `a1a7b7d`; the clone has no env file, only the tracked `.env.example`), then with only `RELAY_API_KEY` and `COMPOSE_PROJECT_NAME=rel42clean` in the shell:

- `docker compose up -d --wait --build`: exit 0 in 28 s. This is the warm-cache time: the images were built minutes earlier in the same Docker engine, so layers were reused; it is not a cold-build time. `docker compose ps`: `api`, `explainer`, `frontend`, `incidents`, `postgres`, `publisher`, `redis`, `simulator`, `webhooks` and `worker` all `running healthy`; `migrate` exited 0 (the smoke script confirms it). `prometheus`, `grafana` and `webhook-sink` are profile-only and were not started (default profiles).
- `python scripts/smoke_stack.py`: all 13 checks `PASS`, `SMOKE_STACK=PASS`, exit 0. The script calls plain `docker compose ps`, so it finds the stack through the `COMPOSE_PROJECT_NAME` environment variable (Phase 2 follow-up 6 is still open, see section 7, item 5).
- `docker compose down -v`: exit 0; the clone folder was deleted; no `rel42clean` container or volume is left.

## 3. Hygiene

| Item | Verdict | Evidence |
|---|---|---|
| Project hygiene | Met | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <workspace>\maintenance\test-project-hygiene.ps1 -ProjectRoot <workspace>\.local\relay-wt\rel42` printed `PROJECT_HYGIENE=PASS CHECKED=2` |
| Template validation | see the end of this file | `validate-template-system.ps1 -Mode Managed` |
| No code changes | Met | `git status` before the commit shows only the files listed at the end of this file; `docs/decisions/0016-adaptive-routing-objective-harness-and-algorithm.md` appeared untracked in the worktree at 07:41 while this review ran. It was written by the primary session, is not part of this review and is not committed by it |

## 4. CI minutes (R12)

Verdict: Met against the 1,000-minute trigger (no month has passed it); at the observed pace the trigger is close. Method as in REL-32 and REL-38: `gh run list --repo brendanmair-project/relay --limit 400 --json databaseId,createdAt,event,conclusion,name` returned 153 runs, the earliest 2026-10-26T12:41:33Z and the latest 2026-11-06T02:15:49Z, so the 30-day window holds every run the repository has; `gh run view <id> --json jobs` for each run; a job's duration is `completedAt` minus `startedAt`, rounded up to a whole minute as the billed estimate (minimum 1), skipped jobs counted as zero. Linux runners, multiplier 1. Two other sources were tried and are unusable: `gh api repos/brendanmair-project/relay/actions/runs/<id>/timing` answered, but with `total_ms: 0` for each of the 9 jobs of the sample run (the latest, push on 2026-11-06), so it does not give minutes for this private repository; the billing endpoint answers 404 and needs the `user` scope (`gh auth refresh -s user`), which was not granted. The figures are therefore an estimate from job times.

| Period (UTC dates) | Runs | Jobs run (skipped) | Raw minutes | Billed estimate | Against 1,000 |
|---|---|---|---|---|---|
| 2026-10-26 to 10-31 | 69 | 308 (180) | 184.2 | 402 | 40% |
| 2026-11-01 to 11-04 (the REL-38 window) | 60 | 285 (195) | 234.5 | 419 | |
| 2026-11-05 to 11-06 (Phase 3) | 24 | 116 (81) | 103.7 | 182 | |
| November so far (1 to 6) | 84 | 401 (276) | 338.2 | 601 | 60% after six days |
| All 153 runs | 153 | 709 (456) | 522.4 | 1,003 | |

Details: billed per day 26 Oct 120, 27 Oct 101, 28 Oct 99, 29 Oct 24, 30 Oct 58, 2 Nov 281, 3 Nov 138, 5 Nov 96, 6 Nov 86 (no run on 31 Oct, 1 Nov and 4 Nov). From 5 November, push runs billed 106 and pull-request runs 76. The October figure is 402, not the 406 of the REL-38 review, with 308 jobs against 312: four jobs without usable timestamps now, probably runs whose data has since aged out; the November 1 to 4 figure is identical (419).

Reading: Phase 3 (REL-57, REL-39, REL-40, REL-41, four pull requests merged on 5 November) cost about 182 billed minutes in two days, less than Phase 2's two heaviest days (281 and 138). The four active days of November average about 150 billed minutes. November has 601, so at that pace it passes 1,000 after about three more active days, which is within REL-43 and REL-44. The REL-32 owner decision (tighten path filters if a month passes 1,000) is not yet triggered and nothing was changed; the candidates in the Phase 2 review (skip Semgrep and the secret scan on docs-only pushes, run the dependency audit on lock-file changes and weekly) still apply. The account-wide total for the 2,000 free minutes (R16) is unknown without the billing scope.

## 5. CI green on `main`

`gh run list --branch main --limit 1 --json conclusion --jq '.[0].conclusion'` printed `success`; that run is the push of `a1a7b7d72542f2a1f6a2bb46b6027aeba0e02a5c` on 2026-11-06T02:15:49Z. Note from the Phase 1 review: path filters mean the latest green `main` run may not have run every code job; this commit is a plan and docs change, so the code jobs for Phase 3 are the green runs of PRs #370, #371 and #372.

## 6. ADR statuses

| ADR | Status in the file and in `docs/decisions/README.md` | Phase 3 evidence |
|---|---|---|
| 0001 to 0014 | Accepted (headers of 0007, 0008 and 0012 carry an explanatory suffix; the log shows Accepted) | Unchanged since the Phase 2 review, which checked each one. Phase 3 evidence only adds: ADR-0003 (the webhook consumer reads `payment_events`; 0 unpublished events at the end of the live runs, delivery bookkeeping per `webhooks/test_fan_out.py`), ADR-0011 (clean-clone start with only `RELAY_API_KEY`, section 2) and ADR-0012 (hygiene and exact pins, section 3, with the sink and sdk services pinned) |
| 0015 webhook delivery, signing and target allowlist | Accepted | Yes, implemented by REL-39 to REL-41: its own `webhooks` container and consumer group (group `webhooks` at lag 0, 0 pending, `entries-read` 416), signed `Relay-Signature` and `Relay-Event-Id` verified by the sink (120 of 120), at most 8 attempts with 2 s doubling backoff capped at 60 s (live gaps 2.0, 4.1, 8.4 s), the host allowlist at creation and at send time (tests above), secret returned once (`webhooks/test_api.py::test_the_secret_is_returned_only_by_the_create_response`). The SDK implements the same algorithm and a test pins them together |

All 15 ADRs have status Accepted in their files and in the log at the reviewed commit. ADR-0016 (adaptive routing objective, harness and algorithm) was added as an untracked file by the primary during this review (`Status: Accepted`, 2026-11-06); it is not in the log at the reviewed commit and is outside this review.

## 7. Follow-ups found (none fixed here)

Each has a proposed disposition: **A** fix now in a small task before Phase 4, **B** fix in Phase 4, **C** accept and keep documented.

1. **`GET /analytics?since=garbage` answers 200 (carried from REL-40).** Live: `curl "http://127.0.0.1:8000/analytics?since=garbage"` returned 200 with the default window (`from` 24 hours before `to`, `to` now), the same body as `GET /analytics`. Cause, from `api/app/analytics/router.py` (`get_analytics`): the endpoint declares only `from`, `to` and `processor`; FastAPI ignores query parameters that a handler does not declare, so `since` is never parsed. The checks that exist do work: `?from=garbage` and `?to=garbage` answer 422 `validation_failed` (`datetime_from_date_parsing`), and `GET /webhooks/deliveries/summary?since=garbage` answers 422. The real defect is the mismatch of names: the analytics window is `from` and `to`, the delivery summary window is `since` and `until`, so a caller who uses `since` on analytics silently gets 24 hours instead of what they meant. Proposed disposition: **C** with a note in the API reference that unknown query parameters are ignored, or **A** if the owner wants strictness: reject undeclared parameters (a 422 for every route changes the documented contract) or accept `since` and `until` as aliases. Recommendation: C plus the guide note; it does not block Phase 4.
2. **`signing.verify` raises `TypeError` on a non-ASCII `v1` (carried from REL-41).** Shown with a one-line Python call in the api image: `python -c "from app.webhooks.signing import verify; print(verify('s','t=1,v1=é',b'x',300,now=1))"` ends in `TypeError: comparing strings with non-ASCII characters is not supported` (from `hmac.compare_digest(expected, candidate)` in `api/app/webhooks/signing.py`, which compares two `str`). The same call with `v1=abc` returns `False`. The timestamp check comes first, so the error needs a timestamp inside the tolerance: with a stale `t` the function returns `False` before it compares. Callers today: only `api/app/webhooks/sink.py` line 59 (the demo sink), plus tests; Relay's own sender uses `sign`, not `verify`, and the SDK has its own `verify_signature` that encodes the candidate to bytes first (`sdk/python/src/relay_sdk/webhooks.py`), so a subscriber using the SDK is not affected. Live effect on the demo sink: `POST http://127.0.0.1:8200/hook` with `Relay-Signature: t=<now>,v1=é` answered `500 Internal Server Error` (a verifier should answer a non-2xx for a bad signature anyway, so the sink status is wrong in kind, not in outcome). Proposed disposition: **A**, as a one-line fix (compare `expected.encode()` with `candidate.encode()`, as the SDK does) with a test in `webhooks/test_signing.py` and in the agreement test; it is small enough to ride along with the first Phase 4 task, but it is the only carried finding that is a clear bug.
3. **The delivery log cannot be read past 100 rows.** `GET /webhooks/deliveries` takes `limit` 1 to 100 (`limit=500` is a 422) and has no cursor, offset or window, so after a run of more than 100 deliveries the log shows the newest 100 only; the 120-delivery run could only be reconciled through the database and the summary. The guide says "filtered by `subscription_id` and `status`" and does not mention the cap. Proposed disposition: **B** (a `before` id or `since` filter), or **C** with a sentence in the guide and the API reference that the list is the newest 100.
4. **The demo scenario never fails a payment at the documented demo size.** The `processor-a-outage` outage covers payments 100 to 199, so the guide's `--count 20` and the exit review's `--count 60` produce only `payment.received`, `payment.authorized`, `payment.captured`, `payment.declined` and `payment.final`. A reader cannot see `payment.failed`, retry or failover events arrive by webhook without `--count 300`. Proposed disposition: **C**, with a sentence in the webhooks guide (try `--count 300 --rate 10` to cross the outage window), or **B** with a smaller scenario for demos.
5. **`scripts/smoke_stack.py` still checks only six services and `migrate`** (Phase 2 follow-up 6, unchanged): `publisher`, `explainer`, `incidents` and now `webhooks` health are not asserted by the script, and it follows the compose project only through `COMPOSE_PROJECT_NAME`. This review confirmed all ten from `docker compose ps --wait`. Proposed disposition: **B**, one small test-and-script change, best made before Phase 4 adds services.
6. **Deactivated subscriptions stay in `GET /webhooks/subscriptions` forever** (the list still showed my mistaken, deactivated subscription with `active: false`; no endpoint removes it). Harmless; **C**.
7. **No live evidence for the eighth failed attempt.** The `failed` terminal state rests on the test only; a live run needs about 3 minutes of waits. Not a defect; **C** unless the owner wants the live proof.

## 8. Risks reassessed with Phase 3 evidence

Updated in [`../delivery/risk-register.md`](../delivery/risk-register.md) (status, notes and date):

| Row | Finding |
|---|---|
| R1 | Re-checked: the webhook consumer was built on `payment_events` (paged by id, money joined from `payments` where a message needs it) with no schema change to the events; 120 of 120 matching events delivered once. Text updated; stays Mitigated |
| R3 | No hosted API appeared in Phase 3; the SDK adds only `httpx` (BSD-3-Clause). Text extended; stays Mitigated |
| R5 | Four consumer groups now (`processing`, `explanations`, `incidents`, `webhooks`), each at lag 0 and 0 pending with 416 entries read after the 60-payment run; Valkey 1.18 MB, `maxmemory` unset, below the trim. A peak backlog is still not sampled by this review, but REL-57 added the lag and pending gauges. Stays Low, "Open (monitor)", re-evaluated at Phase 3 exit as the register promised: no reason to swap the broker |
| R7 | Clean-clone start verified again (section 2): ten services healthy, smoke 13 of 13. Text updated with the date |
| R8 | Still one scenario; Phase 3 found that the demo size never reaches the outage (follow-up 4). Text updated; stays Open |
| R9, R10, R11, R14, R15, R17, R18 | No change in kind. R15: the sink and sdk services pass hygiene with exact pins (`PROJECT_HYGIENE=PASS CHECKED=2`). R17: the webhook endpoints require the key (`webhooks/test_api.py::test_every_webhook_endpoint_requires_the_api_key`) and the sink is loopback-only (`test_compose_webhooks.py::test_the_sink_is_profile_only_supervised_and_loopback_only`) |
| R12 | Updated with the November figures (section 4): 601 billed after six days, projected to pass 1,000 within about three more active days; the trigger has not fired. Owner decision still stands |
| R16 | Relay total from 2026-10-26 to 2026-11-06 about 1,003 billed minutes (section 4); account total unknown |
| New risk | R19 added: the webhook target allowlist and signature verification are only as safe as their callers (a `TypeError` in `verify` and no paging of the delivery log); small, with the dispositions in section 7 |

## 9. Open questions for the owner

1. CI minutes: November is at 601 of 1,000 billed after six days, and about 150 per active day. Tighten the path filters now (which candidate), or wait for the trigger as decided at REL-32? Phase 4 has two large tasks (the harness and the algorithm).
2. Follow-up 2 (`verify` `TypeError`): fix with the first Phase 4 task, in a separate small task, or accept for the demo sink only?
3. Follow-up 1 (`since` on analytics): accept and document that unknown query parameters are ignored, or make the analytics window accept `since` and `until` as the delivery summary does, or reject unknown parameters?
4. Follow-up 3 (delivery log cap of 100): document it or add paging in Phase 4?
5. Should the eighth-attempt `failed` state be shown live once (3 minutes) before Phase 3 is closed, or is the test enough?

## Owner review

Owner review (2026-11-06): approved. Phase 3 is complete and Phase 4 starts after the follow-up task. Answers to the open questions:

1. CI minutes: the primary batches each task's documentation commits into one push from now on. A push that changes only documentation and Markdown will run just the secret scan; pull requests still run every job, and the scheduled audit stays. The CI change is part of REL-58.
2. Follow-up 2 (`verify` `TypeError`): fixed with a test in a small task, REL-58, before Phase 4.
3. Follow-up 1 (`since` on analytics): accepted; the guides note that analytics uses `from` and `to` while the delivery summary uses `since` and `until`, and that unknown query parameters are ignored (REL-58).
4. Follow-up 3 (delivery log cap of 100): paging is added in REL-58. The smoke test also covers every long-running service there.
5. The eighth-attempt `failed` state: the test is enough.

The latency guardrail margin in ADR-0016 is confirmed at 10%. The Phase 4 plan review is in the workspace (`evaluations/relay-plan-review-2026-11-06-phase4.md`).
