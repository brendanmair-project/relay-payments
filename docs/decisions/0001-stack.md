# ADR-0001: Fixed technology stack

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-09-29  
Supersedes: None  
Superseded by: None

## Context and forces

Relay needs a stack chosen before Phase 1 so that the repository guidance, CI and issues can name real tools. The stack was fixed in the original project brief; this ADR records it as an owner decision and states why alternatives were not taken.

- Constraint: Free and open-source software only; local development via Docker Compose is the canonical environment (`docs/architecture/constraints.md`).
- Quality attribute: Demonstrable, testable and reproducible from a clean clone by a reviewer of a portfolio project.
- Evidence: `docs/architecture/constraints.md` lists the fixed stack; Phase 1 exit criteria in `docs/product/roadmap.md` require `docker compose up`, pytest and Playwright in CI.

## Decision

We will use Python with FastAPI, PostgreSQL with SQLAlchemy and Alembic, Redis (Redis Streams for the event backbone), Next.js with TypeScript for the UI, Docker Compose for local orchestration, pytest and Playwright for tests, and GitHub Actions for CI, because this stack is fully free and open source, runs locally end to end, and covers the API, data, event and UI layers the showcase slice needs.

Amended 2026-10-09 by [ADR-0012](0012-phase-1-review-decisions.md): Valkey (Redis-compatible, BSD-3-Clause) replaces Redis as the stream server, because Redis 7.4 and later releases are not open source; every container image is pinned to an exact version.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (no stack chosen) | No commitment | Blocks Phase 1 planning, CI and repository guidance | A portfolio slice needs a concrete, buildable stack |
| Node-only backend (TypeScript end to end) | One language across API and UI | Weaker fit for the planned data and AI-adjacent work; owner prefers Python for the backend | Python and FastAPI give typed request models, OpenAPI docs and simple async I/O |
| Django (with Django REST framework) | Batteries included, mature ORM and admin | Heavier framework; less natural for a small async, event-oriented service | FastAPI plus SQLAlchemy and Alembic gives explicit control over transactions, which the outbox design needs |

## Consequences

### Positive

- Every component runs locally with `docker compose up` and no paid service.
- OpenAPI documentation comes from FastAPI, supporting later developer docs.

### Negative and tradeoffs

- Two languages (Python, TypeScript) and two test frameworks to maintain.
- Redis Streams is lighter than a dedicated broker; see risk R5 in `docs/delivery/risk-register.md`.

### Follow-on work

- Fill in real commands in `AGENTS.md` when Phase 1 code lands.
- Any dependency outside this list needs an owner decision recorded as an Accepted ADR.

## Validation and review

- Validate with: `docker compose up` and the CI pipeline (pytest and Playwright) at the Phase 1 exit.
- Revisit when: Redis Streams proves inadequate (risk R5) or a required capability cannot be met with this stack.
- Reversal/migration cost: Low before Phase 1 code exists; high once the API and data model are built on it.
