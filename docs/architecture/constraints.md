# Relay — Architecture Constraints

## Status
Current. Hard constraints come from the owner's brief; decisions are recorded as ADRs in `decisions/`.

## Hard constraints

1. **Free/open-source only.** Relay must remain fully functional using free and open-source software. A paid dependency (including a paid tier of a freemium service or a hosted AI API) requires an explicit owner decision recorded as an Accepted ADR.
2. **Local development is canonical.** The full environment runs locally via Docker Compose. Local is not a subset of "the real environment"; it is the real environment.
3. **Cloud is optional demo infrastructure only.** Any cloud deployment uses free tiers and is never required for function.
4. **Synthetic data only.** Relay never handles real payments or card data.
5. **Fixed stack** ([ADR-0001](../decisions/0001-stack.md), Accepted; amended by [ADR-0012](../decisions/0012-phase-1-review-decisions.md)): Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Valkey (Redis-compatible stream server, replacing Redis, whose 7.4 and later releases are not open source), Next.js, TypeScript, Docker Compose, pytest, Playwright, GitHub Actions. Container images are pinned to exact versions, and each licence is checked again whenever a pin changes.

## Decisions taken

- **Positioning, single merchant, auth, routing paths:** [ADR-0002](../decisions/0002-positioning-and-business-problem.md). One merchant; one static API key from an environment variable; two simulated processors with injectable outages.
- **Event backbone and event history:** [ADR-0003](../decisions/0003-payment-event-history.md). PostgreSQL is the source of truth; an append-only `payment_events` table is written in the same database transaction as each state change; a relay process publishes rows to Redis Streams. No heavier broker before there is evidence Redis is a bottleneck (risk R5).
- **Payment rules:** [ADR-0004](../decisions/0004-payment-fundamentals.md) and [payment-lifecycle.md](payment-lifecycle.md). Idempotency, integer minor-unit money, state machine.
- **Testing split:** pytest for backend unit and integration tests; Playwright for UI smoke and end-to-end tests. GitHub Actions runs pytest on every pull request and every push to `main`, and Playwright on pull requests only ([ADR-0007](../decisions/0007-development-tooling-and-ci-scope.md)).
- **Currencies, UI access, stored explanations, demo measurement:** [ADR-0009](../decisions/0009-phase-1-owner-decisions.md). USD, EUR, GBP and JPY only; every endpoint needs the API key and the UI uses server routes; explanations stored at final failure; 2-hour manual baseline; static baseline without retry; reproducible within a stated tolerance.

- **Payment attempts and processing reliability:** [ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md) (Accepted 2026-10-01). Attempt numbers, final outcome, state-guarded worker, idempotent processor calls, recovery of stalled work.
- **Local model:** [ADR-0010](../decisions/0010-local-model.md). `granite3.3:2b` (Apache 2.0) on the host Ollama.
- **Review decisions:** [ADR-0012](../decisions/0012-phase-1-review-decisions.md). Payment `reference` with paired, repeatable demo runs; Valkey and exact image pins; explanations in their own container and restart policies; frontend route access rule; regeneration through POST; decided reason values and late results; reporting per explanation source and per rescue path.
- **Build decisions:** [ADR-0011](../decisions/0011-phase-1-build-decisions.md). Clean-clone setup, exact versions, runtime libraries uvicorn, psycopg 3, redis-py, httpx and pydantic-settings added to the stack, sweeper grace period, routing rule, model quality check, host-port overrides.

## Decisions still proposed

- **AI explanation provider** ([ADR-0005](../decisions/0005-ai-explanation-provider.md), Proposed): a local open-source model via Ollama with a deterministic rule-based fallback. Hosted paid APIs need an owner decision.
- **Observability stack** ([ADR-0006](../decisions/0006-observability-stack.md), Proposed): Prometheus and Grafana, to be confirmed at Phase 2 kickoff.

## Process constraint
Any dependency, library or service not in the fixed stack, even if free today, needs an owner decision recorded as an Accepted ADR before adoption, because free tiers change and dependencies add maintenance and security surface.

## Development tooling and CI
Decided in [ADR-0007](../decisions/0007-development-tooling-and-ci-scope.md) (Accepted 2026-10-01): ruff, mypy, pytest-cov, pip-audit, ESLint, Prettier, Vitest with Testing Library, axe-core, npm audit and gitleaks; lint, type check, tests and secret scan on every push, end-to-end tests on pull requests only, dependency audits weekly and on dependency changes.

## Platform limits
The private repository is on the free GitHub plan: branch protection and rulesets are unavailable (checked 2026-09-30, HTTP 403), so "CI must pass before merge" is enforced by the task loop (`gh pr checks`), not by GitHub; and private Actions minutes are limited, so CI caches dependencies and images and runs Playwright only on pull requests (risk R12).
