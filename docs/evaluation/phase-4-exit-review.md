# Phase 4 exit review (REL-45, evidence half)

Date: 2026-11-09. Reviewed commit: `33f1466` (worktree `rel45`, branch `rel-45-phase-4-exit-review-and-project-r`; the clean clone below is of this commit, and this review adds only documents). All data is synthetic. This file records evidence; nothing in the code was changed by this review, and the findings in section 7 are recorded, not fixed. The owner decision of 2026-11-09 is fixed: Phase 4 closes with its exit criterion **not met** after two pre-registered attempts (REL-44 `adaptive`, REL-60 `hybrid`). Every figure below is copied from a committed results file and cited; figures marked "recomputed" were also recalculated from the saved per-run outcome files by this review.

Verdict key: Met, Partly met, Not met. Evidence is a command and what it printed, a file link, or a CI run. Live runs used a shell-only `RELAY_API_KEY` (a plain value, no env file), Docker Compose in a clean clone (project `rel45clean`), and ended with `down -v`.

## Summary

Phase 4 criterion 1 (adaptive routing beats rule-based routing by a stated, reproducible measure) is **Not met**; criterion 2 (no paid dependency without an Accepted ADR) is **Met**.

- Two strategies were measured under the win rule fixed before any run (ADR-0016): `adaptive` (Thompson sampling, REL-44, seeds 11 to 15) and `hybrid` (rules plus a gated sampler, ADR-0017, REL-60, fresh deciding seeds 21 to 25). Neither wins. `adaptive` passes one of three conditions; `hybrid` passes none.
- The one result that held on both iterations is the partial degradation (`processor-a-degraded`, a fault the rule router's 0.5 threshold cannot see): `adaptive` +2.73 pp with latency ratio 0.340, `hybrid` +2.00 pp with ratio 0.605, never worse than `rules` in the `hybrid` run (4 of 5 pairs better, 1 tied).
- The two failures have different causes. REL-44: the calm-day latency guardrail (1.829; cause of its size not established). REL-60: the ADR-0017 gate reasoning was flawed (a 5-attempt window opens the gate on one random error), and exact ties count as "not better", which caps the better-share at 11 of 15 (73%) for any gated design against the 80% bar.
- Audit: every runtime and development dependency and every image is free and open source; no paid service or hosted AI API appears in code or compose. Three licence facts are not stated in any ADR (section 2, items A to C); none is paid, none is a violation of the open-source rule.
- Clean clone: `docker compose up -d --wait --build` exit 0 in 29 s (warm cache), 10 long-running services healthy, `scripts/smoke_stack.py` 19 of 19 checks PASS.
- Hygiene: `PROJECT_HYGIENE=PASS CHECKED=2`. CI on `main`: `success` (the push of `33f1466`).
- Risks: R1, R3, R14 and R19 closed; R20 added (section 4). All 17 ADRs are Accepted and stay so (section 5).

## 1. Roadmap exit criteria (`docs/product/roadmap.md`, Phase 4)

| Criterion | Verdict | Evidence |
|---|---|---|
| Adaptive routing beats the Phase 1 rule-based routing on the synthetic environment by a stated, reproducible measure | **Not met** | Section 1.1 to 1.4. Stated measure and win rule: ADR-0016 and `docs/evaluation/routing-experiments/protocol.md`. Reproducible: yes (REL-30 reproduced exactly, same-seed rerun identical for 300 of 300 references); but neither strategy meets the rule |
| Any paid dependency has an owner decision recorded as an Accepted ADR; otherwise the feature works with free and open-source tooling | **Met** | Section 2 audit: no paid dependency exists, so none needs an ADR; every pin is free and open source |

### 1.1 The measure and the rule (fixed before any comparison)

From `protocol.md` and ADR-0016. Objective: success rate, payments `captured` over final payments, paired per seed on identical payment references (`<scenario>-<seed>-<index>`); revenue per currency is reported alongside, never added across currencies. A candidate wins against `rules` over 3 scenarios by 5 seeds (15 pairs) only when all three hold:

1. the mean paired success-rate uplift is at least 1.0 percentage point;
2. it is better (strictly above zero) on at least 80% of the pairs (12 of 15);
3. p95 creation-to-final latency is at most 1.10 times that of `rules` in every scenario (ratio of the five-seed means).

Scenarios: `normal-day` (200 payments), `processor-a-outage` (300, Processor A down for payments 100 to 199), `processor-a-degraded` (300, A's timeout rate 0.35 for payments 100 to 199, chosen once by reasoning so that A's error rate stays under the rule router's 0.5 threshold and no calibration run existed).

### 1.2 Iteration 1: `adaptive` on seeds 11 to 15 (REL-44, PR #382)

Source: [`routing-experiments/rel44/results.md`](routing-experiments/rel44/results.md) (30 runs, 7600 s of run time). Verdict printed there: NOT A WIN.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +1.82 pp | at least 1.0 pp | yes |
| Pairs better | 10 of 15 (67%) | at least 80% | no |
| Worst scenario p95 latency ratio | 1.829 (`normal-day`) | at most 1.10 | no |

Recomputed from the 30 saved outcome files: 15 pairs, mean +1.82 pp, 10 better, 1 tied, 4 worse; per scenario `normal-day` +3.60 pp (5 of 5 better), `processor-a-outage` -0.87 pp (1 of 5), `processor-a-degraded` +2.73 pp (4 of 5), as in the results file. Latency ratios are not recomputable from the outcome files (they hold status and routing, not times) and are taken from the results file.

### 1.3 Iteration 2: `hybrid` on fresh deciding seeds 21 to 25 (REL-60, PR #394)

Source: [`routing-experiments/rel60/results.md`](routing-experiments/rel60/results.md) (60 runs in six parts, 15327 s total, 7793 s for the deciding set). Verdict printed there: NO WIN.

| Condition | Observed | Required | Holds |
|---|---|---|---|
| Mean paired uplift | +0.58 pp | at least 1.0 pp | no |
| Pairs better | 8 of 15 (53%) | at least 80% | no |
| Worst scenario p95 latency ratio | 1.473 (`normal-day`; `processor-a-outage` also over at 1.118) | at most 1.10 | no |

Recomputed from the saved outcomes: 15 deciding pairs, mean +0.58 pp, 8 better, 5 tied, 2 worse (the two worse pairs are `processor-a-outage` seeds 21 and 24). On the comparison-only seeds 11 to 15 (not deciding): +0.36 pp, 5 better, 8 tied, 2 worse, worst latency ratio 1.004, against `adaptive` on the same seeds +1.82 pp, 10 of 15, 1.829.

### 1.4 Where each strategy helps and costs (per scenario, both iterations)

| Scenario | `adaptive` (seeds 11 to 15): mean, pairs better, p95 ratio | `hybrid` (seeds 21 to 25, deciding): mean, pairs better, p95 ratio | Exploration cost to the faulty processor (`rules` / strategy) |
|---|---|---|---|
| `normal-day` | +3.60 pp, 5 of 5, 1.829 (fails) | +0.20 pp, 1 of 5 (4 exact ties), 1.473 (fails; all from seed 21) | none (no degraded processor) |
| `processor-a-outage` | -0.87 pp, 1 of 5, 0.808 | -0.47 pp, 3 of 5, 1.118 (fails) | adaptive 89.2% / 7.2%; hybrid 89.4% / 14.4% |
| `processor-a-degraded` | +2.73 pp, 4 of 5, 0.340 | +2.00 pp, 4 of 5, 0.605 | adaptive 39.8% / 6.8%; hybrid 55.6% / 28.2% |

Reading: both strategies help where the faulty processor is below the rule router's threshold (the degraded scenario: gain in success and a large cut in latency) and cost a little in the full outage, where `rules` already rescues most payments with its retry and failover. The calm-day behaviour differs: `adaptive` gains success (it prefers Processor B, whose simulated decline and timeout rates are lower) but pays in latency; `hybrid` ties `rules` by design on a calm day except where its gate opens on noise.

### 1.5 Pre-registration evidence

| Item | Evidence |
|---|---|
| Win rule, scenarios, seeds and guardrail fixed before any comparison | `protocol.md` came in with REL-43 (`3bb0d4d`, 2026-11-06 15:43 -0600) and the first runs there were `static` against `rules` only (`routing-experiments/first-runs.md`); ADR-0016 is dated 2026-11-06 |
| REL-44 parameters (window 120 s, half-life 30 s, prior Beta(1, 1)) fixed before the first `adaptive` run | `protocol.md` section "Adaptive strategy parameters" states they were fixed "before any `adaptive` comparison run, from the reasoning below and not from any result". The primary's check in `docs/delivery/process-log.md` (session 38) timed the fix at 19:10 and the first adaptive run at 19:30 on 2026-11-06. The branch history is squashed (`4a512d5`), so the order is not visible in the commits; this rests on that record |
| REL-60 protocol v2 (deciding seeds 21 to 25, gate 0.15, unchanged win rule) committed before any comparison run | Commit `62ae8c8` (2026-11-09 08:19:46 -0600) contains the `hybrid` code, the harness merge function and the "Protocol v2" section of `protocol.md` (`git show 62ae8c8 --stat`); the results arrive in `9a07eca` (15:28:18 -0600 the same day). The saved outcome files carry only checkout times, so the commit order is the evidence; the primary's record in the process log (session 40) says the images were rebuilt first and a smoke run (not counted) checked the routed reasons |
| Nothing tuned after a result | REL-44 parameters unchanged; REL-60 kept the gate and the rule although the first pair and the smoke showed the calm-day sampling (process log, session 40). Neither the gate nor the rule was changed after seeing results |
| No run repeated to change a number | REL-44: four runs unfinished at the tool's two-hour limit were completed once, none redone (`rel44/results.md`, "How the run was executed"). REL-60: "No run was repeated" (`adaptive-routing-results.md`) |

### 1.6 The two diagnosed causes

**REL-44 calm-day latency (open question, see section 6).** `adaptive` sent 52% to 92% of `normal-day` initial routes to Processor B and its p95 ratio was 1.829 (mean p95 about 36 s against about 20 s). The cause of the size is not established.

**REL-60 gate flaw and ties** (`rel60/results.md`, findings (a) and (b)):

- ADR-0017 argued the 0.15 gate is 2.5 times the noisy calm-day ceiling. That held for a long run of attempts, not at the point where the gate opens: the zone needs only `HEALTH_MIN_ATTEMPTS` = 5 attempts, and at 5 attempts one random error is a rate of 0.2, above 0.15. `app/routing/hybrid.py` implements the ADR exactly; the flaw is in the ADR's reasoning. Counted from the outcomes: `normal-day` deciding seed 21 had 174 adaptive routes of 200 payments (from payment 5), a p95 of 47.7 s against 17.4 s for `rules`; seeds 22 to 25 had none. That one seed is the whole `normal-day` ratio of 1.473.
- Exact ties count as "not better". A gated hybrid routes exactly as `rules` when no processor is in the zone, so 4 of the 5 `normal-day` deciding pairs are exact ties (seeds 22 to 25: identical success and revenue). The better-share therefore cannot exceed 11 of 15 (73%) against the 80% bar, whatever the other pairs do. Deciding pairs: 8 better, 5 tied, 2 worse.

Consequence for the verdict: with the rule unchanged, a gated design cannot pass condition 2 even if everything else goes well. That is a property of the rule together with the design, recorded here, and it does not change the result.

### 1.7 Owner decision and future work

Owner decision 2026-11-09: Phase 4 closes with criterion 1 **not met** after the two pre-registered attempts. Listed as future work, not started: a gate that cannot open on one noisy error (a larger attempt minimum or a confidence test) and a rule that does not penalise a deliberate tie, which together need a new ADR, a new protocol and a new set of seeds. The owner's future-work item is a gate that needs about 20 attempts in its window before it opens (the REL-60 gate opened at 5); even then calm-day ties still cap the better-share near 73% under the unchanged ADR-0016 rule. The shipped default stays `ROUTING_STRATEGY=rules` (`docker-compose.yml` lines 77 and 147, `.env.example`); `adaptive` and `hybrid` are opt-in.

## 2. Dependency and paid-service audit (criterion 2)

Verdict: **Met**. Method: manifests and the lock file read (`api/requirements.txt`, `api/requirements-dev.txt`, `simulator/requirements.txt`, `simulator/requirements-dev.txt`, `sdk/python/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json`, `docker-compose.yml`, the four Dockerfiles); Python licences read from the installed package metadata inside the images built from the clean clone (`importlib.metadata`, `License-Expression` or `License` field); npm licences read from the `license` field of each entry in `package-lock.json`; image licences are those the ADRs recorded or, where marked, the upstream project's licence not re-read from the image. Every Python and npm version is an exact pin; every image tag is an exact version (`PROJECT_HYGIENE=PASS CHECKED=2`).

### 2.1 Python runtime (api, worker, publisher, explainer, incidents, webhooks)

| Package | Version | Licence | Where recorded |
|---|---|---|---|
| fastapi | 0.142.2 | MIT | ADR-0001/0011 (stack, versions); licence read from the image |
| uvicorn | 0.54.0 | BSD-3-Clause | ADR-0011 item 3; licence read from the image |
| pydantic-settings | 2.15.0 | MIT | ADR-0011; read from the image |
| sqlalchemy | 2.1.1 | MIT | ADR-0001/0011; read from the image |
| alembic | 1.20.0 | MIT | ADR-0001/0011; read from the image |
| psycopg[binary] | 3.3.6 | LGPL-3.0-only | ADR-0011 names it; **licence not stated in an ADR (item A)** |
| redis (redis-py) | 8.1.0 | MIT | ADR-0011/0012; read from the image |
| httpx | 0.28.1 | BSD-3-Clause | ADR-0011, ADR-0007, `docs/guides/sdk.md` (checked 2026-11-05) |
| prometheus-client | 0.26.0 | Apache-2.0 AND BSD-2-Clause | ADR-0006 (Apache-2.0) |

Transitive packages seen in the images: pydantic 2.14.2 (MIT), starlette 1.10.0 (BSD-3-Clause).

### 2.2 Python development and test tooling

| Package | Version | Licence | Where recorded |
|---|---|---|---|
| pytest | 9.1.1 | MIT | ADR-0011 |
| pytest-cov | 7.1.0 | MIT | ADR-0007 |
| ruff | 0.16.9 | MIT | ADR-0007 |
| mypy | 2.3.1 | MIT | ADR-0007 |
| pip-audit | 2.10.1 | Apache-2.0 (the package metadata lists "Apache Software License") | ADR-0007 |
| relay-sdk | 0.1.0 | MIT | `docs/guides/sdk.md`; installed from the repository, not published; its only runtime dependency is httpx 0.28.1; its dev extra is pytest, ruff, mypy at the api's pins |
| setuptools (build, sdk) | 80.9.0 | MIT (read upstream, not re-read here) | not stated in an ADR (item C) |

The simulator runtime is fastapi 0.142.2 and uvicorn 0.54.0 (same licences as above); its dev tools are pytest 9.1.1, httpx 0.28.1 and ruff 0.16.9.

### 2.3 Frontend (`package.json`, 527 packages in the lock file)

| Direct package | Version | Licence (lock file) | Where recorded |
|---|---|---|---|
| next | 16.4.3 | MIT | ADR-0011 amendment 2026-10-26 |
| react, react-dom | 19.3.0 | MIT | ADR-0001/0011 |
| typescript | 5.9.3 | Apache-2.0 | ADR-0011 (version) |
| eslint 9.39.5, eslint-config-next 16.4.3, prettier 3.9.9, vitest 5.0.3, @vitejs/plugin-react 6.1.1, jsdom 30.1.1, @testing-library/react 16.3.3, @testing-library/jest-dom 7.0.1 | as listed | MIT | ADR-0007 |
| @playwright/test 1.63.0 | | Apache-2.0 | ADR-0007 |
| @axe-core/playwright, axe-core 4.13.0 | | MPL-2.0 | ADR-0007 (file-level copyleft, test tool, nothing shipped) |
| @types/node 24.19.0, @types/react 19.3.0 | | (types only; MIT upstream, not re-read) | not stated in an ADR (item C) |

Lock-file licence counts for non-development packages (the ones that can ship in the frontend image): MIT 19, Apache-2.0 19, LGPL-3.0-or-later 10, ISC 2, and one each of BSD-3-Clause, CC-BY-4.0 (`caniuse-lite`), 0BSD (`tslib`), plus 4 entries with a combined expression that includes LGPL-3.0-or-later. The LGPL entries are all `@img/sharp-*` and `@img/sharp-libvips-*`, optional platform binaries of Next.js's image optimiser; none is a direct dependency and none is stated in an ADR (**item B**). Development-only packages: MIT 395, Apache-2.0 22, ISC 19, MPL-2.0 14, BSD-2-Clause 9, BlueOak-1.0.0 4, MIT-0 2, BSD-3-Clause 2, CC0-1.0 2, Python-2.0 1. No entry has a proprietary, source-available or field-of-use licence.

### 2.4 Container images and CI tools

| Image or tool | Version | Licence | Where recorded |
|---|---|---|---|
| postgres | 16.15 | PostgreSQL Licence (upstream project licence, not re-read from the image) | ADR-0001 (stack); licence not stated (item C) |
| valkey/valkey | 9.1.2 | BSD-3-Clause | ADR-0012 |
| python (base of api, simulator, sdk) | 3.12.15-slim | PSF licence (upstream) | ADR-0011 (version); licence not stated (item C) |
| node (frontend base) | 24.21.0-slim | MIT (upstream) | ADR-0011 (version); licence not stated (item C) |
| ollama/ollama (optional `llm` profile) | 0.40.11 | MIT (upstream project licence, not re-read) | ADR-0005 and ADR-0010 cover the model, not the server (item C) |
| granite3.3:2b (model, pulled by the user, not in an image) | | Apache-2.0 | ADR-0010 |
| prom/prometheus (`observability` profile) | v3.15.1 | Apache-2.0 | ADR-0006 |
| grafana/grafana (open-source edition, `observability` profile) | 13.3.0 | AGPL-3.0 (run unmodified, locally) | ADR-0006 |
| relay/api, relay/simulator, relay/frontend, relay/sdk (built locally) | local | MIT (`LICENSE`) | |
| gitleaks 8.30.1, Semgrep 1.182.1 (CI only) | | MIT; CLI LGPL-2.1 with rules under the Semgrep Rules License v1.0 | ADR-0007 (internal-use limit recorded there) |

### 2.5 Findings of the audit

- **A.** `psycopg` 3.3.6 is LGPL-3.0-only (read from the image). ADR-0011 names the library but not its licence. It is free and open source, used unmodified as a dynamically installed library. Recorded, not fixed.
- **B.** Ten `@img/sharp-*` optional packages in the frontend lock file are LGPL-3.0-or-later (some combined with Apache-2.0 and MIT). They come with Next.js; no ADR mentions them. Free and open source; recorded, not fixed. Whether the production build uses them (the Next.js image optimiser) was not checked.
- **C.** The licences of PostgreSQL, the Python and Node base images, the Ollama server, setuptools and the two `@types` packages are not written in any ADR. They are free and open source on the evidence above, with the marked ones taken from the upstream projects and not re-read from the artefact in this audit.
- **D.** The ADR-0006 and ADR-0007 licence tables record the Grafana AGPL, axe-core MPL and Semgrep rules-licence conditions; nothing in this audit contradicts them.

### 2.6 No paid service or hosted AI API

- Search of `api`, `simulator`, `sdk`, `frontend/app` and the frontend config files, `docker-compose.yml`, `observability`, `scripts` and `.github` for hosted-service names (`openai`, `anthropic`, `claude`, `gpt-`, `gemini`, `cohere`, `huggingface`, `stripe`, `adyen`, `sentry`, `posthog`, `datadog`, `newrelic`, `twilio`, `sendgrid`, `mailgun`, `aws`, `azure`, `gcp`, `cloudflare`, `vercel`, case-insensitive): the only matches are the word "draws" containing `aws` (`api/app/routing/adaptive.py`, `registry.py`, `simulator/demo/render.py`, `scripts/incident_timing.py`, `simulator/tests/test_processors.py`). No real hit.
- Every URL host in the code and compose is loopback (`127.0.0.1`, `localhost`), a compose service name (`api`, `simulator`, `ollama`, `prometheus`, `webhook-sink`), `host.docker.internal` (the host Ollama), or a test fixture (`api.test`, `sim.test`, `evil.example`, the last as a rejected target in allowlist tests). No external endpoint.
- The only credential in compose is `RELAY_API_KEY`, a static local key (ADR-0002); `WEBHOOK_SINK_SECRET` is the demo sink's own signing secret.
- Explanations use the local `granite3.3:2b` through Ollama with a deterministic fallback (ADR-0005, ADR-0010); the routing strategies use only the standard library (`random.betavariate`).
- Therefore no paid dependency, paid tier or hosted AI API exists, and the rule "a paid dependency needs an Accepted ADR" has nothing to apply to.

## 3. Clean clone

Verdict: Met. Method: `git clone --branch rel-45-phase-4-exit-review-and-project-r <workspace>/.local/relay-wt/rel45 <workspace>/.local/rel45-clean` (commit `33f1466`, only the tracked `.env.example`, no env file), then with only `RELAY_API_KEY` and `COMPOSE_PROJECT_NAME=rel45clean` in the shell:

- `docker compose up -d --wait --build`: exit 0 in 29 s. This is a warm-cache time: the images had been built earlier in the same Docker engine (Docker Desktop 29.8.1), so layers were reused; it is not a cold-build time.
- `docker compose ps`: `api`, `explainer`, `frontend`, `incidents`, `postgres`, `publisher`, `redis`, `simulator`, `webhooks` and `worker` all `running healthy` (10 services); `migrate` exited 0. `prometheus`, `grafana`, `webhook-sink`, `sdk` and `ollama` are profile-only and were not started.
- `python scripts/smoke_stack.py`: 19 checks `PASS` (ten services healthy, `migrate` completed, `GET /health` 200 and 401 without the key, simulator control health, frontend `/`, `POST /payments` 201, a payment reaches a final state within 60 s), `SMOKE_STACK=PASS`, exit 0. The script covers every long-running service (REL-58); Phase 3's list of six services plus `migrate` is closed.
- `docker compose down -v`: exit 0; the clone folder was deleted; no `rel45clean` container or volume remains (`docker ps -a` and `docker volume ls` show none).

## 4. Hygiene and CI

| Item | Verdict | Evidence |
|---|---|---|
| Project hygiene | Met | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <workspace>/maintenance/test-project-hygiene.ps1 -ProjectRoot <workspace>/.local/relay-wt/rel45` printed `PROJECT_HYGIENE=PASS CHECKED=2` |
| CI green on `main` | Met | `gh run list --branch main --limit 1 --json conclusion,headSha,createdAt,event` returned `success`, a push, head `33f1466593ce55fed191f9511387a37a6d3fb0ea`, created 2026-11-10T03:11:59Z. This commit changed documents only, so (as the Phase 1 review noted) the code jobs for Phase 4 are the green runs of PRs #381, #382, #393 and #394 |
| Check and template validation | see the end of this file | `worktree-check.ps1 -Target api` and `validate-template-system.ps1 -Mode Managed` |
| CI minutes (R12) | Not re-measured | The last measurement is Phase 3's (601 billed for 1 to 6 November, `phase-3-exit-review.md` section 4). Phase 4 ran 60-run experiments by hand, not in CI, so CI use should be low, but nothing in this review measured it; the account total (R16) is unknown without the billing scope |

## 5. Risks and ADRs

### 5.1 Risks reassessed (updated in [`../delivery/risk-register.md`](../delivery/risk-register.md))

| Row | Finding | Result |
|---|---|---|
| R1 | Event schema under-specified: Phase 4 consumed `payment_events` for the sampler's posterior (decayed counts of `payment.routed` and `payment.failed`) with no change to the event schema beyond one additive reason value (`adaptive`, migration 0007; `hybrid` reuses it). All four phases consumed the events without rework | Closed (Resolved) |
| R2 | Unchanged | Accepted |
| R3 | No hosted API through four phases; the audit of section 2 is the evidence | Closed (Resolved) |
| R5 | Not stress-tested beyond the experiment runs (300 payments at 2 per second, each run on a fresh stream); four consumer groups at lag 0 at Phase 3 exit; the peak backlog is still not sampled by a review (REL-57 added gauges) | Stays Open (monitor) |
| R7 | Clean clone: ten services healthy in 29 s (warm), smoke 19 of 19 | Stays Open; note updated |
| R8 | Phase 4 added a third scenario (`processor-a-degraded`); faults are still only on Processor A, and the demo size still never reaches the outage window | Stays Open; note updated |
| R9, R11, R17, R18 | No change in kind | Unchanged |
| R10 | Stronger: both Phase 4 results are on synthetic processors whose profiles were set by the author; the better-share cap and the calm-day behaviour are properties of those scenarios and of the rule. Neither strategy is claimed to beat `rules` | Stays Open; note updated |
| R12, R16 | Not re-measured (section 4) | Stays Open; note updated |
| R14 | Repeatability: the REL-43 same-seed rerun matched for 300 of 300 references, REL-30 was reproduced exactly, and REL-59 gave payments without a reference a deterministic seed | Closed (Resolved) |
| R15 | All images exact-pinned; hygiene `PROJECT_HYGIENE=PASS CHECKED=2` | Stays Mitigated; note updated |
| R19 | Fixed by REL-58 (`0f8c482`): `verify` compares bytes and never raises on a malformed signature, delivery log paging added (process log, session 36: 1003 passed; live non-ASCII signature 401, pages 50, 50, 20 = 120 unique deliveries) | Closed (Resolved) |
| R20 (new) | The adaptive strategies do not meet the pre-registered win rule; a reader could mistake the partial-degradation strength for a general win, or the unchanged default for an untested one | Open (new 2026-11-09); mitigated by the README leading with the verdict and the default staying `rules` |

### 5.2 ADR final statuses

All 17 ADRs are `Accepted` in their files and in the log (`docs/decisions/README.md`); none is superseded or rejected. Headers of ADR-0007, ADR-0008 and ADR-0012 carry an explanatory suffix after "Accepted".

| ADR | Final status | Phase 4 note |
|---|---|---|
| 0001 to 0015 | Accepted | Unchanged since the Phase 3 review. Phase 4 evidence only: ADR-0001/0011/0012 (free and open-source stack, exact pins) are confirmed by the section 2 audit |
| 0016 adaptive routing objective, harness and algorithm | Accepted (final) | The decisions stand and were applied as written; its "Implementation and result" records the REL-44 result (not a win). The harness, objective and win rule are the evidence base of the verdict |
| 0017 second iteration: gated hybrid | Accepted (final) | Decisions applied as written; its "Implementation and result" records the REL-60 result (not a win) and that decision 2's gate reasoning was flawed. The ADR is kept as written; the flaw is recorded, not edited out |

## 6. Open questions and known limits

1. **REL-44 normal-day latency (open).** `adaptive` ratio 1.829, mean p95 about 36 s against about 20 s. Ruled out: decision time (measured on a test database with 1500 payments of events: `decide_adaptive` 3.4 ms and `compute_health` 2.3 ms per call, so about 1 ms extra, not seconds). Consistent with, not proven: queueing at the single worker behind Processor B's slower profile (p50 250 ms against 120 ms; p95 800 ms against 400 ms). The data do not settle it: the runs with 85% and 92% on B had p50 of 24.5 s and 20.1 s and the run with 52% had 13.1 s, but `rules` with no traffic on B had a p50 of 19.4 s in seed 12 and 2.0 s in seed 11, so the run-to-run queueing noise is as large as the effect. The per-payment queue wait was not recorded, so latency cannot be split between the processor's own time and queueing (`rel44/results.md`, "What the outcomes show, and what they do not"). The REL-60 `normal-day` seed 21 slowdown (47.7 s against 17.4 s) is the same pattern and is likewise unmeasured. Cheapest next check: record the per-payment time between `payment.received` and the first `payment.routed` in the outcome files.
2. **Why `hybrid` lost 2 of 5 outage pairs (seeds 21 and 24).** Early noise-driven sampling does not explain them cleanly (seed 22 had 26 early adaptive routes and was still +0.33 pp); no cause is claimed (`rel60/results.md`).
3. **Win-rule design.** The strictly-better rule penalises a deliberate tie (section 1.6). Not changed; a new rule needs a new ADR and new seeds.
4. **One host, one worker.** All 90 experiment runs were on one Windows 11 host with a single worker process; the absolute latencies (80 to 200 s in the degraded scenario) are queueing at that worker behind the 5 s timeout, so only ratios are compared.
5. **Wall-clock effort.** One 15-pair experiment takes about 2.2 hours of run time (7600 s for REL-44, 7793 s for the REL-60 deciding set), so each further iteration costs about that on this host, in parts under the tool's two-hour limit (lesson L-077).
6. **Licence items A to C of section 2.5** are documentation gaps, not violations; the owner can ask for a one-line ADR amendment each.
7. **CI minutes** were not re-measured at this exit (section 4).
8. Findings of earlier reviews that stay accepted by owner decision: the demo scenario never fails a payment at `--count 20` or 60 (Phase 3 follow-up 4), deactivated subscriptions stay listed, the eighth failed webhook attempt has no live evidence.

## 7. Follow-ups found (none fixed here)

Each has a proposed disposition: **A** fix now, **B** future work, **C** accept and keep documented.

1. Record the queue wait per payment so the latency questions can be settled (section 6, item 1): **B**.
2. Amend ADR-0011 and ADR-0007 with the licence items A to C (psycopg LGPL-3.0, the `@img/sharp-*` LGPL packages, base images, Ollama server, setuptools, `@types`): done in this task: the owner asked for the table complete, so ADR-0011 and ADR-0007 carry an amendment dated 2026-11-09.
3. A new gate and a tie-aware rule as a new iteration (ADR, protocol, seeds): **B**, owner's future work.
4. Re-measure CI minutes before the release task: **C**, or a one-off `gh` run in REL-46.

## Owner review

Owner review (2026-11-09): approved. Phase 4 closes with its exit criterion recorded as not met after two pre-registered attempts, and the project is complete apart from the owner's portfolio release (REL-46). The README leads with the verdict, then the partial-degradation strength, then future work. The licence gaps found by the audit are recorded in an ADR-0011 amendment (and a pointer in ADR-0007).
