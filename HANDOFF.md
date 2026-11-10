# Handoff: relay

Template: claude/handoff@1

Status: Build complete and release-ready: 51 of 52 tasks done; REL-61 release preparation merged (`fea8249`); REL-46 (owner) next: public copy relay-payments  
From: Claude Code session of 2026-10-26 (merged #308 to #313)  
To: Next Claude Code session  
Last updated: 2026-11-10

## Outcome

Relay is a portfolio project on synthetic data: a merchant using two payment processors loses revenue to failed and stuck payments; Relay gives each payment one timeline, explains failures in plain language and fails over to the healthy processor. Foundation documents, ADR-0001 to ADR-0014 (all Accepted), the Phase 1 design (`docs/architecture/containers.md`, `api-contract.md`, `data-model.md`), and a delivery plan of 45 tasks and 258 steps exist. Every task is a GitHub issue and every step a sub-issue. Built so far: the compose stack (PostgreSQL, Valkey, migrate, api `/health`, placeholder frontend), CI, the simulated processors with reference-seeded draws, the shared error format and JSON logging, the pure payment domain module (`api/app/domain/`) and the database schema with its first migration (`api/app/db/`, `api/migrations/`); the transactional outbox service (`api/app/services/transitions.py`), `POST /payments` with idempotency (`api/app/api/`, `api/app/idempotency/`) the outbox publisher (`api/app/outbox/`, compose `publisher`) the read endpoints (`GET /payments`, `GET /payments/{id}`) the async worker with its timeout sweeper (`api/app/worker/`, compose `worker`) the rule-based router (`api/app/routing/`, `GET /processors/health`), the rule-based and model explainers with stored explanations (`api/app/explain/`, the `explainer` container, `api/app/explainer/`) and the load generator (`simulator/generator/`).

## Current state

- Completed: foundation documents; REL-11 (private repository, labels, milestones, issues) with its three steps closed; the 2026-09-30 plan review (see `docs/delivery/process-log.md`, session 5).
- In progress (2026-11-10): REL-46 release: the public copy `brendanmair-project/relay-payments` (one commit, author `335649203+brendanmair-project@users.noreply.github.com`) is prepared locally; creating it waits for the owner's explicit go-ahead.
- Done 2026-10-26 (later): #310 (audit every run, runner pinned; plan step REL-13.8 added and closed), REL-54 (#311, `35496ab`), REL-52 (#312, `2bf6e0d`), REL-14 (#313, `9d28f60`), REL-15 (#315, `a10c7ff`), REL-16 (#316, `962a2cc`), REL-20 (#317, `1a14d4b`), REL-17 (#318, `5a39c5e`), REL-18 (#319, `5479c4b`), REL-21 (#320, `91d9bab`), REL-22 (#321, `b2ee0ad`), REL-50 (#322, `4dad388`), REL-24 (#323, `ee1a68e`), REL-23 (#324, `31cba27`), REL-55 (#331, `3216cb5`), REL-51 (#332, `fd26928`), REL-47 (#338, `dd1709a`), REL-56 (#339, `8f658a5`), REL-26 (#341, `2e342a4`), REL-25 (#342, `84168b1`), REL-48 (#344, `89437e4`, 2026-11-01), REL-27 (#345, `871ac2f`, 2026-11-01), REL-28 (#346, `2c73609`, 2026-11-01), REL-29 (#347, `931bc52`, 2026-11-01), REL-30 (#350, `4c9a5e4`, 2026-11-02), REL-31 (#351, `558fca9`, 2026-11-02), REL-32 (#354, `e73a34c`, 2026-11-02, Phase 1 exit), REL-33 (#355, `4808f69`, 2026-11-02), REL-34 (#356, `3cd31cc`, 2026-11-02), REL-35 (#357, `d8b3259`, 2026-11-03), REL-36 (#358, `4f5c7c3`, 2026-11-03), REL-37 (#359, `f77d115`, 2026-11-03), REL-38 (#366, `257bc9c`, 2026-11-04), REL-57 (#369, `37ae2a3`, 2026-11-05), REL-39 (#370, `79b70e5`, 2026-11-05), REL-40 (#371, `9059e5d`, 2026-11-05), REL-41 (#372, `94fc227`, 2026-11-05), REL-42 (#379, `ab69e41`, 2026-11-06), REL-58 (#380, `0f8c482`, 2026-11-06), REL-43 (#381, `3bb0d4d`, 2026-11-06), REL-44 (#382, `4a512d5`, 2026-11-07), REL-59 (#393, `1ba49b6`, 2026-11-09), REL-60 (#394, `9a07eca`, 2026-11-09), REL-45 (#395, `e30b0f7`, 2026-11-09), REL-61 (#401, `fea8249`, 2026-11-10); all their step issues closed; plan review after REL-13 (workspace `evaluations/relay-plan-review-2026-10-26.md`).
- Done 2026-10-26: PR #308 (the 2026-10-09 review, squash `0a7ac8f`) and REL-13 (PR #309, squash `10e789a`): CI with backend, simulator, frontend, secret scan, PR stack smoke and dependency audit. The first audit failed on a critical Next.js 16.3.8 advisory, so Next.js and `eslint-config-next` moved to 16.4.3 with the owner's approval (ADR-0011 and ADR-0007 amended). All 7 PR checks and the push-to-main run passed.
- Done earlier: REL-10 (Docker Desktop 29.8.1 on WSL2, Compose v5.5.1; Ollama with `granite3.3:2b`, ADR-0010) REL-53 (containers, API contract, data model; ADR-0008 Accepted) and REL-12 (docker compose stack: api `/health`, simulator, frontend, migrate, `relay_test`, smoke test; ADR-0011 build decisions). REL-49 (ADR-0007 Accepted). REL-19 (Processors A and B in `simulator/processors/`, PR #290; contract details in `api-contract.md`).
- Not started: everything else (see `docs/delivery/delivery-plan.md`).
- Working location: `projects/professional/relay`
- Active branch/profile/environment: `main`, pushed to the private remote https://github.com/brendanmair-project/relay. Old local branches `rel-13-ci`, `rel-13-ci-pre-rebase`, `rel-13-ci-before-review` and `review-2026-10-09` are merged or superseded; deleting them needs the owner (`git branch -D` is guard-blocked).

## Scope

- In scope: Phase 1 Showcase slice: payments API with idempotency; two simulated processors and a load generator (public API and simulator control API only); per-payment event history via transactional outbox; state-guarded worker with retry and recovery (ADR-0008); rule-based routing with failover and a static baseline mode; stored explanations (Ollama plus a deterministic fallback); minimal Next.js UI through server routes; pytest, Vitest and Playwright in CI; scripted outage demo with measured results.
- Out of scope: incidents, dashboards, analytics, webhooks, SDK and adaptive routing (Phases 2-4); multi-tenancy; real payments or card data; paid dependencies.
- User intent to preserve: Brendan decides; free and open source only; local-first; the delivery plan and GitHub Issues are the only task tracker; the domain term is "payment"; UI direction in `AGENTS.md` (dense, restrained, status never by color alone).

## Decisions

| Decision | Rationale | Source/owner | Revisit when |
|---|---|---|---|
| Fixed stack (Python, FastAPI, PostgreSQL, Valkey (Redis-compatible, replacing Redis per ADR-0012), Next.js, Docker Compose) | Free, open source, local, covers every layer | ADR-0001 and ADR-0012, Brendan | The stream server proves inadequate (R5) |
| Portfolio positioning, single merchant, static API key, two simulated processors | Concrete demonstrable business problem | ADR-0002, Brendan | Multi-merchant use is wanted |
| Postgres source of truth with transactional outbox to Redis Streams | State and history cannot diverge | ADR-0003, Brendan | Full replay is needed |
| Idempotency key, minor-unit money, payment state machine | Safe retries, exact amounts | ADR-0004, Brendan | Refunds or partial captures are added |
| Ollama plus deterministic fallback; model `granite3.3:2b`, Apache 2.0 (both Accepted; quality check passed 2026-10-30) | Free, offline, testable in CI; open-source licence | ADR-0005 and ADR-0010, Brendan | A prompt or model change: rerun `python -m app.explain.quality` (`docs/evaluation/results.md`) |
| Prometheus v3.15.1 and Grafana 13.3.0 (open-source edition) with `prometheus-client` 0.26.0, under the `observability` profile; metrics on internal-only ports (Accepted 2026-11-02; Sentry and PostHog rejected) | Open source, light, covers the guardrail metrics | ADR-0006 and ADR-0014, Brendan | A pinned version or licence changes, or tracing is needed |
| Development tooling and CI scope (ruff, mypy, ESLint, Prettier, Vitest, axe-core, audits, gitleaks; PR-only e2e; about 465 of 2,000 shared minutes) | Free tools for every planned check; CI inside the free plan | ADR-0007, Brendan (Accepted 2026-10-01) | Minutes pass half the allowance, or the repository goes public |
| Attempts, final outcome, state-guarded worker, idempotent processor calls, recovery | At-least-once delivery and crashes must not stall or double-process payments | ADR-0008, Brendan (Accepted 2026-10-01) | A third processor, more retries or refunds |
| USD/EUR/GBP/JPY; API key on every endpoint with UI server routes; stored explanations; 2-hour manual baseline; static baseline without retry; reproducible within tolerance | Makes Phase 1 measurable and safe without new dependencies | ADR-0009, Brendan (2026-09-30) | More currencies, a second merchant or public hosting |
| Clean-clone setup, exact library versions, runtime libraries, sweeper grace, routing rule, model check, host ports | Removes guesses from Phase 1 | ADR-0011, Brendan (2026-10-01) | A security update or a third processor |
| Payment `reference` for repeatable paired runs; Valkey and exact image pins; `explainer` container and restart policies; frontend route access rule; regeneration through POST; decided reasons and late results; reporting per source and rescue path | Results repeat, the stack is open source, processing never waits on the model, other web pages cannot drive the demo | ADR-0012, Brendan (2026-10-09) | An image version changes, a public demo, or a third processor |

## Evidence and verification

| Check | Command/method | Result | Evidence |
|---|---|---|---|
| Documents and ADRs follow their templates | Parent workspace `validate-template-system.ps1 -Mode Managed` | Pass (0 errors) | Session 2026-09-30 |
| Plan renders and validates | `project-plan.ps1 -Manifest shared/tasks/relay.json -PlanOut docs/delivery/delivery-plan.md` | `PROJECT_PLAN=PASS`, 44 tasks | Session 2026-09-30 |
| Verify hook skips for tdd-red and Docker down | Workspace `test-new-project.ps1` (same script text as `.claude/hooks/verify.ps1`) | 78 cases pass under PowerShell 5.1 and 7 | Session 2026-09-30 |
| Issue update mode | Workspace `test-project-plan.ps1` | 123 cases pass under PowerShell 5.1 and 7 | Session 2026-09-30 |
| Secret guard on every commit | `.githooks/pre-commit` | `SHARED_GIT=PASS` on each commit | Commit history |
| Plan after the 2026-10-09 review, with the phase-exit reachability check | `project-plan.ps1 -Manifest shared/tasks/relay.json` (`phase_exits` declared) | `PROJECT_PLAN=PASS`, 45 tasks, 258 steps; issue sync dry rerun shows zero changes | Session 2026-10-11 |
| Stack on Valkey with exact image pins | `docker compose up -d --wait --build`, `python scripts/smoke_stack.py`, `docker compose run --rm api pytest`, `docker compose run --rm --no-deps simulator pytest`, stream commands with `valkey-cli` | Smoke PASS; 6 api and 31 simulator tests pass; `XREADGROUP`, `XAUTOCLAIM` and `MAXLEN` work on Valkey 9.1.2 | Session 2026-10-09 |

## Changes made

- Files (2026-09-30): ADR-0008, ADR-0009, ADR index, `payment-lifecycle.md`, `system-context.md`, `constraints.md`, glossary, risk register (R11-R13), `docs/product/metrics.md`, `README.md`, `AGENTS.md`, `.gitignore`, `.claude/hooks/verify.ps1`, `docs/delivery/process-log.md`, generated `docs/delivery/delivery-plan.md`.
- External state: private GitHub repository; issues synced from the plan with `-UpdateIssues` (see the workspace handoff for the counts).
- Installed dependencies: pinned in `api/requirements*.txt`, `simulator/requirements.txt` and `frontend/package-lock.json` (ADR-0011).
- Recoverability/rollback: Git history on `main`; issues are edited or added, never closed or deleted by the generator.

## Risks, blockers, and unknowns

- No blocker. Docker, Compose and Ollama are installed and verified; the `workflow` token scope is granted.
- Note: CI runs on `ubuntu-latest`, which GitHub moves to Ubuntu 26 from 2026-10-19 (run annotation); pin the runner if a job breaks.
- Note: Valkey uses the new `valkeydata` volume; the old `relay_redisdata` volume is unused and can be removed with `docker volume rm relay_redisdata`.
- Risks: R3, R8, R9, R10, R11 (processing reliability), R12 (free private GitHub plan: no enforced CI gate, limited minutes), R14 to R17 (from the 2026-10-09 review, mitigated by ADR-0012 except R16, shared Actions minutes); R13 resolved by ADR-0010; see `docs/delivery/risk-register.md`.
- Open (2026-11-02): in one REL-34 live run (seed 8) the generator's 60 s drain gave up with 3 payments not final before the outage-off switch, leaving the outage on; check the drain limit against the sweeper's re-drive timing before the next demo-dependent task (REL-36 MTTD/MTTR).
- R18 mitigated by ADR-0013 (2026-11-01): when the model's cause differs from the rules cause, the rules text is stored with `fallback_reason = cause_mismatch`; implemented in REL-27 (#345); quality run 3 has 3 of 10 timelines on rules text.

## Next actions

1. Owner: REL-46 portfolio release (publish checklist via `/publish-project`, make the repository public, optional free-tier demo); nothing is published without the owner's explicit go-ahead. Claude can prepare the checklist on request. Build work is complete (Phases 1 to 4, `docs/evaluation/phase-4-exit-review.md`).
1a. Republish both Relay boards from a session with the Artifact tool: the board data is regenerated by `project-plan.ps1 -BoardDataOut` (`-Public` for the public page); this session had no Artifact tool.
2. Read ADR-0012 before REL-14, REL-15, REL-17, REL-21 and REL-25: their requirements changed (payment `reference`, reason CHECK, late results, `explainer` container, POST regeneration).
3. `plan-review` ran after REL-13 (2026-10-26); run it again before REL-30. For REL-21 and REL-30 read the REL-19 notes in the process log (session 12): no late answer for a timed-out key; set the same profiles on each reproducibility run. Run the stack with `docker compose up -d --wait`; see AGENTS.md commands) and follow the task loop in `docs/delivery/delivery-plan.md`.
4. After each closed task or step, refresh both progress boards (see the workspace handoff).

## Resume point

Each session also gets `docs/delivery/next.md` through CLAUDE.md: open the task file it names in `docs/delivery/tasks/`, work it with `docs/workflow/workflow.md`, and at the end update `CHANGELOG.md`, `docs/delivery/process-log.md` and this file.

Read `AGENTS.md`, this file and `docs/delivery/delivery-plan.md`. Run `git status --short --branch`. Pick the next Ready task on the board or with `gh issue list --label in-progress`.

## Acknowledgment or completion

Accept by reading this file and checking the worktree. Phase 1 is complete when REL-32 records every exit criterion with evidence.
