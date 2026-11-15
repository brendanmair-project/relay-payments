# relay

Template: claude/showcase@1

[![CI](https://github.com/brendanmair-project/relay-payments/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/brendanmair-project/relay-payments/actions/workflows/ci.yml)

Payment operations platform that helps a two-processor merchant recover revenue lost to failed payments and explain each failure in minutes

**Demo video:** a 90-second business cut and a 5-minute walkthrough with captions, attached to the [latest release](https://github.com/brendanmair-project/relay-payments/releases/latest) of the public copy (synthetic data only).

> **Phase 4 verdict: the exit criterion is not met.** Adaptive routing did not beat the rule-based router under the win rule fixed before the runs (ADR-0016), in two pre-registered attempts: `adaptive` (mean uplift +1.82 pp, better on 10 of 15 pairs, calm-day latency 1.829 times `rules`) and `hybrid` (+0.58 pp, 8 of 15, 1.473). Its consistent strength is partial degradation, the case the rule router cannot see (+2.73 pp and +2.00 pp, with p95 latency at 0.340 and 0.605 of `rules`). All data is synthetic. Every condition and number is in [Results and learnings](#results-and-learnings).

## Overview

Relay gives an online merchant one timeline for every card payment, explains each failure in plain language (AI-assisted, with a rule-based fallback), and automatically routes around a degraded payment processor. It is a portfolio project: a working system built around one concrete business problem, using synthetic data only.

## Problem

An online merchant routes card payments through two payment processors. Failed and stuck payments cost revenue (lost sales, false declines, processor outages), and the payment-operations team spends hours per incident rebuilding what happened across processor dashboards and logs. Relay targets that gap: faster explanation of each failure, and less revenue lost while a processor is degraded.

All data in this project is synthetic. Relay never handles real payments or card data.

## What I built

Phases 1 to 3 and 5 are built, measured and approved by the owner; Phase 4 (adaptive routing) is built and measured, and its exit criterion is not met (see Results and learnings).

- A payments API (FastAPI) with idempotency keys, integer minor-unit money in four currencies and a strict payment state machine.
- PostgreSQL as the source of truth: every state change appends an event to `payment_events` in the same transaction (the outbox), so each payment has one timeline.
- An outbox publisher that moves those events to a Valkey stream, and a worker that consumes them: rule-based routing between Processor A and B, one retry on the other processor, failover when a processor's recent error rate crosses a threshold, and a sweeper that times out or re-drives stuck payments.
- Two simulated processors with different latency, decline and outage profiles, with seeded outcomes keyed on a payment reference, and a control API to start and stop an outage.
- An explainer container that writes a plain-language explanation of every declined or failed payment: a local open-source model (`granite3.3:2b` through Ollama) checked against the payment's own timeline, with the rules text as the fallback (ADR-0013).
- A deterministic load generator (public API only) and a one-command outage demo that compares Relay with static routing payment by payment.
- A Next.js UI: payments list with a demo outage control, and a payment detail page with attempts, timeline, labelled explanation and processor health. The API key stays in the server routes.
- CI with backend, simulator and frontend checks, a secret scan, Semgrep and Playwright end-to-end tests against the compose stack.

Phase 2 added operations depth: an incident detector in its own container that opens an incident when routing avoids a processor, links the affected payments and writes a grounded summary (ADR-0014); incident pages with triage and resolve; Prometheus and Grafana dashboards under the `observability` profile (ADR-0006); and analytics by processor beside the REL-30 baseline.

Phase 3 added integrations (ADR-0015): webhooks for payment lifecycle events, sent from their own `webhooks` container with an HMAC signature, retried with exponential backoff up to 8 attempts, limited to an allowlist of target hosts, with a delivery log and a success-rate summary (the `webhooks-demo` profile adds a sink that checks signatures and fails on demand); developer guides generated from the OpenAPI spec (quickstart, authentication and idempotency, webhooks, API reference; [all guides](docs/guides/README.md)); and a small Python SDK, `relay-sdk`, with examples and signature verification ([SDK guide](docs/guides/sdk.md)). The exit evidence is in `docs/evaluation/phase-3-exit-review.md`. Adaptive routing (Phase 4) is in `docs/product/roadmap.md`.

Phase 4 added two opt-in routing strategies and the harness that measures them: `adaptive` (Thompson sampling over recent processor outcomes, ADR-0016) and `hybrid` (`rules` decides, and the sampler takes over only while a processor looks degraded but not yet failing, ADR-0017), selected with `ROUTING_STRATEGY`; `rules` stays the default. A real-stack experiment harness runs each strategy against `rules` on seeded scenarios under a protocol written before any comparison (`docs/evaluation/routing-experiments/protocol.md`). The measured result is in Results and learnings: neither strategy wins. Exit evidence: `docs/evaluation/phase-4-exit-review.md`.

Phase 5 made the value visible (ADR-0018): the console now leads with the problem and a Money saved headline (revenue recovered per currency, payments rescued, and investigation time saved, estimated against the 2-hour manual baseline), then the AI section, which shows for each failure what the local model saw, its answer, the time it took and the rules cross-check. A one-click outage story mode runs the whole demo from the console, with step captions driven by the run's state. Exit evidence: `docs/evaluation/phase-5-exit-review.md`.

## Architecture

```mermaid
flowchart LR
    Browser[Browser] -->|HTTP| Frontend["frontend<br/>Next.js pages and server routes<br/>(hold RELAY_API_KEY)"]
    Frontend -->|"HTTP + X-API-Key"| Api["api<br/>FastAPI"]
    Frontend -->|"outage switch"| SimControl
    Gen["load generator<br/>(simulator image)"] -->|"HTTP + X-API-Key"| Api
    Gen -->|"outage on/off"| SimControl
    Api -->|"SQL: state + event"| Postgres[("postgres<br/>source of truth<br/>payment_events outbox")]
    Api -.->|"health check"| Valkey
    Api -->|"on-request explanations"| Ollama
    Publisher[publisher] -->|"reads unpublished events"| Postgres
    Publisher -->|XADD| Valkey[("valkey<br/>stream")]
    Valkey -->|"group processing"| Worker["worker<br/>routing, retry, sweeper"]
    Worker -->|"SQL: state + event"| Postgres
    Worker -->|"authorize, capture"| Sim["simulator<br/>Processor A and B API"]
    Valkey -->|"group explanations"| Explainer[explainer]
    Explainer -->|SQL| Postgres
    Explainer -->|prompt| Ollama["Ollama<br/>host install, or optional<br/>llm profile container"]
    SimControl["simulator<br/>control API"] --- Sim
```

Every box is a service in `docker-compose.yml` except the browser, the load generator (it runs from the simulator image with `docker compose run`) and the host Ollama (the `ollama` container is the optional `llm` profile); `migrate` runs once at start. Container details, flows and guarantees: `docs/architecture/containers.md`.

## Tech stack

Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Valkey (Redis-compatible), Next.js, TypeScript, Docker Compose, pytest, Playwright, GitHub Actions. Local model via Ollama (optional). Prometheus and Grafana for metrics and dashboards (optional `observability` profile). Free and open source only, with every container image pinned to an exact version. Rationale: `docs/decisions/0001-stack.md` and `docs/decisions/0012-phase-1-review-decisions.md`.

## Demo

Payments list with the Processor A outage control (synthetic payments from the seeded `processor-a-outage` scenario):

![Payments list showing recent captured payments and a Start Processor A outage button](docs/images/payments-list.png)

Payment detail: this payment failed on Processor A (timeout), was retried on Processor B and declined (expired card). The explanation is labelled with its source (here the model) and sits next to the raw timeline so an analyst can check it:

![Payment detail with attempts, a model explanation labelled with the model name, processor health and the event timeline](docs/images/payment-detail.png)

One-command demo (needs the stack prerequisites, `RELAY_API_KEY` in the shell and the host Ollama running):

```bash
python scripts/outage_demo.py --seed 7 --runs 3
```

For each run it resets the system, then runs the same 300 seeded payments twice: first with static routing (Processor A only, no failover, no retry), then with Relay routing, with Processor A down for payments 100 to 199. It compares the two runs payment by payment and writes `docs/evaluation/outage-demo/results.md` and `results.json`. The stack is left running; stop it with `docker compose down -v`.

## Walkthrough

A recorded run of the one-click outage story on the local stack with the Phase 5 console (synthetic payments only; the host Ollama answered with `granite3.3:2b`; screenshots taken with Playwright, 1280 px wide unless noted; no key appears because keys live in the frontend's server routes).

1. The console's first screen after the story run: the problem, the Money saved headline (revenue recovered per currency, payments rescued, and investigation time saved, estimated against the 2-hour manual baseline) and the before-and-after success rates (58% against 89%, the committed outage demo), with the start of the AI section below. All figures are synthetic.

   ![Console first screen with the problem statement, the Money saved headline and the before-and-after success rates](docs/images/walkthrough/01-console-first-screen.png)

2. Story mode mid-run, after pressing "Run the outage demo": the caption names the step ("Relay routing to Processor B", payment 62 of 90) and the headline numbers are already rising.

   ![Console during the story run with the step caption Relay routing to Processor B and the Money saved headline](docs/images/walkthrough/02-story-mode-mid-run.png)

3. One payment's timeline: while Processor A was avoided, this payment was routed to Processor B (reason failover), B approved it, but the capture timed out. The explanation sits above the raw events, with "How the AI explained this" (what the model saw, its answer, time taken, and the cross-check with the rules).

   ![Payment detail showing a failover to Processor B, a capture timeout, the explanation and the timeline](docs/images/walkthrough/03-payment-timeline-failover.png)

4. Processor health during the outage: Processor A is avoided (25 of 49 attempts failed, 51%), Processor B is preferred, so new payments go to B.

   ![Processor health panel showing Processor A avoided and Processor B preferred](docs/images/walkthrough/04-processor-health-a-avoided.png)

5. The AI section's "One failure, explained": a declined payment (expired card), the facts the model saw, its answer, the time taken (521 ms) and the cross-check, which agreed with the rules on the cause.

   ![One failure explained, with what the model saw, its answer, the time taken and the rules cross-check](docs/images/walkthrough/05-ai-explanation-cross-check.png)

6. The console at phone width (390 px).

   ![Console at phone width](docs/images/walkthrough/06-console-phone.png)

These shots were taken with a one-off Playwright script during a story run, so the committed capture scripts produce similar but not identical images. Rerun a capture with the stack up and `RELAY_API_KEY` set in the shell (it is not part of the CI end-to-end run): `npx --prefix frontend playwright test --config frontend/tests/walkthrough/playwright.config.ts`, or the fixture-based console shots with `npx playwright test --config tests/screenshots/playwright.config.ts` from `frontend/` after `npm run build`. The figures differ slightly on every run.

## How to run

New to the API? Start with the [quickstart](docs/guides/quickstart.md): from `docker compose up` to a first payment, then webhooks, authentication and the generated [API reference](docs/guides/api-reference.md) ([all guides](docs/guides/README.md)).

You need Docker Desktop (or Docker Engine with Compose v2) and Python 3.12 on the host. A clean clone needs no env file: only `RELAY_API_KEY`, set in the shell to any plain value.

```bash
export RELAY_API_KEY=choose-a-local-key   # PowerShell: $env:RELAY_API_KEY = "choose-a-local-key"
docker compose up -d --wait               # postgres, valkey, migrate, api, publisher, worker, explainer, simulator, frontend
python scripts/smoke_stack.py             # every service healthy, one payment reaches a final state

# 60 synthetic payments through the public API
docker compose run --rm simulator python -m generator --scenario processor-a-outage --seed 7 --count 60 --rate 5 --api-url http://api:8000 --control-url http://simulator:8101

# open http://127.0.0.1:3000 (UI); the API is at http://127.0.0.1:8000 (every endpoint needs the X-API-Key header)

python scripts/outage_demo.py --seed 7 --runs 3     # the measured demo (three runs; each waits out a 120 s health window, so allow time)

docker compose run --rm -e TEST_DATABASE_URL=postgresql+psycopg://relay:relay@postgres:5432/relay_test -e TEST_REDIS_URL=redis://redis:6379/1 api pytest   # backend tests
docker compose run --rm --no-deps simulator pytest   # simulator tests
npm ci --prefix frontend && npm --prefix frontend test   # frontend unit tests on the host
npx --prefix frontend playwright install chromium
OLLAMA_URL=http://127.0.0.1:9 docker compose up -d --wait   # no model, so explanations are the rules text the e2e tests expect
npm --prefix frontend run e2e                      # end-to-end tests against the running stack

docker compose down -v                    # stop and delete all data
```

Routing defaults to `rules`; `ROUTING_STRATEGY=adaptive` or `hybrid` (in the shell before `docker compose up`) selects an experimental strategy, and `python scripts/routing_experiment.py` runs the pre-registered comparison (about 2 hours per 15-pair experiment; protocol and commands in `docs/evaluation/routing-experiments/protocol.md`).

Explanations use the host Ollama (`granite3.3:2b`) at `host.docker.internal:11434` by default; with no model reachable the rules text is used. To run the model in a container instead: `docker compose --profile llm up -d --wait`, set `OLLAMA_URL=http://ollama:11434`, then `docker compose --profile llm exec ollama ollama pull granite3.3:2b`. Ports can be changed with `FRONTEND_HOST_PORT`, `API_HOST_PORT` and `SIM_CONTROL_HOST_PORT`. Metrics and dashboards (Prometheus and Grafana, not part of the default stack): `docker compose --profile observability up -d --wait`, then open Grafana at http://127.0.0.1:3001 (Prometheus at http://127.0.0.1:9090); see `docs/architecture/containers.md`.

## Results and learnings

### Phase 4: adaptive routing did not win (read this first)

**Verdict: the Phase 4 exit criterion (adaptive routing beats rule-based routing by a stated, reproducible measure) is not met, after two pre-registered attempts.** Synthetic data only (simulated processors, generated payments, no real card data); this is a result on one simulator, not on real traffic.

The win rule was fixed before any comparison (ADR-0016, `docs/evaluation/routing-experiments/protocol.md`). Across 3 scenarios by 5 seeds (15 pairs), against `rules`, with the same payment references in each pair, a strategy wins only if all three hold:

1. the mean paired success-rate uplift is at least 1.0 percentage point;
2. it is better (strictly above zero) on at least 80% of the pairs, 12 of 15;
3. p95 creation-to-final latency is at most 1.10 times that of `rules` in every scenario.

| Condition | Required | Iteration 1: `adaptive` (REL-44, seeds 11 to 15) | Iteration 2: `hybrid` (REL-60, fresh deciding seeds 21 to 25) |
|---|---|---|---|
| Mean paired uplift | at least 1.0 pp | +1.82 pp: holds | +0.58 pp: fails |
| Pairs better | at least 80% | 10 of 15 (67%): fails | 8 of 15 (53%): fails |
| Worst p95 latency ratio | at most 1.10 | 1.829 in `normal-day`: fails | 1.473 in `normal-day` (also 1.118 in `processor-a-outage`): fails |
| Result | | not a win | not a win |

Sources: `docs/evaluation/routing-experiments/rel44/results.md` and `rel60/results.md` (summary: `docs/evaluation/adaptive-routing-results.md`). Both were recomputed from the saved per-run outcome files at the exit review with the same pair counts. The `hybrid` deciding pairs were 8 better, 5 tied and 2 worse. The protocol, the sampler parameters (REL-44) and the second protocol (REL-60, commit `62ae8c8`) were written before the runs, and nothing was tuned after a result was seen.

Where each strategy helps and where it costs (mean paired success-rate difference, pairs better, p95 latency ratio against `rules`; share of initial routes during the fault sent to the faulty processor, `rules` then the strategy):

| Scenario | `adaptive` (seeds 11 to 15) | `hybrid` (deciding seeds 21 to 25) | Exploration cost of the faulty processor |
|---|---|---|---|
| `normal-day` (no fault) | +3.60 pp, 5 of 5, ratio 1.829 (fails) | +0.20 pp, 1 of 5, ratio 1.473 (fails) | none |
| `processor-a-outage` (full outage) | -0.87 pp, 1 of 5, ratio 0.808 | -0.47 pp, 3 of 5, ratio 1.118 (fails) | adaptive 89.2% / 7.2%; hybrid 89.4% / 14.4% |
| `processor-a-degraded` (partial degradation) | +2.73 pp, 4 of 5, ratio 0.340 | +2.00 pp, 4 of 5, ratio 0.605 | adaptive 39.8% / 6.8%; hybrid 55.6% / 28.2% |

What it shows:

- **The consistent strength is partial degradation.** Where Processor A's timeout rate is 0.35, below the 0.5 error rate at which the rule router fails over, both strategies gained 2 to 3 percentage points and cut p95 latency by roughly two thirds (`adaptive`) or 40% (`hybrid`). `hybrid` was never worse than `rules` there.
- **The cost is in the other two scenarios.** In the full outage `rules` already recovers most payments with its retry, and sampling the down processor costs a little (-0.87 pp and -0.47 pp). On a calm day `adaptive` gained +3.60 pp by sending 52% to 92% of payments to Processor B, whose simulated decline and timeout rates are lower, but its p95 latency was 1.829 times that of `rules`; `hybrid`'s calm-day latency failure came from one seed (21), where one random error opened its gate and it routed 174 of 200 payments with the sampler (p95 47.7 s against 17.4 s).
- **Two diagnosed causes.** (1) The `hybrid` gate reasoning in ADR-0017 was flawed: the gate opens at 5 attempts, where one random error is a rate of 0.2, above the 0.15 gate, so a calm day can sample on noise. (2) Exact ties count as "not better", and a gated hybrid ties `rules` exactly on a calm day (4 of the 5 `normal-day` deciding pairs), which caps the better-share at 11 of 15 (73%) against the 80% required, whatever the other pairs do.
- **Open question: the `adaptive` calm-day latency.** Decision time is ruled out (about 1 ms more per payment). Queueing at the single worker behind the slower Processor B is consistent with the data but was not measured, because the per-payment queue wait was not recorded, and the run-to-run queueing noise is as large as the effect.

Future work (owner decision 2026-11-09; not started): a gate that needs about 20 attempts in its window before it opens, instead of 5, would stop one noisy error from opening it; it would need a new ADR, a new protocol and new seeds. Calm-day ties would still cap the better-share near 73% under the ADR-0016 rule, so a rule that does not penalise a deliberate tie is part of the same decision. Details and the audit: `docs/evaluation/phase-4-exit-review.md`.

### The outage demo and explanations (Phases 1 and 2)

**Read this first for this demo.** All data is synthetic (simulated processors, generated payments, no real card data). The comparison baseline is static routing: every payment goes to Processor A, with no failover and no retry. It is not an industry benchmark, so the uplift shows the benefit of Relay's rules over that baseline on synthetic data only (risk R10, ADR-0009). The 2-hour figure for manual reconstruction of one failure is an assumption, not a measurement (ADR-0009).

Scenario `processor-a-outage`, seed 7, 300 payments, Processor A down for payments 100 to 199, three runs (source: `docs/evaluation/outage-demo/results.json`):

| Measure | Static routing | Relay |
|---|---|---|
| Success rate | 58% | 89% (+31.0 percentage points) |
| Payments compared | 300 | 93 rescued (all from failed), 0 worse, 207 unchanged |

Revenue recovered (Relay minus static over the same payments, minor units, never added across currencies), split by the path that captured the payment:

| Currency | Total | By the retry (89 payments) | By failover (4 payments) |
|---|---|---|---|
| EUR | 3032328 | 2832363 | 199965 |
| GBP | 1618218 | 1446165 | 172053 |
| JPY | 902033 | 902033 | 0 |
| USD | 6810094 | 6713460 | 96634 |

No payment was rescued by a sweeper re-drive in this scenario. The totals can differ from the path split, which counts only payments whose capturing attempt was routed as `retry` or `failover` (definitions in `results.md`).

Time to explanation, from a payment's final failure to its stored explanation (Relay run, model warmed first), per source:

| Source | Payments | Median (P50) | P95 |
|---|---|---|---|
| Model | 30 | 1033.5 ms | 1945.1 ms |
| Rules fallback | 3 | 984.6 ms | 1729.9 ms |
| All | 33 | 1033.5 ms | 1945.1 ms |

The fallback rate was 0.1 (3 of 33), all for `cause_mismatch` (ADR-0013); there were no model failures. Against the assumed 2 hours (7200 s) of manual reconstruction the median is 6966.3 times faster, which inherits the assumption.

Reproducibility: the three runs gave identical success rates, identical revenue per currency and identical routing for every payment (spread 0; tolerance 1 percentage point and 1%). Recovery lag, the time until the router stopped avoiding Processor A after the outage ended, was about 106 s (105.9, 100.8, 105.9 s). The demo runs with a 120 s health window (the default is 60 s), so that lag mostly reflects the setting, not how fast Relay reacts.

Explanation quality (`docs/evaluation/results.md`, 10 fixed synthetic timelines, `granite3.3:2b`): citations valid 10/10, model cause matches the rules cause 7/10, no wrong amounts. When the causes disagree the rules text is stored and shown (ADR-0013, risk R18). Detail for the demo: `docs/evaluation/outage-demo/results.md`.

What the build taught me:

- A seeded simulation repeats only when every time-based mechanism is pinned by the scenario. Three timing fixes made the three runs identical: draining payments before the outage switch, waiting one health window after it, and keeping the health state from aging out mid-outage.
- Run the real model before trusting fake-model tests. The first quality run exposed my own prompt bugs (string citations, a raw minor-unit amount read as dollars): citations were 6/10, then 10/10 after the fixes.
- The model names the first failure, not the final outcome, on retry and failover timelines. Checking its cause against the rules and falling back (ADR-0013) is cheaper and safer than trusting it.
- Build test fixtures from a real API response. Component fixtures that did not match the live API hid a bug until a browser check on the running stack.
- Keep model calls off the payment path: a separate explainer container means a slow or missing model never delays processing.
- Fix the win rule before the runs, and check it against the design as well as the data. Pre-registration let me report two failed attempts as failures; the second one failed partly because its gate was never tested on its own 5-attempt window and the rule counts ties as not better, both checkable on paper beforehand.
- Record the diagnostic you will need before the experiment: the per-payment queue wait would have settled the latency question that is still open.

## Status

Phases 1 to 5 complete. Phase 5 (showcase polish) meets all four exit criteria (`docs/evaluation/phase-5-exit-review.md`); Phase 4 closed with its exit criterion recorded as not met after two pre-registered attempts (`docs/evaluation/phase-4-exit-review.md`, owner decision 2026-11-09). Each phase's exit review is in `docs/evaluation/`. 58 of 58 planned tasks are done. The public copy is https://github.com/brendanmair-project/relay-payments.

## Repository map

- `api/`: FastAPI service (`app/`), Alembic migrations, tests; also the image for migrate, worker, publisher and explainer.
- `simulator/`: Processors A and B, the control API, the load generator (`generator/`) and the demo comparison code (`demo/`).
- `frontend/`: Next.js app (payments list, payment detail, server routes) with Vitest and Playwright tests.
- `sdk/python/`: the `relay-sdk` Python client, examples and tests.
- `observability/`: Prometheus and Grafana configuration (optional profile).
- `scripts/`: host-side scripts (standard library only): `smoke_stack.py`, `outage_demo.py`.
- `docs/product/`: vision, strategy, personas, metrics, roadmap and backlog pointer.
- `docs/architecture/`: system context, constraints, payment lifecycle, containers, API contract, data model, dashboard spec.
- `docs/decisions/`: architecture decision records.
- `docs/evaluation/`: explanation quality results, the outage demo results, the adaptive routing results and experiments, and the phase exit reviews.
- `docs/guides/`: developer guides and the generated API reference.
- `docs/delivery/`: delivery plan, tasks, risk register, process log; `docs/images/`: screenshots.
- `docker-compose.yml`: the local stack.

Licensed under MIT (`LICENSE`).
