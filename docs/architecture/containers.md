# Relay - Containers (Phase 1)

## Status

Design for Phase 1, written in REL-53 and reviewed by the owner with it; amended by [ADR-0012](../decisions/0012-phase-1-review-decisions.md) (Valkey, exact image pins, the `explainer` container, restart policies, frontend route access). It refines [system-context.md](system-context.md); payment rules are in [payment-lifecycle.md](payment-lifecycle.md), endpoints in [api-contract.md](api-contract.md) and tables in [data-model.md](data-model.md). Everything in this file is built and was reconciled with `docker-compose.yml` at the Phase 1 exit review (REL-32, 2026-11-02); the differences found are listed in "Differences found in REL-32" at the end. `docker compose up -d --wait` from a clean checkout with only `RELAY_API_KEY` set brought all eight long-running containers to healthy and `migrate` to exit 0.

## Diagram

```
 Host (the owner's PC)                                   Docker Compose network "relay"
 ─────────────────────                                   ──────────────────────────────────────────────────────────────
 Browser ──HTTP──▶ 127.0.0.1:3000 ──▶ [frontend]  Next.js pages + server routes (hold RELAY_API_KEY)
                                          │ HTTP + X-API-Key            └── demo outage switch ──▶ simulator control API (8101)
 Load generator ──HTTP + X-API-Key──▶ 127.0.0.1:8000 ──▶ [api]  FastAPI: payments, explanations, processor health ──▶ Ollama (on-request explanations)
 (simulator/generator/, runs on the host)                                          │  SQL (one transaction per change: state + event)
       │                                                   ▼
       │                                              [postgres]  source of truth: payments, payment_events,
       │                                                   ▲      idempotency_keys, payment_explanations
       │                                                   │ SQL
       │                                   [publisher] ────┤ reads unpublished events, marks published_at
       │                                        │ XADD
       │                                        ▼
       │                                    [redis]  Valkey: stream relay:payment-events (append-only persistence)
       │                                        │ XREADGROUP / XAUTOCLAIM
       │                          ┌─────────────┴──────────────┐
       │                          ▼                            ▼
       │                      [worker]                    [explainer]  explanation consumer only
       │                 processing consumer + sweeper         │ HTTP
       │                          │ HTTP (internal port 8100)  ▼
       │                          ▼                       Ollama on the host
       │                  [incidents]  third consumer group: detects avoided processors, writes incidents to postgres
       │                  [webhooks]   fourth consumer group: stores and sends signed webhook deliveries, retries with backoff
       │                          │ HTTP POST to allowlisted subscriber URLs (demo: [webhook-sink], profile webhooks-demo)
       │                  [webhooks]  fourth consumer group: stores and sends signed webhook deliveries, retries with backoff
       │                          │ HTTP POST (allowlisted subscriber URLs, e.g. the demo sink under profile webhooks-demo)
       └──HTTP + X-API-Key──▶ 127.0.0.1:8101 [simulator]  host.docker.internal:11434
                              (control API)   Processor A, Processor B (processor API, 8100)
                                                          (or --profile llm container)
 [migrate]  one-off: alembic upgrade head; api, worker, explainer and publisher start only after it succeeds
```

## Containers

| Container | Built from | Runs | Talks to | Host port | Health or readiness |
|---|---|---|---|---|---|
| `frontend` | `frontend/` (Next.js, TypeScript) | Pages for the payments list and detail; server routes under `/api/*` that add the API key and call the api, and the demo outage route that calls the simulator control API | api, simulator (control) | `127.0.0.1:3000` | `GET /` returns 200 |
| `api` | `api/` (FastAPI) | Every endpoint in [api-contract.md](api-contract.md), including on-request and regenerated explanations; appends one JSON line per request to the `api-logs` volume ([data-model.md](data-model.md), Retention); mounts `docs/evaluation/outage-demo/results.json` read-only at `/app/baseline/results.json` for `GET /analytics/baseline` (REL-37) | postgres, redis (health only), Ollama | `127.0.0.1:8000` | `GET /health` with `X-API-Key` from the container environment (checks postgres and redis) |
| `publisher` | `api/` image, command `python -m app.publisher` | Moves unpublished `payment_events` rows to the stream in `id` order and sets `published_at` | postgres, redis | none | heartbeat file checked by the compose health check |
| `worker` | `api/` image, command `python -m app.worker` | Processing consumer (routing, authorize, capture, one retry) and sweeper loop (timeouts, re-drives, expired idempotency keys) | redis, postgres, simulator | none | heartbeat file checked by the compose health check |
| `explainer` | `api/` image, command `python -m app.explainer` | Explanation consumer (group `explanations`): explains final failures with the model or the rules, outside the payment path (ADR-0012) | redis, postgres, Ollama | none | heartbeat file checked by the compose health check |
| `incidents` | `api/` image, command `python -m app.incidents` | Incident detector (group `incidents`, REL-34, ADR-0014): reads `payment.routed` events and opens an incident when the router starts avoiding a processor, records `recovered_at` when health returns, never resolves; part of the default stack, never in the worker | redis, postgres | none | heartbeat file (`/tmp/incidents-heartbeat`) checked by the compose health check |
| `webhooks` | `api/` image, command `python -m app.webhooks` | Webhook delivery (group `webhooks`, REL-39, [ADR-0015](../decisions/0015-webhook-delivery-signing-and-target-allowlist.md)): stores one delivery per matching subscription with its bookkeeping, acknowledges after the commit, then a send loop posts each due delivery signed with `Relay-Signature`, retries with exponential backoff (at most 8 attempts) and cleans up old log rows; part of the default stack, never on the payment path, holds no API key | redis, postgres, subscriber URLs on the allowlist | none | heartbeat file (`/tmp/webhooks-heartbeat`) checked by the compose health check |
| `webhook-sink` (profile `webhooks-demo`, optional) | `api/` image, command `uvicorn app.webhooks.sink:app --port 8200` | Demo subscriber (REL-39): records what Relay posts, verifies the signature when it has the secret, can fail the next N requests so retries can be shown; in memory only, no key, no database. See "Webhook demo sink" below | none | `127.0.0.1:8200` (loopback, for inspection) | `GET /health` |
| `migrate` | `api/` image, command `alembic upgrade head` | One-off; exits 0 when the schema is current | postgres | none | exit code (`service_completed_successfully`) |
| `simulator` | `simulator/` (FastAPI) | Processor A and B (internal processor API) and the control API (outages, profiles) | none | `127.0.0.1:8101` (control only) | `GET /health` on 8101 |
| `reporting` (profile `tools`, one-off) | `api/` image, command `python -m app.reporting` | Guardrail metrics report (REL-51): `docker compose run --rm reporting [--since ... --until ... --reference-prefix <scenario>-<seed>- --json-out /reports/report.json]`; reads `api-logs` read-only and writes JSON to `./reports` on the host | postgres | none | none (exits when done; `restart: "no"`) |
| `postgres` | `postgres:16.15` | Databases `relay` and `relay_test` (created by an init script) | - | none | `pg_isready` |
| `redis` | `valkey/valkey:9.1.2` with `--appendonly yes` (Valkey, Redis-compatible, BSD-3-Clause; volume `valkeydata`) | Stream `relay:payment-events` | - | none | `valkey-cli ping` |
| `prometheus` (profile `observability`, optional) | `prom/prometheus:v3.15.1` (Apache-2.0, exact pin, ADR-0006) | Scrapes the api, worker, publisher, incidents and webhooks containers every 5 s; keeps 7 days in volume `prometheus-data`; config from `observability/prometheus/prometheus.yml` (read-only) | api, worker, publisher, incidents, webhooks (metrics ports) | `127.0.0.1:9090` | `GET /-/healthy` |
| `grafana` (profile `observability`, optional) | `grafana/grafana:13.3.0` (open-source edition, AGPL-3.0, exact pin, ADR-0006) | Four provisioned dashboards (throughput, success rate, latency, processor errors; spec in [dashboard-spec-observability.md](dashboard-spec-observability.md)); anonymous viewers, no admin user and no password in any file; data in `grafana-data` | prometheus | `127.0.0.1:3001` (container 3000, which the frontend owns on the host) | `GET /api/health` |
| `ollama` (profile `llm`, optional) | `ollama/ollama:0.40.11` (exact pin, ADR-0012) | Same model as the host install when the host has none; models live in the `ollama-models` volume | - | none (never clashes with a host install) | `ollama list` |

Named volumes: `pgdata` (postgres), `valkeydata` (Valkey), `api-logs` (the api's request log, read-only for `reporting`), `ollama-models` (profile `llm`) and `prometheus-data` and `grafana-data` (profile `observability`); `reporting` also bind-mounts `./reports` (git-ignored). The postgres container runs `scripts/postgres-init/` once to create `relay_test`. Container stdout logs are capped at 3 files of 10 MB per service (REL-52, `x-logging` in the compose file). Images are pinned to exact versions (`postgres:16.15`, `valkey/valkey:9.1.2`, `python:3.12.15-slim`, `node:24.21.0-slim`), and every long-running service has `restart: unless-stopped`; each process exits non-zero on an unrecoverable error so Docker restarts it ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)). Every published port is bound to `127.0.0.1`, so nothing is reachable from the local network, and the frontend's server routes also refuse requests from other web pages (Host and same-origin checks, [api-contract.md](api-contract.md)). The host ports can be changed with `FRONTEND_HOST_PORT`, `API_HOST_PORT`, `SIM_CONTROL_HOST_PORT`, `PROMETHEUS_HOST_PORT` and `GRAFANA_HOST_PORT` ([ADR-0011](../decisions/0011-phase-1-build-decisions.md)). The load generator lives in `simulator/generator/` (standard library only) and runs on the host against `127.0.0.1:8000` and `127.0.0.1:8101`. The host Ollama is the default (`OLLAMA_URL=http://host.docker.internal:11434`, mapped to `host-gateway` on Linux CI; model `granite3.3:2b`, [ADR-0010](../decisions/0010-local-model.md)). With `docker compose --profile llm up -d --wait` the `ollama` container starts as well (default runs never start it); set `OLLAMA_URL=http://ollama:11434` for the api and the explainer and pull the model once with `docker compose --profile llm exec ollama ollama pull granite3.3:2b`. The container publishes no host port, so it cannot clash with a host install.

## Flows

| # | From | To | What flows | Guarantee |
|---|---|---|---|---|
| F1 | Load generator, frontend server routes | api | `POST /payments` and reads, with `X-API-Key` | Idempotent creation ([ADR-0004](../decisions/0004-payment-fundamentals.md), [ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md)) |
| F2 | api, worker | postgres | State change plus its `payment_events` row in one transaction | State and history never diverge ([ADR-0003](../decisions/0003-payment-event-history.md)) |
| F3 | publisher | redis | Each event once per publish pass, in `payment_events.id` order | At-least-once; a crash before `published_at` is set republishes |
| F4 | redis | worker (group `processing`) | Trigger events: `payment.received`, `payment.retry_scheduled`, `payment.redriven` | At-least-once; the worker locks the payment row and checks state and attempt, so duplicates change nothing |
| F5 | worker | simulator processor API | Authorize and capture with key `<payment_id>:<attempt_no>` and the payment's optional `reference`, on which the simulator seeds its draws | A repeated key returns the first result, never a second charge; runs with one seed repeat per reference (ADR-0012) |
| F6 | worker sweeper | postgres, redis | Timeouts to `failed`; re-drive triggers for stalled payments | No payment waits forever, even if a stream entry is lost |
| F7 | redis | explainer (group `explanations`) | `payment.final` events with a failed or declined outcome | Explanation stored outside the payment path, in its own container, so model calls never delay processing ([ADR-0009](../decisions/0009-phase-1-owner-decisions.md), [ADR-0012](../decisions/0012-phase-1-review-decisions.md)) |
| F8 | explainer | Ollama | Prompt built only from the payment's own events; the free-text `description` is never sent | Falls back to the rule-based explainer when slow or absent ([ADR-0005](../decisions/0005-ai-explanation-provider.md)) |
| F9 | Load generator, frontend server routes | simulator control API | Outage on or off, profiles, with `X-API-Key` | Part of the synthetic environment, not of Relay |
| F11 | redis | incidents (group `incidents`) | `payment.routed` events; the detector re-reads the event row (`data.health`, `occurred_at`) from postgres | At-least-once and possibly late: it applies an event only if its id is newer than the last applied per processor, in one transaction with the change, and acknowledges after the commit, so duplicates, late entries and a crash between commit and ack change nothing ([ADR-0014](../decisions/0014-phase-2-incident-detection-and-observability-profile.md)) |
| F10 | api | Ollama | On-request explanations (`GET /payments/{id}/explanation`) and regenerated ones (`POST /payments/{id}/explanation/regenerate`) | Same prompt rules and fallback as F8; the endpoint always answers |

The worker and the explainer read the same stream through two consumer groups, in separate containers, so explanation work never delays payment processing; a REL-25 test proves it with a hanging fake model. Messages left pending by a crashed consumer are reclaimed with `XAUTOCLAIM` after an idle timeout. The stream is trimmed with an approximate `MAXLEN`; recovery always reads PostgreSQL, never old stream entries.

## Start order and shutdown

1. `postgres` and `redis` become healthy.
2. `migrate` runs and exits 0.
3. `api`, `publisher`, `explainer`, `incidents`, `webhooks` and `simulator` start after `migrate` (and healthy `postgres` and `redis`); `worker` also waits for a healthy `simulator`; `frontend` starts after `api` is healthy.

On `SIGTERM` the worker, the explainer, the incident detector and the webhooks consumer stop reading new messages, finish the current one (or leave it pending for reclaim) and exit; the publisher finishes its current batch. Worker, explainer, incidents, webhooks and publisher have `stop_grace_period: 15s`. The explainer touches its heartbeat after every entry, so a backlog of slow model calls cannot make the health check fail. After a crash, `restart: unless-stopped` brings a service back and pending messages are reclaimed. `docker compose up -d --wait` returns only when every long-running container is healthy (REL-48).

## Configuration

Settings come from the shell or the repository's env file (only the example file is committed), through compose interpolation. No service loads the whole file: each receives only the variables listed under "Used by" below (checked by `api/tests/test_compose_stack.py`, ADR-0012), with the default shown here, so a clean clone needs only `RELAY_API_KEY`. `REQUEST_LOG_PATH` (api and reporting, default `/var/log/relay/api-requests.jsonl`) and `BASELINE_RESULTS_PATH` (api, default `/app/baseline/results.json`) are the variables not in the example. Defaults:

| Variable | Default | Used by |
|---|---|---|
| `RELAY_API_KEY` | none (required) | api, explainer (settings), frontend server routes, simulator control API, load generator, health checks and `scripts/smoke_stack.py` |
| `API_URL` | `http://api:8000` | frontend server routes |
| `SIMULATOR_CONTROL_URL` | `http://simulator:8101` | frontend server routes (demo outage switch) |
| `DATABASE_URL` | `postgresql+psycopg://relay:relay@postgres:5432/relay` | api, worker, explainer, incidents, webhooks, publisher, migrate, reporting |
| `TEST_DATABASE_URL` | `.../relay_test` | tests only |
| `TEST_REDIS_URL` | `redis://redis:6379/1` | tests only (flushed between tests) |
| `REDIS_URL` | `redis://redis:6379/0` (Valkey speaks the same protocol) | api, worker, explainer, incidents, webhooks, publisher |
| `SIMULATOR_URL` | `http://simulator:8100` | worker |
| `OLLAMA_URL`, `OLLAMA_MODEL` | `http://host.docker.internal:11434`, `granite3.3:2b` | explainer, api |
| `BASELINE_RESULTS_PATH` | `/app/baseline/results.json` | api (the REL-30 results file, mounted read-only by compose; absent means the baseline is unavailable, REL-37) |
| `ROUTING_STRATEGY` | `rules` (`static` for the baseline; any name in the strategy registry, an unknown one means `rules`; see [routing-experiments](routing-experiments.md)) | worker, api (health report) |
| `PROCESSOR_TIMEOUT_SECONDS` | `5` | worker, sweeper, reporting, simulator (answers stay below it; an injected timeout answers after it) |
| `SWEEP_TIMEOUT_GRACE_SECONDS` | `5` | sweeper, reporting: fails an attempt only after the processor timeout plus this grace ([ADR-0011](../decisions/0011-phase-1-build-decisions.md)) |
| `REDRIVE_AFTER_SECONDS` | `30` | sweeper, reporting |
| `SWEEP_INTERVAL_SECONDS` | `5` | sweeper |
| `KEY_CLEANUP_INTERVAL_SECONDS` | `60` | sweeper (worker) |
| `RECLAIM_IDLE_MS` | `30000` | worker (the explainer uses the same default in code) |
| `STREAM_MAXLEN` | `10000` | publisher |
| `HEALTH_WINDOW_SECONDS`, `HEALTH_MIN_ATTEMPTS`, `HEALTH_ERROR_THRESHOLD` | `60`, `5`, `0.5` | worker, api |
| `IDEMPOTENCY_TTL_HOURS`, `IDEMPOTENCY_LEASE_SECONDS` | `24`, `30` | api |
| `EXPLAIN_TIMEOUT_SECONDS` | `20` | explainer, api |
| `SIM_SEED` | `42` | simulator |
| `FRONTEND_HOST_PORT`, `API_HOST_PORT`, `SIM_CONTROL_HOST_PORT`, `PROMETHEUS_HOST_PORT`, `GRAFANA_HOST_PORT` | `3000`, `8000`, `8101`, `9090`, `3001` | docker compose port bindings (the last two only with profile `observability`) |
| `WEBHOOK_ALLOWED_HOSTS` | `webhook-sink,localhost,127.0.0.1` | api (checked at creation), webhooks (checked at send time): comma-separated exact hostnames |
| `WEBHOOK_BACKOFF_BASE_SECONDS`, `WEBHOOK_BACKOFF_FACTOR`, `WEBHOOK_BACKOFF_MAX_SECONDS` | `2`, `2`, `60` | webhooks: the wait after the n-th failed attempt is `min(base * factor^(n-1), max)` |
| `WEBHOOK_LOG_RETENTION_DAYS`, `WEBHOOK_TIMEOUT_SECONDS` | `7`, `5` | webhooks: age at which delivered and failed log rows are deleted; request timeout |
| `WEBHOOK_SINK_SECRET`, `WEBHOOK_SINK_HOST_PORT` | empty, `8200` | webhook-sink (profile `webhooks-demo`): the secret it verifies with, and its loopback host port |
| `WEBHOOKS_HEARTBEAT_PATH` | `/tmp/webhooks-heartbeat` | webhooks (not passed by compose; the default is what the health check reads) |
| `METRICS_PORT` | `9100` | api, worker, publisher, incidents, webhooks: port of the metrics server inside the compose network; unset means no server (tests, bare runs) |
| `POSTGRES_PASSWORD` | `relay` | postgres (local only) |

## Observability profile and metrics access rule (REL-33)

`docker compose --profile observability up -d --wait` adds `prometheus` and `grafana` ([ADR-0006](../decisions/0006-observability-stack.md), [ADR-0014](../decisions/0014-phase-2-incident-detection-and-observability-profile.md)); the default stack, the clean-clone run and the CI e2e job never start them. Metrics are defined once in `api/app/metrics/` and are never served on the keyed public API. The api serves `/metrics` on its own port 9100 (started in its lifespan from `METRICS_PORT`), and the worker and publisher each start a `prometheus_client` HTTP server on 9100 in their own container. None of these ports is published on the host (no `ports:` mapping), so only containers on the compose network reach them, no key is needed and none is written into the Prometheus config. The api runs one uvicorn process (the image `CMD` sets no `--workers`), so its default registry is complete and the client's multiprocess mode is not used; add it before raising the worker count. The processes expose: payments created, API requests and duration by route template and status, processor calls and duration by processor, operation and outcome, final payments by processor and outcome, and outbox events published with their publish lag, and incidents opened by processor and source (`relay_incidents_opened_total`, zero-initialised for A and B; the `incidents` container starts the same server from `METRICS_PORT` and Prometheus scrapes it as job `relay-incidents`; manual incidents are counted by the api). The `webhooks` container serves `relay_webhook_deliveries_total{outcome}` (`delivered`, `retried`, `failed`, zero-initialised) and the gauge `relay_webhook_pending`, scraped as job `relay-webhooks`; panels read the gauge with `job="relay-webhooks"`, because every process exports it at zero. Labels are low-cardinality; payment ids are never labels. Grafana runs with anonymous Viewer access, the login form disabled and no admin user (`GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION`), so there is no password to commit; dashboards are provisioned read-only files.

## Webhook demo sink (REL-39)

`docker compose --profile webhooks-demo up -d --wait` adds `webhook-sink` (the default `up` never starts it; the `webhooks` container runs without it). `webhook-sink` is in the default allowlist (`WEBHOOK_ALLOWED_HOSTS`), so a subscription to `http://webhook-sink:8200/hook` is accepted; any host not on the list, such as `http://postgres:5432/`, is refused with 422 `webhook_target_not_allowed` and never fetched. The sink listens on `127.0.0.1:8200` of the host for inspection (`WEBHOOK_SINK_HOST_PORT`) and keeps everything in memory; its configuration endpoints are not authenticated, which is why it is bound to loopback and exists only for the demo.

1. Create a subscription with the API key: `POST /webhooks/subscriptions` with `{"url": "http://webhook-sink:8200/hook", "event_types": ["payment.final"]}`; keep the `secret` from the response, it is shown once.
2. Give the sink the secret so it verifies signatures: `POST http://127.0.0.1:8200/config` with `{"secret": "<secret>"}` (or set `WEBHOOK_SINK_SECRET` before starting it).
3. Run payments (for example a short `python -m generator` run); read what arrived with `GET http://127.0.0.1:8200/received`: each item has the `event_id`, the parsed `body`, the answer `status` and `signature_valid`.
4. Show retries: `POST http://127.0.0.1:8200/config` with `{"fail_next": 3}` answers the next three requests with 503; `GET /webhooks/deliveries?subscription_id=<id>` then shows `attempt` rising with `last_status_code` 503 and growing gaps between attempts (2, 4 and 8 s with the defaults), and finally `delivered`. `DELETE http://127.0.0.1:8200/received` clears the record.

## Out of scope for Phase 1

The SDK (Phase 3), more than one merchant, and any cloud deployment. Webhooks, planned out of Phase 1, were built in REL-39 (see the `webhooks` container above).

## Differences found in REL-32

| Difference | Resolution |
|---|---|
| The Status paragraph still said only postgres, redis, migrate, api, simulator and a placeholder frontend were built | Replaced with the reconciliation statement above |
| The `reporting` service (profile `tools`, REL-51) was missing from the container table | Row added |
| Volumes, the `./reports` bind mount, the log-size cap (REL-52) and the postgres init script were not described | Added after the container table |
| Start order said `worker` starts with the others; the compose file makes it wait for a healthy `simulator` | Corrected in "Start order and shutdown" |
| `PROCESSOR_TIMEOUT_SECONDS` and the sweep settings are also passed to `reporting` | Added to the "Used by" column |
| Everything else (ports bound to `127.0.0.1`, exact image pins `postgres:16.15`, `valkey/valkey:9.1.2`, `ollama/ollama:0.40.11`, `python:3.12.15-slim`, `node:24.21.0-slim`, restart policies, grace periods, health checks, variable defaults) | Matched the compose file and Dockerfiles; no change |
