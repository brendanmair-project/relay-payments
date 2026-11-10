# ADR-0012: Phase 1 review decisions: reproducible paired runs, open-source event store, isolated explanations, UI route access and reporting

Template: claude/decision@1

Status: Accepted (by the owner, 2026-10-09, after the full project review)  
Decision owner: Brendan  
Date: 2026-10-09  
Supersedes: None (amends ADR-0001, ADR-0009 and ADR-0011 as stated below)  
Superseded by: None

## Context and forces

The full project review of 2026-10-09 (workspace `evaluations/relay-project-review-2026-10-09.md`) found choices that change the schema, the API, the stack or the reported results. The owner accepted the recommended option for each on 2026-10-09. No payment code exists yet (REL-14 has not started), so each change costs a document edit now instead of a migration later.

- Constraint: free and open source only (`docs/architecture/constraints.md`); results must be reproducible within the tolerance ADR-0009 sets; the browser never holds the API key.
- Quality attribute: results a reviewer can reproduce and trust; payment processing that never waits on the model; nothing in the stack reachable from other web pages.
- Evidence: (1) simulator draws are keyed on the payment id, a random UUID created by the api, so runs never repeat and the baseline and Relay runs compare different draws; with 10,000 payments per run, revenue recovered would agree within 1% across three runs only about 5% of the time; (2) `redis:7` resolves to Redis 7.4.11, licensed only under RSALv2 or SSPLv1 (`LICENSE.txt` at tag 7.4.11), which is not open source; (3) compose has no restart policy, and the explanation consumer shares the worker with payment processing; (4) the frontend server routes add the API key for any caller that reaches 127.0.0.1:3000, including other web pages; (5) `GET .../explanation?regenerate=true` writes data; (6) time to explanation gets better when the model fails, because the rules fallback answers in milliseconds.

## Decision

We will apply the following, because each makes Phase 1 reproducible, open source and safe before the code that depends on it is written:

1. **Payment reference and paired draws (amends ADR-0009 item 6).** `POST /payments` accepts an optional `reference` (1 to 64 characters: letters, digits, `-`, `_` and `.`), stored on the payment, returned with it and included in the request hash. The worker sends it to the processors. The simulator seeds every draw on the reference when one is present, otherwise on the payment id; the processor idempotency key stays `<payment_id>:<attempt_no>`. The load generator gives every scenario payment a deterministic reference (`<scenario>-<seed>-<index>`). Runs with one seed then draw the same outcome for the same scenario payment, and REL-30 compares the baseline and Relay payment by payment. References are not unique: two payments with one reference share their draws, which is harmless and documented. The tolerance of 1 percentage point on success rate and 1% on revenue recovered stays; the remaining variation comes only from timing (the health window and worker scheduling).
2. **Open-source event store and exact image pins (amends ADR-0001 and ADR-0011 item 2).** Valkey 9.1.2 (BSD-3-Clause; the Linux Foundation fork of Redis 7.2) replaces Redis as the stream server. It speaks the same protocol, including Streams, consumer groups and `XAUTOCLAIM`, so redis-py stays the client; the compose service keeps the name `redis` and the variables keep `REDIS_URL` and `TEST_REDIS_URL`, so no code changes. Its data lives in a new volume, `valkeydata`, because Valkey cannot read data written by Redis 7.4. Every container image is pinned to an exact version: `postgres:16.15`, `valkey/valkey:9.1.2`, `python:3.12.15-slim` and `node:24.21.0-slim`, and `ollama/ollama:0.40.0` for the optional `llm` profile; CI service images use the same pins. The licence is checked again at the new version whenever a pin changes, and the workspace check `maintenance/test-project-hygiene.ps1` rejects floating tags.
3. **Isolated explanations and restarting services.** Explanations run in their own `explainer` container (the api image, `python -m app.explainer`, consumer group `explanations`), so model calls never share a process with payment processing; the `worker` keeps the processing consumer and the sweeper. Every long-running service (api, worker, explainer, publisher, simulator, frontend) has `restart: unless-stopped`, and each process exits non-zero on an unrecoverable error so Docker restarts it. A test proves that payments still finalize on time while a fake model hangs.
4. **Frontend server-route access rule.** The Next.js server routes answer only requests whose `Host` is `localhost` or `127.0.0.1` (any port), which blocks DNS rebinding. The state-changing route (the demo outage switch, `POST /api/demo/outage`) also requires a same-origin request (`Sec-Fetch-Site: same-origin`, or an `Origin` equal to the app's own origin) and rejects every other request with 403, which blocks cross-site requests; reads stay GET. A public demo (REL-46) runs in a read-only mode: no outage switch, no regeneration and a rate limit, with its own authentication decided in its hosting ADR.
5. **Regeneration through POST.** `POST /payments/{id}/explanation/regenerate` generates, stores (`trigger=regenerate`) and returns a new explanation. `GET /payments/{id}/explanation` only reads, except that it still fills a missing explanation for a final payment (`trigger=on_request`).
6. **Decided reason values and late results.** Event `reason` values are a closed list per event type ([data-model.md](../architecture/data-model.md)), enforced by a shared enum in code and a CHECK constraint. Every processor result whose attempt or expected state no longer matches is written as `attempt.late_result` with reason `stale_attempt` (the attempt is no longer current) or `after_timeout` (the sweeper already failed the current attempt); no result is ever dropped. A late approval is reported as an orphaned authorization in the explanation.
7. **Reporting rules (amends ADR-0009 items 3 and 5 for reporting).** Time to explanation is reported per source (model and rules) with the fallback rate and the explanation backlog, measured after warming the model. Revenue recovered is reported in total and split by how each payment was rescued (`payment.routed` reason `retry` or `failover`). The model quality check (ADR-0011 item 6) also compares each model explanation's stated cause with the rules explainer's cause for the same timeline. The free-text `description` is never sent to the model.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state | No work | REL-30 cannot meet its tolerance; Redis 7.4 is not open source; model calls can delay payments; any web page can trigger the outage switch | The review showed each one fails |
| Confidence intervals instead of a payment reference | No API or schema change | Revenue recovered needs about 600,000 payments per run to agree within 1% | Exact, paired runs are cheaper and stronger evidence |
| Redis 8 under its AGPLv3 option | Keeps the Redis name | Copyleft; the licence choice must be re-checked on every update | The permissive fork fits the open-source rule with less to track |
| Explanations in a thread of the worker | One container fewer | Shares a process, interpreter lock and failure domain with processing | A separate container isolates failures and is simpler to test |
| A token for the UI's server routes | Stronger than a host check | Needs a login or a secret in the browser | Local only; a public demo decides its own authentication |

## Consequences

### Positive

- REL-30's results repeat per payment, and the baseline comparison is paired.
- The whole stack is open source at the versions actually run, and builds no longer drift.
- Payment processing never waits on the model, and crashed services come back on their own.
- No other web page can drive the demo or read payments through the UI.

### Negative and tradeoffs

- One more container (`explainer`) and one more optional field (`reference`).
- Image versions need a deliberate update pass, with a licence check each time.

### Follow-on work

- `api-contract.md`, `data-model.md`, `containers.md`, `payment-lifecycle.md`, `metrics.md`, `constraints.md` and `docker-compose.yml` are updated with this ADR.
- Plan: new task REL-54 (simulator draws on the reference) and updated requirements in REL-14, REL-15, REL-17, REL-18, REL-21 to REL-30, REL-46, REL-48, REL-50 and REL-51, synced to issues.
- REL-13: CI service images use the pinned versions.

## Validation and review

- Validate with: three seeded REL-30 runs within the tolerance plus a per-reference paired comparison; `maintenance/test-project-hygiene.ps1` passing for Relay; a REL-25 test with a hanging fake model; REL-29 tests that reject a foreign `Host` and a cross-site POST to the outage switch; REL-15's CHECK rejecting an unknown reason.
- Revisit when: an image version changes (check its licence), a public demo is hosted, or a third processor is added.
- Reversal/migration cost: Low before REL-14; the reference column and the explainer container are additive.
