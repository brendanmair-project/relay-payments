# Changelog: Relay

Template: claude/changelog@1

## How to read this

Every change that lands in this project, newest first. One entry per day under a `### YYYY-MM-DD` heading; each line names what changed, the task id (or `chore`) and the short commit id. Decisions and lessons go in `docs/delivery/process-log.md`, not here.

## Entries

### 2026-11-10

- REL-61: release preparation: no machine paths in tracked files (with a test), hooks that skip without the workspace, and a recorded walkthrough of the outage demo in the README. (REL-61, fea8249)

### 2026-11-09

- REL-45: Phase 4 exit review (adaptive routing did not beat rules after two pre-registered attempts; no paid dependency), final results in the README, licence amendments and the project retrospective; approved by the owner. (REL-45, e30b0f7)
- REL-60: gated hybrid routing strategy (ADR-0017); on the fresh pre-registered seeds it does not win under ADR-0016 (+0.58 pp, 8 of 15 pairs better, normal-day latency 1.47x), with the strongest result in partial degradation (+2.0 pp, latency 0.60x). (REL-60, 9a07eca)
- REL-59: the worker's payment snapshot carries the id, so adaptive routing seeds deterministically for payments without a reference. (REL-59, 1ba49b6)

### 2026-11-07

- REL-44: adaptive routing strategy (Thompson sampling, ADR-0016) with the adaptive routed reason; measured on the pre-registered protocol it does not win (+1.82 pp mean uplift, better on 10 of 15 pairs, normal-day latency 1.83x), with far lower exploration cost during faults. (REL-44, 4a512d5)

### 2026-11-06

- REL-43: routing strategy registry, a partial-degradation scenario, a pre-registered protocol (ADR-0016) and the experiment harness on the real stack; the first run reproduces REL-30 exactly. (REL-43, 3bb0d4d)
- REL-58: webhook signature verification never raises on a malformed signature, cursor paging for the delivery log (api and SDK), smoke test covers every service, and docs-only pushes to main run just the secret scan. (REL-58, 0f8c482)
- REL-42: Phase 3 exit review approved (webhooks, docs and SDK exit criteria met with fresh evidence), ADR-0016 for Phase 4 (objective, real-stack harness, Thompson sampling, win rule), Phase 4 refined and REL-58 follow-ups added. (REL-42, ab69e41)

### 2026-11-05

- REL-41: Python SDK (sdk/python): payments and webhooks client on httpx, ADR-0015 signature verification checked against the api, examples, compose sdk service, path-filtered CI job and an SDK guide. (REL-41, 94fc227)
- REL-40: developer guides (quickstart, authentication and idempotency, webhooks), a drift-tested API reference generated from the completed OpenAPI spec, and GET /webhooks/deliveries/summary for the delivery success rate. (REL-40, 9059e5d)
- REL-39: outbound webhooks (ADR-0015): keyed subscriptions, HMAC-signed delivery from an own consumer, exponential-backoff retries with a per-attempt log, host allowlist, demo sink and metrics. (REL-39, 79b70e5)
- REL-57: affected_count on the incident list, paged incident detail, the creation-to-final latency and not-final-overdue guardrail panels with per-group stream lag and pending, and one success-rate definition (captured over final) (REL-57, 37ae2a3)

### 2026-11-04

- REL-38: Phase 2 exit review (incidents, outcome metrics and ADR-0006 met; two guardrail panels scheduled in REL-57), ADR-0015 webhook design and Phase 3 refined (REL-38, 257bc9c)

### 2026-11-03

- REL-37: analytics by processor and time range (volume, success rate, latency, failure reasons, revenue recovered by rescue path, time to explanation per source) on the reporting code, with the REL-30 baseline from a read-only mounted results file (REL-37, f77d115)
- REL-36: incident list and detail pages with triage and resolve through same-origin server routes, e2e with axe and key checks, measured time to detect and recover, and a generator drain limit that covers the re-drive cycle (REL-36, 4f5c7c3)
- REL-35: incidents linked to affected payments and events, and a stored incident summary from the model with rules fallback per reason (citations only from linked events), with a real-model quality check (REL-35, d8b3259)

### 2026-11-02

- REL-34: incident detector in its own container (ADR-0014: opens when routing avoids a processor, recovery on preferred health, one open incident per processor) and the keyed incident lifecycle API (REL-34, 3cd31cc)
- REL-33: Prometheus and Grafana under the observability profile (ADR-0006 accepted), metrics for api, worker and publisher on internal-only ports, four provisioned dashboards (REL-33, 4808f69)
- REL-32: Phase 1 exit review (every exit criterion met with evidence, ADR-0003 live forced-failure run, ADR-0008/0009 validated, docs reconciled with the code), ADR-0014 and Phase 2 refined (REL-32, e73a34c)
- REL-31: showcase README with the outage-demo results, caveats, Mermaid architecture diagram, screenshots and a clean-clone-tested How to run (REL-31, 558fca9)
- REL-30: one-command outage demo against static routing with reproducible results (+31 pp success rate, revenue recovered per currency and rescue path, time to explanation per source, recovery lag); reset tool, generator drain and health-window wait (REL-30, 4c9a5e4)

### 2026-11-01

- REL-29: Playwright end-to-end tests against docker compose on every pull request (payment detail flow, axe, key exposure, host and same-origin guards) (REL-29, 931bc52)
- REL-28: demo outage control on the payments page (start and stop Processor A, state as text) through a same-origin POST route and a read-only state route; the API key stays on the server (REL-28, 2c73609)
- REL-27: payment detail page (attempts, timeline, labelled explanation, processor health, empty and error states); rules text on cause mismatch (ADR-0013) (REL-27, 871ac2f)
- REL-48: full local stack from a clean clone with only RELAY_API_KEY; per-service environment, optional llm profile, graceful shutdown tests and a per-entry explainer heartbeat (REL-48, 89437e4)

### 2026-10-30

- REL-25: AI explainer (local Ollama granite3.3:2b, rules fallback), stored explanations, GET and POST regenerate explanation endpoints, explainer container; ADR-0005 Accepted (REL-25, 84168b1)

### 2026-10-29

- Frontend payments list: dashboard spec, 5 s auto-refresh, amounts from minor units, Retrying as text, server routes holding the API key, host guard, Chrome DevTools MCP (REL-26, 2e342a4)

### 2026-10-28

- CI actions pinned to commit SHAs with the release tag in a comment; Semgrep's mutable-tag rule now enforces it; ADR-0007 amended (REL-56, 8f658a5)
- Idempotency key cleanup in the worker's sweeper loop: expired keys deleted in batches with `SKIP LOCKED`, keys with a live lease kept, expiry verified with a controllable clock (REL-47, dd1709a)
- Plan: new task REL-56 (pin CI actions to commit SHAs, owner decision; feeds the Phase 1 exit) (chore)
- Guardrail metrics report (`python -m app.reporting`, compose `reporting` in the `tools` profile): latency and publish-lag percentiles, per-processor success, stuck payments, API 5xx rate, revenue recovered by rescue path, explanation timing per source (REL-51, fd26928)
- Semgrep static analysis in CI (1.182.1; Python, TypeScript and OWASP Top Ten rule sets, `--error`), the local command in AGENTS.md, ADR-0007 amended; the first scan found only mutable action tags, suppressed with a reason (REL-55, 3216cb5)

### 2026-10-27

- Plan: new task REL-55 (Semgrep static analysis in CI, feeds the Phase 1 exit), step REL-26.8 (Chrome DevTools MCP), and tool comparisons added to REL-33 (Sentry, PostHog) and REL-46 (Vercel or Cloudflare, Neon or Supabase), from the owner's tooling review (chore)
- Rule-based payment explainer: 18 named patterns with a plain-language cause, next step and cited events, including the orphaned authorization after a timeout (REL-24, ee1a68e)
- Synthetic load generator (`python -m generator` in `simulator/`): seeded mix, deterministic references, `normal-day` and `processor-a-outage` scenarios, public and control APIs only (REL-23, 31cba27)
- Timeout sweeper in the worker: timed-out `routed`/`authorized` attempts fail with reason `timeout` (retry-eligible from `routed`), stalled `received` and retrying payments are re-driven with `payment.redriven`, safe under concurrency (REL-50, 4dad388)
- Rule-based router: health per processor from recent events, failover to B when A is avoided, one retry on the other processor, `ROUTING_STRATEGY=static` baseline, `GET /processors/health` (REL-22, b2ee0ad)

### 2026-10-26

- Async payment worker: state-guarded consumer group `processing`, XAUTOCLAIM reclaim, ack after commit, route (processor A, static) / authorize / capture with idempotency keys and `reference`, late results recorded as `attempt.late_result`; `worker` compose service; the stack smoke now creates a payment and waits for a final state (REL-21, 91d9bab)
- `GET /payments/{id}` with the ordered event timeline, and `GET /payments` with repeatable filters and a keyset cursor on `(created_at, id)` (REL-18, 5479c4b)
- `POST /payments`: 401, 400 and 422 checks before the key is claimed, idempotency with leases, takeover and stored-response replay (`Idempotent-Replayed`), canonical-JSON request hash, optional `reference` (REL-17, 5a39c5e)
- Outbox publisher: unpublished events to `relay:payment-events` with `SKIP LOCKED`, mark after `XADD`, approximate `MAXLEN`, a `publisher` compose service with a heartbeat health check (REL-20, 1a14d4b)
- Transactional outbox: each state change and its event (plus `payment.final` or `payment.retry_scheduled`) in one transaction under a row lock, gapless per-payment `seq`, non-state-change events and late results through the same path (REL-16, 962a2cc)
- Database schema and first reversible Alembic migration: `payments`, `payment_events` (append-only trigger; only `published_at` may be set, once) and `idempotency_keys` as in data-model.md; SQLAlchemy models; insert-only events module (REL-15, a10c7ff)
- Payment domain model: `Money` with the currency table, the lifecycle state machine with attempt-scoped results and `is_final`, reason enums per event type (REL-14, 9d28f60)
- Shared error format for every 4xx and 5xx, JSON logs with correlation IDs, the rotating request log, engine and Redis client created once, compose log caps (REL-52, 2bf6e0d)
- Simulator draws seeded on the payment `reference` when sent; the reference is part of the idempotent request (REL-54, 35496ab)
- CI dependency audit runs on every pull request and push to `main`; runner pinned to `ubuntu-24.04`; ADR-0007 amended (chore, a383901)
- Next.js and `eslint-config-next` 16.3.8 to 16.4.3 and `npm audit fix` for vite, undici and zod, after the first CI dependency audit found a critical Next.js advisory; ADR-0011 and ADR-0007 amended (REL-13)

### 2026-10-14

- CI pipeline (backend, simulator, frontend, secret scan, PR stack smoke, dependency audit) and the fast local suite for the Stop hook; ruff, mypy, ESLint, Prettier, Vitest wired in; coverage gate; CI badge (REL-13; pushed once the owner adds the workflow token scope)

### 2026-10-11

- Full project review applied: ADR-0012 (payment `reference` for repeatable paired demo runs, Valkey replacing Redis 7.4 with exact image pins and restart policies, explanations in their own container, frontend route access rule, regeneration through POST, decided reason values and late results, reporting per source and rescue path); design, metrics, risk and status docs updated; plan gained REL-54 and wires REL-27, REL-47 and REL-50 into the Phase 1 exit (chore)

### 2026-10-01

- Simulated Processors A and B: authorize and capture, runtime profiles and outages, seeded order-independent outcomes, idempotent first results, keyed control API (REL-19)
- ADR-0007 development tooling and CI scope Accepted (REL-49, 94fa096)
- Stack skeleton: api with /health, simulator, frontend, docker compose with health checks, migrate, relay_test, smoke test; ADR-0011 build decisions; plan aligned with the design (REL-12, e7d3b08)
- Phase 1 design: containers, API contract and data model; ADR-0008 Accepted; REL-51 and REL-52 wording for request logs (REL-53, fd5c9c3)
- ADR-0010 local model `granite3.3:2b`; REL-25 updated; risk R13 resolved; REL-10 closed (chore, 2da2533)

### 2026-09-30

- Folder template applied (guides in every standard folder, pull request template, licence), plan review results, refreshed generated docs (chore, 05898b1)
- Working docs added: generated next steps, one file per task, workflow and definition of done; tools, changelog, process log and risk register follow the shared templates (chore, 92ed95e)
- Standard project layout: docs map, delivery folder, `CLAUDE.local.md` ignored (chore, c1d4793)
- Project moved under `projects/professional/` (chore, cb7a464)
- Plan review fixed 25 gaps: ADR-0008, ADR-0009, new task REL-53, 44 tasks (chore, c08404d)
- Handoff updated after plan review and boards (chore, 5fecdcc)

### 2026-09-29

- Handoff and plain-language workflow in the plan (chore, 261410d)
- Delivery plan: 43 tasks with 229 steps after completeness review (chore, 831fbde)
- Delivery plan: `in-progress` label marks started tasks (chore, 1a404a6)
- Delivery plan: dashboard spec before UI (REL-26, 4afe431)
- Playwright MCP (isolated) and `security-guidance` plugin for this project, UI direction (chore, 9380c21)
- Foundation: portfolio positioning, payment domain, ADRs 0001-0006, full delivery plan (chore, f08d9bd)
