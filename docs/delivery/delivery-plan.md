# Relay delivery plan

_Generated from the project task plan by project-plan.ps1. Edit the plan, not this file._

## Outcome

Relay helps a two-processor merchant recover revenue lost to failed payments and explains each failure in plain language, demonstrated end to end on synthetic data with measured results

## How work gets done

1. Pick the next Ready task (everything it depends on is done) and mark its issue in progress
2. Create a branch for the task from main
3. Write a short brief for the task: files it may change, requirements, checks, and when to stop
4. Write the tests first, then the change (create .claude/tdd-red while tests are meant to fail so the stop hook allows it, and delete it before running the task's checks); run the task's checks and fix failures (three failed attempts means rethink the approach)
5. An independent reviewer checks the change against the requirements
6. Final review, then open a pull request; merge only after `gh pr checks` shows every CI check passing, because the free private plan cannot enforce it
7. Merge, close the issue and record progress in the project handoff
8. At the end of each phase, check the exit criteria, update risks and decisions, and plan the next phase in detail

Task status lives in GitHub Issues, one issue per task id.

## Checks

| Check | Command | Proves |
| --- | --- | --- |
| api-tests | `docker compose run --rm --build api pytest` | Backend unit and integration tests pass |
| api-lint | `docker compose run --rm --build api sh -c "ruff check . && ruff format --check . && mypy app"` | Backend lint, format and type check pass |
| sim-tests | `docker compose run --rm --build --no-deps simulator pytest` | Simulator tests pass |
| sim-lint | `docker compose run --rm --build --no-deps simulator sh -c "ruff check . && ruff format --check ."` | Simulator lint and format check pass (generator and demo code included) |
| web-check | `npm --prefix frontend run lint && npm --prefix frontend run build` | Frontend lint and production build pass |
| web-test | `npm --prefix frontend test` | Frontend unit and component tests pass (Vitest, ADR-0007) |
| e2e | `npm --prefix frontend run e2e` | Playwright end-to-end tests pass against docker compose (script `e2e` in frontend/package.json) |
| stack-up | `docker compose up -d --wait` | Every service starts and reports healthy locally |
| stack-smoke | `python scripts/smoke_stack.py` | The running stack answers its health checks and, from REL-21 on, a new payment reaches a final state |
| ci-green | `gh run list --branch main --limit 1 --json conclusion --jq '.[0].conclusion'` | Latest GitHub Actions run on main is green: the command prints success |
| docs-review | `owner reads the changed documents` | Documents are accurate, consistent and link correctly |
| owner-confirm | `owner confirms in chat` | The owner confirms the manual step is done |
| sdk-tests | `docker compose --profile sdk run --rm sdk pytest` | Python SDK tests pass |

## Overview

| Phase | Tasks | Count |
| --- | --- | --- |
| Setup | REL-10 to REL-13 | 5 |
| Phase 1 - Showcase slice | REL-53 to REL-46 | 29 |
| Phase 2 - Operations depth | REL-33 to REL-38 | 6 |
| Phase 3 - Integrations | REL-57 to REL-42 | 5 |
| Phase 4 - Optimization | REL-58 to REL-61 | 7 |

## Setup

| ID | Task | Owner | Depends on | Checks |
| --- | --- | --- | --- | --- |
| REL-10 | Install local prerequisites: Docker Desktop (WSL2) and Ollama with a small model | You | - | `owner-confirm` |
| REL-11 | Create the private GitHub repository, labels, milestones and issues from this plan | Claude | - | `docs-review` |
| REL-12 | Monorepo skeleton and docker compose (Postgres, Redis, API and frontend hello-world) | Claude | REL-10, REL-53 | `stack-up`, `api-tests`, `stack-smoke` |
| REL-49 | ADR-0007: development tooling and CI scope | Claude | REL-12 | `docs-review` |
| REL-13 | CI pipeline and local verification gate | Claude | REL-11, REL-12, REL-49 | `ci-green`, `web-test` |

### REL-10: Install local prerequisites: Docker Desktop (WSL2) and Ollama with a small model

- Owner: You
- Depends on: None
- Labels: infra
- Paths: `(local machine)`

Acceptance:
- [ ] docker compose version succeeds
- [ ] ollama run llama3.2:3b answers a prompt
- [ ] Both need only free software

Steps:
1. **Install Docker Desktop with the WSL2 backend** - Run `maintenance/setup/install-docker-wsl.ps1` from the workspace elevated (command in the project handoff), approve the prompt, restart Windows and open Docker Desktop once; done when Docker Desktop reports it is running.
2. **Verify Docker Compose works** - Run `docker compose version` in a terminal; done when it prints a version number without an error.
3. **Install Ollama and pull a small model** - Install Ollama from ollama.com and run `ollama pull llama3.2:3b`; done when the download completes. (Done 2026-09-29: Ollama installed and `llama3.2:3b` pulled; the local API answered on localhost:11434 on 2026-09-30.)
4. **Check the model answers a prompt** - Run `ollama run llama3.2:3b` and ask a short question; done when the model replies, then confirm in chat that both tools work.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-11: Create the private GitHub repository, labels, milestones and issues from this plan

- Owner: Claude
- Depends on: None
- Labels: infra, docs
- Paths: `docs/delivery/delivery-plan.md`

Acceptance:
- [ ] The private GitHub repository exists and matches the local commit
- [ ] One issue per task with its REL ID, labels and phase milestone
- [ ] docs/delivery/delivery-plan.md is generated from this plan

Steps:
1. **Create the private repository and push the local commit** - The private GitHub repository was created and the local commit pushed; the remote main matches the local commit.
2. **Create labels, phase milestones and one issue per task** - Labels, milestones and one issue per task were created from the plan, each carrying its REL ID, labels and phase milestone.
3. **Generate docs/delivery/delivery-plan.md from the plan** - The delivery plan document was rendered from the task plan file and reviewed for accuracy and working links.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-12: Monorepo skeleton and docker compose (Postgres, Redis, API and frontend hello-world)

- Owner: Claude
- Depends on: REL-10, REL-53
- Labels: infra
- Paths: `api/`, `simulator/`, `frontend/`, `docker-compose.yml`, `.env.example`, `scripts/`, `api/migrations/`

Acceptance:
- [ ] docker compose up brings Postgres, Redis, api and frontend up healthy
- [ ] `GET /health` with `X-API-Key` returns 200 `{status, database, redis}` when postgres and redis are reachable, 401 without the key and 503 when a dependency is down; the compose health check reads the key from the container environment and `scripts/smoke_stack.py` from `.env`
- [ ] Configuration via .env with a committed .env.example only
- [ ] docker-compose.yml also defines a simulator service skeleton so simulator checks can run
- [ ] The stack smoke test is a host-side script, `scripts/smoke_stack.py` (Python standard library only), run after `docker compose up -d --wait`
- [ ] A one-off `migrate` service runs `alembic upgrade head` (an empty Alembic environment for now); api, worker and publisher start only after it succeeds
- [ ] Tests use a separate `relay_test` database created by a Postgres init script; tests never touch the development database
- [ ] Dependencies are pinned: Python in requirements files with exact versions, the frontend in a committed package-lock.json installed with `npm ci`

Steps:
1. **Write a failing compose health smoke test** - Add `scripts/smoke_stack.py` (Python standard library only) that checks container health through `docker compose ps` and calls `GET /health` with `X-API-Key` (read from `.env`) expecting 200 `{status, database, redis}` on the running stack, and 401 without the key; it fails before the services exist.
2. **Scaffold api, simulator and frontend directories** - Create `api/` (FastAPI with a `/health` route, pytest config), `simulator/` and `frontend/` (Next.js hello page) with Dockerfiles. Pin Python dependencies with exact versions and commit the frontend package-lock.json. The simulator is a FastAPI app serving the processor API on 8100 (internal) and the control API on 8101 (`GET /health` and control routes require `X-API-Key`), per api-contract.md "Simulator APIs"; both ports are served from one process (`python -m app.serve`).
3. **Write docker-compose.yml with health checks** - Define services per docs/architecture/containers.md: Postgres, Redis, api, simulator, frontend and the one-shot `migrate`. Published ports bind to 127.0.0.1 (frontend 3000, api 8000, simulator control 8101; overridable by `FRONTEND_HOST_PORT`, `API_HOST_PORT` and `SIM_CONTROL_HOST_PORT`); the simulator processor API on 8100 is internal only. Named volume `api-logs` at `/var/log/relay` writable by the api user; Redis runs with `--appendonly yes`; named volumes `pgdata` and `redisdata`; the frontend depends on api healthy. Health checks per the containers table: `pg_isready`, `redis-cli ping`, `/health` with the key, frontend `GET /`, simulator `GET /health` on 8101 with the key. `docker compose up -d --wait` reports all healthy with the one-shot `migrate` exiting 0.
4. **Add .env.example and load configuration from .env** - Read settings from environment variables. `.env.example` lists every variable in containers.md Configuration (including `RELAY_API_KEY`, `TEST_DATABASE_URL` and `TEST_REDIS_URL`) plus `POSTGRES_PASSWORD` and the host-port overrides, with an obviously local placeholder `RELAY_API_KEY`; compose refuses to start when the key is empty (`${RELAY_API_KEY:?}`). The README states `cp .env.example .env`. Commit only `.env.example` and confirm `.env` is git-ignored.
5. **Run the checks and fix failures** - `docker compose run --rm api pytest` passes, `python scripts/smoke_stack.py` passes and `GET /health` returns 200 from the running stack.
6. **Add Alembic and the migrate service** - Initialise an empty Alembic environment in `api/migrations/` and a one-off `migrate` compose service that api waits on with `service_completed_successfully` (worker and publisher follow in later tasks).
7. **Create the test database** - The init script `scripts/postgres-init/01-create-test-db.sql` creates `relay_test`. Tests use `TEST_DATABASE_URL=postgresql+psycopg://relay:relay@postgres:5432/relay_test` and `TEST_REDIS_URL=redis://redis:6379/1`; pytest never uses `DATABASE_URL` or `REDIS_URL`. The README notes the init script runs only on a fresh volume.
8. **Document host setup for frontend checks** - Run `npm ci --prefix frontend` on the host so `web-check` works, and record the setup command for `AGENTS.md`.
9. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-49: ADR-0007: development tooling and CI scope

- Owner: Claude
- Depends on: REL-12
- Labels: infra, docs
- Paths: `docs/decisions/`

Acceptance:
- [ ] ADR-0007 is Accepted and lists each tool outside the fixed stack (ruff, mypy, ESLint, Prettier, Vitest with Testing Library, @axe-core/playwright, pytest-cov, pip-audit, npm audit, a secret scanner) with its free/open-source license
- [ ] It defines CI scope: what runs on every push and pull request, and what is deferred
- [ ] REL-13 links to it
- [ ] It records the free private plan's Actions minute budget and how CI stays within it (caching, path filters, Playwright on pull requests only)
- [ ] It records that merges are gated by `gh pr checks` because branch protection is unavailable on the free private plan (risk R12)

Steps:
1. **Survey the tooling the checks need** - List every tool the planned checks call that is not in the fixed stack, with license and why it is needed.
2. **Write ADR-0007** - Record the tools, the CI scope and alternatives considered, using the project's ADR format.
3. **Owner decision** - The owner reviews the ADR and marks it Accepted; the decisions index is updated.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-13: CI pipeline and local verification gate

- Owner: Claude
- Depends on: REL-11, REL-12, REL-49
- Labels: infra, testing
- Paths: `.github/workflows/`, `.claude/verify-command.txt`, `AGENTS.md`, `frontend/`

Acceptance:
- [ ] CI runs backend lint, types and tests plus frontend lint, unit tests (Vitest) and build on every push and pull request
- [ ] verify-command.txt runs the fast local suite
- [ ] AGENTS.md lists the real commands
- [ ] Test coverage reported with a CI-enforced minimum for the domain and idempotency modules
- [ ] CI runs dependency audits (pip-audit, npm audit) and a secret scan; tools follow ADR-0007
- [ ] The fast local suite finishes in under 3 minutes; the stop hook skips while `.claude/tdd-red` exists and when Docker is not running
- [ ] CI caches pip, npm and Docker layers and uses path filters to stay within the free private minutes (ADR-0007)
- [ ] Vitest is set up in `frontend/` so `web-test` runs locally and in CI
- [ ] CI follows ADR-0012 and the workspace hygiene check: service images use the exact pins (`postgres:16.15`, `valkey/valkey:9.1.2`); every job has `timeout-minutes`; branch pushes run CI only on `main` (pull requests cover branches); `pip-audit` also audits `requirements-dev.txt`, which the api image ships; images built with bake are tagged so compose reuses them; the simulator job also lints `scripts/`; no build output (for example `tsconfig.tsbuildinfo`) is committed

Steps:
1. **Write the local verify script and prove it fails on a broken test** - Add `.claude/verify-command.txt` running the fast suite (backend lint, types and tests, frontend lint and unit tests); done when a deliberately failing test makes it fail and `.claude/tdd-red` makes the hook skip.
2. **Add the GitHub Actions workflow** - Create a workflow under `.github/workflows/` that runs ruff, mypy and pytest plus frontend lint, Vitest and build on every push and pull request, with dependency and image caching and path filters.
3. **Update AGENTS.md with the real commands** - Replace the placeholder setup, test, lint, type-check and run commands with commands verified to work.
4. **Add the CI badge to the README** - Link the workflow status badge in `README.md`; done when it shows the current run.
5. **Get CI green on main** - Push and confirm the latest run on main passes (`gh run list --branch main --limit 1`).
6. **Set up Vitest for frontend unit tests** - Add Vitest and Testing Library per ADR-0007 with one passing example test so `web-test` runs locally and in CI.
7. **Fix the first audit's findings and audit every pull request** - Added 2026-10-26 after the first CI audit failed: Next.js and eslint-config-next to 16.4.3 with npm audit fix (PR #309), then the audit on every pull request and push to main and the runner pinned to ubuntu-24.04 (PR #310); ADR-0007 and ADR-0011 amended.
8. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

## Phase 1 - Showcase slice

| ID | Task | Owner | Depends on | Checks |
| --- | --- | --- | --- | --- |
| REL-53 | Phase 1 design: container diagram, API contract and data model; owner accepts ADR-0008 | Claude | REL-11 | `docs-review` |
| REL-52 | API foundations: shared error format and structured logging with correlation IDs | Claude | REL-13 | `api-tests`, `api-lint` |
| REL-14 | Payment domain model and lifecycle state machine | Claude | REL-13, REL-53 | `api-tests`, `api-lint` |
| REL-15 | Database schema and first Alembic migration (payments, payment_events, idempotency_keys) | Claude | REL-14, REL-53 | `api-tests`, `api-lint` |
| REL-16 | Record every state change as a payment event in the same database transaction (transactional outbox) | Claude | REL-15 | `api-tests`, `api-lint` |
| REL-17 | POST /payments with API-key auth, validation and Idempotency-Key | Claude | REL-16, REL-52 | `api-tests`, `api-lint` |
| REL-18 | GET /payments/{id} with event timeline, and GET /payments with pagination and filters | Claude | REL-17 | `api-tests`, `api-lint` |
| REL-19 | Simulated Processors A and B with latency, decline-rate and outage controls | Claude | REL-12 | `sim-tests` |
| REL-54 | Simulator: seed processor draws on the payment reference (ADR-0012) | Claude | REL-13, REL-19 | `sim-tests`, `sim-lint` |
| REL-20 | Outbox publisher to Redis Streams (at-least-once) | Claude | REL-16 | `api-tests`, `api-lint` |
| REL-21 | Async payment worker: routes, authorizes and captures via the processors | Claude | REL-18, REL-19, REL-20, REL-54 | `api-tests`, `stack-up`, `stack-smoke`, `api-lint` |
| REL-50 | Timeout sweeper: fail timed-out attempts and re-drive stalled payments | Claude | REL-21 | `api-tests`, `api-lint` |
| REL-47 | Idempotency key expiry and cleanup job | Claude | REL-17, REL-50 | `api-tests`, `api-lint` |
| REL-51 | Guardrail metrics: latency percentiles, error rate, publish lag, per-processor success | Claude | REL-20, REL-21 | `api-tests`, `api-lint` |
| REL-22 | Rule-based router with health tracking, failover and one retry on the other processor | Claude | REL-21 | `api-tests`, `api-lint` |
| REL-23 | Synthetic load generator using only the public API, with scripted scenarios | Claude | REL-18, REL-19 | `sim-tests`, `sim-lint` |
| REL-24 | Rule-based payment explainer (always available fallback) | Claude | REL-18, REL-19 | `api-tests`, `api-lint` |
| REL-25 | LLM explainer via local Ollama with fallback; explanations stored at final failure; GET /payments/{id}/explanation | Claude | REL-24, REL-10, REL-21 | `api-tests`, `api-lint` |
| REL-48 | Full local stack in docker compose with health checks and graceful shutdown | Claude | REL-20, REL-21, REL-25 | `stack-up`, `stack-smoke` |
| REL-26 | Frontend: payments list with status, processor and amount | Claude | REL-18, REL-13 | `web-check`, `web-test` |
| REL-27 | Frontend: payment detail with timeline, explanation and processor health | Claude | REL-26, REL-25, REL-22 | `web-check`, `web-test`, `api-tests` |
| REL-28 | Demo controls: inject and clear a Processor A outage from the UI or CLI | Claude | REL-19, REL-26 | `web-check`, `sim-tests`, `web-test`, `sim-lint` |
| REL-29 | Playwright smoke tests in CI against docker compose | Claude | REL-28, REL-48, REL-27 | `e2e`, `ci-green` |
| REL-30 | Scripted outage demo and metrics against a static-routing baseline | Claude | REL-22, REL-23, REL-25, REL-48, REL-51, REL-50 | `stack-up`, `sim-tests`, `sim-lint`, `api-tests`, `api-lint` |
| REL-31 | Showcase README: results, architecture diagram, screenshots or GIF | Claude | REL-30, REL-29, REL-27 | `docs-review` |
| REL-55 | Static security analysis with Semgrep in CI | Claude | REL-13 | `ci-green`, `docs-review` |
| REL-56 | Pin CI actions to commit SHAs | Claude | REL-55 | `ci-green`, `docs-review` |
| REL-32 | Phase 1 exit review and Phase 2 refinement | Claude | REL-31, REL-47, REL-55, REL-56 | `ci-green`, `docs-review` |
| REL-46 | Portfolio release: publish checklist, public repo, optional free-tier demo | You | REL-32, REL-61 | `owner-confirm` |

### REL-53: Phase 1 design: container diagram, API contract and data model; owner accepts ADR-0008

- Owner: Claude
- Depends on: REL-11
- Labels: phase-1, docs
- Paths: `docs/architecture/`

Acceptance:
- [ ] docs/architecture/containers.md shows every Phase 1 container (api, worker with sweeper, publisher, migrate, simulator, frontend with server routes, Postgres, Redis, optional Ollama) and what flows between them
- [ ] docs/architecture/api-contract.md lists every Phase 1 endpoint with auth, request, response, error shape, idempotency and pagination; the generated OpenAPI must match it
- [ ] docs/architecture/data-model.md defines payments (attempt_no, is_final, status_changed_at), payment_events (seq, attempt_no, published_at), idempotency_keys (unique key, request hash, in-progress state, expires_at) and payment_explanations, with indexes
- [ ] The owner has marked ADR-0008 Accepted, or the documents follow the owner's changes, before REL-14 starts

Steps:
1. **Write the container diagram** - Draw every Phase 1 container and the flows between them in `docs/architecture/containers.md`, matching `system-context.md`.
2. **Write the API contract** - List each Phase 1 endpoint with API-key auth, request and response fields, the shared error shape, idempotency rules and pagination in `docs/architecture/api-contract.md`.
3. **Write the data model** - Define tables, columns, constraints and indexes in `docs/architecture/data-model.md`, including attempt fields, the idempotency in-progress state and stored explanations.
4. **Check consistency with the lifecycle and ADRs** - Compare the three documents with `payment-lifecycle.md` and ADRs 0003, 0004, 0008 and 0009; fix any mismatch.
5. **Owner decision on ADR-0008** - The owner reviews ADR-0008 and marks it Accepted (or asks for changes, which are applied); the decisions index is updated.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-52: API foundations: shared error format and structured logging with correlation IDs

- Owner: Claude
- Depends on: REL-13
- Labels: phase-1, api
- Paths: `api/app/core/`

Acceptance:
- [ ] One JSON error shape for 400, 401, 404, 409, 422, 500 and 503 with the codes in api-contract.md, declared in the OpenAPI spec and the API contract (REL-53)
- [ ] Structured JSON logs carry a correlation ID from the request into payment events, the worker and the publisher
- [ ] The api writes one JSON line per request (time, method, path template, status, duration_ms, correlation_id) to stdout and appends it to `/var/log/relay/api-requests.jsonl` on the `api-logs` volume, which REL-51 reads for the API 5xx rate (docs/architecture/data-model.md)
- [ ] Tests cover the error shape and correlation ID propagation
- [ ] `X-Correlation-ID` rules as in api-contract.md
- [ ] The request-log file is size-capped with rotation (3 files of 10 MB) and compose caps container stdout logs
- [ ] The database engine and Redis client are created once at startup and reused (REL-12's `/health` builds them on every call); an invalid `X-Correlation-ID` is replaced, not rejected, as api-contract.md says

Steps:
1. **Write failing tests for errors and correlation IDs** - Cover the error body for each status and a correlation ID that propagates from the request to logs and a context object (the stored-event assertion moves to REL-16 and REL-17).
2. **Implement the error model and handlers** - Add a shared error schema and FastAPI exception handlers so every error response has the same shape.
3. **Add structured logging with correlation IDs** - Log JSON lines; accept or generate an X-Correlation-ID per request and pass it through events and background processes.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-14: Payment domain model and lifecycle state machine

- Owner: Claude
- Depends on: REL-13, REL-53
- Labels: phase-1, api
- Paths: `api/app/domain/`

Acceptance:
- [ ] Every transition in payment-lifecycle.md is allowed and every other one is rejected
- [ ] Money is integer minor units plus one of USD, EUR, GBP or JPY from a single currency table (ADR-0009); floats, non-positive amounts and other currencies are rejected
- [ ] Pure module with no database access
- [ ] A rejected transition changes nothing and writes no event
- [ ] Transitions are attempt-scoped: a result for a non-current attempt is rejected without changing state (ADR-0008)
- [ ] is_final is computed as in payment-lifecycle.md, including retries disabled for the static baseline
- [ ] Event `reason` values come from one shared enum per event type that matches data-model.md "Reason values" (ADR-0012)

Steps:
1. **Write failing tests for the transition table** - Parametrised pytest cases cover every allowed row of `payment-lifecycle.md` and assert every other pair is rejected, including the single retry from failed to routed. Include stale-attempt results and the is_final rule.
2. **Write failing tests for money rules** - Cases require integer minor units with a currency from the table USD, EUR, GBP (2 digits) and JPY (0 digits), and reject floats, negative or zero amounts and any other currency.
3. **Implement the money value object** - Add a `Money` type in `api/app/domain/` with validation; its tests pass.
4. **Implement the payment state machine** - Add the state enum and a pure transition function that takes the current state, attempt number and retry setting, returns the new state, attempt and is_final, or raises on an invalid or stale-attempt transition, enforcing one retry per payment.
5. **Confirm the module is pure and passes lint and types** - Check that `api/app/domain/` imports no database code and that ruff, mypy and pytest pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-15: Database schema and first Alembic migration (payments, payment_events, idempotency_keys)

- Owner: Claude
- Depends on: REL-14, REL-53
- Labels: phase-1, api, events
- Paths: `api/app/db/`, `api/migrations/`

Acceptance:
- [ ] alembic upgrade head and downgrade base both succeed on a fresh database
- [ ] Tables, columns, CHECK constraints and indexes match docs/architecture/data-model.md exactly (including the `payment_events` type CHECK with all 13 event types, `UNIQUE (payment_id, seq)`, the partial publisher index, `(type, processor, occurred_at)`, `payments(created_at DESC, id DESC)` and `idempotency_keys(expires_at)`); a database trigger makes `payment_events` append-only (UPDATE only sets `published_at` from null)
- [ ] amount_minor is BIGINT
- [ ] payment_events has a per-payment sequence number and a published_at marker
- [ ] Indexes on payments(status, processor, created_at) and payments(status, status_changed_at) exist in addition to those listed above
- [ ] payments has attempt_no, is_final and status_changed_at; payment_events has attempt_no
- [ ] `idempotency_keys` has `lease_token`, `lease_expires_at` and the stored-response columns
- [ ] All timestamps are timestamptz in UTC
- [ ] `payments.reference` (varchar(64), nullable, CHECK on letters, digits, `-`, `_` and `.`) and the `payment_events.reason` CHECK on the decided values exist; a test inserts an unknown reason and sees it rejected (ADR-0012)

Steps:
1. **Write failing migration and model tests** - Tests run `alembic upgrade head` then `downgrade base` on a fresh database, check `amount_minor` is BIGINT, and assert the code has no update or delete path for events.
2. **Define the SQLAlchemy models** - Add `payments`, `payment_events` and `idempotency_keys` models in `api/app/db/` following `docs/architecture/data-model.md`: BIGINT `amount_minor`, currency, status, processor, attempt_no, is_final, status_changed_at and UTC timestamps; a unique idempotency key with a request hash and an in-progress state.
3. **Generate the first reversible Alembic migration** - Create the migration in `api/migrations/` with working upgrade and downgrade steps, including an ordering column and a published marker for events.
4. **Make payment_events append-only in code** - Expose only an insert function for events: no update or delete path except setting `published_at` (REL-20); cover it with a test.
5. **Run the checks against a fresh database** - Upgrade and downgrade succeed in the compose Postgres, and the tests run against `relay_test`; `api-tests` and `api-lint` pass.
6. **Add the reference column and the reason check** - Add `payments.reference` and the `payment_events.reason` CHECK from data-model.md to the migration and models, with tests for an invalid reference and an unknown reason.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-16: Record every state change as a payment event in the same database transaction (transactional outbox)

- Owner: Claude
- Depends on: REL-15
- Labels: phase-1, events
- Paths: `api/app/services/`

Acceptance:
- [ ] A failed write leaves neither the state change nor its event
- [ ] Events for a payment are strictly ordered
- [ ] Test proves the invariant with a forced failure
- [ ] Each transition locks the payment row and checks the expected state and attempt before writing; a mismatch writes nothing (ADR-0008)
- [ ] Non-state-change events (attempt results, late result, redriven, explained) are appended through the same row-locked path; `payment.final` and `payment.retry_scheduled` are written in the same transaction as their state change; a concurrency test mixes state-change and non-state-change writers on one payment; every event stores `correlation_id`

Steps:
1. **Write failing tests for atomic state changes** - Tests cover state change plus event written together, and a forced failure mid-transaction leaving neither the new state nor its event.
2. **Implement the transition service** - In `api/app/services/`, apply a domain transition and insert its `payment_events` row inside one database transaction. It locks the payment row (`SELECT ... FOR UPDATE`) and verifies the expected state and attempt first.
3. **Guarantee strict event ordering per payment** - Assign a per-payment sequence under a row lock so events are ordered; a concurrency test confirms no gaps or duplicates.
4. **Prove the invariant with the forced-failure test** - Inject an error after the state update and assert rollback removes both writes; `api-tests` pass.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-17: POST /payments with API-key auth, validation and Idempotency-Key

- Owner: Claude
- Depends on: REL-16, REL-52
- Labels: phase-1, api
- Paths: `api/app/api/`, `api/app/idempotency/`

Acceptance:
- [ ] Missing or wrong API key returns 401
- [ ] Same key and body returns the original response; same key with a different body returns 409
- [ ] Invalid amount or currency returns 422 with a clear message
- [ ] A missing Idempotency-Key header returns 400
- [ ] Errors use the shared error format from REL-52
- [ ] Two concurrent requests with the same key create exactly one payment; the second gets 409 while the first is in progress, then the stored response
- [ ] Request bodies are compared by a hash of their canonical JSON
- [ ] Currencies outside USD, EUR, GBP and JPY return 422
- [ ] Behaviour, headers and error codes follow api-contract.md `POST /payments` and the data-model.md create flow: 401, 400 and 422 checks run before the key is claimed; a replay returns the stored first response with `Idempotent-Replayed: true`; an expired lease may be taken over by the same body, and a stalled first request cannot complete a taken-over key
- [ ] `POST /payments` accepts the optional `reference` (1 to 64 letters, digits, `-`, `_` and `.`), stores it and includes it in the request hash; an invalid reference returns 422 (ADR-0012)

Steps:
1. **Write failing API tests from the acceptance criteria** - Cover 401 for a missing or wrong key, 400 for a missing Idempotency-Key, replay of the same key and body, 409 for a changed body, and 422 for invalid amount or currency. Add a parallel-request test for one key and a 422 case for an unsupported currency. Add tests for lease takeover, a stalled first request waking after takeover (one payment only), a different body on a completed, in-progress and expired key, and the check order.
2. **Add API-key authentication** - Add a FastAPI dependency comparing the `X-API-Key` header to the key from the environment; unauthorised calls return 401.
3. **Implement request validation** - Define the request model using the domain `Money` rules so bad amounts or currencies return 422 with a clear message.
4. **Implement POST /payments with idempotency** - Create the payment and its `received` event in one transaction; claim the key first (unique insert with an in-progress state and request hash), store the response, and replay or reject repeats with 409 within 24 hours.
5. **Run the checks and review the OpenAPI output** - `api-tests` and `api-lint` pass and the generated OpenAPI shows the endpoint, header and error responses.
6. **Accept and store the optional reference** - Validate, store and return `reference` per api-contract.md, include it in the canonical body hash, and test valid, invalid and replayed requests with it.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-18: GET /payments/{id} with event timeline, and GET /payments with pagination and filters

- Owner: Claude
- Depends on: REL-17
- Labels: phase-1, api
- Paths: `api/app/api/`

Acceptance:
- [ ] Unknown id returns 404
- [ ] Timeline lists events in order with timestamps
- [ ] `GET /payments` supports repeatable `status`, `processor` A or B, `is_final`, `limit` 1-100 (default 20) and a keyset cursor on `(created_at, id)` descending returning `{items, next_cursor}`; a malformed cursor returns 400 `malformed_request`; responses include `display_status`, `status_changed_at` and `final_at`; `GET /payments/{id}` returns 404 for a non-UUID id and the full event list
- [ ] Both endpoints require the API key (ADR-0009)
- [ ] Responses include attempt_no and is_final so clients can show a Retrying state
- [ ] Responses include `reference` (null when the payment has none)

Steps:
1. **Write failing tests for the read endpoints** - Cover 404 for an unknown id, timeline order and timestamps, and list pagination plus filters by status and processor.
2. **Implement GET /payments/{id} with the event timeline** - Return the payment and its events ordered by sequence with timestamps; unknown ids return 404. Include attempt_no and is_final.
3. **Implement GET /payments with pagination and filters** - Add the repeatable `status` filter, `processor` (A or B), `is_final`, `limit` 1-100 (default 20) and a keyset cursor on `(created_at, id)` descending returning `{items, next_cursor}`; a malformed cursor returns 400 `malformed_request`. Items include `display_status`, `status_changed_at` and `final_at`, per api-contract.md.
4. **Document the responses and run the checks** - Ensure response models appear in OpenAPI; `api-tests` and `api-lint` pass.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-19: Simulated Processors A and B with latency, decline-rate and outage controls

- Owner: Claude
- Depends on: REL-12
- Labels: phase-1, simulator
- Paths: `simulator/processors/`, `simulator/app/`

Acceptance:
- [ ] Authorize and capture endpoints per processor
- [ ] Profiles configurable per processor; an outage can be switched on and off at runtime
- [ ] Seeded runs are reproducible
- [ ] Timeouts are a distinct injectable failure type alongside declines and outages
- [ ] Authorize and capture accept an idempotency key (payment id and attempt); a repeated key returns the first result without a new outcome
- [ ] Outcomes derive from the seed, payment id and attempt, not from arrival order (ADR-0009)
- [ ] The control API (outage on and off, profiles) is separate from the processor API and requires the API key
- [ ] Routes, bodies, responses and ports follow api-contract.md Simulator APIs (processor API 8100, control API 8101 with `X-API-Key`; profile body `latency_ms_p50`, `latency_ms_p95`, `decline_rate`, `timeout_rate`; `SIM_SEED` default 42; an injected timeout answers later than `PROCESSOR_TIMEOUT_SECONDS`)

Steps:
1. **Write failing simulator tests** - Cover authorize and capture per processor, configurable latency and decline rate, runtime outage toggle, and identical results for the same seed.
2. **Scaffold the simulator service** - Add a FastAPI app under `simulator/processors/` with Processor A and B routes and a compose service.
3. **Implement authorize and capture endpoints** - Each processor approves, declines with a reason, or times out according to its profile. Repeated calls with the same idempotency key return the first result.
4. **Add profiles and the runtime outage control** - Configure latency and decline rate per processor via environment or the control API (API key required), and switch an outage on and off without a restart.
5. **Make seeded runs reproducible** - Derive each outcome from a hash of the seed, payment id and attempt so arrival order does not matter; a test replays a seed in a different order and compares outcomes. `sim-tests` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-54: Simulator: seed processor draws on the payment reference (ADR-0012)

- Owner: Claude
- Depends on: REL-13, REL-19
- Labels: phase-1, simulator
- Paths: `simulator/processors/`, `simulator/app/`, `simulator/tests/`

Acceptance:
- [ ] The processor API accepts an optional `reference` in the authorize and capture body (1 to 64 characters: letters, digits, `-`, `_` and `.`); an invalid value returns 422 `validation_error`
- [ ] Every draw hashes the seed, processor, the reference when present (otherwise the payment id), attempt number and operation; the idempotency key stays `<payment_id>:<attempt_no>`
- [ ] Two payments with different ids and the same reference draw the same outcome; without a reference the behaviour and every existing test are unchanged
- [ ] The reference is part of the body, so a repeated key with a different reference is 409 `idempotency_key_reused`
- [ ] api-contract.md "Simulator APIs" matches the implementation

Steps:
1. **Write failing tests for reference-seeded draws** - In `simulator/tests/`, add tests that two payment ids with one reference get identical outcomes and latencies on both processors and operations, that no reference keeps today's payment-id draws, that an invalid reference is 422 and that a repeated key with a different reference is 409.
2. **Accept the optional reference in the processor API** - Add `reference` (optional, pattern `^[A-Za-z0-9._-]{1,64}$`) to the authorize and capture body in `simulator/app/apps.py` and to `ChargeRequest`, so it takes part in the stored-request comparison.
3. **Seed draws on the reference** - In `simulator/processors/outcomes.py` and `simulator.py`, pass the reference (or the payment id when absent) as the draw key; keep the idempotency key and stored results unchanged. Run `sim-tests` and `sim-lint`.
4. **Open pull request and pass review** - Open a pull request that links ADR-0012, run the checks, get an independent review and merge only after `gh pr checks` passes.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-20: Outbox publisher to Redis Streams (at-least-once)

- Owner: Claude
- Depends on: REL-16
- Labels: phase-1, events
- Paths: `api/app/outbox/`, `docker-compose.yml`

Acceptance:
- [ ] Every committed event is published at least once, including after a restart
- [ ] Published events are marked so they are not re-sent in normal operation
- [ ] The stream is trimmed with an approximate MAXLEN; recovery never depends on old stream entries (ADR-0008)

Steps:
1. **Write failing tests for at-least-once publishing** - Tests cover publishing every committed event, republishing after a restart before the mark is stored, and not resending marked events.
2. **Implement the outbox reader** - In `api/app/outbox/`, select unpublished events in order using `FOR UPDATE SKIP LOCKED`.
3. **Publish to Redis Streams and mark events** - Add each event to a stream and set the published marker after the write is acknowledged. Trim with an approximate MAXLEN.
4. **Run as a process in docker compose** - Add a `publisher` compose service (`python -m app.publisher`, one instance) with a heartbeat file; a restart test confirms nothing is lost.
5. **Run the checks** - `api-tests` pass against the compose Postgres and Redis.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-21: Async payment worker: routes, authorizes and captures via the processors

- Owner: Claude
- Depends on: REL-18, REL-19, REL-20, REL-54
- Labels: phase-1, events, routing
- Paths: `api/app/worker/`, `scripts/`, `docker-compose.yml`, `api/requirements.txt`

Acceptance:
- [ ] A received payment reaches captured, declined or failed without manual steps
- [ ] A duplicate or late message changes nothing: the worker acts only on trigger events and only when the payment's state and attempt still match under a row lock (ADR-0008)
- [ ] Every processor call is recorded as an event
- [ ] Uses a fixed processor until the router (REL-22) is wired in; graceful shutdown finishes or releases in-flight messages
- [ ] Processor calls carry the key `<payment_id>:<attempt_no>`
- [ ] Messages left pending by a crashed consumer are reclaimed with XAUTOCLAIM after an idle timeout
- [ ] A late processor result for an old attempt is recorded as an event only
- [ ] `scripts/smoke_stack.py` also creates a payment and waits for a final state
- [ ] Trigger events are `payment.received`, `payment.retry_scheduled` and `payment.redriven` (consumer group `processing`, stream `relay:payment-events`); events written: `payment.routed` (reason `static` until REL-22), `attempt.authorize_result` and `attempt.capture_result` (`data.result`, `latency_ms`), `attempt.late_result` (reason `stale_attempt`), and `payment.final` with `data.outcome` in the same transaction as the final state change; entry point `python -m app.worker`; until REL-22 retries are disabled, so every `failed` is final
- [ ] Processor calls send the payment's `reference` (ADR-0012)
- [ ] A processor result whose attempt or expected state no longer matches is written as `attempt.late_result` with reason `stale_attempt` or `after_timeout` and never dropped; tested with a fake processor, because the simulator never answers a timed-out key late (ADR-0012)
- [ ] `httpx` moves to `api/requirements.txt`, because the worker needs it at runtime; the worker exits non-zero on an unrecoverable error so `restart: unless-stopped` restarts it

Steps:
1. **Write failing tests for the worker lifecycle** - Cover a received payment reaching captured, declined or failed, duplicate and late messages changing nothing, an event per processor call, and reclaim of a crashed consumer's pending message.
2. **Implement the state-guarded stream consumer** - In `api/app/worker/`, consume the stream in a consumer group, act only on trigger events, lock the payment and check state and attempt before acting, and reclaim idle pending messages with XAUTOCLAIM.
3. **Implement route, authorize and capture** - Choose a processor (simple placeholder choice until the router lands), call the simulator with the key `<payment_id>:<attempt_no>`, and record each call and result as an event.
4. **Add the worker to compose and run end to end** - The stack starts healthy and a payment created through the API reaches a final state; `api-tests` and `stack-up` pass.
5. **Send the reference and record late results** - Send `reference` on authorize and capture; record every mismatched result as `attempt.late_result` (`stale_attempt` or `after_timeout`) and test both with a fake processor.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-50: Timeout sweeper: fail timed-out attempts and re-drive stalled payments

- Owner: Claude
- Depends on: REL-21
- Labels: phase-1, events
- Paths: `api/app/worker/`

Acceptance:
- [ ] Timeouts apply after `PROCESSOR_TIMEOUT_SECONDS` + `SWEEP_TIMEOUT_GRACE_SECONDS` (default 5): a payment in routed or authorized past that moves to failed with an event
- [ ] Only failures from routed are then eligible for the single retry
- [ ] The sweep is idempotent and safe to run concurrently
- [ ] A payment in received, or failed and retrying, is re-driven only when `status_changed_at` and `last_driven_at` are both older than `REDRIVE_AFTER_SECONDS`; `last_driven_at` is set and `payment.redriven` written in one transaction, without a state change; the sweep runs every `SWEEP_INTERVAL_SECONDS`; a test runs the sweep twice inside the threshold and sees one `payment.redriven`
- [ ] A lost stream entry (deleted in the test) still ends with a final payment
- [ ] A result for the current attempt that arrives after the sweeper failed it is recorded as `attempt.late_result` with reason `after_timeout` (ADR-0012)

Steps:
1. **Write failing tests for stuck payments** - Cover routed and authorized timeouts, the event written, re-drive of stalled received and retrying payments, a deleted stream entry, and repeated sweeps.
2. **Implement the sweep** - Periodically select overdue payments using the (status, status_changed_at) index; move timed-out attempts to failed through the domain state machine and republish triggers for stalled received or retrying payments.
3. **Wire it into the worker** - Run the sweep on an interval in the worker and log each move with its correlation ID.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-47: Idempotency key expiry and cleanup job

- Owner: Claude
- Depends on: REL-17, REL-50
- Labels: phase-1, api
- Paths: `api/app/jobs/`, `api/app/worker/`

Acceptance:
- [ ] A key past `expires_at` starts a new payment even with a different body; before expiry a different body returns 409 `idempotency_key_reused`
- [ ] A scheduled cleanup deletes only expired keys
- [ ] Tests use a controllable clock

Steps:
1. **Write failing tests with a controllable clock** - Cover reuse after 24 hours, 409 before expiry and cleanup deleting only expired keys.
2. **Implement expiry checks** - Verify the takeover implemented in REL-17 with the controllable clock.
3. **Implement the cleanup job** - Delete expired keys using the expires_at index; the cleanup runs in the worker's sweeper loop.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-51: Guardrail metrics: latency percentiles, error rate, publish lag, per-processor success

- Owner: Claude
- Depends on: REL-20, REL-21
- Labels: phase-1, testing
- Paths: `api/app/reporting/`, `docker-compose.yml`

Acceptance:
- [ ] P50, P95 and P99 processing latency, publish lag and per-processor success rate are computed from stored events; the API 5xx rate is computed from the api's structured request logs (REL-52, data-model.md)
- [ ] `docker compose run --rm reporting` (a `tools`-profile service on the api image mounting `api-logs` read-only) prints them for a run and REL-30 uses them
- [ ] Only final payments count; payments not final past the sweeper threshold are reported (target zero)
- [ ] The report gives time to explanation per source with the fallback rate and backlog, and revenue recovered split by rescue path, for REL-30 (ADR-0012)

Steps:
1. **Write failing tests on fixed event data** - Compute each metric from a small known set of events and assert exact values.
2. **Implement the calculations** - Derive latency from event timestamps, publish lag from published_at, and success rate per processor.
3. **Add the report command** - Add `python -m app.reporting` in `api/app/reporting/`, run through `docker compose run --rm reporting`, that prints a table for the last run and saves it as JSON for the demo results.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-22: Rule-based router with health tracking, failover and one retry on the other processor

- Owner: Claude
- Depends on: REL-21
- Labels: phase-1, routing
- Paths: `api/app/routing/`

Acceptance:
- [ ] Rolling error rate per processor; above the threshold new payments go to the other processor
- [ ] A failed payment is retried once on the other processor
- [ ] Each routing decision and its reason is an event
- [ ] GET /processors/health returns each processor's recent error rate and routing state
- [ ] Only a technical failure from routed is retried; declines and authorized-to-failed are never retried
- [ ] Health comes from recent attempt events in PostgreSQL, so the worker and the API agree and a restart loses nothing (ADR-0008)
- [ ] ROUTING_STRATEGY=static sends every payment to Processor A with no failover and no retry (baseline, ADR-0009); `rules` is the default
- [ ] GET /processors/health requires the API key
- [ ] Health definition: an attempt is `payment.routed`; an error is `payment.failed` with reason `timeout`, `outage` or `capture_failed` (including sweeper timeouts); declines are never errors; states `preferred`, `avoided` and `unknown`; defaults 60 s window, 5 attempts, 0.5 error rate
- [ ] Routing prefers A and uses B only when A is `avoided` and B is not; if both are avoided or unknown, the payment stays on A

Steps:
1. **Write failing router tests** - Cover a rolling error rate per processor, switching new payments above the threshold, one retry on the other processor, and a routing event with its reason.
2. **Implement rolling health tracking** - In `api/app/routing/`, compute a windowed error rate per processor from recent attempt events in PostgreSQL.
3. **Implement threshold routing and failover** - Send new payments to the healthy processor when the other exceeds the configured error-rate threshold.
4. **Implement the single retry** - When a routed attempt fails technically, move failed to routed on the other processor, once per payment, and never after a decline.
5. **Record decisions as events and wire into the worker** - Write each routing decision and reason as a payment event, use the router in the worker, and confirm `api-tests` pass.
6. **Add the routing strategy switch** - Read `ROUTING_STRATEGY` (`rules` by default; `static` for the baseline: Processor A only, no failover, no retry) and test both.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-23: Synthetic load generator using only the public API, with scripted scenarios

- Owner: Claude
- Depends on: REL-18, REL-19
- Labels: phase-1, simulator
- Paths: `simulator/generator/`

Acceptance:
- [ ] Configurable rate and payment mix
- [ ] Named deterministic scenarios (normal day, Processor A outage)
- [ ] Uses only the public payment API and the simulator control API; no database, Redis or internal access
- [ ] Runs on the host against `http://127.0.0.1:8000` and `http://127.0.0.1:8101`, reading `RELAY_API_KEY` from `.env`; code in `simulator/generator/` (standard library only); tests run under `sim-tests`
- [ ] Every generated payment gets a deterministic `reference` `<scenario>-<seed>-<index>`, so runs with one seed repeat payment by payment (ADR-0012)

Steps:
1. **Write failing generator tests** - Cover configurable rate and payment mix, deterministic named scenarios, and that only HTTP calls to the public API are made.
2. **Implement the API client** - In `simulator/generator/`, create payments with unique, seed-derived Idempotency-Keys through the public payment API only, with no database or Redis access.
3. **Implement rate and mix controls** - Configure payments per second and the mix of amounts and currencies, driven by a seed.
4. **Add the named scenarios** - Define `normal-day` and `processor-a-outage` scenarios that switch the outage through the simulator control API at fixed points.
5. **Add a command-line entry point and run the checks** - Run a scenario with one command; `sim-tests` pass.
6. **Give every payment a deterministic reference** - Generate `reference` as `<scenario>-<seed>-<index>` and test that two runs of a scenario produce the same references in the same order.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-24: Rule-based payment explainer (always available fallback)

- Owner: Claude
- Depends on: REL-18, REL-19
- Labels: phase-1, ai
- Paths: `api/app/explain/`

Acceptance:
- [ ] Produces a plain-language cause and next step for every final outcome the simulator can create, including a decline, a timeout, an outage, a failed capture, a late result after retry and a payment captured after retry
- [ ] Deterministic output for tests
- [ ] Each explanation carries `cited_event_seqs`
- [ ] A late approval after a timeout is explained as an orphaned authorization (ADR-0012)

Steps:
1. **Write failing explainer tests** - Enumerate each outcome the simulator can create (decline reasons, timeout, outage, failed capture, late result after retry, captured after retry, stalled and re-driven) and expect a fixed cause and next step for each.
2. **Implement the timeline analysis** - In `api/app/explain/`, derive the failure pattern from the ordered events of a payment.
3. **Write the plain-language templates** - Map each pattern to a short cause and recommended next step, avoiding jargon.
4. **Prove determinism and coverage** - Same timeline gives identical text and every simulator pattern is covered; `api-tests` pass.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-25: LLM explainer via local Ollama with fallback; explanations stored at final failure; GET /payments/{id}/explanation

- Owner: Claude
- Depends on: REL-24, REL-10, REL-21
- Labels: phase-1, ai, api
- Paths: `api/app/explain/`, `api/app/worker/`, `api/migrations/`, `api/app/api/`, `api/app/explainer/`, `docker-compose.yml`

Acceptance:
- [ ] Prompt uses only the payment's own timeline (no invented facts; cites event seqs)
- [ ] Model unavailable or slow falls back to the rule-based explainer and says so
- [ ] Tests run without a model; ADR 0005 moved to Accepted
- [ ] The explanation is labelled with its source (model or rules) and shown next to the raw timeline, never instead of it
- [ ] An explanation is generated when a payment reaches a final failure, outside the payment-processing path, and stored in `payment_explanations` (ADR-0009) with columns `source` (model or rules), `model`, `text`, `cited_event_seqs`, `trigger` (final_failure, on_request or regenerate), `fallback_reason`, `final_event_at` and `generated_at`; consumer group `explanations` on `payment.final` with outcome declined or failed; a partial unique index with `ON CONFLICT DO NOTHING`, and `payment.explained` written only on insert; GET returns 409 `payment_not_final` for a non-final payment; `on_request` generation for a final payment without one
- [ ] GET returns the stored explanation (and fills a missing one for a final payment); `POST /payments/{id}/explanation/regenerate` makes a new one (201); both require the API key (ADR-0012)
- [ ] Time to explanation is `generated_at - final_event_at`, recorded for the north-star metric
- [ ] The API reaches Ollama at `OLLAMA_URL`, default `http://host.docker.internal:11434` (the host install)
- [ ] The explainer uses `granite3.3:2b` (Apache 2.0, ADR-0010); ADR-0005 moves to Accepted citing ADR-0010
- [ ] A model answer citing a seq outside the payment's timeline is rejected and the rules explainer is used with `fallback_reason=citation_check_failed`
- [ ] Automatic explanations run in their own `explainer` container (api image, `python -m app.explainer`, consumer group `explanations`); a test proves payments still finalize within the normal time while a fake model hangs (ADR-0012)
- [ ] The prompt never includes the free-text `description`; a test proves it (ADR-0012)
- [ ] The model quality check also compares each model explanation's stated cause with the rules explainer's cause for the same timeline (ADR-0012)

Steps:
1. **Write failing tests using a fake model client** - Cover grounded prompts citing event seqs, fallback on unavailable or slow model with a visible label, and the endpoint responses, all without a running model. Add a test that a redelivered `payment.final` creates no second explanation row or `payment.explained` event.
2. **Build the grounded prompt** - Compose the prompt from only the payment's own timeline and require the answer to cite event seqs.
3. **Implement the Ollama client with timeout and fallback** - Call the local Ollama HTTP API with a configurable timeout; on error or timeout return the rule-based explanation labelled as fallback.
4. **Generate and store explanations at final failure** - Add a `payment_explanations` table and migration; when a payment becomes final with a failure, queue generation outside the payment path and store the result with its source and time.
5. **Add GET /payments/{id}/explanation** - Return the stored text plus its source (model or fallback), model name, cited event seqs and generation time; GET only reads, except that it fills a missing explanation for a final payment (`trigger=on_request`); regeneration is the POST endpoint in REL-25.10 (ADR-0012); unknown ids return 404 and a non-final payment 409.
6. **Accept ADR 0005 and run the checks** - Move ADR 0005 to Accepted citing ADR-0010 (model `granite3.3:2b`, Apache 2.0); `api-tests` pass with no model running.
7. **Run the model quality check** - Manual check outside CI: 10 fixed timelines, every citation must be valid in all 10; otherwise switch to the rules text and consider `granite3.3:8b`. Record the result.
8. **Run explanations in their own explainer container** - Add `python -m app.explainer` (consumer group `explanations`) as its own compose service from the api image, and prove with a hanging fake model that payments still finalize on time.
9. **Move regeneration to POST and keep the description out of the prompt** - Implement `POST /payments/{id}/explanation/regenerate`, keep GET read-only apart from filling a missing explanation, and test that `description` never reaches the prompt.
10. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-48: Full local stack in docker compose with health checks and graceful shutdown

- Owner: Claude
- Depends on: REL-20, REL-21, REL-25
- Labels: phase-1, infra
- Paths: `docker-compose.yml`, `api/`, `simulator/`

Acceptance:
- [ ] From a clean clone, docker compose up -d --wait starts API, worker, publisher, simulator, Postgres, Redis and frontend healthy
- [ ] Each long-running process has a health or readiness check; worker and publisher shut down gracefully
- [ ] Containers reach the host Ollama through `host.docker.internal` (mapped to `host-gateway` for Linux CI); the optional `--profile llm` container publishes no host port, so it never clashes with a host install
- [ ] The migrate service completes before api, worker and publisher start
- [ ] Redis runs with append-only persistence (ADR-0008)
- [ ] Every long-running service (api, worker, explainer, publisher, simulator, frontend) has `restart: unless-stopped`, and each service receives only the environment variables it uses instead of the whole env file (ADR-0012)

Steps:
1. **Add the remaining services to compose** - Verify and complete the worker, publisher and simulator service definitions: `.env` variables, `depends_on` migrate, Redis append-only, Ollama profile.
2. **Add health and readiness checks** - Give every service a healthcheck compose can wait on; worker and publisher write a heartbeat file each loop and the health check fails if it is stale.
3. **Handle shutdown signals** - Worker and publisher stop taking new messages and finish or release in-flight ones on SIGTERM.
4. **Add the Ollama profile and verify from a clean clone** - Put Ollama behind --profile llm without a host port and map host.docker.internal to host-gateway, then clone fresh and confirm docker compose up -d --wait is healthy and `scripts/smoke_stack.py` passes. Document `ollama pull granite3.3:2b` for the `llm` profile.
5. **Restart policies and per-service environment** - Add `restart: unless-stopped` to every long-running service, replace the shared env file with per-service variables, and verify a killed worker comes back and finishes its pending messages.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-26: Frontend: payments list with status, processor and amount

- Owner: Claude
- Depends on: REL-18, REL-13
- Labels: phase-1, ui
- Paths: `frontend/app/`, `docs/architecture/`, `frontend/proxy.ts`, `.mcp.json`

Acceptance:
- [ ] Before UI code: docs/architecture/dashboard-spec.md written from the workspace DASHBOARD-SPEC template (decision question, audience, freshness, states); frontend-design and ui-polish-audit skills follow it
- [ ] Shows latest payments with auto-refresh
- [ ] Amounts formatted from minor units and currency
- [ ] Works at phone width
- [ ] All data comes through Next.js server routes that add the API key; the browser never receives it (ADR-0009)
- [ ] A failed payment that is not final shows as Retrying, with a text label
- [ ] Frontend server routes `/api/payments`, `/api/payments/[id]`, `/api/payments/[id]/explanation`, `/api/processors/health` and `/api/demo/outage` use the env names `API_URL`, `SIMULATOR_CONTROL_URL` and server-only `RELAY_API_KEY` (never `NEXT_PUBLIC_`)
- [ ] The UI uses the API's `display_status`
- [ ] Every frontend server route rejects a `Host` other than `localhost` or `127.0.0.1` with 403, through a Next.js request guard (`frontend/proxy.ts`, the Next.js 16 name for middleware) (ADR-0012)
- [ ] The project-scoped `.mcp.json` also offers the Chrome DevTools MCP server (exact version, isolated profile) for console, network and performance debugging; the page's console shows no errors on load

Steps:
1. **Write docs/architecture/dashboard-spec.md** - Fill the dashboard spec template with the decision question, audience, freshness and states before any UI code.
2. **Write failing component and formatting tests** - Cover amount formatting from minor units and currency, status labels, and empty, loading and error states.
3. **Build the payments list page** - In `frontend/app/`, show status (Retrying for non-final failures), processor, amount and time for the latest payments, fetched through a server route, with a status label not relying on color alone. Use the API's `display_status` and the server routes `/api/payments` and `/api/payments/[id]`.
4. **Add auto-refresh** - Poll the list endpoint on an interval and show when it last updated.
5. **Check phone width and run the checks** - Verify the layout with screenshots at desktop and phone width; `web-check` passes.
6. **Add the host guard for server routes** - Add the request guard that returns 403 for any `Host` other than `localhost` or `127.0.0.1`, with a unit test.
7. **Add Chrome DevTools MCP for browser debugging** - Added 2026-10-27 (owner's tooling review): add the Chrome DevTools MCP server (Apache-2.0, exact version pinned) next to Playwright in the project-scoped `.mcp.json` with an isolated profile, and use it to check the list page's console, network requests and performance; Playwright stays the test runner.
8. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-27: Frontend: payment detail with timeline, explanation and processor health

- Owner: Claude
- Depends on: REL-26, REL-25, REL-22
- Labels: phase-1, ui
- Paths: `frontend/app/`, `api/app/explain/`, `docs/evaluation/`

Acceptance:
- [ ] Timeline, explanation (with model or fallback label) and current processor health are visible
- [ ] Clear empty and error states
- [ ] Shows each attempt with its processor, and the stored explanation's source and generation time
- [ ] Data comes through server routes only
- [ ] Frontend server routes `/api/payments`, `/api/payments/[id]`, `/api/payments/[id]/explanation`, `/api/processors/health` and `/api/demo/outage` use the env names `API_URL`, `SIMULATOR_CONTROL_URL` and server-only `RELAY_API_KEY` (never `NEXT_PUBLIC_`)
- [ ] The UI uses the API's `display_status`
- [ ] When the model's stated cause differs from the rules explainer's cause for the same timeline, the rules text is stored and shown with `fallback_reason = cause_mismatch` (ADR-0013); a test with a fake model that names a different cause proves it, and the page shows the source label and fallback reason

Steps:
1. **Write failing tests for the detail page states** - Cover timeline, explanation with model or fallback label, processor health, and empty and error states.
2. **Build the detail page and timeline** - Add a route under `frontend/app/` that shows events in order with timestamps and monospace ids.
3. **Show the explanation with its source label** - Fetch the explanation endpoint and label it as model-generated or rule-based fallback.
4. **Use the rules text when the model's cause disagrees** - In `api/app/explain/generate.py`, compare the model answer's `cause` with the rules explainer's cause for the same timeline and fall back to the rules text with `fallback_reason = cause_mismatch` when they differ (ADR-0013); test it with a fake model, then rerun `python -m app.explain.quality` on the host and record the result in `docs/evaluation/results.md`.
5. **Show current processor health** - Display each processor's current status from the routing health data.
6. **Add empty and error states, check phone width** - Handle unknown payment, failed fetch, slow explanation and payment not final (409 `payment_not_final`); request the explanation only for declined, failed or retried payments; `web-check` passes.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-28: Demo controls: inject and clear a Processor A outage from the UI or CLI

- Owner: Claude
- Depends on: REL-19, REL-26
- Labels: phase-1, ui, simulator
- Paths: `frontend/app/`, `simulator/`, `frontend/proxy.ts`

Acceptance:
- [ ] One action starts and stops an outage
- [ ] The control uses the simulator control API, which requires the API key
- [ ] The browser never holds the API key; outage controls go through a server-side route
- [ ] Frontend server routes `/api/payments`, `/api/payments/[id]`, `/api/payments/[id]/explanation`, `/api/processors/health` and `/api/demo/outage` use the env names `API_URL`, `SIMULATOR_CONTROL_URL` and server-only `RELAY_API_KEY` (never `NEXT_PUBLIC_`)
- [ ] The outage switch is `POST /api/demo/outage` only, and it rejects requests that are not same-origin (`Sec-Fetch-Site: same-origin` or a matching `Origin`) with 403 (ADR-0012)

Steps:
1. **Write failing tests for outage control** - Cover start and stop of an outage via the API key protected control, and rejection without the key.
2. **Call the REL-19 control API from a server route** - Call the REL-19 control API (`POST /control/processors/a/outage`, `GET /control/processors`) from the `/api/demo/outage` server route with `SIMULATOR_CONTROL_URL` and the key.
3. **Add the UI control** - Add a start and stop button in `frontend/app/` that calls the control through a server-side route so the key stays out of the browser.
4. **Show the current outage state** - Display whether the outage is active and update after each action.
5. **Run the checks** - `web-check` and `sim-tests` pass.
6. **Require a same-origin POST for the outage switch** - Make the outage route POST-only and reject cross-site requests with 403 in the request guard, with unit tests for same-origin, cross-site and missing headers.
7. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-29: Playwright smoke tests in CI against docker compose

- Owner: Claude
- Depends on: REL-28, REL-48, REL-27
- Labels: phase-1, testing
- Paths: `frontend/tests/`, `.github/workflows/`

Acceptance:
- [ ] Create a payment, open its detail, see timeline and explanation
- [ ] Runs in CI on every pull request
- [ ] An accessibility check (axe, per ADR-0007) reports no serious or critical violations on the list and detail pages
- [ ] A test confirms the API key never appears in browser requests or page source
- [ ] Setup installs frontend dependencies and the Playwright browser (`npx playwright install chromium`) locally and in CI
- [ ] Tests show that a foreign `Host` header and a cross-site POST to `/api/demo/outage` are rejected with 403 (ADR-0012)
- [ ] The `e2e` check runs `npm --prefix frontend run e2e`, a script that points Playwright at `frontend/playwright.config.ts`

Steps:
1. **Write the failing end-to-end tests** - In `frontend/tests/`, script create a payment, open its detail, and see the timeline and explanation.
2. **Configure Playwright against docker compose** - Add config and a start script that installs the Playwright browser, brings up the stack and waits for health.
3. **Make the tests stable** - Use the fallback explainer and seeded data so results do not depend on a model or timing.
4. **Add the CI job** - Add a job under `.github/workflows/` running Playwright on every pull request, uploading traces on failure.
5. **Run e2e locally and in CI** - `e2e` passes locally and the latest CI run is green.
6. **Add accessibility and key-exposure checks** - Run axe on the list and detail pages and assert no serious or critical violations; assert the API key never appears in browser traffic or page source.
7. **Test the host and same-origin guards** - Add Playwright tests that send a foreign `Host` and a cross-site POST to the outage switch and expect 403.
8. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-30: Scripted outage demo and metrics against a static-routing baseline

- Owner: Claude
- Depends on: REL-22, REL-23, REL-25, REL-48, REL-51, REL-50
- Labels: phase-1, testing, docs
- Paths: `simulator/demo/`, `docs/evaluation/`, `api/app/demo/`, `api/app/reporting/`, `api/tests/`, `scripts/`, `simulator/generator/`

Acceptance:
- [ ] One command runs baseline and Relay routing over the same seeded outage scenario
- [ ] Reports success-rate uplift, simulated revenue recovered and median time to explanation
- [ ] Results saved under docs/evaluation/
- [ ] The baseline runs the same seeded scenario with ROUTING_STRATEGY=static: Processor A only, no failover, no retry (ADR-0009)
- [ ] Metric definitions (median time to explanation, revenue recovered per currency) are written next to the results
- [ ] Median time to explanation is compared with the 2-hour manual-reconstruction baseline, stated as an assumption (ADR-0009)
- [ ] Results state that the data is synthetic and the baseline is static routing (risk R10)
- [ ] Each run starts from a documented reset that empties the payments tables, deletes `relay:payment-events` and recreates the groups, truncates the request log, and resets simulator outage and profiles
- [ ] Three runs with one seed agree within 1 percentage point on success rate and 1% on revenue recovered; the tolerance is printed with the results
- [ ] The baseline and Relay runs use the same deterministic references; each run's per-reference outcomes are saved before the next reset and compared payment by payment (ADR-0012)
- [ ] The reset uses `TRUNCATE ... RESTART IDENTITY CASCADE`, because the append-only trigger rejects DELETE, and a test proves the reset empties every table
- [ ] Revenue recovered is also split by rescue path (`payment.routed` reason `retry` or `failover`), and time to explanation is reported per source (model and rules) with the fallback rate and the largest backlog, after warming the model (ADR-0012)
- [ ] The reset and the routing-mode switch live where they can reach the system: the reset is an api-image tool (`python -m app.demo.reset`, run like the `reporting` service) tested against the test database by `api-tests`, and one host script (`scripts/outage_demo.py`, standard library, like `smoke_stack.py`) runs the compose steps, the generator and the reporting tool; the load generator keeps its public-API-only access
- [ ] Explanation fallbacks are reported per reason (`cause_mismatch` separately from model unavailable, timeout, error and citation failures), so a model that disagrees is not counted as a model outage (ADR-0013)
- [ ] Before an outage switch the load generator waits until every payment already sent is final, so the outage boundary falls between the same two payments in every run (owner decision 2026-11-01, after payment 099 raced the switch)
- [ ] After the outage ends the generator also waits one health window before the next payment, so recovery starts from a clean health state in every run; the results state this and report Relay's recovery lag (seconds until Processor A is no longer avoided) per run (owner decision 2026-11-02, after recovery routing varied with wall-clock time)
- [ ] The demo runs with `HEALTH_WINDOW_SECONDS=120` (the default config stays 60 s) so the outage sits well inside the health window, saves each payment's processor and routed reasons with its outcome, and states the window in the results (owner decision 2026-11-02, after two payments at the window edge varied)

Steps:
1. **Define the metrics and write failing tests** - Define success-rate uplift, simulated revenue recovered and median time to explanation, and test the calculations on small fixed inputs.
2. **Implement a static-routing baseline mode** - Run the same scenario with `ROUTING_STRATEGY=static` (Processor A only, no failover, no retry), restarting `api` and `worker` with the new `ROUTING_STRATEGY` between modes.
3. **Script the run in simulator/demo/** - In `simulator/demo/`, one command resets the database, runs the seeded outage scenario with baseline routing, resets again, runs it with Relay routing, and collects outcomes through the public API.
4. **Compute and save the results** - Produce a results table and save it as markdown and JSON under `docs/evaluation/`.
5. **Verify reproducibility** - Run three times with the same seed and confirm the results agree within the stated tolerance; `stack-up` and `sim-tests` pass.
6. **Pair runs by reference and report per rescue path and per explanation source** - Save each run's per-reference outcomes, compare baseline and Relay payment by payment, and add the retry/failover split and the per-source time to explanation to the results.
7. **Make the reset TRUNCATE-based and test it** - Implement the reset with `TRUNCATE ... RESTART IDENTITY CASCADE`, delete the stream and recreate the groups, and test that every table is empty afterwards.
8. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.
9. **Put the reset in the api image and the orchestration on the host** - Add `api/app/demo/reset.py` (TRUNCATE ... RESTART IDENTITY CASCADE, delete the stream and recreate the groups, truncate the request log) with an `api-tests` test that every table is empty afterwards; add `scripts/outage_demo.py` on the host that resets, switches `ROUTING_STRATEGY` by restarting `api` and `worker`, runs the generator and the reporting tool, and saves the results.
10. **Split explanation fallbacks by reason** - Extend `api/app/reporting/metrics.py` so the explanation metrics report the fallback count per `fallback_reason`, with `cause_mismatch` separate (ADR-0013), and test it on fixed inputs.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-31: Showcase README: results, architecture diagram, screenshots or GIF

- Owner: Claude
- Depends on: REL-30, REL-29, REL-27
- Labels: phase-1, docs
- Paths: `README.md`, `docs/`

Acceptance:
- [ ] README sections filled with real results from REL-30
- [ ] Architecture diagram matches the code
- [ ] How to run works on a clean clone
- [ ] README states that all data is synthetic and the comparison baseline is static routing (risk R10)
- [ ] The README reports revenue recovered by the retry and by failover separately, and time to explanation per source (ADR-0012)

Steps:
1. **Fill README sections with real results** - Insert the numbers and links from `docs/evaluation/` and remove placeholders.
2. **Create the architecture diagram** - Draw a diagram of the API, worker, simulator, outbox, Redis, Postgres, Ollama and UI, and check each box against the code.
3. **Add screenshots or a GIF** - Capture the payments list, detail with explanation and the outage demo.
4. **Write and test How to run on a clean clone** - Clone fresh, follow the instructions exactly, and fix any gap.
5. **Review links and accuracy** - The owner reads the documents; links resolve and claims match the results.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-55: Static security analysis with Semgrep in CI

- Owner: Claude
- Depends on: REL-13
- Labels: infra, security
- Paths: `.github/workflows/`, `docs/decisions/`, `AGENTS.md`

Acceptance:
- [ ] Added 2026-10-27 from the owner's tooling review: Semgrep Community Edition (open source) scans the Python (`api/`, `simulator/`, `scripts/`) and TypeScript (`frontend/`) code on every pull request and push to `main`
- [ ] ADR-0007 is amended (owner-approved) with Semgrep: exact version, licence checked at that version, the rule sets used and why
- [ ] The CI job uses an exactly pinned Semgrep image or package, sets `timeout-minutes` and fails on findings of ERROR severity
- [ ] The rule sets cover Python, TypeScript and the OWASP Top Ten; every existing finding is fixed or suppressed inline with a written reason, so the first run on `main` is clean
- [ ] AGENTS.md lists the local command that runs the same scan

Steps:
1. **Amend ADR-0007 with Semgrep** - Record the exact Semgrep version, its licence at that version, the rule sets and the CI cost; the owner approves the amendment.
2. **Add the Semgrep CI job and the local command** - Add a `semgrep` job to `.github/workflows/ci.yml` with an exact pin and `timeout-minutes`, and the same scan as a documented local command.
3. **Triage the first findings** - Fix each finding, or suppress it inline with a reason a reviewer can check; the first run on `main` is clean.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-56: Pin CI actions to commit SHAs

- Owner: Claude
- Depends on: REL-55
- Labels: infra, security
- Paths: `.github/workflows/`, `docs/decisions/`

Acceptance:
- [ ] Added 2026-10-28: the owner decided to pin every GitHub Action in `.github/workflows/` to a full commit SHA, with the release tag in a trailing comment (`uses: actions/checkout@<40-hex sha> # v7.x.y`)
- [ ] Each SHA is resolved from the action's official repository for the tag in use and recorded with its tag; no third-party mirror
- [ ] The inline `nosemgrep: github-actions-mutable-action-tag` suppressions from REL-55 are removed and the Semgrep job still passes
- [ ] ADR-0007 is amended: actions are pinned to SHAs, and updates are a reviewed edit (tag comment plus SHA) checked by the Semgrep rule
- [ ] Every CI job still passes on the pull request

Steps:
1. **Resolve the commit SHAs** - For each action and tag in use, read the tag's commit SHA from the official repository (`gh api repos/<owner>/<repo>/commits/<tag>`).
2. **Pin the actions and remove the suppressions** - Replace each `@vN` with the SHA and a `# vN.x.y` comment, remove the `nosemgrep` lines, and run the Semgrep scan locally.
3. **Amend ADR-0007** - Record the pinning rule and how updates are made and reviewed.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-32: Phase 1 exit review and Phase 2 refinement

- Owner: Claude
- Depends on: REL-31, REL-47, REL-55, REL-56
- Labels: phase-1, docs
- Paths: `docs/`, `HANDOFF.md`

Acceptance:
- [ ] Every Phase 1 exit criterion checked with evidence
- [ ] Risk register, ADR statuses and process log updated
- [ ] Phase 2 tasks refined in this plan and re-synced to issues
- [ ] Risks R1 and R5 reassessed with implementation evidence; the event schema reviewed against Phase 2 consumers
- [ ] A forced failure between state change and publish shows no lost or duplicated events (ADR-0003 validation)
- [ ] From a clean clone, docker compose up -d --wait is healthy
- [ ] ADR-0008 and ADR-0009 validated with implementation evidence (duplicate delivery, consumer crash, late result, concurrent idempotency, lost stream entry, idempotency lease takeover and the sweeper re-driving a stalled payment once per threshold)
- [ ] CI minute use and the manual merge gate reviewed (risk R12)
- [ ] api-contract.md, data-model.md and containers.md are reconciled with the implementation and the generated OpenAPI (differences recorded)
- [ ] `maintenance/test-project-hygiene.ps1` passes for Relay, and the `plan-review` skill runs again with checklist items PR-29 to PR-36 before Phase 2 is refined

Steps:
1. **Check each Phase 1 exit criterion with evidence** - For every exit criterion in the roadmap, record evidence such as a command output, CI run link or test name.
2. **Update the risk register and ADR statuses** - Reassess R1 and R5 with implementation evidence, and update ADR statuses (including 0005).
3. **Update the process log and README** - Add the phase summary and lessons to `docs/delivery/process-log.md` and refresh the README status.
4. **Refine Phase 2 tasks and subtasks in this plan** - Adjust requirements, dependencies and subtasks for Phase 2 using what was learned.
5. **Re-sync issues and regenerate the delivery plan** - Regenerate `docs/delivery/delivery-plan.md`, sync issues from the plan, and confirm the owner has reviewed the documents.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-46: Portfolio release: publish checklist, public repo, optional free-tier demo

- Owner: You
- Depends on: REL-32, REL-61
- Labels: docs, infra
- Paths: `README.md`, `LICENSE`

Acceptance:
- [ ] User runs /publish-project relay and approves going public
- [ ] Any demo hosting is free tier and recorded in an ADR
- [ ] The hosting ADR compares the free tiers of Vercel or Cloudflare (frontend) and Neon or Supabase (managed PostgreSQL) with keeping the demo on Docker Compose, and keeps the demo read-only (ADR-0012) (owner's tooling review, 2026-10-27)
- [ ] Before going public, the owner reviews commit author emails in history (private-phase commits use the personal Gmail address) and decides whether to accept or rewrite them
- [ ] Once public, branch protection requiring CI is turned on (risk R12)
- [ ] A public demo runs read-only (no outage switch, no regeneration, rate-limited), with its own authentication decided in its hosting ADR (ADR-0012)

Steps:
1. **Run the publish checklist** - Run `/publish-project relay` and read its checklist findings.
2. **Fix any checklist findings** - Resolve items such as secrets, licence, README and history; rerun until it passes. Include the commit author email review and, after going public, branch protection requiring CI.
3. **Decide on demo hosting** - If you want a hosted demo, choose a free tier and have the choice recorded in an ADR; otherwise skip.
4. **Approve going public** - Explicitly approve making the repository public, then confirm in chat.

Out of scope:
- Never public without the owner's explicit approval

## Phase 2 - Operations depth

| ID | Task | Owner | Depends on | Checks |
| --- | --- | --- | --- | --- |
| REL-33 | Observability: Prometheus metrics and Grafana dashboards in docker compose | Claude | REL-32 | `stack-up`, `api-tests`, `api-lint` |
| REL-34 | Incident detection rules and incident lifecycle API | Claude | REL-33 | `api-tests`, `api-lint`, `stack-up` |
| REL-35 | Link incidents to affected payments and generate an AI incident summary | Claude | REL-34, REL-25 | `api-tests`, `api-lint` |
| REL-36 | Incident UI: list, detail and triage actions | Claude | REL-35 | `web-check`, `e2e`, `web-test`, `sim-tests`, `sim-lint` |
| REL-37 | Analytics: volume, success rate, latency and failure reasons by processor | Claude | REL-33 | `api-tests`, `web-check`, `web-test`, `api-lint` |
| REL-38 | Phase 2 exit review and Phase 3 refinement | Claude | REL-36, REL-37 | `ci-green`, `docs-review` |

### REL-33: Observability: Prometheus metrics and Grafana dashboards in docker compose

- Owner: Claude
- Depends on: REL-32
- Labels: phase-2, infra
- Paths: `observability/`, `api/app/metrics/`, `docker-compose.yml`, `api/tests/`, `api/app/outbox/`, `api/app/worker/`, `docs/architecture/`

Acceptance:
- [ ] ADR 0006 accepted
- [ ] Before ADR-0006 is accepted it compares Prometheus and Grafana with Sentry (error tracking) and PostHog (product analytics) against the free and open-source rule, self-hosted under Docker Compose, and records the choice (owner's tooling review, 2026-10-27)
- [ ] Throughput, success rate, latency and processor error rate dashboards load locally
- [ ] Dashboard spec written first; dashboards include API 5xx rate, publish lag and P50/P95/P99 latency
- [ ] The relay (publisher) process exposes metrics; a seeded demo run feeds the dashboards
- [ ] Prometheus and Grafana run under the compose profile `observability` (owner decision 2026-11-02, ADR-0014): the default stack, the clean-clone run and the CI e2e job do not start them
- [ ] Both images are pinned to an exact version with the licence checked at that version; each new service has a restart policy, a health check, only the variables it reads and host ports bound to 127.0.0.1, and `api/tests/test_compose_stack.py` covers them; dashboards and the scrape config are provisioned as files and parsed by a test

Steps:
1. **Confirm and accept ADR 0006** - The owner confirms Prometheus and Grafana, and the ADR status moves to Accepted before any build work.
2. **Write failing metrics tests** - Cover counters and histograms for payment throughput, outcomes, latency and processor errors exposed at `/metrics`.
3. **Instrument the API and worker** - Add Prometheus client metrics in `api/app/metrics/` labelled by processor and outcome.
4. **Add Prometheus and Grafana to docker compose** - Under `observability/`, provision the scrape config, data source and dashboards as files.
5. **Build the four dashboards** - Throughput, success rate, latency and processor error rate; done when they load after `docker compose up` with a demo scenario running.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.
7. **Add the observability profile with pinned, licence-checked images** - Add Prometheus and Grafana under the `observability` compose profile, pinned to exact versions with licences checked, provisioned from files, and extend `api/tests/test_compose_stack.py` for them.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-34: Incident detection rules and incident lifecycle API

- Owner: Claude
- Depends on: REL-33
- Labels: phase-2, api
- Paths: `api/app/incidents/`, `api/app/db/`, `api/migrations/`, `api/tests/`, `docker-compose.yml`, `docs/architecture/`, `docs/decisions/`

Acceptance:
- [ ] A processor error-rate spike opens an incident automatically
- [ ] Incidents move detect -> triage -> resolve; invalid moves rejected
- [ ] Incidents can also be created manually (POST /incidents)
- [ ] Detection runs in its own consumer (`incidents` container reading the event stream), never in the payment worker, and opens an incident when the router starts avoiding a processor, reusing the routing health threshold; it records `recovered` when health returns, and only an analyst resolves (owner decision 2026-11-02, ADR-0014)
- [ ] At most one open incident per processor, enforced by a unique partial index and proved by a concurrent test; the detector handles duplicate, late and redelivered stream entries and a consumer crash without opening a second incident or losing one (PR-1, PR-5)
- [ ] Every incident endpoint requires the API key; `api-contract.md`, `data-model.md` and `containers.md` are updated with the incidents table, endpoints and container in the same pull request

Steps:
1. **Write failing tests for detection and lifecycle** - Cover an error-rate spike opening one incident, no duplicates while open, valid detect to triage to resolve moves and rejected invalid moves.
2. **Add the incident model and migration** - Create the incidents table and Alembic migration for `api/app/incidents/`.
3. **Implement the incident state machine** - Allow only detect to triage to resolve, rejecting all other moves.
4. **Implement detection rules** - Open an incident when a processor's error rate exceeds the threshold for a set window.
5. **Add the lifecycle API** - Add list, get and transition endpoints protected by the API key; `api-tests` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.
7. **Run detection in its own consumer with one open incident per processor** - Add the `incidents` consumer container (restart policy, health check, per-service variables), the unique partial index for open incidents, and tests for concurrency, duplicates, late entries and a crash.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-35: Link incidents to affected payments and generate an AI incident summary

- Owner: Claude
- Depends on: REL-34, REL-25
- Labels: phase-2, ai
- Paths: `api/app/incidents/`, `api/app/explain/`, `api/tests/`, `docs/evaluation/`, `api/app/db/`, `api/migrations/`, `docs/architecture/`

Acceptance:
- [ ] Incident lists affected payments and events
- [ ] Summary grounded in linked events, with rule-based fallback
- [ ] The incident summary cites only linked events; a citation outside them, a model failure or a cause that disagrees with the rules falls back to the rules summary with a `fallback_reason` (as ADR-0005 and ADR-0013); payment descriptions are never sent to the model
- [ ] A real-model quality check on fixed synthetic incidents reports citation validity and fallback rate per reason, recorded in `docs/evaluation/results.md` (PR-31)

Steps:
1. **Write failing tests for linking and summaries** - Cover affected payments and events listed for an incident, a grounded summary, and fallback without a model.
2. **Link incidents to affected payments and events** - Store the links when payments fail during the incident window and expose them in the incident detail.
3. **Implement the rule-based summary** - Produce a deterministic summary from the linked events.
4. **Implement the model summary with fallback** - Reuse the Ollama client with a grounded prompt, falling back to the rule-based summary and labelling the source.
5. **Run the checks** - `api-tests` pass without a model.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-36: Incident UI: list, detail and triage actions

- Owner: Claude
- Depends on: REL-35
- Labels: phase-2, ui
- Paths: `frontend/app/`, `frontend/tests/`, `frontend/proxy.ts`, `scripts/`, `simulator/generator/`, `simulator/tests/`, `docs/evaluation/`, `docs/architecture/`

Acceptance:
- [ ] Triage and resolve from the UI
- [ ] E2E test covers the incident flow
- [ ] Incident views follow an updated dashboard spec
- [ ] Mean time to detect and to resolve are measured for injected incidents
- [ ] Triage and resolve go through frontend server routes that accept only same-origin POST requests on localhost hosts, and the e2e suite covers axe on the incident pages and the key never appearing in browser traffic (ADR-0012, PR-27, PR-35)
- [ ] Mean time to detect is incident opened minus the outage switch time, and mean time to resolve is resolved minus opened; both are computed from stored or saved timestamps (the demo saves its switch times), and repeated runs pin every timing mechanism or state a tolerance (PR-18, lesson L-068)
- [ ] Before the timing runs, the generator's drain limit covers the sweeper's re-drive cycle (default at least two re-drive intervals plus grace) and a drain timeout prints the unfinished payments with their statuses, so the outage-off switch is never skipped silently (open item from REL-34)

Steps:
1. **Write failing end-to-end and component tests** - Cover the incident list, detail, triage and resolve actions.
2. **Build the incident list page** - In `frontend/app/`, list incidents with state, processor and time.
3. **Build the incident detail page** - Show the summary, affected payments and events with links to payment detail.
4. **Add triage and resolve actions** - Buttons call the lifecycle API and show valid next steps only.
5. **Extend Playwright to the incident flow** - Cover detection through resolve; `web-check` and `e2e` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-37: Analytics: volume, success rate, latency and failure reasons by processor

- Owner: Claude
- Depends on: REL-33
- Labels: phase-2, api, ui
- Paths: `api/app/analytics/`, `frontend/app/`, `api/app/reporting/`, `api/tests/`, `frontend/tests/`, `docker-compose.yml`, `docs/architecture/`, `api/app/main.py`

Acceptance:
- [ ] Numbers derived from payment_events
- [ ] Filterable by time range and processor
- [ ] Shows simulated revenue recovered and success-rate uplift against the static-routing baseline
- [ ] Baseline figures come from the REL-30 results files
- [ ] Analytics endpoints require the API key and the UI reads them through server routes; revenue recovered is split by rescue path and time to explanation by source with fallback reasons, reusing `api/app/reporting/` rather than a second implementation (PR-20, PR-31)
- [ ] Event-derived figures come from `payment_events`; amounts, currency and the handling processor are joined from `payments` (events carry no money, and terminal events have no processor; REL-32 exit review, R1), so no event schema change is needed
- [ ] The api reads the REL-30 baseline from `docs/evaluation/outage-demo/results.json` mounted read-only by compose (path from a setting); when the file is absent the analytics answer says the baseline is unavailable instead of failing

Steps:
1. **Write failing analytics tests** - Compute volume, success rate, latency and failure reasons from fixed events, filtered by time range and processor.
2. **Implement the aggregation queries** - In `api/app/analytics/`, derive figures from `payment_events` only.
3. **Add the analytics API** - Expose time range and processor filters with validation.
4. **Build the analytics page** - Show the figures by processor in `frontend/app/` with the filters.
5. **Run the checks** - `api-tests` and `web-check` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-38: Phase 2 exit review and Phase 3 refinement

- Owner: Claude
- Depends on: REL-36, REL-37
- Labels: phase-2, docs
- Paths: `docs/`, `HANDOFF.md`

Acceptance:
- [ ] Exit criteria checked with evidence
- [ ] Risks, ADRs, process log and README updated
- [ ] Phase 3 tasks refined
- [ ] Risk R5 reassessed with Phase 2 evidence
- [ ] From a clean clone, docker compose up -d --wait is healthy
- [ ] `maintenance/test-project-hygiene.ps1` passes for Relay, and `plan-review` runs again with the full checklist before Phase 3 is refined

Steps:
1. **Check each Phase 2 exit criterion with evidence** - Record evidence for incidents, dashboards, ADR 0006 and outcome metrics against the baseline.
2. **Update the risk register and ADR statuses** - Reassess risks and confirm ADR 0006 is Accepted.
3. **Update the process log and README** - Add the phase summary and lessons and refresh the README.
4. **Refine Phase 3 tasks and subtasks in this plan** - Adjust requirements, dependencies and subtasks for Phase 3 using what was learned.
5. **Re-sync issues and regenerate the delivery plan** - Regenerate `docs/delivery/delivery-plan.md`, sync issues, and have the owner review.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

## Phase 3 - Integrations

| ID | Task | Owner | Depends on | Checks |
| --- | --- | --- | --- | --- |
| REL-57 | Incident and dashboard follow-ups: affected count, paged detail, missing guardrail panels, one success rate | Claude | REL-38 | `api-tests`, `api-lint`, `web-check`, `web-test`, `e2e` |
| REL-39 | Webhooks: subscriptions, HMAC-signed delivery, retries with backoff, delivery log | Claude | REL-57 | `api-tests`, `api-lint`, `stack-up` |
| REL-40 | Developer documentation from the OpenAPI spec with a quickstart | Claude | REL-39 | `docs-review`, `api-tests`, `api-lint` |
| REL-41 | Python SDK with examples and tests | Claude | REL-40 | `sdk-tests` |
| REL-42 | Phase 3 exit review and Phase 4 refinement | Claude | REL-41 | `ci-green`, `docs-review` |

### REL-57: Incident and dashboard follow-ups: affected count, paged detail, missing guardrail panels, one success rate

- Owner: Claude
- Depends on: REL-38
- Labels: phase-3, ui
- Paths: `api/app/incidents/`, `api/tests/`, `frontend/app/`, `frontend/tests/`, `docs/architecture/`, `observability/`, `api/app/metrics/`, `api/app/analytics/`, `api/app/worker/`, `api/app/outbox/`, `docs/product/`

Acceptance:
- [ ] `GET /incidents` returns `affected_count` per incident, so the list page makes one request per refresh instead of one per incident (owner decision 2026-11-04, REL-38 follow-up)
- [ ] The incident detail page shows the affected payments paged or collapsed, with each payment's events collapsed by default, so a large incident stays readable
- [ ] Component and e2e tests cover both; the API contract is updated
- [ ] Grafana gains the two guardrail panels Phase 2 lacked: payment latency from creation to final, and payments not final after the sweeper threshold; and a stream lag and pending gauge per consumer group; all new series zero-initialised and covered by the dashboard file tests (owner decision 2026-11-04, REL-38)
- [ ] One success-rate definition, captured over final payments as `docs/product/metrics.md` states, is used by the Grafana panel and `/analytics`, and stated in `api-contract.md` before the developer docs and SDK depend on it (owner decision 2026-11-04)

Steps:
1. **Write failing tests for the count and the paged detail** - Cover `affected_count` on the list endpoint, the list page using it, and the paged or collapsed detail.
2. **Add affected_count to GET /incidents** - Compute it in the list query and document it in `api-contract.md`.
3. **Use the count on the list page** - Drop the per-incident detail requests.
4. **Page or collapse the detail page** - Collapse each payment's events by default and page the affected payments.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.
6. **Add the missing guardrail panels and the stream lag gauge** - Add creation-to-final latency and payments-not-final metrics and panels, and a lag and pending gauge per consumer group, zero-initialised and covered by the dashboard file tests.
7. **Unify the success-rate definition** - Use captured over final payments in the Grafana panel and `/analytics`, and state it in `api-contract.md` and `metrics.md`.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-39: Webhooks: subscriptions, HMAC-signed delivery, retries with backoff, delivery log

- Owner: Claude
- Depends on: REL-57
- Labels: phase-3, api
- Paths: `api/app/webhooks/`, `api/app/db/`, `api/migrations/`, `api/tests/`, `docker-compose.yml`, `docs/architecture/`, `api/app/main.py`, `api/app/metrics/`, `observability/`

Acceptance:
- [ ] Subscriber receives a signed event for a payment state change
- [ ] Failed deliveries retry with backoff and are visible in a delivery log
- [ ] Subscriptions filter by event type
- [ ] Delivery failure and retry behavior are documented
- [ ] Webhooks follow ADR-0015 (owner decision 2026-11-04): a `webhooks` container with its own consumer group stores each delivery (attempt, status, next attempt, last response) in the same transaction as its bookkeeping and acknowledges after the commit, so a crash loses nothing and a duplicate stream entry produces one delivery
- [ ] Each delivery carries `Relay-Event-Id` and `Relay-Signature: t=<unix seconds>,v1=<HMAC-SHA256 hex of t.body>`; the body never includes the payment description; retries back off exponentially (settings, at most 8 attempts, then `failed`) and every attempt is in the delivery log with a retention setting
- [ ] Subscription URLs must be http(s) to a host in `WEBHOOK_ALLOWED_HOSTS` (default: the local demo sink and localhost), checked at creation and at send time; anything else is 422 and never fetched (server-side request forgery)
- [ ] The signing secret is generated by Relay, returned only in the create response, and never returned again or logged; the subscription API requires the key; a demo sink runs under a compose profile; the new container has a restart policy, health check and per-service variables covered by the compose test; deliveries are counted in a metric scraped by Prometheus

Steps:
1. **Write failing webhook tests** - Cover subscription CRUD, a valid HMAC signature on delivery, backoff schedule after failures, and delivery log entries.
2. **Add subscription models and endpoints** - In `api/app/webhooks/`, register a URL, secret and event types with a migration.
3. **Sign deliveries with HMAC** - Send a timestamped SHA-256 HMAC header so subscribers can verify authenticity.
4. **Deliver from the event stream with retries** - Consume payment events and retry failed deliveries with exponential backoff up to a limit.
5. **Add the delivery log** - Record each attempt with status and response; expose it via the API. `api-tests` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-40: Developer documentation from the OpenAPI spec with a quickstart

- Owner: Claude
- Depends on: REL-39
- Labels: phase-3, docs
- Paths: `docs/guides/`, `api/app/`, `api/tests/`, `docs/architecture/api-contract.md`, `README.md`

Acceptance:
- [ ] Quickstart takes a new developer to a first successful API call
- [ ] A clean-room run following only the docs reaches a first successful API call; the time is recorded
- [ ] Webhook delivery success rate is reported
- [ ] The generated OpenAPI declares the API-key security scheme, marks `Idempotency-Key` required on `POST /payments`, uses enums for currency and status, and lists only the error codes each endpoint can return (differences recorded in the REL-32 exit review)
- [ ] Webhook delivery success rate is defined as delivered over final deliveries (delivered plus failed) in a window, computed from the delivery log, and documented with the retry schedule and signature check from ADR-0015
- [ ] Owner decision 2026-11-05: the webhook delivery success rate is reported by a keyed `GET /webhooks/deliveries/summary?since=&until=` returning delivered, failed and pending counts and `success_rate` (null when no delivery is final), documented in the API reference and `api-contract.md`
- [ ] Owner decision 2026-11-05: the API reference is committed Markdown in `docs/guides/` plus the exported `openapi.json`, generated by a standard-library module in `api/app` (no new dependency), with a test that fails when the committed files differ from the live spec
- [ ] Owner decision 2026-11-05: the clean-room run is done by a fresh subagent with no project context, cloning into a temporary folder and following only the docs; the time and every gap found are recorded in `docs/guides/`, the gaps fixed, then the owner reads the documents
- [ ] The `Differences from the generated OpenAPI` table in `api-contract.md` is updated to what remains after the fixes, and `README.md` links to the quickstart

Steps:
1. **Generate the API reference from the OpenAPI spec** - Export the spec and render reference pages in `docs/guides/`.
2. **Write the quickstart** - Take a new developer from `docker compose up` to a first successful payment with copy-pasteable commands.
3. **Document authentication, idempotency and webhooks** - Explain the API key, Idempotency-Key rules, signatures, retries and error codes.
4. **Test the quickstart on a clean clone** - Follow it exactly and fix any gap; the owner reviews the documents.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-41: Python SDK with examples and tests

- Owner: Claude
- Depends on: REL-40
- Labels: phase-3, api
- Paths: `sdk/python/`, `docker-compose.yml`, `.github/workflows/`, `api/tests/`, `docs/guides/`, `AGENTS.md`

Acceptance:
- [ ] Create, read, list payments and verify webhook signatures
- [ ] Examples run against the local stack
- [ ] A compose `sdk` service (profile `sdk`) runs the SDK tests so `sdk-tests` works
- [ ] The SDK depends only on libraries already in the fixed stack (httpx), pinned exactly, with the licence checked; CI runs `sdk-tests` (path-filtered), and the SDK verifies `Relay-Signature` exactly as ADR-0015 defines
- [ ] Owner decision 2026-11-05: the client covers payments (create with a generated `Idempotency-Key` unless one is given, get, list with cursor paging) and webhooks (signature verification, subscriptions create, list, get and delete, the delivery log and `GET /webhooks/deliveries/summary`); other endpoints stay HTTP-only
- [ ] Owner decision 2026-11-05: one synchronous `RelayClient` on `httpx.Client`; typed dataclass models; API errors raised as one exception type carrying status, code, message and correlation id
- [ ] Owner decision 2026-11-05: installed from the repository (`pip install ./sdk/python`, pyproject, Python 3.12, MIT); nothing is published to a package index
- [ ] The `sdk` service and the CI job run ruff, the format check, mypy and pytest for the SDK; a test in `api/tests` proves the SDK's verification agrees with `app/webhooks/signing` on signed and tampered bodies
- [ ] `docs/guides/` gains an SDK guide linked from its index and the quickstart's next steps, and `AGENTS.md` lists `sdk/` and its commands

Steps:
1. **Write failing SDK tests** - Cover create, get and list payments and webhook signature verification against mocked HTTP.
2. **Scaffold the package** - Add packaging, typing and a client class under `sdk/python/`.
3. **Implement payment methods with typed models** - Create, read and list payments, generating idempotency keys by default.
4. **Implement webhook signature verification** - Verify signature and timestamp tolerance, raising a clear error on mismatch.
5. **Add examples and run them against the local stack** - Examples create and list a payment and verify a webhook; tests pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-42: Phase 3 exit review and Phase 4 refinement

- Owner: Claude
- Depends on: REL-41
- Labels: phase-3, docs
- Paths: `docs/`, `HANDOFF.md`, `README.md`

Acceptance:
- [ ] Exit criteria checked
- [ ] Phase 4 tasks refined
- [ ] From a clean clone, docker compose up -d --wait is healthy
- [ ] `maintenance/test-project-hygiene.ps1` passes for Relay, and `plan-review` runs again with the full checklist before Phase 4 is refined; CI minutes are checked against the R12 threshold
- [ ] The findings carried from REL-40 and REL-41 are recorded with a disposition: `GET /analytics?since=garbage` answers 200 instead of 422, and the api's `signing.verify` raises TypeError on a non-ASCII `v1` value

Steps:
1. **Check each Phase 3 exit criterion with evidence** - Record evidence for webhook delivery, documented retries and the docs-only first API call.
2. **Update the risk register and ADR statuses** - Reassess risks and update ADR statuses.
3. **Update the process log and README** - Add the phase summary and lessons and refresh the README.
4. **Refine Phase 4 tasks and subtasks in this plan** - Adjust requirements, dependencies and subtasks for Phase 4 using what was learned.
5. **Re-sync issues and regenerate the delivery plan** - Regenerate `docs/delivery/delivery-plan.md`, sync issues, and have the owner review.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

## Phase 4 - Optimization

| ID | Task | Owner | Depends on | Checks |
| --- | --- | --- | --- | --- |
| REL-58 | Phase 3 follow-ups: webhook signature fix, delivery log paging, smoke coverage, docs-only CI | Claude | REL-42 | `api-tests`, `api-lint`, `sdk-tests`, `stack-smoke` |
| REL-43 | Routing experiment harness comparing strategies on seeded scenarios | Claude | REL-58 | `api-tests`, `api-lint`, `sim-tests`, `sim-lint` |
| REL-44 | Adaptive routing strategy measured against the rule-based baseline | Claude | REL-43 | `api-tests`, `api-lint`, `web-check`, `web-test`, `e2e`, `sim-tests`, `sim-lint` |
| REL-59 | Deterministic routing seed for every payment | Claude | REL-44 | `api-tests`, `api-lint` |
| REL-60 | Second adaptive iteration: gated hybrid measured on fresh seeds | Claude | REL-59 | `api-tests`, `api-lint`, `sim-tests`, `sim-lint` |
| REL-45 | Phase 4 exit review and project retrospective | Claude | REL-60 | `ci-green`, `docs-review` |
| REL-61 | Release preparation: local paths removed, recorded walkthrough | Claude | REL-45 | `api-tests`, `api-lint`, `web-check`, `e2e`, `docs-review` |

### REL-58: Phase 3 follow-ups: webhook signature fix, delivery log paging, smoke coverage, docs-only CI

- Owner: Claude
- Depends on: REL-42
- Labels: phase-4, maintenance
- Paths: `api/app/webhooks/`, `api/tests/`, `sdk/python/`, `scripts/`, `docs/guides/`, `docs/architecture/`, `.github/workflows/`, `api/app/openapi_schema.py`, `api/app/api/`

Acceptance:
- [ ] Owner decision 2026-11-06 (REL-42 review): `app/webhooks/signing.verify` returns False instead of raising on a non-ASCII or otherwise malformed `v1` value (compare bytes, as the SDK does), with a test; the demo sink answers 401 rather than 500 for such a header, and the SDK agreement test gains the non-ASCII case
- [ ] Owner decision 2026-11-06 (REL-42 review): `GET /webhooks/deliveries` pages with a cursor like `GET /payments` (newest first, a `next_cursor`), the 100-row cap is gone, and the SDK's `list_deliveries` follows the cursor (or gains an iterator) with tests; `api-contract.md`, the regenerated `docs/guides/api-reference.md` and `openapi.json` and the SDK guide are updated
- [ ] Owner decision 2026-11-06 (REL-42 review): `scripts/smoke_stack.py` checks every long-running service in the default profile, including `publisher`, `explainer`, `incidents` and `webhooks`
- [ ] Owner decision 2026-11-06 (REL-42 review): a push to `main` that changes only documentation and Markdown runs just the secret scan job; pull requests still run every job and the scheduled audit stays; `test-project-hygiene.ps1` still passes
- [ ] Owner decision 2026-11-06 (REL-42 review): the guides note that `/analytics` takes `from` and `to` while the delivery summary takes `since` and `until`, and that unknown query parameters are ignored

Steps:
1. **Write failing tests** - Cover the non-ASCII signature, delivery log paging in the api and the SDK, and the smoke script's service list.
2. **Fix signature verification** - Compare bytes in `app/webhooks/signing.verify` and add the case to the SDK agreement test.
3. **Page the delivery log** - Cursor paging on `GET /webhooks/deliveries`, the SDK following it, and the contract, reference and guides regenerated.
4. **Cover every service in the smoke test and slim docs-only CI** - Extend `scripts/smoke_stack.py`; make a docs-only push to `main` run only the secret scan.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-43: Routing experiment harness comparing strategies on seeded scenarios

- Owner: Claude
- Depends on: REL-58
- Labels: phase-4, routing, testing
- Paths: `scripts/`, `api/app/routing/`, `api/tests/`, `simulator/generator/`, `simulator/processors/`, `simulator/app/`, `simulator/tests/`, `docs/evaluation/`, `docs/architecture/`

Acceptance:
- [ ] Same scenarios replayed per strategy; results table with success rate, revenue and latency
- [ ] The routing objective is defined as a reproducible measure before strategies are compared
- [ ] Owner decision 2026-11-06 (REL-42 plan review, ADR-0016): the objective is the success rate (captured over final payments, the REL-57 definition) compared per seed on identical payment references; revenue captured per currency is reported alongside, and p95 creation-to-final latency is a guardrail
- [ ] Owner decision 2026-11-06 (REL-42 plan review, ADR-0016): the harness drives the real compose stack with the load generator, one run per strategy per seed on the same references, by extending `scripts/outage_demo.py` (or a sibling script reusing it) rather than an in-process model; CI tests the harness logic with fakes, and the full comparison is a documented manual run with its duration recorded
- [ ] Strategies are selected by `ROUTING_STRATEGY` through a small registry in `api/app/routing/` (today `rules` and `static`), so REL-44 adds a strategy without touching the worker
- [ ] A third seeded scenario with a partial degradation of one processor (a raised error rate rather than a full outage) is added to the generator, with whatever simulator control it needs, so the comparison covers calm, outage and partial degradation
- [ ] The harness reports per strategy, scenario and seed the success rate, revenue, p95 latency and paired differences, as `results.json` and `results.md` under `docs/evaluation/routing-experiments/`; its first run compares `static` with `rules` and must agree with the REL-30 results within their tolerance

Steps:
1. **Write failing harness tests** - Cover strategy plug-in, identical scenario replay per strategy and the results table.
2. **Define the strategy interface** - In `api/app/routing/`, a strategy registry behind `ROUTING_STRATEGY`: a strategy chooses a processor from health data and the payment; `rules` and `static` move behind it unchanged.
3. **Implement scenario replay** - Extend `scripts/outage_demo.py` (or a sibling) to run every strategy on every scenario and seed against the compose stack, restarting the routing services between runs so each starts fresh, and add the partial-degradation scenario.
4. **Produce the results table** - Write `results.json` and `results.md` under `docs/evaluation/routing-experiments/` with success rate, revenue, p95 latency and paired differences per strategy, scenario and seed.
5. **Run the checks** - Two runs with the same seed match; `api-tests` pass.
6. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-44: Adaptive routing strategy measured against the rule-based baseline

- Owner: Claude
- Depends on: REL-43
- Labels: phase-4, routing
- Paths: `api/app/routing/`, `api/app/db/`, `api/migrations/`, `api/tests/`, `docker-compose.yml`, `docs/evaluation/`, `docs/architecture/`, `docs/decisions/`, `README.md`, `api/app/domain/`, `api/app/explain/`, `frontend/app/`, `frontend/tests/`, `scripts/`, `simulator/demo/`, `simulator/tests/`

Acceptance:
- [ ] Beats the rule-based router on the agreed objective across seeded scenarios, or the result is documented honestly
- [ ] Owner decision 2026-11-06 (REL-42 plan review, ADR-0016): the adaptive strategy is Thompson sampling: a Beta-Bernoulli posterior per processor over a recent, decaying window of outcomes, standard library only (`random.betavariate`), no new dependency
- [ ] The learned state lives in shared storage (PostgreSQL or Valkey), not one worker's memory, so several worker processes and a restart see the same posterior (PR-6)
- [ ] The sampler's random draws are seeded from the payment `reference` (ADR-0012), so a paired run repeats exactly; a test runs the same references twice and gets the same routing
- [ ] Owner decision 2026-11-06 (REL-42 plan review, ADR-0016): the adaptive strategy wins when, across 3 scenarios x 5 seeds against `rules`, the mean paired success-rate uplift is at least 1 percentage point, it is better on at least 80% of paired runs, and p95 latency is not worse by more than the margin ADR-0016 states; otherwise the result is reported honestly as not winning
- [ ] The exploration cost is reported: the share of payments routed to the processor that was degraded at the time, per scenario
- [ ] `rules` stays the default; the strategy never waits on a model call (ADR-0012)
- [ ] A payment routed by the adaptive strategy carries a new routed reason `adaptive`: added to `RoutedReason`, to the `payment_events` reason CHECK by a migration, to the rule-based explainer's texts and to any UI reason labels, with tests (PR-23); its posterior is computed from recent `payment_events` in PostgreSQL the way `app/routing/health.py` computes health, so no new table is needed unless the ADR says otherwise

Steps:
1. **Agree the objective and write failing tests** - Record the measure to beat (for example revenue recovered) and add tests comparing strategies on fixed seeds.
2. **Implement the adaptive strategy** - In `api/app/routing/`, add a free, open-source learning approach such as a bandit that uses recent outcomes.
3. **Wire it behind a switch** - Select the strategy by configuration so the rule-based router stays the default.
4. **Run the experiment harness on all seeded scenarios** - Compare against the rule-based baseline across all seeds and record the numbers in `docs/evaluation/`, whether or not it wins.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-59: Deterministic routing seed for every payment

- Owner: Claude
- Depends on: REL-44
- Labels: phase-4, routing
- Paths: `api/app/worker/`, `api/app/routing/`, `api/tests/`

Acceptance:
- [ ] Owner decision 2026-11-09 (ADR-0017): the worker's payment snapshot carries the payment id, so the adaptive sampler seeds from the id when a payment has no reference, never randomly; a test routes a payment without a reference identically twice and in two processes

Steps:
1. **Write the failing test** - A payment without a reference routes identically twice and across processes.
2. **Add the id to the worker snapshot** - Pass it to the strategy so the seed falls back to the id.
3. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-60: Second adaptive iteration: gated hybrid measured on fresh seeds

- Owner: Claude
- Depends on: REL-59
- Labels: phase-4, routing
- Paths: `api/app/routing/`, `api/tests/`, `scripts/`, `simulator/demo/`, `simulator/tests/`, `docs/evaluation/`, `docs/architecture/`, `docs/decisions/`

Acceptance:
- [ ] Owner decision 2026-11-09 (ADR-0017): a `hybrid` strategy: `rules` decides unless a processor's recent error rate (health window and counting of `app/routing/health.py`, at least `HEALTH_MIN_ATTEMPTS` attempts) is above the gate 0.15 and not above the failover threshold, in which case the REL-44 sampler routes with reason `adaptive`; failover and retries as `rules`
- [ ] Owner decision 2026-11-09 (ADR-0017): a protocol v2 section in `docs/evaluation/routing-experiments/protocol.md`, committed before any comparison run: deciding seeds 21 to 25, comparison-only seeds 11 to 15, strategies `rules` and `hybrid`, everything else as protocol v1
- [ ] The full comparison runs in parts under 2 hours each (lesson L-077) with images rebuilt first and the routed reasons checked in the outcomes; the verdict on seeds 21 to 25 under the unchanged ADR-0016 win rule, plus the seeds 11 to 15 comparison, is recorded in `docs/evaluation/routing-experiments/rel60/` and `docs/evaluation/adaptive-routing-results.md`, whether or not it wins

Steps:
1. **Write failing tests** - Hybrid equals rules outside the degraded zone, samples inside it, fails over above the threshold.
2. **Implement the hybrid strategy** - Register `hybrid` in `api/app/routing/`, reusing the REL-44 sampler.
3. **Pre-register protocol v2** - Commit the seeds and strategies before any run.
4. **Run the comparison in parts and record the verdict** - 60 runs in parts under 2 hours; results and verdict in `docs/evaluation/`.
5. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-45: Phase 4 exit review and project retrospective

- Owner: Claude
- Depends on: REL-60
- Labels: phase-4, docs
- Paths: `docs/`, `README.md`

Acceptance:
- [ ] Final results in README
- [ ] Retrospective in process log
- [ ] From a clean clone, docker compose up -d --wait is healthy
- [ ] Audit confirms no paid dependency exists without an Accepted ADR
- [ ] The README states the ADR-0016 win rule and the measured result with its numbers, whether or not the adaptive strategy won
- [ ] Owner decision 2026-11-09: the README leads with the verdict under the pre-registered rule (each condition with its numbers) for both iterations (REL-44 adaptive, REL-60 hybrid), then a per-scenario table of where each helps and where it costs
- [ ] The Phase 4 exit criterion is recorded as met or not met from the REL-60 deciding seeds; the normal-day latency cause of REL-44 is recorded as an open question with what was ruled out
- [ ] Owner decision 2026-11-09: Phase 4 closes with its exit criterion recorded as not met after two pre-registered attempts (REL-44 adaptive, REL-60 hybrid); the README leads with that verdict, then the consistent partial-degradation strength, and lists as future work a gate that needs about 20 attempts before opening, noting that calm-day ties still cap the better-share near 73% under the ADR-0016 rule

Steps:
1. **Check each Phase 4 exit criterion with evidence** - Record evidence for the adaptive comparison and confirm no paid dependency is used or an ADR exists.
2. **Update the risk register and ADR statuses** - Close or reassess remaining risks and finalise ADR statuses.
3. **Put final results in the README** - Replace interim numbers with final measured results and limits.
4. **Write the retrospective in the process log** - Summarise what worked, what did not and what to do differently.
5. **Re-sync issues and regenerate the delivery plan** - Regenerate `docs/delivery/delivery-plan.md`, close finished issues, and have the owner review.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening

### REL-61: Release preparation: local paths removed, recorded walkthrough

- Owner: Claude
- Depends on: REL-45
- Labels: phase-4, release
- Paths: `docs/`, `README.md`, `api/tests/`, `.githooks/`, `.claude/`, `frontend/tests/`, `scripts/`

Acceptance:
- [ ] Owner decision 2026-11-10 (REL-46 preparation): no tracked file contains an absolute path into the owner's Windows user folder (in either slash style) or the owner's email address; docs and results use repository-relative paths or a `<workspace>` placeholder; the git hooks find the workspace guard relatively and skip with a message when it is absent (a public clone has no workspace); a test fails if such a path or address appears in any tracked file
- [ ] Owner decision 2026-11-10 (REL-46 preparation): a recorded walkthrough instead of a hosted demo: screenshots taken with Playwright on the local stack during the scripted outage (payments list, a payment timeline with failover, processor health, and the analytics or incident view), stored under `docs/images/walkthrough/` and shown in the README with captions; synthetic data only, no keys visible
- [ ] Owner decision 2026-11-10 (REL-46 preparation): the public copy is a fresh repository created from the release commit as one initial commit authored with the owner's GitHub noreply address; this private repository keeps its history; creating the public repository is REL-46 and needs the owner's explicit go-ahead

Steps:
1. **Write the failing path test** - A test that no tracked file contains a machine path or the owner's address.
2. **Replace the paths** - Docs, results and hooks; hooks resolve the workspace guard relatively and skip when it is absent.
3. **Capture the walkthrough** - Playwright screenshots of the outage demo, added to the README.
4. **Open pull request and pass review** - CI is green, the reviewer confirms correctness against the requirements, the maintainer approves, and the pull request is squash-merged with the issue closed.

Out of scope:
- No work from later phases
- No paid services or hosted AI APIs
- No test weakening
