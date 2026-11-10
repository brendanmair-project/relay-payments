# ADR-0011: Phase 1 build decisions: setup, versions, runtime libraries and small rules

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-10-01  
Supersedes: None (amends ADR-0001's library list)  
Superseded by: None

## Context and forces

The plan review before Phase 1's first code task (REL-12) found choices the design left open, which REL-12, REL-22, REL-25 and REL-50 would otherwise have invented. The owner chose the recommended option for each on 2026-10-01.

- Constraint: free and open source only; any library outside the fixed stack needs an Accepted ADR (`docs/architecture/constraints.md`); `docker compose up -d --wait` must work from a clean clone.
- Quality attribute: reproducible builds and an exact processing outcome under at-least-once delivery (ADR-0008).
- Evidence: pre-REL-12 plan review of 2026-10-01 (recorded in `docs/delivery/process-log.md`, session 9); package versions checked against PyPI and npm on 2026-10-01.

## Decision

We will apply the following, because each removes a guess from Phase 1 without adding risk:

1. **Clean-clone setup.** `.env.example` ships an obviously local placeholder `RELAY_API_KEY`; the README's first command is `cp .env.example .env`; compose refuses to start when the key is empty (`${RELAY_API_KEY:?}`).
2. **Versions.** Base images `python:3.12-slim`, `node:24-slim`, `postgres:16`, `redis:7`. Libraries are pinned exactly: FastAPI 0.142.2, uvicorn 0.54.0, pydantic-settings 2.15.0, SQLAlchemy 2.1.1, Alembic 1.20.0, psycopg[binary] 3.3.6, redis 8.1.0, httpx 0.28.1, pytest 9.1.1; Next.js 16.3.8, React 19.3.0, TypeScript 5.9.3 (the last 5.x line; TypeScript 7 is too new for Next.js tooling).
3. **Runtime libraries.** uvicorn (ASGI server), psycopg 3 (PostgreSQL driver), redis-py (Redis client), httpx (HTTP client for the worker and tests) and pydantic-settings (configuration) are part of the ADR-0001 stack. Linters, type checkers and test tooling remain ADR-0007's (REL-49).
4. **Sweeper timeout.** The sweeper fails an attempt only after `PROCESSOR_TIMEOUT_SECONDS` plus `SWEEP_TIMEOUT_GRACE_SECONDS` (default 5), so it never races the worker's own HTTP timeout.
5. **Routing rule.** The router prefers Processor A and uses B only when A is `avoided` and B is not; when both are `avoided` or `unknown`, it stays on A.
6. **Model quality check (REL-25).** Ten fixed timelines are explained by the model; the check passes when every citation in all ten is a valid event `seq`. It runs manually, outside CI. On failure the rules text is shown and `granite3.3:8b` is considered (ADR-0010).
7. **Host ports.** 3000, 8000 and 8101 stay the defaults and can be changed with `FRONTEND_HOST_PORT`, `API_HOST_PORT` and `SIM_CONTROL_HOST_PORT` in `.env`; the contract's URLs describe the defaults.

Amended 2026-10-09 by [ADR-0012](0012-phase-1-review-decisions.md): item 2's base images were major or minor tags, which let `redis:7` move to Redis 7.4 (not open source); images are now pinned exactly (`postgres:16.15`, `valkey/valkey:9.1.2`, `python:3.12.15-slim`, `node:24.21.0-slim`).

Amended 2026-10-26 (REL-13, owner-approved): item 2's Next.js pin moves from 16.3.8 to 16.4.3 (MIT, rechecked on npm), because the first CI dependency audit found a critical advisory (GHSA-2464-fhr4-w9xw, remote code execution in the Image Optimization API) and two more high ones that 16.3.8 does not fix; `npm audit fix` also moved the transitive vite, undici and zod versions in the lock file. Next.js 16.4 rewrites `frontend/tsconfig.json` on build (`jsx: react-jsx`, `.next/dev/types` included), so that file is committed in the rewritten form.

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| A setup script that generates the key | No placeholder key | One more script to maintain | Copying the example is simpler and still safe locally |
| Major-only image tags | Fewer edits | Builds drift silently | Exact pins make results reproducible |
| Write ADR-0007 before REL-12 | Tooling decided once | Delays the skeleton | Runtime libraries are needed now; tooling can wait |
| Sweeper timeout equal to the worker timeout | One setting | The two write at the same moment; the loser is mislabelled | A grace period removes the race |

## Consequences

### Positive

- REL-12 to REL-50 build from decided values; nothing is invented in code review.

### Negative and tradeoffs

- Exact pins need a deliberate update pass; ADR-0007 (REL-49) sets how dependency updates are checked.

### Follow-on work

- `docs/architecture/containers.md` gains `TEST_REDIS_URL`, `SWEEP_TIMEOUT_GRACE_SECONDS`, the host-port variables, the load-generator location and the idempotency cleanup in the worker; the plan tasks REL-12 to REL-52 are updated to match.

## Validation and review

- Validate with: REL-12's checks from a clean clone; REL-50's timeout test with the grace period; REL-22's routing tests for both-avoided and both-unknown.
- Revisit when: a dependency needs a security update, or a third processor is added.
- Reversal/migration cost: Low.

Amendment 2026-11-09 (REL-45, owner-approved): the final dependency audit (`docs/evaluation/phase-4-exit-review.md`, section 2) found licences that no ADR stated. All are free and open source, and none is paid. They are recorded here. "Upstream" marks a licence taken from the upstream project rather than re-read from the built artefact.

| Item | Version | Licence |
|---|---|---|
| psycopg[binary] (runtime) | 3.3.6 | LGPL-3.0-only, read from the api image; used unmodified as an installed library |
| `@img/sharp-*` and `@img/sharp-libvips-*` (optional platform binaries of Next.js's image optimiser, frontend lock file) | as locked | LGPL-3.0-or-later, some combined with Apache-2.0 and MIT; none is a direct dependency |
| postgres image | 16.15 | PostgreSQL Licence (upstream) |
| python base image (api, simulator, sdk) | 3.12.15-slim | PSF licence (upstream) |
| node base image (frontend) | 24.21.0-slim | MIT (upstream) |
| ollama/ollama server (optional `llm` profile) | 0.40.11 | MIT (upstream); the model's licence is in ADR-0010 |
| setuptools (SDK build backend) | 80.9.0 | MIT (upstream) |
| @types/node, @types/react (development types) | 24.19.0, 19.3.0 | MIT (upstream) |

Re-check these licences whenever a version changes, as ADR-0012 requires for every pin.
