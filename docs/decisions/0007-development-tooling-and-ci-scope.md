# ADR-0007: Development tooling and CI scope

Template: claude/decision@1

Status: Accepted (by the owner, 2026-10-01, in task REL-49)  
Decision owner: Brendan  
Date: 2026-10-01  
Supersedes: None  
Superseded by: None

## Context and forces

The planned checks (`api-lint`, `web-check`, `web-test`, `e2e`, audits, secret scan) call tools outside the fixed stack (ADR-0001, amended by ADR-0011), and every such tool needs an Accepted ADR (`docs/architecture/constraints.md`). CI (REL-13) also needs a defined scope that fits the free private plan.

- Constraint: free and open-source software only; the repository is private on GitHub Free, which includes 2,000 GitHub Actions minutes per month for the whole account (shared by every private repository the owner has, six today), 500 MB of artifact storage and 10 GB of cache per repository, and no branch protection or rulesets on private repositories (risk R12).
- Quality attribute: every merge is checked the same way locally and in CI; CI stays inside the minute budget.
- Evidence: package registries (npm and PyPI) checked 2026-10-01 for the versions and licences below; GitHub's Actions billing page checked 2026-10-01 for the allowance; branch protection unavailable checked 2026-09-30 (HTTP 403).

## Decision

We will adopt the following tools and CI scope, because they cover every planned check with free, widely used tools and keep CI well inside the shared minute budget.

### Tools outside the fixed stack

| Tool | Version | Licence | Used for | Check |
|---|---|---|---|---|
| ruff | 0.16.9 | MIT | Python lint and format (`ruff check`, `ruff format --check`) | `api-lint` |
| mypy | 2.3.1 | MIT | Python type check (`mypy app`) | `api-lint` |
| pytest-cov | 7.1.0 | MIT | Coverage report for pytest; a 90% gate on the domain and idempotency modules from REL-13 (see Coverage below), project-wide threshold set in REL-32 | `api-tests` |
| pip-audit | 2.10.1 | Apache-2.0 | Known-vulnerability audit of pinned Python dependencies | `audit` |
| ESLint with `eslint-config-next` | 9.39.5 / 16.4.3 | MIT | TypeScript and React lint | `web-check` |
| Prettier | 3.9.9 | MIT | Frontend format check | `web-check` |
| Vitest with `@vitejs/plugin-react` and jsdom | 5.0.3 / 6.1.1 / 30.1.1 | MIT | Frontend unit and component tests | `web-test` |
| Testing Library (`@testing-library/react`, `@testing-library/jest-dom`) | 16.3.3 / 7.0.1 | MIT | Component queries and assertions | `web-test` |
| `@axe-core/playwright` (axe-core) | 4.13.0 | MPL-2.0 (file-level copyleft; used unmodified as a test tool, nothing shipped) | Accessibility checks inside Playwright tests | `e2e` |
| `npm audit` | bundled with npm | Artistic-2.0 (npm) | Known-vulnerability audit of the frontend lockfile | `audit` |
| gitleaks | 8.30.1 | MIT | Secret scan of every push and the full history before publication | `secrets` |
| Semgrep CLI (Community Edition) with the registry rule sets `p/python`, `p/typescript`, `p/owasp-top-ten` | 1.182.1 | CLI: LGPL-2.1; rule sets: Semgrep Rules License v1.0 (use "only for your own internal business purposes"; no distributing the rules or making them "available to others as a service"; checked at https://semgrep.dev/legal/rules-license on 2026-10-27) | Static security analysis of `api/`, `simulator/`, `scripts/` and `frontend/` | `semgrep` |

Playwright (`@playwright/test` 1.63.0, Apache-2.0) is already in the fixed stack. All tools are dev-only; none is part of a running container's runtime path except that the api image keeps its test dependencies so `docker compose run --rm api pytest` works (ADR-0011). Versions are pinned exactly in `api/requirements-dev.txt` and `frontend/package-lock.json` by REL-13.

`httpx` stays the HTTP client and test-client transport (ADR-0011). Starlette now warns that its test client prefers `httpx2` (BSD-3-Clause); we revisit when Starlette drops `httpx` support, with a one-line amendment here.

### CI scope (GitHub Actions, Linux runners only)

| Workflow job | Runs on | What it runs | Skipped when |
|---|---|---|---|
| `backend` | Every pull request and every push to `main` | `ruff check`, `ruff format --check`, `mypy app`, `pytest --cov` against Postgres and Valkey service containers | Only `docs/**`, `*.md` or `frontend/**` changed |
| `simulator` | Every pull request and every push to `main` | `ruff`, `pytest` for `simulator/`, and `ruff` for the host-side `scripts/` | Only docs or `api/**`/`frontend/**` changed |
| `frontend` | Every pull request and every push to `main` | `npm ci`, `eslint`, `prettier --check`, `next build` (type check), `vitest run` | Only docs or `api/**`/`simulator/**` changed |
| `secrets` | Every pull request and every push to `main` | gitleaks on the pushed commits | Never |
| `e2e` | Pull requests only | `docker compose up -d --wait`, `scripts/smoke_stack.py`, Playwright with axe | Only docs changed |
| `audit` | Weekly schedule, every pull request and every push to `main` | `pip-audit`, `npm audit --audit-level=high` | Never |
| `semgrep` | Every pull request and every push to `main` (not the weekly schedule) | `semgrep scan --config p/python --config p/typescript --config p/owasp-top-ten --error --metrics off` | Never |

Minute budget: path filters skip code jobs for documentation-only changes; pip, npm and Docker layers are cached (`actions/cache`, BuildKit `type=gha`); `concurrency` cancels superseded runs on the same branch; Playwright runs on pull requests only. Expected cost: about 6 minutes per push and 15 per pull request; at 40 pushes and 15 pull requests a month, about 465 minutes, under a quarter of the shared 2,000. The REL-13 workflow prints its duration so the estimate can be checked in the Phase 1 exit review (REL-32).

Merge gate: branch protection is unavailable on the free private plan, so the task loop merges only after `gh pr checks <number>` shows every check passing (risk R12). When the repository goes public (REL-46), Actions become free and branch protection with required checks is turned on.

Coverage: from REL-13, CI enforces at least 90% line coverage on the domain (`api/app/domain/`) and idempotency (`api/app/idempotency/`) modules once they exist (`api/tools/coverage_gate.py`); the project-wide threshold is set in REL-32.

Amendment 2026-10-01 (REL-13): ESLint is pinned to 9.39.5 instead of 10.11.0, because `eslint-plugin-react` 7.37.5 bundled by `eslint-config-next` 16.3.8 fails on ESLint 10 (it calls the removed `context.getFilename`); revisit when the plugin supports ESLint 10.

Amendment 2026-10-14 (ADR-0012, owner-approved review of 2026-10-09): branch pushes run CI only on `main`, because pull requests already cover branches and a push to a branch with an open pull request otherwise ran the workflow twice; every job has `timeout-minutes` (GitHub's default is 360); service images are pinned exactly (`postgres:16.15`, `valkey/valkey:9.1.2`); `pip-audit` reads the dev requirement files, which include the runtime ones, because the api image ships its test dependencies; the account's 2,000 minutes are shared by seven private repositories, with Relay's monthly budget set to 600 in the workspace `projects/README.md`.

Amendment 2026-10-26 (REL-13, owner-approved): `eslint-config-next` follows Next.js to 16.4.3 (MIT), because the first CI audit failed on Next.js 16.3.8 advisories (ADR-0011 amendment of the same date); ESLint 9.39.5 still works with it.

Amendment 2026-10-26 (owner-approved, after the Next.js finding): the `audit` job runs on every pull request and push to `main`, not only when a requirements or lock file changes, because new advisories are published against versions that have not changed; it costs about half a minute per run. Every job runs on `ubuntu-24.04` instead of `ubuntu-latest`, which GitHub began moving to Ubuntu 26 on 2026-10-19, so a runner change arrives as a reviewed edit.

Amendment 2026-10-27 (REL-55, owner-approved tooling review): Semgrep Community Edition 1.182.1 (CLI under LGPL-2.1) scans the Python and TypeScript code in a new `semgrep` job, installed with `pip install semgrep==1.182.1`, `timeout-minutes: 10`, on every pull request and push to `main` and not on the weekly schedule. The registry rule sets `p/python`, `p/typescript` and `p/owasp-top-ten` (Semgrep Rules License v1.0: running them on our own code in our CI is internal use; the rules are not copied into the repository, so publishing it later distributes nothing) cover both languages and the OWASP Top Ten; `--error` fails the job on any finding and `--metrics off` sends nothing to Semgrep. It costs about one minute per run. The first scan found only `github-actions-mutable-action-tag` on the `uses:` lines of `ci.yml` (14 lines); these first-party and Docker-maintained actions stay on major tags (`@v7`, `@v4`) so Dependabot-style updates remain simple, and each line carries an inline `nosemgrep` suppression. Pinning actions to commit SHAs is a possible later hardening. Local command: AGENTS.md, Authoritative commands.

Amendment 2026-11-09 (REL-45, owner-approved): the licences of the development tooling that no ADR stated (the SDK's setuptools build backend and the `@types` packages) are recorded with the rest of the audit in the ADR-0011 amendment of the same date. They are all MIT, taken from upstream.

Amendment 2026-10-28 (REL-56, owner decision): every GitHub Action in `.github/workflows/` is pinned to a full commit SHA with its release tag in a trailing comment (`uses: actions/checkout@<sha> # v7.0.1`), each SHA read from the action's official repository for that tag (`gh api repos/<owner>/<repo>/commits/<tag>`); the REL-55 `nosemgrep` suppressions are removed, so Semgrep's `github-actions-mutable-action-tag` rule now enforces the pin. An update is a reviewed edit of both the SHA and the tag comment. Pinned on 2026-10-28: `actions/checkout` v7.0.1, `actions/setup-python` v7.1.0, `actions/setup-node` v7.1.0, `docker/setup-buildx-action` v4.4.1, `docker/bake-action` v7.5.0.

Deferred: a project-wide coverage threshold (set in REL-32 from the Phase 1 baseline), CodeQL and dependency review (need GitHub Advanced Security on private repositories; revisit at REL-46), Dependabot version updates (Phase 2), performance and load tests in CI (Phase 2).

## Alternatives considered

| Alternative | Benefits | Costs/risks | Why not selected |
|---|---|---|---|
| Keep current state (no tooling ADR) | No work | Checks call unapproved tools; REL-13 cannot start | Blocks CI |
| flake8 + black + isort instead of ruff | Long history | Three tools, slower | ruff covers all three |
| pyright instead of mypy | Fast, strict | Node dependency in the Python toolchain | mypy fits the Python-only image |
| Jest instead of Vitest | Widely used | Slower, more configuration with Next.js and ESM | Vitest is simpler for this stack |
| TruffleHog instead of gitleaks | Verifies live credentials | AGPL-3.0; network calls to verify | gitleaks is MIT and offline |
| Run every job on every push | Simplest | Roughly doubles minutes; e2e is the slowest job | Path filters and PR-only e2e keep the budget |

## Consequences

### Positive

- Every planned check has an approved tool; local and CI runs use the same commands and pins.

### Negative and tradeoffs

- More dev dependencies to keep updated (the weekly audit flags vulnerable ones).
- Without branch protection, the merge gate depends on the task loop being followed until publication.

### Follow-on work

- REL-13 builds `.github/workflows/ci.yml`, pins these tools, wires `.claude/verify-command.txt`, and links this ADR.
- Update `AGENTS.md` lint, type-check and format commands when REL-13 lands.

## Validation and review

- Validate with: REL-13's first green run on a pull request; the run time against the estimate at REL-32.
- Revisit when: the account's Actions minutes pass half the allowance in a month, Starlette drops `httpx`, or the repository goes public.
- Reversal/migration cost: Low; each tool is replaceable on its own.
