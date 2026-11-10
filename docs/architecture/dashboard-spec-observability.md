# Observability dashboards specification

Template: claude/dashboard@1

Status: Active (REL-33)  
Owner: Brendan  
Last reviewed: 2026-11-02  
Review due: 2026-12-02

## Decision question

These dashboards answer: **Is Relay processing payments correctly right now, and if not, is the fault in the API, the publisher or one processor?**

Expected action when the answer is abnormal: a high API 5xx rate means check the api logs (`docker compose logs api`); growing publish lag means check the publisher and Valkey; one processor with a low success rate or high error rate means the router should already be failing over (`GET /processors/health`), and during the demo the outage controls explain it.

## Audience and use moment

- Primary audience: an operator or the demo viewer watching the system while the load generator runs.
- Used during: the seeded outage demo (`processor-a-outage`) and while debugging a local run, with the dashboard open in a browser tab.
- Expected comprehension time: under 10 seconds to tell whether errors, latency or lag are abnormal.

Grafana serves the dashboards read-only to anonymous viewers on `127.0.0.1:3001`. Status is always readable from the panel title, legend table (last and max values) and unit, never from color alone.

## Data sources and freshness

| Source | Authority | Refresh | Stale after | Failure behavior |
|---|---|---|---|---|
| Prometheus (`http://prometheus:9090`, Grafana data source uid `prometheus`) | Counters and histograms from `api/app/metrics/`, scraped every 5 s from the api, worker, publisher, incidents and webhooks containers (`observability/prometheus/prometheus.yml`) | Dashboards refresh every 5 s; default range 15 minutes | 15 s without a new sample | Grafana shows "No data"; the Prometheus targets page (`/targets`) shows which process is down |

Metrics access rule (decided 2026-11-02): metrics are never served on the keyed public API. The api serves `/metrics` on its own port 9100, and the worker and publisher each serve theirs on 9100, all inside the compose network only (no `ports:` mapping), so no key is needed and none is stored in the scrape config. The api runs a single uvicorn process (the image `CMD` has no `--workers`), so the default registry of that one process is the complete view and the client's multiprocess mode is not needed. Prometheus retention is 7 days (risk register PR-7).

Metric definitions live in `api/app/metrics/__init__.py` and use only low-cardinality labels (route template, status, processor, operation, outcome). Payment ids, references and keys are never labels. Success rate and failure counts stay consistent with the guardrail definitions in `docs/product/metrics.md` and `api/app/reporting/metrics.py`: one success-rate definition (REL-57, `docs/product/metrics.md`): captured payments over final payments, where final means captured, declined or failed, so declines count in the denominator. The Grafana panel, `/analytics` and the guardrail report all use it, and each final payment counts once under the processor that handled it. Series that are new in REL-57 (`relay_payment_processing_seconds`, `relay_payments_not_final_overdue`, `relay_stream_group_lag`, `relay_stream_group_pending`) start at zero in their process so a first burst is visible (lesson L-070).

## At-a-glance summary

| Signal | Meaning | Healthy | Warning | Critical |
|---|---|---|---|---|
| API 5xx rate | Server errors per second | 0 | Above 0 for 1 minute | Above 1 percent of requests |
| Publish lag P95 | Delay between a state change and its stream entry | Under 1 s | 1 s to 5 s | Over 5 s |
| Success rate by processor | Captured over final, 5-minute window | Within 5 points of the other processor | More than 5 points lower | Under 50 percent |
| Payments not final past the sweeper threshold | Payments stuck beyond the timeout threshold | 0 | Above 0 for 1 minute | Above 0 for 5 minutes |
| Stream lag per group | Entries a consumer group has not received | Under 100 | 100 to 1,000 and growing | Over 1,000 |
| Processor error rate | Timeouts and outages over calls | Under 5 percent | 5 to 50 percent | Over 50 percent (the router's default threshold) |

Thresholds are demo-scale choices for a local run; Phase 2 incident rules (REL-34) own the real detection thresholds.

## Primary signals

Four dashboards, each loading at `http://127.0.0.1:3001/d/<uid>`. P50, P95 and P99 are computed with `histogram_quantile` over a 1-minute rate of the histogram buckets. Counters expose `_total` series.

### Relay: throughput and API health (`relay-throughput`)

#### Payments created per second

- Question and reading: Payments accepted by POST /payments (replays excluded). A drop to zero while traffic is expected means the API or the load generator stopped.
- Unit: `reqps` (Grafana unit id)
- PromQL (created): `sum(rate(relay_payments_created_total[1m]))`

#### API requests per second by route

- Question and reading: All API requests by route template. Shows which endpoints carry the load.
- Unit: `reqps` (Grafana unit id)
- PromQL (legend: route): `sum by (route) (rate(relay_http_requests_total[1m]))`

#### API 5xx rate

- Question and reading: Server errors per second and as a share of all requests. Any sustained value above zero needs investigation.
- Unit: `reqps` (Grafana unit id)
- PromQL (5xx per second): `sum(rate(relay_http_requests_total{status=~"5.."}[1m])) or vector(0)`
- PromQL (5xx share): `(sum(rate(relay_http_requests_total{status=~"5.."}[1m])) or vector(0)) / sum(rate(relay_http_requests_total[1m]))`

#### Publish lag P95

- Question and reading: Seconds from event creation to stream publish (95th percentile). Rising lag means the publisher is behind and new events reach consumers late.
- Unit: `s` (Grafana unit id)
- PromQL (P95): `histogram_quantile(0.95, sum by (le) (rate(relay_outbox_publish_lag_seconds_bucket[1m])))`
- PromQL (P50): `histogram_quantile(0.5, sum by (le) (rate(relay_outbox_publish_lag_seconds_bucket[1m])))`

#### Events published per second

- Question and reading: Outbox events copied to the stream. Flat at zero while payments are created means the publisher is stuck.
- Unit: `ops` (Grafana unit id)
- PromQL (published): `sum(rate(relay_outbox_events_published_total[1m]))`

#### Stream lag and pending by consumer group

- Question and reading: Entries on the payment event stream a consumer group has not yet received (lag) and has received but not acknowledged (pending), per group (processing, explanations, incidents, webhooks, and any group the stream lists later), read by the publisher every 5 seconds with `XINFO GROUPS`. Growing lag means that consumer is behind; growing pending means it is failing or stuck on entries.
- Unit: `short` (Grafana unit id)
- PromQL (legend: lag group): `max by (group) (relay_stream_group_lag{job="relay-publisher"})`
- PromQL (legend: pending group): `max by (group) (relay_stream_group_pending{job="relay-publisher"})`

#### Webhook deliveries per second by outcome

- Question and reading: Webhook delivery attempts by outcome (REL-39): delivered, retried (the subscriber failed and a retry is scheduled) and failed (gave up after 8 attempts, or the target is no longer on the allowlist). Sustained retried or failed means a subscriber is down; it never slows payments, because the webhooks container is off the payment path.
- Unit: `ops` (Grafana unit id)
- PromQL (legend: outcome): `sum by (outcome) (rate(relay_webhook_deliveries_total[1m]))`

#### Webhook deliveries waiting to be sent

- Question and reading: Deliveries stored and not yet delivered or failed, retries included, set by the webhooks container every pass. Growing means subscribers are failing or the sender is behind. Only the webhooks container sets it, so the panel filters on its job.
- Unit: `short` (Grafana unit id)
- PromQL (legend: pending): `max(relay_webhook_pending{job="relay-webhooks"})`

### Relay: payment success rate by processor (`relay-success-rate`)

#### Success rate by processor

- Question and reading: Captured payments divided by final payments over 5 minutes, per processor. A processor falling below the other is degraded or in an outage; routing should shift traffic away from it.
- Unit: `percentunit` (Grafana unit id)
- PromQL (legend: processor): `sum by (processor) (increase(relay_payments_final_total{outcome="captured"}[5m])) / sum by (processor) (increase(relay_payments_final_total[5m]))`

#### Final payments by processor and outcome

- Question and reading: Payments reaching a final state in the last 5 minutes: captured, declined or failed.
- Unit: `short` (Grafana unit id)
- PromQL (legend: processor outcome): `sum by (processor, outcome) (increase(relay_payments_final_total[5m]))`

#### Final payments per second

- Question and reading: Rate of payments reaching any final state. Compare with payments created to spot a backlog.
- Unit: `ops` (Grafana unit id)
- PromQL (final): `sum(rate(relay_payments_final_total[1m]))`

#### Failure share by processor

- Question and reading: Failed payments (timeouts, outages, capture failures) divided by final payments over 5 minutes. Declines are excluded because the card issuer, not the processor, caused them.
- Unit: `percentunit` (Grafana unit id)
- PromQL (legend: processor): `sum by (processor) (increase(relay_payments_final_total{outcome="failed"}[5m])) / sum by (processor) (increase(relay_payments_final_total[5m])) or sum by (processor) (increase(relay_payments_final_total[5m])) * 0`

#### Payments not final past the sweeper threshold

- Question and reading: Payments not final whose last state change is older than the sweeper timeout (10 seconds by default), counted after each sweeper pass. The target is 0 (the guardrail in `docs/product/metrics.md`); a value above zero means payments are stuck or waiting for a re-drive.
- Unit: `short` (Grafana unit id)
- PromQL (legend: not final): `max(relay_payments_not_final_overdue{job="relay-worker"})`

### Relay: latency (`relay-latency`)

#### API request latency P50/P95/P99

- Question and reading: Time the API takes to answer, as the 50th, 95th and 99th percentile. A rising P99 with a flat P50 points to a slow dependency affecting some requests.
- Unit: `s` (Grafana unit id)
- PromQL (P50): `histogram_quantile(0.5, sum by (le) (rate(relay_http_request_duration_seconds_bucket[1m])))`
- PromQL (P95): `histogram_quantile(0.95, sum by (le) (rate(relay_http_request_duration_seconds_bucket[1m])))`
- PromQL (P99): `histogram_quantile(0.99, sum by (le) (rate(relay_http_request_duration_seconds_bucket[1m])))`

#### Processor call latency P50/P95/P99 by processor

- Question and reading: Time each processor takes per authorize or capture call (a timeout counts at the time waited). Compare the processors: the slower one is the candidate for failover.
- Unit: `s` (Grafana unit id)
- PromQL (legend: P50 processor): `histogram_quantile(0.5, sum by (le, processor) (rate(relay_processor_call_duration_seconds_bucket[1m])))`
- PromQL (legend: P95 processor): `histogram_quantile(0.95, sum by (le, processor) (rate(relay_processor_call_duration_seconds_bucket[1m])))`
- PromQL (legend: P99 processor): `histogram_quantile(0.99, sum by (le, processor) (rate(relay_processor_call_duration_seconds_bucket[1m])))`

#### API request latency P95 by route

- Question and reading: 95th percentile latency per route template, to find which endpoint is slow.
- Unit: `s` (Grafana unit id)
- PromQL (legend: route): `histogram_quantile(0.95, sum by (le, route) (rate(relay_http_request_duration_seconds_bucket[1m])))`

#### Payment creation-to-final latency P50/P95/P99 by processor

- Question and reading: Seconds from a payment being created to its final state (captured, declined or failed), per processor that handled it, observed where the payment becomes final (the worker and the sweeper). It includes retries and the sweeper timeout, so a rising P99 with a flat P50 means a few payments are retried or stuck. A processor with no final payment in the window returns no series.
- Unit: `s` (Grafana unit id)
- PromQL (legend: P50 processor): `histogram_quantile(0.5, sum by (le, processor) (rate(relay_payment_processing_seconds_bucket[1m])))`
- PromQL (legend: P95 processor): `histogram_quantile(0.95, sum by (le, processor) (rate(relay_payment_processing_seconds_bucket[1m])))`
- PromQL (legend: P99 processor): `histogram_quantile(0.99, sum by (le, processor) (rate(relay_payment_processing_seconds_bucket[1m])))`

### Relay: processor errors (`relay-processor-errors`)

#### Processor error rate

- Question and reading: Timeouts and outages divided by all calls, per processor, over 1 minute. Above the routing threshold (50 percent by default) the router treats a processor as degraded.
- Unit: `percentunit` (Grafana unit id)
- PromQL (legend: processor): `sum by (processor) (rate(relay_processor_calls_total{outcome=~"timeout|outage"}[1m])) / sum by (processor) (rate(relay_processor_calls_total[1m])) or sum by (processor) (rate(relay_processor_calls_total[1m])) * 0`

#### Processor errors per second by kind

- Question and reading: Timeouts (no answer in time) and outages (503 or unreachable) per processor. Timeouts point to slowness, outages to a processor that is down.
- Unit: `ops` (Grafana unit id)
- PromQL (legend: processor outcome): `sum by (processor, outcome) (rate(relay_processor_calls_total{outcome=~"timeout|outage"}[1m]))`

#### Processor calls per second by outcome

- Question and reading: Every call by processor, operation outcome (approved, declined, captured, failed, timeout, outage). Shows where traffic goes during failover.
- Unit: `ops` (Grafana unit id)
- PromQL (legend: processor outcome): `sum by (processor, outcome) (rate(relay_processor_calls_total[1m]))`

## Exceptions and thresholds

- Panels with a 0 to 1 scale (success rate, error rate, failure share) are fixed at 0 to 1 so a small change is not magnified.
- A processor with no calls in the window returns no series (the ratio has no denominator), which reads as "no data", not as healthy. A processor with calls but no errors shows 0 (the `or ... * 0` term keeps its series), and the API 5xx panel shows 0 rather than "No data" (`or vector(0)`).
- A group the stream does not list yet shows its zero start value, not "No data". The lag gauge keeps its last value when the server cannot work out a lag (entries trimmed away).
- Declines are not processor errors: they are excluded from the error rate and counted as final outcomes only.
- The sweeper's timeouts (a payment failed because no answer arrived) count as final failures for the processor, not as processor calls.

## Interactions and drill-downs

- Global filters: the time range picker and refresh interval; no template variables in Phase 2.
- Preserved context in links: the dashboard dropdown links the four dashboards.
- Keyboard and focus behavior: Grafana's own controls; refreshes do not move focus.
- Runbook or action destination: the api and worker logs, `GET /processors/health`, and the outage controls in the Relay UI.

## Empty, loading, error, and stale states

| State | Visible message | Available action |
|---|---|---|
| Loading | Grafana's panel spinner | None |
| Empty | "No data" until the load generator runs | Run `docker compose run --rm simulator python -m generator ...` |
| Partial | Panels of the stopped process show "No data" | Check the Prometheus targets page |
| Error | Panel error icon with the query error | Check `docker compose ps` for prometheus |
| Stale | The last point is older than 15 s | Check that the services are running |

## Ownership and lifecycle

- Definition location: this file, `docs/architecture/dashboard-spec-observability.md`, with the dashboards as JSON in `observability/grafana/dashboards/` (provisioned read-only) and the parse test in `api/tests/test_observability_files.py`.
- Change review: pull request review; a changed panel updates this spec in the same pull request, and the test fails when a panel title is missing here or a query uses an undefined metric.
- Usage review: at each phase exit review (REL-38).
- Retirement trigger: replaced by a different observability stack (ADR-0006) or a hosted deployment with its own monitoring.

Single-owner gauges: every process imports `app.metrics`, so every process exports the stream lag, pending and not-final-overdue gauges at zero, but only the publisher (lag, pending), the worker (overdue) and the webhooks container (`relay_webhook_pending`) set them. Their panels therefore filter on the owning job, so a dead owner shows no data instead of a reassuring 0.
