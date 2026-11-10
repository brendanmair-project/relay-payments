# Relay - Process log

Template: claude/process-log@1

## Status

Phases 1 to 4 complete; Phase 4 closes with its exit criterion not met after two pre-registered attempts (owner decision 2026-11-09; `docs/evaluation/phase-4-exit-review.md`); approved by the owner on 2026-11-09; next is REL-46 (release, owner). The retrospective is the last section of this file. See `next.md`.

## How to use this

Chronological log of every documentation step taken on this project so far. Kept for two reasons: (1) so the reasoning behind each doc's current state can be checked for correctness, and (2) so the project's process is presentable/demonstrable on its own, not just its output. Add one entry per working session, newest last, under Sessions. File changes go in `CHANGELOG.md`; current state goes in `HANDOFF.md`.

## Sessions

### Session 1 — Foundation created

**Scope:** Project management and engineering foundation only. No application code, dependencies, database, API, or frontend, per explicit instruction.

Created:
- `docs/product/vision.md` — product concept, problem statement (flagged as unvalidated assumption), non-goals
- `docs/product/strategy.md` — strategic principles (local-first, synthetic-before-real, observable-by-construction, sequenced complexity, no-paid-deps-without-approval)
- `docs/product/personas.md` — five candidate personas (Dana/Ops Analyst, Priya/Platform Engineer, Sam/Integrating Developer, Marcus/Incident Responder, speculative Risk/Compliance persona), all flagged unconfirmed
- `docs/product/jobs-to-be-done.md` — nine candidate JTBDs derived from the feature list
- `docs/product/metrics.md` — five metric categories, north star explicitly left undefined pending positioning
- `docs/product/roadmap.md` — eight phases sequenced by technical dependency, no dates/estimates
- `docs/product/backlog.md` — Epic 0 (this work) plus seed Epics 1–2 for Phase 1, with explicit "not included yet" list
- `docs/architecture/system-context.md` — external actors, coarse system boundary diagram, data-flow assumption flagged open
- `docs/architecture/constraints.md` — hard constraints from the brief (FOSS-only, local-dev-canonical, fixed stack) plus flagged undecided items (observability, event backbone, auth, AI provider)
- `AGENTS.md` — operating rules for engineers/agents: don't silently invent decisions, FOSS-only, local-first, respect sequencing
- `README.md` — project overview and navigation

**Approach:** Followed the brief's instruction to identify assumptions and open questions rather than inventing answers. Every ambiguous area (audience/positioning, AI provider, event architecture model, auth, observability stack, routing semantics) was surfaced explicitly rather than resolved.

**Delivered:** file list, assumptions, open product questions, open architecture questions, proposed first epic, pre-implementation risks — per the requested completion format.

---

### Session 2 — Review and hardening pass

**Trigger:** User asked "is there anyway to improve this."

**Gaps identified during self-review:**
1. No ADR mechanism to record decisions once open questions get resolved.
2. No glossary — overloaded terms (transaction, event, routing) risked drifting in meaning across docs.
3. No phase-level Definition of Done — roadmap was ordered but not exit-testable.
4. Open questions were phrased as pure questions with no recommended position to react to.
5. Personas and JTBDs weren't cross-referenced.
6. Backlog items lacked acceptance criteria — closer to a topic list than groomable stories.
7. Risks only existed in a one-time completion summary, not a living document.
8. Missing basic repo hygiene (`.gitignore`, license status).

User confirmed: "Yes add these and heavily review to ensure nothing is missing."

**Added:**
- `docs/decisions/README.md` + `0000-adr-template.md` — ADR index and template
- `docs/product/glossary.md` — ten core terms defined, with notes on where a term's meaning is still an open architecture question
- `docs/delivery/risk-register.md` — eight risks (R1–R8) with likelihood/impact/status/mitigation, explicitly framed as a living document
- Exit criteria added to every phase in `docs/product/roadmap.md`
- **Proposed defaults**, each explicitly marked "pending approval" and tied to an ADR requirement, for: event-sourcing model, observability stack, event backbone, AI provider, routing-path semantics, north star metric, synthetic-generator API boundary
- Persona tags added to every JTBD in `docs/product/jobs-to-be-done.md`, plus a flagged persona-coverage gap
- Acceptance criteria added to every Epic 1/2 backlog story in `docs/product/backlog.md`
- `.gitignore` (foundation-phase stub) and `LICENSE.md` (explicitly flagged as an open decision, not silently chosen)
- Updated `AGENTS.md` and `README.md` to reference all new files so nothing is orphaned

**Explicitly not added (flagged as optional, lower priority):** `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.env.example` — judged premature before positioning/visibility and Phase 1 tooling exist.

---

### Session 3 — Packaging and task visualization

**Trigger:** User asked for a zip package, every step documented under tasks, and a Jira-like task board for presentability.

**Added:**
- Ticket IDs (`REL-1` … `REL-27`) added to every item in `docs/product/backlog.md` for traceability
- `docs/task-board.md` — canonical Done / In Progress / To Do / Blocked board in table form, declared the source of truth over the visual board
- `docs/board.html` (also published as a standalone artifact) — a Jira-style visual Kanban board rendering the same data as `task-board.md`
- This changelog (`CHANGELOG.md`) — a chronological record of every step across all three sessions, for correctness review and for presenting the project's process
- Full project bundled into a single zip archive for download/sharing

**Note on correctness:** The task board's card counts and ticket IDs are generated to match `docs/task-board.md` exactly. If the two ever disagree, `task-board.md` is authoritative — see the maintenance note at the bottom of that file.

---

### Session 4 — Portfolio repositioning and revision

**Trigger:** The owner (Brendan) decided Relay is a portfolio project that solves a concrete business problem, and asked for the foundation to be revised accordingly. This file was previously `CHANGELOG.md`; it is now the process log.

**Decisions applied (recorded as ADRs 0001-0006 in `docs/decisions/`):**
- Positioning: a portfolio project on synthetic data only, solving multi-processor payment failure. Domain term "transaction" renamed to "payment"; single merchant with one static API key; two simulated processors.
- Scope: the 8-phase roadmap replaced by Phase 0 Foundation, Phase 1 Showcase slice, Phase 2 Operations depth, Phase 3 Integrations, Phase 4 Optimization, each with exit criteria.
- Event history: PostgreSQL is the source of truth, with an append-only `payment_events` table written in the same database transaction (transactional outbox) and a relay process publishing to Redis Streams.
- Payment fundamentals: idempotency keys, integer minor-unit money, and a payment state machine in `docs/architecture/payment-lifecycle.md`.
- Single task list: GitHub Issues. `docs/task-board.md` and `docs/board.html` deleted; `docs/product/backlog.md` rewritten as the issue seed list starting at REL-10.
- Lighter approvals: the owner is the sole decision-maker; "PM approval" replaced by an owner decision recorded as an Accepted ADR.
- Public readiness: MIT `LICENSE` added, `.gitignore` moved to the repository root, personal-history sentence removed from `docs/product/strategy.md`.

**Changed:** all `docs/product/` docs, glossary, risk register, constraints, system context, ADR index, `AGENTS.md`, `CLAUDE.md`, `README.md`, `HANDOFF.md`.

**Removed:** `docs/_import/` (originals merged), `docs/task-board.md`, `docs/board.html`, `LICENSE.md`, `0000-adr-template.md` (ADRs now follow the workspace template `templates/decisions/ADR.template.md`).

---

### Session 5 — Plan review: 25 gaps fixed (2026-09-30)

**Trigger:** The owner asked for a review of the whole project for missing steps, then for every gap to be fixed and the task list checked again.

**Gaps found and how they were fixed:**
- Processing correctness (A1-A9): stalled `received` payments, late processor answers applied to the retry, no attempt tracking, `failed` meaning both retrying and finished, worker trigger unspecified, processor calls not idempotent, concurrent idempotency race, router health in one process's memory, unbounded stream. Fixed by ADR-0008 (Proposed; owner acceptance gated in REL-53), the rewritten `payment-lifecycle.md` and requirements in REL-14 to REL-22, REL-48 and REL-50.
- Environment and tooling (B1-B8): no migrate step, tests sharing the dev database, no frontend host setup, Ollama host/container clash, the Stop hook blocking the failing-test stage and Docker-down turns, no merge gate on the free private plan, the plan generator unable to update existing issues, the smoke test in the wrong place. Fixed in REL-12, REL-13, REL-25, REL-29, REL-48 and REL-49; the verify hook now skips for `.claude/tdd-red` and a stopped Docker; the workspace generator gained `-UpdateIssues`.
- Owner decisions (C1-C6): recorded as ADR-0009 (Accepted): currencies USD, EUR, GBP, JPY; API key on every endpoint with UI server routes; explanations stored at final failure; 2-hour manual baseline; static baseline without retry; reproducibility within a stated tolerance. `docs/product/metrics.md` updated.
- Document inconsistencies (D1-D6): generator access to the simulator control API, error shape in OpenAPI rather than a Phase 3 reference, the missing Phase 1 design documents (new task REL-53), failed-capture explanations, README wording.

**Found while re-checking the task list:** frontend component tests had no runner or check (added the `web-test` check and Vitest in ADR-0007 and REL-13); the metrics, demo and experiment code sat outside every check (moved to `api/app/reporting/`, `simulator/demo/` and `api/app/experiments/`); the SDK check could not reach `sdk/` (compose `sdk` profile); no accessibility or API-key-exposure check (REL-29); no database reset between demo runs (REL-30); the model licence may not be open source (risk R13, REL-25); history emails before going public (REL-46).

**Changed:** ADR-0008 and ADR-0009 (new), ADR index, `payment-lifecycle.md`, `system-context.md`, `constraints.md`, glossary, risk register (R11-R13), `docs/product/metrics.md`, `README.md`, `AGENTS.md`, `.gitignore`, `.claude/hooks/verify.ps1`, and the generated `docs/delivery/delivery-plan.md` (44 tasks, 241 steps).

### Session 6 — Board, standard layout and working docs (2026-09-30)

- Goal: verify Docker, make the board interactive, give every project the same layout and generated working docs.
- Decisions: tasks keep one source (`shared/tasks/relay.json`); `next.md`, task files, workflow and definition of done are generated from it (user decision); docs moved into `docs/{product,architecture,decisions,delivery,workflow}`.
- Surprises and lessons: closing GitHub issues from Claude was blocked by the auto-mode classifier, so the owner closes REL-10; a full-screen overlay hidden only by the claude.ai wrapper blocked clicks in a plain browser.

### Session 7 — Owner decisions and local model (2026-10-01)

- Goal: apply the owner's acceptance of every plan-review recommendation.
- Decisions: ADR-0010 picks `granite3.3:2b` (Apache 2.0) for explanations; REL-10 closed on GitHub after Docker and Ollama were verified.
- Surprises and lessons: the Ollama page for one candidate did not show its licence, so only models with a verified licence were considered.

### Session 8 — REL-53 Phase 1 design (2026-10-01)

- Goal: write the container diagram, API contract and data model, and record the owner's acceptance of ADR-0008.
- Decisions: ADR-0008 Accepted by the owner; keyset pagination; one error shape; idempotency keys claimed with a lease token so a stalled request can never complete a key another request took over; the sweeper re-drives at most once per threshold (`last_driven_at`); processor health counts routed attempts and technical failures, never declines; the API 5xx rate comes from a request-log file on a volume (REL-51 and REL-52 plan wording updated).
- Surprises and lessons: an independent review found 12 gaps, three of which would have produced wrong code (two payments for one key after a lease takeover, a status CHECK rejecting every new payment, a re-drive on every sweep); a second review confirmed the fixes and found three follow-ups, also fixed. Review design documents against the tasks that implement them, not only against the ADRs.

### Session 9 — Plan review before Phase 1 code, and REL-12 skeleton (2026-10-01)

- Goal: run plan-review before the first code task, then build the stack skeleton.
- Decisions: ADR-0011 (owner): clean-clone setup with a placeholder key and a compose guard, exact versions, runtime libraries added to the stack, sweeper grace period, routing rule, model quality check, host-port overrides. The review's 26 plan fixes align REL-12 to REL-52 with the design.
- Surprises and lessons: pytest needs `pythonpath` and no cache in a read-only non-root image; Starlette now warns that `httpx` should become `httpx2` for its test client (kept `httpx` per ADR-0011; revisit in ADR-0007); `docker compose up --wait` handles the one-shot migrate service correctly; the smoke test reads health through `docker compose ps` because Postgres and Redis are not published.

### Session 10 — REL-49 ADR-0007 tooling and CI scope (2026-10-01)

- Goal: approve the tools the planned checks need and define CI scope.
- Decisions: ADR-0007 Accepted by the owner; licences and versions checked on npm and PyPI; GitHub Free includes 2,000 Actions minutes per month shared by all private repositories, so e2e runs on pull requests only and audits weekly.
- Surprises and lessons: the minute allowance is per account, not per repository; axe-core is MPL-2.0 (fine as an unmodified test tool).

### Session 11 — REL-13 CI pipeline and local gate (2026-10-01)

- Goal: wire the ADR-0007 tools into a fast local suite and GitHub Actions.
- Decisions: ESLint pinned to 9.39.5 (ADR-0007 amendment: `eslint-plugin-react` from `eslint-config-next` 16.3.8 breaks on ESLint 10); a 90% coverage gate on the domain and idempotency modules once they exist; REL-17 owns `api/app/idempotency/`; compose images named `relay/<service>:dev` so the CI bake cache and `docker compose up` share them.
- Surprises and lessons: from Git Bash, `cmd.exe /c` and `-v ...:/repo` are rewritten into Windows paths (use `//c` or `MSYS_NO_PATHCONV=1`); the real Stop hook runs through PowerShell and is unaffected. The local suite must rebuild images (`run --build`) or it tests stale code. npm 11 blocks install scripts by default (`unrs-resolver`), and lint works without it.

- 2026-10-26 follow-up: the first CI run (PR #309) passed every job except the dependency audit, which found a critical Next.js 16.3.8 advisory (GHSA-2464-fhr4-w9xw). The owner chose to upgrade inside REL-13: Next.js and `eslint-config-next` to 16.4.3 (ADR-0011 and ADR-0007 amended), `npm audit fix` for the transitive packages. Lesson: the audit job found something real the first time it ran; a pin accepted in an ADR goes stale, so re-run `npm audit` before a task that touches the lock file.

### Session 12 — REL-19 simulated processors (2026-10-01)

- Goal: build Processors A and B while REL-13 waits for the owner's `workflow` token scope (REL-19 depends only on REL-12).
- Decisions: outcomes are SHA-256 draws over seed, processor, payment, attempt and operation, so order never matters; an optional `capture_failure_rate` (default 0) makes the contract's `failed` capture reachable; an outage hides stored results; a timeout answers 504 only after the worker's timeout and a repeated key times out again; capture needs an approved authorize on the same processor and key (409 `not_authorized`); answered latency is capped below the worker timeout.
- Surprises and lessons: an independent review found no high issues; its notes for later tasks: REL-21 cannot get a late success for a timed-out key from the simulator (test the late-answer path with a fake processor), and REL-30's three-run check must set the same profiles each run because a simulator restart resets them. REL-19 brings REL-13's simulator tooling unchanged so the REL-13 rebase stays small.

### Session 13 — Full project review and ADR-0012 (2026-10-09 to 2026-10-11)

- Goal: review the whole project (plan, design, code, CI branch, repository state) for gaps, then apply every finding with the owner's approval of all recommended options. Findings and evidence: workspace `evaluations/relay-project-review-2026-10-09.md`.
- Decisions: ADR-0012 Accepted by the owner: a payment `reference` seeds the simulator's draws so demo runs repeat and the baseline is compared payment by payment; Valkey 9.1.2 replaces Redis because Redis 7.4 is licensed RSALv2/SSPLv1 (not open source); every image pinned exactly; explanations in their own `explainer` container; restart policies; frontend routes answer only localhost hosts and the outage switch only same-origin POSTs; regeneration through POST; decided reason values; late results never dropped; reporting per explanation source and per rescue path. Plan: REL-27, REL-47 and REL-50 now feed the Phase 1 exit (they had no dependents), new task REL-54, lint checks on every task, `phase_exits` declared.
- Surprises and lessons: (1) seeding draws on the api's random payment ids made runs unrepeatable: revenue recovered would vary about 2.4% between 10,000-payment runs against a 1% tolerance; (2) the floating `redis:7` tag had silently moved to a non-open-source licence; (3) three tasks had no dependents, so the exit review could finish without them, and three other projects had the same defect in their CI task; the workspace plan generator now rejects such plans (`phase_exits`). Valkey cannot read Redis 7.4 data, so it uses a new volume; the shell guard blocks any command whose text mentions `.env`, so compose edits went through the file editor.

### Session 14 — REL-13 merged, plan review, REL-52, REL-14 and REL-54 (2026-10-26)

- Goal: merge the review (#308) and CI (#309), make audits catch advisories against unchanged pins, re-run the plan review, then build the three Ready tasks. Plan review: workspace `evaluations/relay-plan-review-2026-10-26.md`.
- Decisions (owner-approved): Next.js 16.4.3 inside REL-13; the audit runs on every pull request and the runner is pinned (#310, ADR-0007 amendment, plan step REL-13.8); task check commands rebuild images (`run --build`) and `ci-green` prints the run conclusion. REL-14's `transition` takes the stored `is_final`, because a `failed` payment on attempt 1 is final from `authorized` and retrying from `routed`; REL-15's `payments.is_final` column supplies it. REL-52 logs unknown routes and pre-routing 401s with path `<unmatched>` and maps non-404 HTTP errors (for example 405) to `malformed_request`.
- Surprises and lessons: (1) the first audit found a critical advisory against an ADR-accepted pin, so an audit gated on lock-file changes misses exactly this case; (2) the worktrees had no local settings file (guard-protected) and host Python is blocked by Windows Application Control, so the task checks ran in the project images with `docker run` on a test network; (3) two workers' first red runs stopped at lint before pytest ran, so red was not observed; the primary ran mutation checks on REL-14 instead (both mutants caught). Sonnet workers built the three tasks in parallel; the primary reviewed each diff and reran each check.
- REL-15 (same day, PR #315): schema, trigger and models. Decisions: `status_changed_at` defaults to `now()`; reason values are one database CHECK and checked per event type in code. Lesson: the trigger mutation checks first passed against a schema left at head by an earlier run, so the schema tests now rebuild from base each session; the explicit DELETE branch of the trigger is redundant (NEW is NULL on DELETE) but kept for its clearer message.
- REL-16 (same day, PR #316): the transition service owns no transaction (the caller commits); companion events follow data-model.md lines 92-98. The concurrency test was proven by removing the row lock (it failed 3 of 3 runs). A first merge attempt was refused by the auto-mode classifier; the owner then asked for it. Merged branches are now removed with the workspace `prune-merged-branches.ps1` (squash merges defeat `git branch -d`).
- REL-17 (PR #318) and REL-20 (PR #317), built in parallel with one Postgres and Valkey per worktree (the db tests rebuild the schema, so a shared database would break the other worker). Decisions: REL-17 validates the body by hand so the 400 header check precedes the 422 body check; REL-20 reads its settings from the environment and publishes ids only. Mutation checks: completing a key without the lease token, and marking before `XADD`, are each caught by a test. Open: a 503 mapping for a database outage on `POST /payments` belongs to the shared error handling. The classifier refused merging #317 until the owner asked.
- REL-18 (PR #319): the cursor keeps microseconds because responses truncate timestamps to milliseconds; invalid query values are 422. Keyset mutations (`<=`, no id tie-breaker) were each caught. Lesson L-060: merges go through only when the owner's latest message asks for them; the owner was asked to add a narrow `gh pr merge` allow rule, which Claude cannot add itself (self-modification is blocked).
- REL-21 (PR #320): the consumer group starts from id `0` so entries published before the first worker are not lost; acks follow the commit; a crash after the route commit leaves the payment for the REL-50 sweeper (no resume logic). Mutations (ack before handling, no late check) were each caught by three tests. The stack smoke proved the whole path for the first time: `POST /payments` to a final state in under 60 s. The owner then authorized the narrow `gh pr merge` allow rule, and #320 merged without a refusal.

### Session 15 — REL-22 router and REL-50 sweeper (2026-10-27)

- Goal: finish the processing path (failover, single retry, recovery of stuck payments). Built in parallel with exclusive files (REL-22: `app/routing/`, the handler, the health route; REL-50: `worker/sweeper.py`, the loop in `worker/__main__.py`) and one shared rule: retries are on unless `ROUTING_STRATEGY=static`. REL-22 merged first (#321); REL-50 was rebased and switched from a private helper to `app.routing.config.retries_enabled` (#322).
- Decisions: `avoided` is strictly above the threshold and needs `HEALTH_MIN_ATTEMPTS`; the retry ignores health and goes to the other processor; the worker acts on state (received -> attempt 1, failed and retrying -> attempt 2), so retry and re-drive triggers both work; the sweeper re-drives before it times out within one pass and locks each candidate with `SKIP LOCKED` plus the due condition.
- Surprises and lessons: REL-22's health and router modules were written before their tests, so they were never seen red; four mutations (threshold `>=`, window removed, both-avoided to B) and two for the sweeper (no grace, no locked re-check) were each caught. The REL-21 tests needed an autouse `ROUTING_STRATEGY=static` fixture, because the default became `rules`.
- REL-23 (#324) and REL-24 (#323) in parallel; mutations (unseeded mix, orphan rule keyed on a decline) were each caught. REL-24 added two patterns beyond the task list: `late_capture_after_timeout` and an `unknown` fallback so the explainer never crashes.
- Owner's tooling review (workspace `policies/plugin-integration-policy.md`, "Preferred tool stack"): the plan gained REL-55 (Semgrep CLI in CI; the Semgrep plugin stays rejected), REL-26.8 (Chrome DevTools MCP next to Playwright), and comparisons in REL-33 (Sentry, PostHog against Prometheus and Grafana) and REL-46 (Vercel or Cloudflare, Neon or Supabase for the demo); Linear, Postman, Composio and Codex are declined.
- REL-55 (#331, 2026-10-28): the baseline scan found 14 `github-actions-mutable-action-tag` findings and nothing in the code; they are suppressed inline because pinning actions to commit SHAs changes ADR-0007's pinning policy (owner decision, open). The rule-set licence was checked at its source (Semgrep Rules License v1.0: internal use only, no distribution or service) and the ADR quotes it; the first draft had paraphrased the workspace template.
- REL-51 (#332): nearest-rank percentiles with integer math; rescue paths `retry`, `failover` and `redrive` (the last also applies to the static baseline); the explanation section reads `payment.explained` events and says "not available yet" until REL-25. The worker hit the session usage limit mid-task and was resumed from its saved state with no rework. A floor-for-ceil mutation was caught by six tests. `reports/` is now git-ignored.
- REL-47 (#338): cleanup keeps an expired key whose lease is still valid (stricter than data-model.md); a "delete two days early" mutation was caught.
- REL-56 (#339, owner decision): actions pinned to commit SHAs read from each action's repository, the REL-55 suppressions removed so Semgrep enforces the pin. First task run with the new workspace scripts `task-start.ps1` and `task-finish.ps1`: start, push, PR, CI, merge, step closes and the changelog worked; the docs step failed on a PowerShell return-value bug (helper output joined the exit code), fixed with a regression test, and the remaining steps were done by hand.

### Session 16 — REL-26 frontend payments list (2026-10-29)

- Goal: the first UI task, done with the new workspace tooling: `task-start.ps1`, a contract from `worker-contract.ps1` with risk notes, `worktree-check.ps1 -Target web` (added for the frontend), and `task-finish.ps1`.
- Decisions: dashboard spec first (`docs/architecture/dashboard-spec.md`); 5 s refresh, Stale after 15 s; status as a bordered text label (Retrying dashed, Failed and Declined thicker) so it never relies on color; amounts through `Intl.NumberFormat` from a BigInt-built decimal string; frontend-only error codes `forbidden_host`, `forbidden_origin` and `dependency_unavailable` (not yet in api-contract.md, add when REL-27 touches it); Chrome DevTools MCP `chrome-devtools-mcp@1.12.0 --isolated --no-usage-statistics`.
- Verification on the running stack (25 payments from `python -m generator --scenario normal-day --seed 7`): desktop 1280 px and a Pixel 7 emulation (Playwright with installed Chrome) show the list, the status bar wraps on the phone and the table scrolls inside its box; headless Chrome logged no console errors; 20 rows rendered. Screenshots kept locally in the workspace `.local/rel26-shots/`.
- Surprises and lessons: (1) the first PR (#340) failed the full-history secret scan on a key-like test constant (`const KEY = "test-key-sentinel-..."`, gitleaks `generic-api-key`); renamed to `SENTINEL` with a plain value and rebuilt as one commit on a fresh branch (#341), because a fix commit would leave the flagged commit in the scanned history; (2) a 390 px desktop Chrome window is wider than it looks (Chrome's minimum window width), so phone checks need device emulation, not a narrow window; (3) parallel workers hit the session usage limit four times; one worker at a time since.

### Session 17 — REL-25 AI explainer (2026-10-30)

- Goal: explanations from the host's Ollama (`granite3.3:2b`) with the REL-24 rules as the fallback, stored at final failure by a separate `explainer` container, plus `GET /payments/{id}/explanation` and `POST .../regenerate`. One sonnet worker on a `worker-contract.ps1` contract with risk notes; PR #342, squash `84168b1`.
- Decisions: model answers are constrained by a JSON schema (cause from the rules' keys, text, integer citations) and still checked: any citation outside the payment's timeline or a bad answer falls back to the rules with `fallback_reason`; an extra reason `model_error` covers HTTP errors and malformed replies; the model call runs with no database transaction open; the prompt states the amount formatted from minor units and never the `description`; ADR-0005 Accepted citing ADR-0010.
- Verification: 633 api tests (written first, seen failing on assertions); quality check on host Ollama 0.40.11 recorded in `docs/evaluation/results.md`: run 1 failed (citations 6/10, one answer said "$1250 USD" for 12.50 USD), run 2 after the fixes passed (citations 10/10, cause match 6/10, wrong amounts 0). Live stack from main: all eight services healthy; 60 generated payments; every declined or failed payment got one model explanation and one `payment.explained` event, none for captured ones; time to explanation 1.6 s on average (max 2.2 s); amounts in the texts match the stored amounts, JPY without decimals.
- Surprises and lessons: (1) the first quality run exposed our own prompt bugs (string citations, a raw minor-unit amount the model read as dollars), not only model weakness: run the real-model check before trusting a fake-model test suite; (2) the model names the first failure, not the final outcome, on retry and failover timelines (risk R18; decide in REL-27 whether to show the rules text when causes disagree); (3) a new consumer group created at id 0 explains the whole stream history on first start, so time-to-explanation figures must be measured per run (REL-30); (4) under a large backlog with a slow model the explainer's 30 s heartbeat can go stale (REL-48).

### Session 18 — REL-48 full local stack (2026-11-01)

- Goal: a clean clone starts healthy with only `RELAY_API_KEY`; per-service environment (ADR-0012), optional `llm` profile, graceful shutdown and the explainer heartbeat under a backlog. One sonnet worker on a `worker-contract.ps1` contract (2026-10-31); the primary resumed its uncommitted result, fixed one format issue and ran the live checks. PR #344, squash `89437e4`.
- Decisions: no `env_file`; each service lists the variables its code reads with the `.env.example` defaults through interpolation; `ollama/ollama:0.40.11` under profile `llm` with no host port; the explainer touches its heartbeat after every entry; a compose contract test (`api/tests/test_compose_stack.py`) keeps the per-service variable list. ADR-0013 (rules text when causes disagree, R18) was committed separately the same day as `64aa24c`.
- Verification: `worktree-check.ps1 -Target api` PASS (639 passed); compose tests with the repo mounted 43 passed; clean clone with no env file: all eight services healthy, `smoke_stack.py` PASS; worker killed with SIGKILL from outside the Docker API restarted (RestartCount 1); worker, publisher and explainer stop with exit 0.
- Surprises and lessons: (1) after a Docker Desktop restart the worktree's isolated Postgres and Valkey containers stay exited and every DB test errors with `failed to resolve host 'postgres'`; `docker start relay-wt-pg-<id> relay-wt-valkey-<id>` fixes it; (2) `docker compose kill` counts as a manual stop, so the restart policy does not fire; crash tests must kill the process from outside the Docker API; (3) `smoke_stack.py` reads the default compose project, so set `COMPOSE_PROJECT_NAME` when using `-p`.

### Session 19 — REL-27 payment detail (2026-11-01)

- Goal: the payment detail page (attempts, timeline, labelled explanation, processor health, empty and error states) and ADR-0013 (rules text when the model's cause disagrees). One sonnet worker on a `worker-contract.ps1` contract; PR #345, squash `871ac2f`.
- Decisions: the cause check compares the model's `cause` with the rules explainer's `pattern`; a missing cause counts as a mismatch; the explanation is requested for Declined, Failed, Retrying or retried payments only; attempts are labelled by their last state event (authorized, captured, declined, failed), not their last event.
- Verification: api CHECK=PASS (642), web CHECK=PASS; Vitest seen failing first; mutation checks kill both changes (the api one by `worktree-check -Mutate`, the web one by a manual revert, since `-Mutate` supports api and sim only); real-model quality run 3: citations 10/10, cause match 7/10, wrong amounts 0; detail page checked on the running stack at 1280 px and on a Pixel 7 emulation.
- Surprises and lessons: (1) the browser check caught what unit tests missed: the worker's fixture events did not match the live API (no `attempt.*`, `retry_scheduled` or `explained` events), so attempts showed `payment.explained`; build component fixtures from a real API response; (2) the worker did not observe the api test failing first; a mutation check stood in for it; (3) `task-finish` cleanup fails with Permission denied when the calling shell's working directory is inside the worktree; leave the worktree before running it.

### Session 20 — REL-28 demo outage control (2026-11-01)

- Goal: start and stop a Processor A outage from the UI without the key reaching the browser. The POST route, same-origin check and host guard already existed from REL-26, so the work was the UI control and a way to read the starting state. One sonnet worker; PR #346, squash `2c73609`.
- Decisions: a read-only `GET /api/demo/state` returns only the outage flags (no simulator profiles); the control shows Unknown and stays disabled until the first read succeeds; on error it keeps the last known state; no new CLI, because the generator's `processor-a-outage` scenario already switches the outage.
- Verification: web CHECK=PASS (102 Vitest); on the running stack through the frontend routes: state false, same-origin POST 200, state true, cross-site POST 403, GET 405, foreign Host 403, key absent from responses; screenshots at 1280 px (active) and Pixel 7 (inactive).
- Surprises and lessons: (1) `worker-contract.ps1` picked `-Target sim` because the task's paths list `simulator/`; for a frontend-only change the target had to be switched to `web` by hand; (2) the worktree's `node_modules` had no `.bin` again, so the worker reran `npm ci`.

### Session 21 — REL-29 Playwright e2e in CI (2026-11-01)

- Goal: end-to-end tests against the compose stack on every pull request: payment detail flow, axe, key exposure, host and same-origin guards. One sonnet worker (allowed to run compose under project `rel29e2e`); PR #347, squash `931bc52`.
- Decisions: deterministic runs by pointing the explainer at an unreachable `OLLAMA_URL` (rules text at once) and setting both processors to decline every payment for the run; one Playwright worker because specs share simulator profiles; npm `overrides` pins `playwright-core` to 1.63.0 because `@axe-core/playwright` 4.13.0 pulls 1.64.1 and the mismatched `Page` types broke `tsc` in the frontend image build; `upload-artifact` pinned to the v7.0.2 commit, looked up by the primary from the release tag.
- Verification: e2e 6 of 6 locally (worker and primary runs); red run by changing the explanation assertion to the model label; web CHECK=PASS (102 Vitest); all 8 PR checks green, the e2e job took 6 min 56 s.
- Surprises and lessons: (1) adding a dev dependency can break the production image build when the tests are inside `tsc`'s scope; build the image locally before pushing; (2) a local e2e run leaves `test-results/`, which `format:check` then flags; ignored in `.prettierignore`.

### Session 22 — plan review and REL-30 outage demo (2026-11-01 to 2026-11-02)

- Goal: one command that compares static routing with Relay routing on the same seeded outage, with reproducible results. Plan review first (workspace `evaluations/relay-plan-review-2026-11-01.md`): the reset and the mode switch moved to an api-image tool and a host script (REL-30.9), and fallbacks are reported per reason (REL-30.10). One sonnet worker over four rounds; PR #350, squash `4c9a5e4`.
- Decisions (owner, 2026-11-01 and 2026-11-02, recorded as REL-30 requirements): the generator drains every sent payment before an outage switch; it waits one health window after the outage ends and measures the recovery lag; the demo runs with `HEALTH_WINDOW_SECONDS=120` (default stays 60 s). Each round fixed one timing dependency: payment 099 racing the switch, recovery routing aging out with wall-clock time, and two payments at the window edge late in the outage.
- Results (seed 7, three runs, every measure identical): success rate 58% static against 89% Relay (+31.0 pp); 93 payments rescued (89 by retry, 4 by failover), none worse; revenue recovered per currency and rescue path; Relay median time to explanation 1033.5 ms with a 0.1 fallback rate (all `cause_mismatch`); recovery lag about 106 s, set mostly by the 120 s window.
- Verification: api CHECK=PASS (650), sim CHECK=PASS (103), tests first in every round; demo exit 0 with REPRODUCIBILITY=PASS; all PR checks green after two fixes (Semgrep flagged the TRUNCATE text, suppressed inline with the reason; CI lints `scripts/` with the simulator's settings, which the local sim check does not).
- Surprises and lessons: (1) a seeded simulation is only reproducible when every time-based mechanism (async processing, health windows) is pinned by the scenario; save routing per reference so a difference can be traced; (2) the local `sim` check does not lint `scripts/`, CI does; (3) `task-finish` could not rerun after failing checks (PR already open); fixed to reuse the open PR, with a lifecycle test; (4) a worker's wait loop watched only for success text and missed a SyntaxError for 40 minutes; watch the process exit.

### Session 23 — REL-31 showcase README (2026-11-02)

- Goal: the README filled with the REL-30 results, an architecture diagram, screenshots and a How to run that works on a clean clone. One sonnet worker; owner reviewed and approved; PR #351, squash `558fca9`.
- Decisions: Mermaid diagram in the README, checked against `docker-compose.yml` and `containers.md`; numbers only from `docs/evaluation/outage-demo/results.json` and `docs/evaluation/results.md` (checked by script by the primary); caveats in a "Read this first" paragraph (synthetic data, static baseline, 2-hour assumption, recovery lag set by the 120 s demo window).
- Verification: clean clone with only `RELAY_API_KEY`: stack healthy, smoke PASS, tests and e2e pass after two README fixes; links resolve; template check 0 errors.
- Surprises and lessons: (1) the clean-clone run found two real gaps the existing docs hid: api pytest needs `TEST_DATABASE_URL` and `TEST_REDIS_URL` without an env file, and the e2e suite expects the rules explainer (unreachable `OLLAMA_URL`, as CI sets); (2) the session could not attach files for the owner's review, so the documents were opened in Chrome instead.

### Session 24 — REL-32 Phase 1 exit review (2026-11-02)

- Goal: close Phase 1 with evidence and refine Phase 2. Split: a sonnet worker gathered the evidence (`docs/evaluation/phase-1-exit-review.md`), the primary ran the full `plan-review` on Phase 2 (workspace `evaluations/relay-plan-review-2026-11-02-phase2.md`). Owner approved; PR #354, squash `e73a34c`.
- Decisions (owner): ADR-0014 (incident detector in its own consumer reusing the routing health threshold, one open incident per processor; Prometheus and Grafana under the `observability` profile); CI minutes kept as is, checked at REL-38, path filters tightened if a month passes 1,000 minutes (R12). Plan fixes: REL-37 joins `payments` for amounts (events carry no money), REL-40 fixes the OpenAPI gaps, and the Phase 2 checklist gaps (pins and licences, compose contract, grounding and quality check, same-origin triage, MTTD/MTTR definitions).
- Evidence: all five roadmap exit criteria met; ADR-0003 live forced failure (publisher killed between XADD and its published mark, 300 payments, 2,869 events): nothing lost, no duplicate in any timeline, 140 harmless duplicate stream entries; every ADR-0008 case has a named test; design docs reconciled with the code and the generated OpenAPI; hygiene PASS.
- Surprises and lessons: (1) `docker kill` never triggers the restart policy, so crash-restart evidence comes from REL-48's outside kill; (2) a worker cannot register a template-marked file it creates outside its owned paths, so the primary registers it, and a registry entry for a file that only exists on an unmerged branch fails the live guard until the merge lands; (3) path filters mean the latest green `main` run may not have run the code jobs, so exit evidence names the run that did.

### Session 25 — REL-33 observability (2026-11-02)

- Goal: Prometheus and Grafana for the guardrail metrics, after accepting ADR-0006. One sonnet worker; PR #355, squash `4808f69`.
- Decisions: ADR-0006 Accepted by the owner after a licence comparison checked at the exact versions (Prometheus v3.15.1 Apache-2.0, Grafana 13.3.0 open-source edition AGPL-3.0, `prometheus-client` 0.26.0 Apache-2.0; Sentry FSL-1.1 is source-available, not open source; PostHog is partly proprietary); `grafana/grafana` is the open-source edition and `grafana/grafana-enterprise` the Enterprise one; metrics on internal-only port 9100 so no key enters the Prometheus config; Grafana anonymous viewer with no admin account.
- Verification: api CHECK=PASS (663), compose and observability-file tests pass on the host, Semgrep 0 findings; live: 10 services healthy, targets up, four dashboards fed by a seeded outage run, default `up` starts neither service.
- Surprises and lessons: (1) the primary's review caught an outage burst missing from the dashboard: all increments of a new label value fell between two scrapes, so the series was born above zero and `rate()` saw no increase; every known series now starts at zero (test written first); (2) the dashboard spec's queries were generated from the built dashboards, not strictly before them; recorded in the PR evidence.

### Session 26 — REL-34 incident detector (2026-11-02)

- Goal: incident detection in its own consumer and the incident lifecycle API, as ADR-0014 decided. One sonnet worker; PR #356, squash `3cd31cc`.
- Decisions: the detector reads the router's own health snapshot (`payment.routed.data.health`), so incidents agree with routing; per-processor `last_event_id` under a row lock in the same transaction as the incident change, ack after commit, and a unique partial index for one open incident per processor; recovery recorded only on `preferred` health (primary's review change: an avoided processor gets no traffic, ages to `unknown` and may still be down); recovery never applies to manual incidents; Prometheus scrapes the new container.
- Verification: api CHECK=PASS (722), 73 host-side compose and file tests, Semgrep 0 findings; live: one incident for A in the seeded outage, recovered after it, transitions and key checks as specified.
- Surprises and lessons: (1) `unknown` health means no recent traffic, not health: any rule that treats it as recovery is wrong for an avoided processor (same window effect as L-068); (2) re-running a seed creates no new payments (idempotency keys replay), so a second live run needs a new seed; (3) one run hit the generator's 60 s drain limit with 3 payments not final (open item in HANDOFF); (4) `finish.ps1` reported a verify failure when another session pushed right after its commit, although the commit had landed.

### Session 27 — REL-35 incident links and summary (2026-11-03)

- Goal: link incidents to affected payments and events, and a grounded incident summary with rules fallback and a real-model quality check. One sonnet worker; squash `d8b3259`. The plan first gained `api/app/db/`, `api/migrations/` and `docs/architecture/` for REL-35 (lesson L-050).
- Decisions: the detector links failures (`payment.failed`, or `attempt.*_result` with `timeout` or `outage`) on the incident's processor from `opened_at - HEALTH_WINDOW_SECONDS` while open, in its own transaction and event-id order; summaries stored like explanations (generate on first request, regenerate on POST); fallback reasons `citation_check_failed`, the model reasons, `cause_mismatch` and `no_linked_events` (model not called); prompt bounded to 30 event lines, no descriptions or ids; no transaction open during the model call.
- Verification: api CHECK=PASS (780), host compose tests, Semgrep 0; quality check (granite3.3:2b, Ollama 0.40.13): citations 6/6 in two runs, cause match 4/6 and 5/6 (mismatches fall back per ADR-0013); live: one incident on A with 74 linked payments and a model summary whose 28 citations were all linked events.
- Surprises and lessons: (1) the cause-match rate varies between runs (4/6, 5/6), so report each run, not one rate; (2) a day boundary during task-finish makes the sync check fail on the handoff date until the handoff is updated.

### Session 28 — REL-36 Incident UI: list, detail and triage actions (2026-11-03)

- Goal: the incident UI with triage and resolve, measured time to detect and recover, and the generator drain fix (open item from REL-34). One sonnet worker; PR #358, squash `4f5c7c3`. The plan first gained `scripts/`, the generator and `docs/evaluation/` for REL-36.
- Decisions: drain limit 2 x (re-drive 30 s + grace 5 s) + 30 = 100 s, with unfinished payments listed on timeout; the generator records outage switch times; triage and resolve through same-origin server routes (`isSameOrigin` moved to `lib/upstream.ts`); only the valid next action shows; timing pinned at 2 payments/s and the 120 s demo health window, with the spread of three runs as the tolerance; MTTR from scripted resolution is reported as the API path, not a human.
- Verification: web CHECK=PASS (129), sim CHECK=PASS (109), e2e 12 passed as CI runs them, scripts lint and Semgrep 0; timing: detect 57.1 s (52.7 to 62.8), recovery after the outage 129.8 s (128.3 to 132.5), no drain timeout; screenshots at 1280 px and Pixel 7 reviewed.
- Surprises and lessons: (1) the list reads each incident's detail for its affected count (no count on the list endpoint) and the detail page lists every payment and event, so a large incident is a long page; both are REL-38 follow-ups; (2) Semgrep flags the ignored `frontend/.next` build output in a worktree scan with `--no-git-ignore`; delete it first; (3) `task-wrapup.ps1` did the mechanical handoff edits for the first time.

### Session 29 — REL-37 Analytics: volume, success rate, latency and failure reasons by processor (2026-11-03)

- Goal: analytics by processor and time range with the REL-30 baseline beside them. One sonnet worker; PR #359, squash `f77d115`. The plan first gained `docker-compose.yml`, `docs/architecture/` and `api/app/main.py` for the baseline mount.
- Decisions: figures reuse `app/reporting` (a test asserts identical numbers); money and the handling processor are joined from `payments`; the processor filter keeps payments routed to that processor (a retried payment counts under both); the baseline file is mounted read-only and a missing or malformed file answers `available: false`; range presets in the UI (1 h, 24 h, 7 d, 31 d).
- Verification: api CHECK=PASS (812), web CHECK=PASS (149), host compose tests, Semgrep 0, analytics e2e 4 of 4 (the full suite runs in the PR's CI job); live: A success rate 0.93, 0 during the outage, 1 after; rescue split retry 52, failover 40, redrive 21; baseline 58 against 89.
- Surprises and lessons: (1) the primary's review caught a `run_date` taken from the results file's modification time, which is the checkout time; a date must come from the data, never from a file timestamp; (2) the worker wrote the API before its tests, so those were never seen red; (3) a ruff import-sort error followed a one-line import removal, so run `ruff check --fix` after hand edits.

### Session 30 — REL-38 Phase 2 exit review and Phase 3 refinement (2026-11-04)

- Goal: close Phase 2 with evidence and refine Phase 3. Split: a sonnet worker gathered the evidence (`docs/evaluation/phase-2-exit-review.md`), the primary ran the full `plan-review` on Phase 3 (workspace `evaluations/relay-plan-review-2026-11-04-phase3.md`). Owner approved; PR #366, squash `257bc9c`.
- Decisions (owner): ADR-0015 (webhooks in their own consumer with crash-safe stored deliveries, `Relay-Signature` and `Relay-Event-Id`, at most 8 retries with backoff, a host allowlist against request forgery, secret shown once); REL-57 before webhooks for the incident follow-ups, the two missing guardrail panels, a stream lag gauge and one success-rate definition; CI kept as is (about 406 billed minutes in October, 419 in November so far, under 1,000).
- Evidence: incidents (rule and manual, linked, lifecycle in API and UI), outcome metrics and ADR-0006-first all Met; guardrail dashboards Partly met (two metrics without a panel, now in REL-57); clean clone healthy; R5 Low with three groups at lag 0; hygiene PASS.
- Surprises and lessons: (1) the REL-32 review added an OpenAPI requirement to REL-40 without the api paths it needs, so lesson L-050 applies to requirements added during reviews too; (2) concurrent `finish.ps1` runs from two sessions race on push, and a registry entry for a file that exists only on an unmerged branch fails the live guard until the merge; (3) `smoke_stack.py` ignores the compose project name and skips three services (a REL-57 or later follow-up).

### Session 31 — REL-57 Incident and dashboard follow-ups: affected count, paged detail, missing guardrail panels, one success rate (2026-11-05)

- Goal: the Phase 2 follow-ups the owner placed before webhooks: `affected_count` on the incident list, a paged detail page, the two missing guardrail panels with a stream lag and pending gauge per group, and one success-rate definition. First task run with the `project-task-loop` skill; PR #369, squash `37ae2a3`.
- Decisions: client-side paging over the single detail query; success rate captured over final payments (declines count) attributed to the final attempt's processor, now the same in `/analytics`, the reporting code and Grafana; single-owner gauges read only from their owning job.
- Verification: api CHECK=PASS (823), web CHECK=PASS (152), e2e 18, host-side tests 84, Semgrep 0; live: processing histogram 220 observations equal to the analytics counts, `/analytics` and Grafana success rates equal (A 0.925, B 0.83), affected_count equal to the detail.
- Surprises and lessons: (1) the worker hit the weekly usage limit before writing anything, then its shell tool stopped returning verdicts after the api check; the primary resumed it with SendMessage and then ran the live check, e2e, host tests, Semgrep and the commit itself; (2) a gauge that every process exports at zero but only one sets reads as healthy when its owner dies, so its panel must filter on the owning job; (3) collapsed `<details>` content stays in the DOM, so e2e text locators must be scoped to the opened item.

### Session 32 — REL-39 Webhooks: subscriptions, HMAC-signed delivery, retries with backoff, delivery log (2026-11-05)

- Goal: outbound webhooks per ADR-0015: keyed subscriptions, HMAC-signed delivery from an own consumer, retries with backoff, host allowlist, delivery log, demo sink and metrics.
- Decisions: owner limited subscribable types to the six lifecycle types (ADR-0015 item 6, database CHECK); secret returned only at creation; a per-attempt log table (`webhook_delivery_attempts`, migration 0006) so retries are visible through `GET /webhooks/deliveries/{id}`; backoff 2 s, factor 2, cap 60 s, 8 attempts.
- Verification: worktree-check api PASS (953 passed) rerun by the primary; live check by the primary: 21 payments gave 21 unique signed deliveries verified by the sink, one delivery with three forced failures logged 503, 503, 503, 200 with gaps 2.2, 4.4, 8.3 s, disallowed host 422, no key 401, secret absent from logs; CI green on PR #370.
- Surprises and lessons: forcing failures on the sink while 20 payments were in flight spread them across three deliveries (one retry each), so the backoff growth only shows with a single in-flight delivery; task-finish was killed by the 10-minute background limit after merging (CI alone takes about 8 minutes), so its push, cleanup and prune were finished by hand: run it with a longer background timeout.

### Session 33 — REL-40 Developer documentation from the OpenAPI spec with a quickstart (2026-11-05)

- Goal: developer documentation from the OpenAPI spec (quickstart, authentication and idempotency, webhooks, generated reference), the OpenAPI gaps from the Phase 1 exit review closed, and the webhook delivery success rate reported.
- Decisions: owner chose (2026-11-05) a keyed `GET /webhooks/deliveries/summary`, a committed Markdown reference plus `openapi.json` generated by a standard-library module with a drift test, and a clean-room run by a fresh subagent; the OpenAPI fixes are schema-only post-processing so the 400-before-422 order and every error body stay unchanged; `api-contract.md` and `README.md` added to the owned paths.
- Verification: worktree-check api PASS (995 passed) rerun by the primary; docs and drift tests with the repository mounted 44 passed, 0 skipped; live probe of 32 error-provoking requests, every status documented for its operation, 401 without key everywhere; clean-room run 43 s to the first 201 (warm build cache); PowerShell variants run by the primary; owner approved the docs (the files could not be attached in the session); CI green on PR #371.
- Surprises and lessons: the API key middleware also guards `/docs`, so the quickstart points to the generated reference; `return` inside `ForEach-Object` does not stop a PowerShell loop (now `for` with `break`); docs tests skip in the api image and run in CI, so the primary ran them with the repository mounted; worktree removal failed with Permission denied again, held by the editor's language server, and was finished by hand; `/analytics?since=garbage` answers 200 (pre-existing, for the Phase 3 exit review).

### Session 34 — REL-41 Python SDK with examples and tests (2026-11-05)

- Goal: a Python SDK for merchants integrating with Relay: payments and webhooks, signature verification exactly as ADR-0015, examples against the local stack, its own compose service and CI job.
- Decisions: owner chose (2026-11-05) payments plus webhooks scope, one synchronous `RelayClient` on httpx, and installing from the repository (nothing published); httpx 0.28.1 pinned exactly (BSD-3-Clause); lint, format and type checks added to the SDK service and CI; `sdk/` also triggers the backend job so the signature agreement test runs on SDK-only changes; the webhook example runs its own receiver because the demo sink keeps neither raw bodies nor headers.
- Verification: `sdk` service (ruff, format, mypy, 54 tests) and worktree-check api PASS (995 passed) rerun by the primary; repository-mounted run of the agreement (17 cases), compose and docs tests 91 passed, 0 skipped; live: SDK installed in a fresh venv, both examples ran, a real signed `payment.final` delivery verified; CI green on PR #372.
- Surprises and lessons: the api's `signing.verify` raises TypeError on a non-ASCII `v1` (demo sink only; for REL-42); tests that need the repository skip inside the api image, so the primary runs them with the checkout mounted at `/repo`; task-finish's new cleanup warning fired on its first real case and the run completed in one pass (L-074).

### Session 35 — REL-42 Phase 3 exit review, evidence half (2026-11-06)

- Goal: close Phase 3 with fresh evidence (`docs/evaluation/phase-3-exit-review.md`); the `plan-review` and the Phase 4 refinement are the primary's. Split as at REL-32 and REL-38: a sonnet worker gathered the evidence, nothing in the code was changed.
- Phase 3 summary, what shipped (REL-57, REL-39, REL-40, REL-41, PRs #369 to #372, all merged 2026-11-05): the Phase 2 follow-ups (affected count, paged incident detail, two missing guardrail panels, one success-rate definition); webhooks per ADR-0015 (keyed subscriptions, HMAC-signed delivery from the own `webhooks` container, 8 attempts with 2 s doubling backoff capped at 60 s, host allowlist, delivery log and summary, demo sink); developer documentation generated from the OpenAPI spec with a quickstart (clean-room run 43 s to the first payment); the `relay-sdk` Python client with examples and a signature agreement test.
- Phase 3 decisions: ADR-0015 (owner limited subscribable types to the six lifecycle types, secret shown once, a per-attempt log table); a keyed delivery summary endpoint; installing the SDK from the repository, nothing published; CI kept as is under the 1,000-minute trigger.
- Evidence: 60 seeded payments gave 120 matching events, 120 deliveries and 120 distinct signature-valid messages at the sink, summary equal to the table, repeated on a fresh stack; a single in-flight delivery retried with gaps 2.0, 4.1 and 8.4 s; SDK example from a fresh venv; clean clone healthy in 28 s with smoke 13 of 13; hygiene PASS; CI on `main` success; about 601 billed minutes for 1 to 6 November (R12 trigger not fired, close).
- Surprises and lessons: (1) the `/analytics?since=garbage` finding is not a validation bug: the endpoint has no `since` (it is `from` and `to`), and undeclared query parameters are ignored, so the real issue is inconsistent window names; (2) `verify` raises only when the timestamp is inside the tolerance, because that check comes first, so a test of the TypeError needs a current `t`; (3) the delivery log lists at most 100 rows with no paging, so a 120-delivery run could only be reconciled through the database; (4) the documented demo size never reaches the scenario's outage, so no payment fails; (5) forcing sink failures with two events in flight spreads them, so the retry demo subscribes to `payment.final` only; (6) the Actions timing endpoint returns zero milliseconds for this private repository, so minutes still come from job durations; (7) creating a subscription without capturing its secret cannot be undone except by deactivating it, so capture the response on the first call.
- Primary's half: `plan-review` of Phase 4 against PR-1 to PR-36 (workspace `evaluations/relay-plan-review-2026-11-06-phase4.md`) found seven gaps, all fixed in the plan. The measure and win rule were undecided; a randomised strategy would not repeat on paired seeds; the harness was an in-process package with no way to drive the processors; nothing said where learned state lives; the new `adaptive` reason would be rejected by the reason CHECK; REL-43 and REL-44 owned almost none of the paths they must change; and only two scenarios existed. Owner decisions recorded as ADR-0016: paired success rate with a 10% p95 latency guardrail, a real-stack harness extending `scripts/outage_demo.py`, Thompson sampling seeded from the payment reference with its posterior computed from PostgreSQL, and a win at +1 pp on at least 80% of 3 x 5 pairs.
- Owner review (2026-11-06): Phase 3 approved; REL-58 added before REL-43 for the follow-ups (signature fix, delivery log paging, smoke coverage, docs-only pushes running only the secret scan); the primary batches each task's documentation commits into one push from now on, because 66 of November's 85 CI runs were pushes to `main`, mostly docs-only, at about 5 billed minutes each. Merged as PR #379 (`ab69e41`); task-finish's sync step failed only on the handoff date, as expected before the wrap-up.

### Session 36 — REL-58 Phase 3 follow-ups: webhook signature fix, delivery log paging, smoke coverage, docs-only CI (2026-11-06)

- Goal: close the Phase 3 follow-ups the owner placed at the REL-42 review before Phase 4: signature verification that never raises, delivery log paging, smoke coverage of every service, and docs-only pushes running only the secret scan (CI minutes, R12).
- Decisions: `signing.verify` compares bytes (`surrogatepass` so even a lone surrogate mismatches); the demo sink answers 401 for any invalid signature when it has a secret; delivery paging reuses the payments cursor through a shared `app/api/cursor.py`, default page 20 as for payments, cap of 100 per page; the SDK's `list_deliveries` returns a page plus `iter_deliveries` (unreleased, so the shape could change); docs-only means a push where every file is `docs/**` or `*.md`, never a pull request, manual run or schedule, and everything counts as changed without a usable base commit.
- Verification: worktree-check api PASS (1003 passed) and the sdk service (57 passed) rerun by the primary; repository-mounted tests pass and the 7 classification tests, which need git, pass on the host (18 of 18 in the file); live: smoke with all ten services, pages of 50, 50, 20 = 120 unique deliveries equal to the summary, bad cursor 400, non-ASCII signature 401; CI green on PR #380, and the following docs-only push ran only change detection and the secret scan.
- Surprises and lessons: the primary read the CI classification line by line (the riskiest change, because a mistake silently skips checks on main) and checked the first real docs-only push on GitHub; the classification tests skip in the api image (no git), so they need a host or CI run; task-finish's cleanup warning fired again on a held directory and the run completed in one pass.

### Session 37 — REL-43 Routing experiment harness comparing strategies on seeded scenarios (2026-11-06)

- Goal: the Phase 4 experiment harness of ADR-0016: a strategy registry, a partial-degradation scenario, a protocol fixed before any comparison, the real-stack harness and its first runs.
- Decisions: strategies register behind `ROUTING_STRATEGY` (unknown names fall back to `rules`); the worker passes the payment to the strategy (one line in `api/app/worker/handlers.py`, outside the planned paths, needed for reference-seeded sampling); `processor-a-degraded` raises A's timeout rate to 0.35 for payments 100 to 199, chosen by reasoning so its error rate (about 0.36) stays under the rule router's 0.5 threshold; protocol seeds 11 to 15, counts 200/300/300, rate 2 per second, health window 120 s, drain 400 s (amended after a failed first smoke attempt and before any comparison existed); the harness reuses `outage_demo.py` and keeps its logic in `simulator/demo/experiment.py`.
- Verification: worktree-check api (1009 passed) and sim (139 passed) rerun by the primary; the REL-30 reproduction checked against `docs/evaluation/outage-demo/results.json` (static 58.0, rules 89.0, revenue identical in all four currencies); smoke paired differences recomputed from the per-run figures (+1.00, +31.33, +20.33 pp); determinism rerun identical for all 300 references; CI green on PR #381 after one lint fix.
- Surprises and lessons: CI lints `scripts/` from inside `simulator/`, where `demo` is first-party, so an import-order error passed the lint the contract named (run from the repository root) and failed CI; the fix was one blank line and the rerun reused the PR. In the degraded scenario p95 latency is queue-dominated (219 s static, 133 s rules). Applied to `rules` against `static`, the 10% latency guardrail would fail in normal-day (1.26) and the outage (1.82) because of retries: a strict guardrail to raise with the REL-44 result.

### Session 38 — REL-44 Adaptive routing strategy measured against the rule-based baseline (2026-11-07)

- Goal: the `adaptive` routing strategy of ADR-0016 (Thompson sampling) and its measurement against `rules` on the pre-registered protocol.
- Decisions: parameters fixed in `protocol.md` before any comparison (window 120 s, half-life 30 s, prior Beta(1, 1)); posterior from the events `health.py` counts, declines never errors; draws seeded from SHA-256 of the reference; retries exactly as `rules`; new routed reason `adaptive` (migration 0007, explainer text, UI label).
- Verification: worktree-check api (1037), sim (148) and web rerun by the primary; the primary recomputed all 30 per-run success rates from the committed outcome files (no mismatch; pooled +1.82 pp, 10 of 15 better), confirmed every adaptive route carries reason `adaptive`, and that the parameters were fixed (19:10) before the first adaptive run (19:30); CI green on PR #382. **Verdict: not a win** under ADR-0016: the mean uplift passes (+1.82 pp against 1.0) but only 67% of pairs are better (80% needed) and normal-day p95 latency is 1.83x `rules`. Per scenario: normal-day +3.60 pp (5 of 5), outage -0.87 pp (1 of 5), degraded +2.73 pp (4 of 5) with latency 0.34x. Exploration cost during faults: outage 89.2% to 7.2%, degraded 39.8% to 6.8%.
- Surprises and lessons: the first smoke ran a stale api image (`rules` under the name adaptive): rebuild images before any comparison and check the routed reasons in the outcomes. The tool's 2-hour background limit cut the full run at run 27; the 4 unfinished runs were completed separately and merged, none redone; split long experiments into parts. The normal-day gain comes from routing to Processor B, whose simulated decline and timeout rates are lower; the normal-day latency cause is not established. The worker hit its 5-hour usage limit after the runs and was resumed with SendMessage. Open for REL-45: payments without a reference are seeded randomly (the worker's snapshot has no id).

### Session 39 — REL-59 Deterministic routing seed for every payment (2026-11-09)

- Goal: a deterministic adaptive routing seed for every payment, the ADR-0017 prerequisite for the second iteration.
- Decisions: the worker's payment snapshot carries the id, so `adaptive.seed_for` falls back to it instead of fresh entropy; done by the primary without a worker (one field and one test). Owner decisions of 2026-11-09 at the start of REL-45: a second iteration before Phase 4 closes (ADR-0017: gated hybrid, gate 0.15, fresh deciding seeds 21 to 25, unchanged ADR-0016 win rule); the README leads with the verdict, then the trade-off; the REL-44 normal-day latency cause is recorded as an open question.
- Verification: the new test failed on its assertion first (a random seed against the id-derived one); worktree-check api PASS (1038 passed); CI green on PR #393.
- Surprises and lessons: task-finish resolved relative `-Summary` and `-Evidence` paths from a different directory when run in the background and stopped with `input file not found`; pass absolute paths.

### Session 40 — REL-60 Second adaptive iteration: gated hybrid measured on fresh seeds (2026-11-09)

- Goal: the second adaptive iteration of ADR-0017: a gated hybrid of `rules` and the REL-44 sampler, measured on fresh pre-registered seeds under the unchanged ADR-0016 win rule.
- Decisions: the hybrid samples only while a processor has at least 5 attempts and an error rate above 0.15 and is not avoided; protocol v2 (deciding seeds 21 to 25, comparison seeds 11 to 15) committed in `62ae8c8` before any run; 60 runs in six parts under 2 hours, merged by committed code. Owner decision 2026-11-09 after the result: Phase 4 closes with its exit criterion not met, the gate fix listed as future work.
- Verification: the primary recomputed the verdict from the 60 outcome files (15 deciding pairs: +0.58 pp, 8 better, 5 tied, 2 worse; worst latency ratio 1.47), equal to `results.json`; worktree-check api (1057) and sim (156) rerun by the primary; CI green on PR #394. **Verdict: not a win**, failing all three conditions; the degraded scenario is again the strength (+2.0 pp, never worse, latency 0.60x).
- Surprises and lessons: the ADR-0017 gate reasoning was wrong: at 5 attempts one random error is a rate of 0.2, above the 0.15 gate, so a calm seed (21) sampled 174 of 200 payments at 2.7x latency; the primary saw it in the smoke and the first pair and kept the pre-registered protocol rather than change it after seeing results. Exact ties count as not better, so a design that copies `rules` on calm days caps its better-share at 73%. The worker hit its usage limit after four parts and was resumed from its saved parts; a bash heredoc turned `\n` in Python strings into real newlines three times (use the Edit tool or `chr(92)`).

### Session 41 — REL-45 Phase 4 exit review and project retrospective (2026-11-09)

- Goal: close Phase 4 with fresh evidence (`docs/evaluation/phase-4-exit-review.md`), the final README results and this retrospective. Documentation only: findings are recorded, not fixed.
- Decisions: owner decision 2026-11-09, fixed before the work: the exit criterion is recorded as not met after two pre-registered attempts, the README leads with the verdict (each condition with its numbers, both iterations), then the per-scenario table, then the consistent partial-degradation strength and the future-work item (a gate that needs about 20 attempts to open; calm-day ties still cap the better-share near 73% under the ADR-0016 rule). Risks R1, R3, R14 and R19 closed, R20 added; all 17 ADRs stay Accepted.
- Verification: clean clone of the branch (`33f1466`), `docker compose up -d --wait --build` exit 0 in 29 s (warm cache), 10 services healthy, smoke 19 of 19, `down -v`, folder deleted; dependency audit with licences read from the built images and the lock file (no paid dependency, no hosted AI API; three licence facts not written in any ADR); both iterations' pair counts recomputed from the saved outcome files and equal to the results files; hygiene `PROJECT_HYGIENE=PASS CHECKED=2`; CI on `main` success.
- Surprises and lessons: (1) the licence audit found facts that no ADR states (psycopg is LGPL-3.0, Next.js brings LGPL `@img/sharp-*` binaries, base images and the Ollama server have no recorded licence); they are free and open source, so the criterion holds, but "a licence recorded for each dependency" was never a written practice, only "free and open source". (2) The branch history of REL-44 is squashed, so the order "parameters fixed before the first run" rests on the primary's recorded times and not on commits; REL-60's protocol commit (`62ae8c8`) is the stronger form of evidence. (3) Outcome files hold only status and routing, so latency ratios cannot be recomputed from them; the queue wait per payment would have settled the latency question.

## Retrospective

Written at the end of the project (2026-11-09) from the 41 sessions above, the lessons in the workspace learning log (L-065 to L-078 are cited where they apply) and the exit reviews. Facts are from the log and the repository; the "do differently" items are my inference from them.

### The project in numbers

- 4 phases after the foundation, 51 tasks in the plan (258 steps at the 2026-10-11 count), 49 done before REL-45 and 50 with it; REL-46 (portfolio release) is the owner's.
- 162 commits on the branch from 2026-09-29 to 2026-11-09, 50 of them squash-merged pull requests (`git log`, counting subjects that end in a PR number), 17 ADRs (all Accepted), 20 risks (R1 to R20; R4, R6, R13, R1, R3, R14 and R19 closed), 3 earlier exit reviews approved by the owner and this fourth one.
- Backend tests: 1,057 in the api suite and 156 in the simulator suite at REL-60 (session 40), plus the SDK suite and the frontend and Playwright tests.
- Phase 4 measurement: 90 experiment runs (30 for REL-44, 60 for REL-60), about 2.2 hours of run time per 15-pair experiment. Result: two pre-registered attempts, neither won; exit criterion not met.

### What worked

- **Pre-registration kept the result honest.** The win rule, scenarios, seeds and sampler parameters were fixed before any comparison (protocol, ADR-0016); the REL-60 protocol v2 was committed (`62ae8c8`) before any run. When the first pair and the smoke run showed the hybrid sampling on a calm day, the primary kept the protocol and reported the failure rather than change the gate after seeing results. The README can therefore say "not met" and be believed.
- **Independent recomputation.** At every measured task the primary recomputed headline numbers from raw saved files rather than trusting the worker's summary: all 30 REL-44 success rates and all 60 REL-60 outcome files (sessions 38 and 40), the REL-30 reproduction against the stored demo results and the smoke differences (session 37). This review did it again for both iterations. No mismatch was found; the value is that none had to be taken on trust.
- **Determinism as a design constraint.** Seeding simulator draws on a payment `reference` (ADR-0012, found in the 2026-10-09 review) is why paired comparisons, the three identical demo runs and the 300-of-300 rerun were possible at all (R14). REL-59, a deterministic seed for payments without a reference, came from the same thinking.
- **The worker contract and review loop.** One bounded worker per task with owned paths, a test-first run (`worktree-check -RedOnly`), a stop condition and a check the primary reruns before integrating. Examples: the REL-43 import-order error was caught by CI and fixed in one line without losing the PR (session 37); the REL-60 worker hit its usage limit after four of six parts and was resumed from its saved parts, because parts were saved separately (session 40, L-077).
- **Splitting the exit review.** A worker gathers evidence on a clean clone, the primary does the plan review and the owner decides (sessions 24, 30, 35). Each review found real follow-ups (the `verify` `TypeError`, the unpaged delivery log, a smoke script that covered six of ten services) and the owner placed them before the next phase.
- **Cheap guards for repeated mistakes.** Hygiene checks for exact image pins (R15 came from `redis:7` silently becoming a non-open-source release), the project sync guard, `task-finish` and `worktree-check` removed whole classes of manual error. L-074 (editor locks on the worktree) became a script change, and L-073 (a 10-minute background limit killed task-finish after the merge) became a rule to use 30 minutes or more.
- **Free and open source held.** The local model with a deterministic fallback (ADR-0005, ADR-0010), Valkey instead of Redis (ADR-0012), Prometheus and Grafana OSS (ADR-0006) and the rejection of Sentry and PostHog kept the stack free; the Phase 4 audit confirms it.

### What did not work

- **The adaptive routing result.** Neither strategy beat `rules` under the rule fixed in advance. `adaptive` passed on average uplift (+1.82 pp) but not on reliability (10 of 15 pairs) or latency (1.829 on a calm day); `hybrid` passed nothing (+0.58 pp, 8 of 15, 1.473). The consistent strength is the partial degradation the rule router cannot see: +2.73 pp and +2.00 pp with p95 at 0.340 and 0.605 of `rules`.
- **A design argument not tested against its own window.** ADR-0017 justified the 0.15 gate as 2.5 times the long-run calm-day error ceiling, but the gate opens at 5 attempts, where one random error is a rate of 0.2. A short simulation of the 5-attempt window before pre-registering would have shown it. The cost was a whole second iteration (60 runs, about 4 hours of run time) that could not pass.
- **A win rule that penalises a deliberate tie.** "Strictly better" counts exact ties as not better, and a gated hybrid ties `rules` exactly on a calm day, so 4 of 5 calm pairs were ties and the better-share was capped at 11 of 15 (73%) against 80% before any run. That cap follows from arithmetic available when the rule and the design were fixed; it was found in the results.
- **Two causes left unmeasured.** The REL-44 calm-day latency (decision time ruled out, queueing at the single worker only consistent) and the hybrid's two lost outage pairs have no established cause, because the per-payment queue wait was never recorded. Latency is also queue-dominated at one worker, so only ratios were usable.
- **CI cost surprised us.** Docs-only pushes billed about 5 minutes each and Relay reached 601 of 1,000 minutes in six days of November (L-075); the fix (docs-only pushes run only the secret scan, batched docs commits) came after the cost. The lint CI ran differed from the one the worker contract named (L-076).
- **Stale and cut-off long runs.** The first REL-44 smoke ran a stale api image, so `rules` ran under the name `adaptive`; the full run was cut at run 27 of 30 by the tool's two-hour limit (L-077). Both were caught and neither cost a result, but both were avoidable with an image rebuild step and runs split into parts from the start.
- **Fakes hid real defects until a real run.** The first explanation quality run exposed prompt bugs (citations 6 of 10, then 10 of 10 after fixes), and invented UI fixtures hid a wrong attempt label that only a browser check caught (L-065).
- **Metrics that cannot see a burst.** A Prometheus counter born above zero shows no increase to `rate()`, so an outage between two scrapes was invisible until every label combination was created at zero on startup (L-070).
- **Scope discipline** (L-078): a spot check elsewhere grew into a font project. Here the exit reviews recorded findings with a disposition and the owner placed them, and this task recorded the licence gaps and the gate flaw without fixing them.

### What to do differently

1. **Test a design against its own decision threshold before pre-registering it.** For any gate, simulate the smallest window it can open on, and check what the win rule does to the pairs the design ties by construction. Both REL-60 flaws were checkable on paper.
2. **Decide how ties count when writing a win rule**, and state the maximum attainable share for each design family in the protocol.
3. **Record the diagnostic you will need.** Add the per-payment queue wait (received to first routed) to the outcome files before the first comparison, so "latency" is explainable afterwards.
4. **Budget iterations, not just runs.** One honest attempt costs about 2.2 hours of run time plus preparation, and two attempts without a gate-level pilot spent the Phase 4 budget on one pre-registered failure each. A small unregistered pilot on non-deciding seeds to catch design errors, then one pre-registered run, is the cheaper shape.
5. **Write the licence into each ADR that adds a dependency or image**, and run the audit at each phase exit rather than once at the end; the three gaps found now would each have been one line when the dependency arrived.
6. **Commit the evidence that proves pre-registration.** Keep the protocol commit separate and before the first run, and do not squash away the history that carries the order; REL-44's timing rests on a log entry because the history is squashed.
7. **Cost CI before adding work to it.** Estimate billed minutes per push type at each phase kickoff (L-075) and keep path filters from the start.
8. **Run the real thing early.** Real model before fake-model confidence, real API responses for fixtures, a rebuilt image before any comparison, and a browser check on the running stack.

### Session 42 — REL-61 Release preparation: local paths removed, recorded walkthrough (2026-11-10)

- Goal: make the repository ready for the owner's public release: no machine paths or the owner's address in tracked files, hooks that work without the workspace, and a recorded walkthrough instead of a hosted demo.
- Decisions: owner, 2026-11-10: a fresh public repository `relay-payments` from the release commit as one commit with the GitHub noreply author (the private `relay` keeps its history); paths cleaned with a test; a recorded walkthrough, not a hosted demo (a public demo would need its own authentication and read-only mode, ADR-0012). The path test is Vitest over `git ls-files` because the api image has no `.git`.
- Verification: worktree-check web and api PASS rerun by the primary; the primary's own grep found no machine path in any tracked file; two screenshots viewed (synthetic, no key, status as text); CI green on PR #401 and on the post-merge docs commit.
- Surprises and lessons: the workspace generator `maintenance/project-docs.ps1` wrote the owner's absolute path into every project's `workflow.md`, so the post-merge regeneration would have broken the new test on main; the primary fixed the generator first and matched the branch to its output. The template stop hook blocked on another session's unregistered career-kit files; the primary registered two, the other session committed them, and both sessions held their workspace commits by message to avoid an index-lock collision.
