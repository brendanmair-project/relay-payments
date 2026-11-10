# relay repository guidance

Template: claude/repository-agent@1

## Scope and purpose

- This file applies to the repository rooted at `projects/professional/relay`.
- The project exists to serve this purpose: a portfolio project that solves a concrete business problem with synthetic data only. An online merchant routes card payments through two processors; failed and stuck payments cost revenue and take hours to investigate. Relay gives every payment one timeline, explains each failure in plain language (AI-assisted), and routes around a degraded processor.
- Status: Phases 1 and 2 complete (`docs/evaluation/phase-1-exit-review.md`, `phase-2-exit-review.md`); Phase 3 (webhooks, developer docs, SDK) is next, decisions in ADR-0015, starting with REL-57. Check before building on anything.
- Treat source code, tests, configuration, and documentation in this repository as project facts. Keep personal preferences in the global Claude instructions.
- Before editing a specialized subtree, check for a closer `AGENTS.override.md` or `AGENTS.md`.

## Project map

- `docs/product/`: vision, strategy, personas, jobs to be done, metrics, roadmap, and `backlog.md` (pointer to the task plan).
- `docs/product/glossary.md`; `docs/architecture/` (system context, constraints, `payment-lifecycle.md`, `containers.md`, `api-contract.md`, `data-model.md`).
- Standard layout (see `docs/README.md`): `docs/delivery/` (next steps, one file per task, plan, process log, risk register), `docs/workflow/` (workflow, definition of done, tools), `docs/evaluation/`, `docs/images/`, `scripts/`, `data/` (synthetic only), `CHANGELOG.md`, `.github/pull_request_template.md`.
- `docs/decisions/`: ADRs (`README.md` explains the process and holds the log).
- `api/`: FastAPI service (`app/`), Alembic migrations (`migrations/`, `alembic.ini`), pytest tests (`tests/`); also the image for migrate, worker and publisher.
- `simulator/`: Processors A and B (`processors/`: profiles, seeded outcomes, idempotent results; REL-19) behind the processor API (8100, internal) and the keyed control API (8101) in `app/`; tests in `tests/`; the load generator arrives in REL-23.
- `frontend/`: Next.js app (placeholder page until REL-26).
- `sdk/python/`: the `relay-sdk` Python client (REL-41; `src/relay_sdk/`, `tests/` on a mock transport, `examples/`), installed from the repository with `pip install ./sdk/python`, built and tested by the compose `sdk` service; guide in `docs/guides/sdk.md`.
- `scripts/`: host-side scripts (standard library only): `smoke_stack.py`; `postgres-init/` creates `relay_test`. `docker-compose.yml` and `.env.example` sit at the root.
- `README.md`: showcase overview. `LICENSE`: MIT.

Update this map when a structural change would otherwise make it misleading.

## Authoritative commands

Run commands from `projects/professional/relay` unless a command says otherwise.

- Setup: `cp .env.example .env` (then set `RELAY_API_KEY`); host frontend tooling: `npm ci --prefix frontend`.
- Build: `docker compose build`.
- Focused test: `docker compose run --rm api pytest tests/test_health.py` (any test file or `-k` expression); simulator: `docker compose run --rm --build --no-deps simulator pytest`.
- Full test: the fast suite in `.claude/verify-command.txt` (backend and simulator lint, types and tests, frontend lint, format, types and Vitest; about 45 s, run by the Stop hook), then `python scripts/smoke_stack.py` against the running stack. CI (`.github/workflows/ci.yml`, ADR-0007) runs the same checks plus the coverage gate, a gitleaks secret scan and, on pull requests, the stack smoke test. Merge only after `gh pr checks <number>` passes (no branch protection on the free private plan).
- Lint: `docker compose run --rm --build api ruff check .`, the same for `simulator`, and `npm --prefix frontend run lint`.
- Type-check: `docker compose run --rm --build api mypy app` and `npm --prefix frontend run typecheck`.
- Format check: `docker compose run --rm --build api ruff format --check .` (same for `simulator`) and `npm --prefix frontend run format:check`; to fix, mount the source: `docker compose run --rm --no-deps -v "$PWD/api:/app" api ruff format .`, or `npm --prefix frontend run format`.
- SDK checks (REL-41, CI job `sdk`): `docker compose --profile sdk run --rm sdk` runs `ruff check .`, `ruff format --check .`, `mypy src` and `pytest` for `sdk/python` (add `--build` after editing it; tests only: `docker compose --profile sdk run --rm --build sdk pytest`). `api/tests/test_sdk_signature_agreement.py` needs the repository checkout (it skips inside the api image): `cd api && pytest tests/test_sdk_signature_agreement.py` on the host.
- Static security scan (same as the CI `semgrep` job, ADR-0007): `docker run --rm -v "$PWD:/src" -w /src semgrep/semgrep:1.182.1 semgrep scan --config p/python --config p/typescript --config p/owasp-top-ten --error --metrics off`, or `pip install semgrep==1.182.1` and the same `semgrep scan ...`; suppress only inline with `# nosemgrep: <rule-id>` and a reason.
- End-to-end tests (REL-29): with the stack up (`docker compose up -d --wait`) and `RELAY_API_KEY` set in the shell, run `npx --prefix frontend playwright install chromium` once, then `npm --prefix frontend run e2e`; CI runs the same in the `e2e` job.
- Local run: `docker compose up -d --wait` (stop with `docker compose down`; `down -v` also deletes data). A clean clone needs only `RELAY_API_KEY` in the shell or in the env file: each service receives just the variables it reads, with the defaults of the committed example. Optional local model in a container instead of the host Ollama: `docker compose --profile llm up -d --wait`, set `OLLAMA_URL=http://ollama:11434`, then `docker compose --profile llm exec ollama ollama pull granite3.3:2b`. Metrics and dashboards (Prometheus and Grafana, REL-33): `docker compose --profile observability up -d --wait`, then Grafana at http://127.0.0.1:3001 (four dashboards, anonymous viewer) and Prometheus at http://127.0.0.1:9090; the default `up` never starts them.

Replace every placeholder with a verified command as Phase 1 code lands (tasks REL-12 onward). Do not invent commands.

## Architecture and invariants

- The stack is chosen (ADR-0001, amended by ADR-0011 and ADR-0012): Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Valkey (Redis-compatible; the compose service is still named `redis`), Next.js, TypeScript, Docker Compose, pytest, Playwright, GitHub Actions, plus uvicorn, psycopg 3, redis-py, httpx and pydantic-settings. Libraries and container images are pinned to exact versions; never use a floating image tag, and re-check the licence whenever a version changes (ADR-0012).
- PostgreSQL is the source of truth. Every state change appends a row to the append-only `payment_events` table in the same database transaction; a relay process publishes those rows to a Valkey stream (ADR-0003, ADR-0012).
- The load generator uses only the public API; it has no database access.
- Money is an integer `amount_minor` (BIGINT) plus an ISO 4217 `currency`; never floats. `POST /payments` requires an `Idempotency-Key`. Payment states and transitions follow `docs/architecture/payment-lifecycle.md`; invalid transitions are rejected (ADR-0004).
- Synthetic data only: never real payments or card data. Authentication is one static API key from an environment variable; single merchant (ADR-0002).
- The explanation endpoint must work without a model: local Ollama model first, deterministic rule-based fallback otherwise, so tests and CI need no model (ADR-0005, Accepted in REL-25; ADR-0010). Automatic explanations run in their own `explainer` container, never in the payment worker, and the free-text `description` is never sent to the model (ADR-0012).
- Demo runs must repeat: the simulator seeds its draws on the payment `reference`, which the load generator sets deterministically (ADR-0012).
- The frontend's server routes hold the API key, so they answer only `localhost`/`127.0.0.1` hosts, and the outage switch accepts only same-origin `POST` requests (ADR-0012, `docs/architecture/api-contract.md`).

Preserve these invariants unless the task explicitly changes the architecture and the associated tests, ADRs and documentation are updated.

## Change boundaries

- Keep changes within the user-requested scope. Do not silently invent product or architecture decisions; surface the ambiguity as an open question, and add it to `docs/delivery/risk-register.md` if it affects several phases.
- Free and open source only. A paid dependency, service or API (including a paid tier or a hosted AI API) needs an explicit owner decision recorded as an Accepted ADR. Any dependency outside the fixed stack needs the same.
- Local-first: every feature works via Docker Compose; cloud is optional demo infrastructure on free tiers.
- Respect phase order in `docs/product/roadmap.md`. Do not build later-phase capabilities early; if a request spans phases, confirm scope first.
- The owner (Brendan) is the sole decision-maker. A decision is made when it is recorded as an Accepted ADR in `docs/decisions/`, following the structure in `docs/decisions/README.md`. A "proposed default" elsewhere is not authoritative.
- GitHub Issues is the only task tracker. Tasks are defined in the task plan, published as `docs/delivery/delivery-plan.md` (generated; edit the plan, not the file), and each task has one issue; do not create other task boards.
- Do not edit generated or vendored files directly: `docs/delivery/next.md`, `docs/delivery/delivery-plan.md`, `docs/delivery/tasks/**`, `docs/workflow/workflow.md`, `docs/workflow/definition-of-done.md` and `docs/README.md` are generated from the workspace plan (`.claude/rules/generated-docs.md`).
- Do not change public interfaces, persistence formats, security controls, or production dependencies unless the task requires it.
- Never commit credentials, tokens, private keys, local environment files, or production data.
- Preserve unrelated user changes in a dirty worktree.

## Conventions

- Portfolio project: README.md follows the showcase format (parent workspace templates/showcase); the repository stays private until /publish-project passes its checklist; commits use the Gmail identity while private and the GitHub noreply address once public.
- Use the domain term "payment", not "transaction" (except "database transaction"). The glossary defines terms; check it before assuming a meaning.
- Keep this repository independent of the parent workspace; it has its own git history.
- Follow automated formatter and linter output; do not duplicate their complete rule sets here.
- Add comments for non-obvious intent and constraints, not line-by-line narration.
- UI direction: an operations tool for payment analysts. Dense, restrained and trustworthy; monospace for payment IDs, amounts and timestamps; status never shown by color alone; motion only in response to user actions. Write a dashboard spec before the first UI task (REL-26). This direction overrides generic design-skill defaults.
- Browser verification: Playwright MCP, project-scoped in `.mcp.json` (isolated profile). Screenshot UI changes at desktop and phone width before calling them done.
- Security review: the `security-guidance` plugin is enabled for this project only (`.claude/settings.json`). It reviews edits and diffs, and adds a model call at the end of each turn.

## Workflow and verification

Project workflow: `docs/delivery/next.md` says what to do now and `docs/delivery/tasks/<ID>.md` holds each task in full; work every task with `docs/workflow/workflow.md`, finish it against `docs/workflow/definition-of-done.md`, use the tools in `docs/workflow/tools.md`, and record every change in `CHANGELOG.md`. Files marked GENERATED come from `shared/tasks/relay.json` in the workspace; never edit them by hand.

1. Inspect the relevant implementation, tests, and closest instruction file.
2. Make the smallest coherent change that satisfies the request. When writing tests that must fail first, create `.claude/tdd-red` (git-ignored) so the Stop hook does not block; delete it before running the task's checks. The hook also skips, without blocking, when a Docker command is configured and Docker is not running.
3. Run the narrowest relevant check first.
4. Expand to lint, type-check, build, or the full suite in proportion to impact.
5. If a required check cannot run, report the exact command, failure, and unverified risk.

Verification matrix:

- Documentation-only change: re-read changed docs for consistency with the ADRs and glossary; run the parent workspace template check for `AGENTS.md`, `HANDOFF.md` and ADRs.
- Local implementation change: the focused test for the changed module, then `docker compose run --rm api pytest`.
- Cross-module or public-interface change: full test plus `python scripts/smoke_stack.py`, and the API contract updated in the same pull request.
- Dependency, build, or release change: `docker compose build`, `docker compose up -d --wait` from `docker compose down -v`, full test and smoke; new libraries need an Accepted ADR (ADR-0011 lists the current ones).

## Definition of done

- Requested behavior is implemented without unrelated expansion.
- Relevant tests cover the success path and important failure or edge cases.
- Applicable checks pass, or unresolved failures and their impact are explicitly reported.
- Documentation and examples match changed behavior.
- No secrets, accidental generated output, debug artifacts, or unrelated files are included.
- The final handoff names changed files, verification performed, and remaining risks.

## Nested guidance

Use a nested `AGENTS.override.md` only when a subtree needs genuinely different commands, invariants, or safety boundaries. State exactly what it replaces. Keep repository-wide rules in this root file and avoid copying them into the override.
