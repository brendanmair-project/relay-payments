# Tools: Relay

Template: claude/project-tools@1

Last reviewed: 2026-09-30

## Stack

| Layer | Tool and version | Why (decision record) |
|---|---|---|
| API and worker | Python with FastAPI; versions pinned in requirements files in REL-12 | [ADR-0001](../decisions/0001-stack.md) |
| Database | PostgreSQL with SQLAlchemy and Alembic migrations | [ADR-0001](../decisions/0001-stack.md), [ADR-0003](../decisions/0003-payment-event-history.md) |
| Events | Redis Streams (transactional outbox from Postgres) | [ADR-0001](../decisions/0001-stack.md), [ADR-0003](../decisions/0003-payment-event-history.md) |
| Web UI | Next.js with TypeScript; `package-lock.json` installed with `npm ci` | [ADR-0001](../decisions/0001-stack.md) |
| Local runtime | Docker Desktop 29.8.1 on WSL2, Docker Compose v5.5.1 (verified 2026-09-30) | [ADR-0001](../decisions/0001-stack.md) |
| Tests | pytest, Vitest, Playwright | [ADR-0001](../decisions/0001-stack.md); tooling scope in ADR-0007 (written in REL-49) |
| AI explanations | Ollama on the host with `granite3.3:2b` (Apache 2.0, installed 2026-10-01) plus a rule-based fallback | [ADR-0005](../decisions/0005-ai-explanation-provider.md), [ADR-0010](../decisions/0010-local-model.md) |
| Observability | Prometheus and Grafana (Proposed, confirmed at Phase 2 kickoff) | [ADR-0006](../decisions/0006-observability-stack.md) |
| CI | GitHub Actions | [ADR-0001](../decisions/0001-stack.md) |

## Commands

| Purpose | Command | Where it runs |
|---|---|---|
| Start the stack | `docker compose up -d --wait` | Host |
| Backend tests | `docker compose run --rm api pytest` | api container |
| Backend lint and types | `docker compose run --rm api sh -c "ruff check . && mypy app"` | api container |
| Simulator tests | `docker compose run --rm simulator pytest` | simulator container |
| Frontend lint and build | `npm --prefix frontend run lint && npm --prefix frontend run build` | Host |
| Frontend tests | `npm --prefix frontend test` | Host |
| End-to-end tests | `npx --prefix frontend playwright test` | Host, against the running stack |
| Stack smoke test | `python scripts/smoke_stack.py` | Host |
| SDK tests | `docker compose --profile sdk run --rm sdk pytest` | sdk container |
| CI status | `gh run list --branch main --limit 1` and `gh pr checks` | Host |
| Task status | `gh issue list -R brendanmair-project/relay` | Host |

Every command a task check uses is listed in [definition-of-done.md](definition-of-done.md); keep this table in step with it.

## Claude Code setup

| Tool | Type | Use it for |
|---|---|---|
| `.claude/hooks/verify.ps1` | Stop hook | Runs the command in `.claude/verify-command.txt` when a turn ends (set once the stack exists); skips while `.claude/tdd-red` exists or Docker is down |
| `.claude/rules/generated-docs.md` | Rule | Stops hand edits to generated docs |
| Playwright MCP (`.mcp.json`, isolated) | MCP server | Driving the UI from Claude during development |
| `security-guidance` | Plugin (this project only) | Security review of payment and API code |
| `plan-review` | Skill | Plan checks before each phase's first code task and at phase exits |
| `implementation-plan` | Skill | Turning a large task into a reviewed plan |
| `tdd` | Skill | Test-first work on every behavior change |
| `change-verification` | Skill | Running the task's checks and reporting evidence |
| `scoped-code-review` | Skill | The independent review step of the task loop |
| `playwright-cli` | Skill | Browser checks of the dashboard and boards |
| `ui-polish-audit` | Skill | Polishing the dashboard before showcase |
| `sonnet-worker`, `sonnet-reviewer` | Agents | Bounded implementation and first-pass review |

## Services and accounts

| Service | Used for | Cost and access |
|---|---|---|
| GitHub (`brendanmair-project/relay`, private) | Code, issues, Actions CI | Free private plan; cannot enforce required checks, so merge only after `gh pr checks` passes |
| Docker Desktop | Local stack | Free for personal use; installed on the owner's PC |
| Ollama | Local AI explanations | Free, local; no hosted model API without an Accepted ADR |
| Claude artifacts (Relay boards) | Private and public progress boards | Owner's claude.ai account |

## Changing tools

Add or replace a tool only through a decision record in `docs/decisions/`, then update this file, `AGENTS.md` and the task plan in the same change, and note it in `CHANGELOG.md`.
