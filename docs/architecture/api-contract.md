# Relay - API contract (Phase 1)

## Status

Design for Phase 1, written in REL-53 and amended by [ADR-0012](../decisions/0012-phase-1-review-decisions.md) (payment `reference`, regeneration through POST, frontend route access). The OpenAPI document that FastAPI generates must match this file: REL-52 checks the error shape, REL-17 the create endpoint and REL-18 the reads, each against this file, and a change to either side needs the other changed in the same pull request. Reconciled with the running api and its generated `/openapi.json` at the Phase 1 exit review (REL-32, 2026-11-02): paths, methods, parameters, bodies, status codes, error shape and field lists agree; the few places where the generated document says less than this file are listed under "Differences from the generated OpenAPI". Rules behind the endpoints are in [payment-lifecycle.md](payment-lifecycle.md); storage is in [data-model.md](data-model.md).

## Conventions

- Base URL: `http://127.0.0.1:8000` (api container, [containers.md](containers.md)). No version prefix in Phase 1; a `/v1` prefix arrives with the SDK in a later phase, with a decision record.
- JSON in and out, UTF-8. Field names are `snake_case`.
- Money is `amount_minor` (integer, minor units) plus `currency`; never a float ([ADR-0004](../decisions/0004-payment-fundamentals.md)).
- Timestamps are ISO 8601 in UTC with a `Z` suffix, for example `2026-10-01T14:03:22.418Z`.
- Ids are UUIDs (version 4) in canonical lowercase form.
- `X-Correlation-ID`: optional on requests (1 to 64 characters of letters, digits, `-` and `_`); generated when absent or invalid (an invalid value is replaced, never rejected); always returned, and carried into the payment's events and the worker's logs (REL-52).

## Authentication

Every endpoint, reads and `/health` included, requires `X-API-Key: <RELAY_API_KEY>` ([ADR-0009](../decisions/0009-phase-1-owner-decisions.md)). A missing or wrong key returns 401 with the error shape below. The browser never holds the key: the frontend's server routes add it ([containers.md](containers.md)). Keys are compared in constant time. There is no CORS configuration because no browser calls the api directly.

## Metrics access rule

The public API serves no `/metrics` route and exposes no metrics, so the key check in the section above covers every endpoint. Prometheus metrics are served on separate ports inside the compose network only (api, worker and publisher on 9100, not published on the host), which needs no key; see [containers.md](containers.md), "Observability profile and metrics access rule" (REL-33).

## Error shape

Every 4xx and 5xx response uses one body (REL-52):

```json
{
  "error": {
    "code": "validation_failed",
    "message": "currency must be one of USD, EUR, GBP, JPY",
    "details": [{"field": "currency", "issue": "not_supported"}],
    "correlation_id": "c0a8012e-5f3b-4b2e-9a51-7a4f2c9d1e10"
  }
}
```

`details` is present only for 422. Codes:

| HTTP | `code` | When |
|---|---|---|
| 400 | `idempotency_key_missing` | `POST /payments` without `Idempotency-Key` |
| 400 | `malformed_request` | Body is not valid JSON, a header has an invalid format, or a cursor is malformed (an invalid `X-Correlation-ID` is replaced, not rejected) |
| 401 | `unauthorized` | Missing or wrong `X-API-Key` |
| 404 | `not_found` | Unknown payment or incident id, or an unknown path |
| 409 | `idempotency_key_reused` | Same key with a different request body |
| 409 | `idempotency_request_in_progress` | Same key while the first request is still being processed; sent with `Retry-After: 1` |
| 409 | `payment_not_final` | Explanation requested for a payment that is not final |
| 409 | `incident_already_open` | `POST /incidents` for a processor that already has an open incident |
| 409 | `invalid_incident_transition` | An incident transition other than detected to triaged or triaged to resolved |
| 422 | `validation_failed` | A field is missing, has the wrong type, or is out of range |
| 500 | `internal_error` | Unexpected failure; no internals are revealed |
| 503 | `dependency_unavailable` | PostgreSQL unreachable (any endpoint) or the stream server (Valkey, compose service `redis`) unreachable (`/health`) |

## Resources

### Payment

| Field | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `amount_minor` | integer | 1 to 1,000,000,000,000 |
| `currency` | string | `USD`, `EUR`, `GBP` or `JPY` |
| `description` | string or null | Up to 200 characters |
| `reference` | string or null | The merchant's order reference, 1 to 64 characters of letters, digits, `-`, `_` and `.`; not unique; the simulator seeds its draws on it ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)) |
| `status` | string | `received`, `routed`, `authorized`, `captured`, `declined`, `failed` |
| `attempt_no` | integer | 0 before routing, then 1 or 2 |
| `is_final` | boolean | A `failed` payment with `is_final=false` is retrying |
| `display_status` | string | `Received`, `Processing`, `Retrying`, `Captured`, `Declined`, `Failed`; derived for clients |
| `processor` | string or null | `A` or `B` for the current attempt; null before routing |
| `created_at` | timestamp | |
| `status_changed_at` | timestamp | |
| `final_at` | timestamp or null | Set when `is_final` becomes true |

`display_status` is `Processing` for `routed` and `authorized`, and `Retrying` for a non-final `failed`.

### Event (timeline entry)

| Field | Type | Notes |
|---|---|---|
| `seq` | integer | 1, 2, 3 ... per payment; the timeline order |
| `type` | string | One of the event types in [data-model.md](data-model.md) |
| `attempt_no` | integer | |
| `from_status`, `to_status` | string or null | `to_status` is set for every state change; `from_status` too, except on `payment.received`; both are null for other events |
| `processor` | string or null | |
| `reason` | string or null | One of the decided values per event type in [data-model.md](data-model.md) "Reason values", for example `failover`, `timeout`, `outage`, `insufficient_funds`, `stale_attempt` or `after_timeout` |
| `data` | object | Type-specific detail, for example `{"latency_ms": 812}` |
| `occurred_at` | timestamp | |

### Explanation

| Field | Type | Notes |
|---|---|---|
| `payment_id` | uuid | |
| `source` | string | `model` or `rules` |
| `model` | string or null | For example `granite3.3:2b`; null for `rules` |
| `text` | string | Plain-language cause and next step |
| `cited_event_seqs` | array of integer | Every fact in `text` cites one of these timeline entries |
| `trigger` | string | `final_failure`, `on_request` or `regenerate` |
| `generated_at` | timestamp | |
| `fallback_reason` | string or null | Why the model was not used, for example `model_timeout` or `cause_mismatch` (the model named a different cause than the rules, ADR-0013) |

## Endpoints

### `GET /health`

Liveness and readiness for compose and the smoke test; both send `X-API-Key` (the compose health check reads it from the container environment, `scripts/smoke_stack.py` from `.env`). Returns 200 with `{"status": "ok", "database": "ok", "redis": "ok"}`, or 503 with the error shape naming the failing dependency.

### `POST /payments`

Creates a payment in `received` and publishes `payment.received`.

Headers: `X-API-Key`, `Idempotency-Key` (1 to 255 printable ASCII characters), `Content-Type: application/json`.

Request body:

```json
{"amount_minor": 1999, "currency": "USD", "description": "Order 4471", "reference": "normal-day-42-000017"}
```

| Field | Rule |
|---|---|
| `amount_minor` | Required integer, 1 to 1,000,000,000,000 |
| `currency` | Required, one of `USD`, `EUR`, `GBP`, `JPY` |
| `description` | Optional string, up to 200 characters; never sent to the model ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)) |
| `reference` | Optional string, 1 to 64 characters of letters, digits, `-`, `_` and `.`; part of the request hash like every field |

Unknown fields return 422.

Responses:

| Status | Body | When |
|---|---|---|
| 201 | Payment | Created; header `Location: /payments/{id}` |
| 201 | Same Payment as the first response | Same key and same body (a replay); header `Idempotent-Replayed: true`. The body is the stored first response, not the payment's current state |
| 400, 401, 409, 422 | Error | See the error codes |

Order of checks: the API key (401), the `Idempotency-Key` header (400) and body validation (422) all run before the key is claimed, so a rejected request never holds a key. Then the key is claimed: a different body hash returns 409 `idempotency_key_reused` first, whatever the key's state, unless the key is past its 24 hours (then it starts a new payment); the same hash returns the stored response when completed, or 409 `idempotency_request_in_progress` while in progress.

Idempotency ([payment-lifecycle.md](payment-lifecycle.md), [ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md)): bodies are compared by the SHA-256 of their canonical JSON (keys sorted, no insignificant whitespace). A key is held `in_progress` with a lease of `IDEMPOTENCY_LEASE_SECONDS`; when that lease expires without completing, a request with the same body may take the key over (a different body still gets 409 `idempotency_key_reused`). Keys expire after 24 hours, after which the same key starts a new payment.

### `GET /payments`

Lists payments, newest first.

| Query | Rule |
|---|---|
| `status` | Optional; repeatable (`?status=failed&status=declined`) |
| `processor` | Optional; `A` or `B` |
| `is_final` | Optional; `true` or `false` |
| `limit` | Optional; 1 to 100, default 20 |
| `cursor` | Optional; the opaque `next_cursor` from the previous page |

Response 200:

```json
{"items": [{"id": "...", "amount_minor": 1999, "currency": "USD", "status": "captured", "display_status": "Captured", "attempt_no": 1, "is_final": true, "processor": "A", "created_at": "...", "status_changed_at": "...", "final_at": "...", "description": null, "reference": null}], "next_cursor": null}
```

Pagination is keyset on `(created_at, id)`, both descending: the cursor encodes the last item's pair, so pages stay stable while new payments arrive. `next_cursor` is null on the last page. A malformed cursor returns 400 `malformed_request`.

### `GET /payments/{id}`

Returns the Payment plus `"events": [Event, ...]` in `seq` order, with every event, including processor calls, late results and re-drives. 404 for an unknown id; 404 also for an id that is not a UUID.

### `GET /payments/{id}/explanation`

Returns the latest stored Explanation for a final payment. It only reads, except that a final payment without an explanation gets one generated and stored.

| Status | When |
|---|---|
| 200 | Explanation returned. A final payment without one yet (for example a capture after retry) gets one generated and stored with `trigger=on_request` |
| 404 | Unknown payment |
| 409 `payment_not_final` | The payment is still processing or retrying |

A final failure gets its explanation automatically, outside the payment path, from the `explainer` container ([ADR-0009](../decisions/0009-phase-1-owner-decisions.md), [ADR-0012](../decisions/0012-phase-1-review-decisions.md)); time to explanation runs from the final event to the first stored explanation. Generation on request waits up to `EXPLAIN_TIMEOUT_SECONDS` for the model and then falls back to the rule-based explainer, so this endpoint always answers.

### `POST /payments/{id}/explanation/regenerate`

Generates a new explanation now, stores it with `trigger=regenerate` and returns it (201, Explanation). No body. 404 for an unknown payment, 409 `payment_not_final` for a payment that is not final. Regeneration is a POST so that prefetching, crawlers or retried reads never call the model ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)).

### `GET /processors/health`

```json
{
  "strategy": "rules",
  "window_seconds": 60,
  "error_threshold": 0.5,
  "processors": [
    {"name": "A", "attempts": 41, "errors": 30, "error_rate": 0.73, "state": "avoided"},
    {"name": "B", "attempts": 12, "errors": 0, "error_rate": 0.0, "state": "preferred"}
  ],
  "computed_at": "..."
}
```

An attempt is a `payment.routed` event in the window; an error is a `payment.failed` event in the window (reason `timeout`, `outage` or `capture_failed`, including timeouts written by the sweeper). Declines are the processor working normally and are never errors (REL-22). Attempts and errors are each counted by their own event time, so a failure on a payment routed just before the window counts as an error without its attempt; with a 60-second window this skew is small and accepted. Computed from these events in PostgreSQL over the window ([ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md)), so the worker and this endpoint agree. `state` is `preferred`, `avoided` (error rate above the threshold with at least `HEALTH_MIN_ATTEMPTS` attempts) or `unknown` (too few attempts). Under `strategy=static` both report their rates, but routing always uses A. Under `rules`, routing prefers A and uses B only when A is `avoided` and B is not; when both are `avoided` or `unknown` it stays on A ([ADR-0011](../decisions/0011-phase-1-build-decisions.md)).

### Incident

| Field | Type | Meaning |
|---|---|---|
| `id` | string (UUID) | |
| `processor` | `A`, `B` or null | Null for a manual incident that names no processor |
| `source` | string | `rule` (opened by the detector) or `manual` |
| `status` | string | `detected`, `triaged` or `resolved` |
| `title` | string | 1 to 200 characters |
| `opened_at` | timestamp | The opening event's time for a rule incident; the request time for a manual one |
| `opened_by_event_id` | integer or null | The event that opened a rule incident |
| `recovered_at` | timestamp or null | When routing saw the processor healthy again (`preferred`, not merely `unknown`; rule incidents only); the incident stays open until an analyst resolves it |
| `triaged_at`, `resolved_at` | timestamp or null | Set by the transitions |
| `created_at` | timestamp | |

An incident for a processor is opened by the `incidents` container when the router starts avoiding it ([ADR-0014](../decisions/0014-phase-2-incident-detection-and-observability-profile.md)), or by an analyst. At most one incident per processor is open (status not `resolved`) at a time. Every incident endpoint requires `X-API-Key`.

### `GET /incidents`

Lists incidents, newest first by `opened_at`.

| Query | Rule |
|---|---|
| `status` | Optional; `detected`, `triaged` or `resolved` |
| `processor` | Optional; `A` or `B` |
| `limit` | Optional; 1 to 100, default 50 |

Response 200: `{"items": [IncidentListItem, ...]}`, where an IncidentListItem is the Incident plus `affected_count` (REL-57): the number of payments linked to the incident, the length of the detail's `affected_payments`, 0 for an incident without a processor. It is computed in the list query itself (one statement however many incidents), so a list page needs one request per refresh and no per-incident detail request. `POST /incidents` and the transitions still return the plain Incident. An invalid filter is 422 `validation_failed`. There is no cursor yet.

### `GET /incidents/{id}`

Returns the Incident plus `affected_count` (REL-57, equal to the number of `affected_payments`) and `affected_payments` (REL-35): one object per payment linked to the incident, in the order they were linked. 404 `not_found` for an unknown id and for an id that is not a UUID.

| Field | Type | Meaning |
|---|---|---|
| `id` | string (UUID) | The payment |
| `status` | string | The payment's current status |
| `amount_minor` | integer | Minor units, with `currency` |
| `currency` | string | |
| `processor` | `A`, `B` or null | The payment's current processor (after a failover it can differ from the incident's) |
| `events` | array | The incident-relevant events of this payment, oldest first: failures on the incident's processor. Each has `id` (the global event id that summaries cite), `type`, `reason`, `processor` and `occurred_at` |

`affected_payments` is returned whole (REL-57 decision: the frontend pages it 20 per page by slicing client-side; a server `limit` and `offset` would add an API surface and a second request per page for a list that is already one query, so it is revisited if an incident passes a few thousand payments). The description is never returned. Payments are linked by the detector when they fail on the incident's processor in the lookback window before it opened, and while it is open and not recovered ([data-model.md](data-model.md#incident_payments)). A manual incident without a processor has an empty list.

### `GET /incidents/{id}/summary`

Returns the latest stored IncidentSummary. An incident without one gets one generated and stored with `trigger: "on_request"`; only the POST below generates again, so prefetching or retried reads never call the model twice. 404 `not_found` for an unknown id.

| Field | Type | Meaning |
|---|---|---|
| `incident_id` | string (UUID) | |
| `source` | string | `model` or `rules` |
| `model` | string or null | The model name when `source` is `model` |
| `text` | string | Two or three sentences for an analyst |
| `cited_event_ids` | array of integers | Event ids, all among the incident's linked events |
| `cause` | string | `outage`, `timeouts`, `mixed` (the rules cause), or `none` when nothing is linked |
| `trigger` | string | `on_request` or `regenerate` |
| `generated_at` | timestamp | |
| `fallback_reason` | string or null | Why the rules summary was stored: `citation_check_failed` (a citation outside the linked events, or an unusable answer), `model_timeout`, `model_unreachable`, `model_error`, `cause_mismatch` (the model's cause differs from the rules cause, [ADR-0013](../decisions/0013-rules-text-when-causes-disagree.md)) or `no_linked_events` (no model call) |

The model sees the linked failure events (id, type, time, processor, reason), the counts and the amounts in major units: never a payment description. Generation waits up to `EXPLAIN_TIMEOUT_SECONDS` for the model and then falls back to the rules summary, so this endpoint always answers.

### `POST /incidents/{id}/summary/regenerate`

Generates a new summary now, stores it with `trigger: "regenerate"` and returns it (201, IncidentSummary). No body. 404 `not_found` for an unknown id.

### `POST /incidents`

Opens an incident by hand. Body `{"processor": "A" | "B" | null (optional), "title": "..."}`; `title` is required, 1 to 200 characters after trimming. Response 201, Incident with `source: "manual"`, `status: "detected"`. A processor that already has an open incident gets 409 `incident_already_open` (also when the other one was opened by the detector, and for concurrent requests: the database allows one). Without a processor there is no limit.

### `POST /incidents/{id}/transitions`

Body `{"to": "triaged" | "resolved"}`. Only detected to triaged and triaged to resolved are allowed and return 200 with the updated Incident (`triaged_at` or `resolved_at` set). Any other move (for example detected to resolved, a repeat, or `to: "detected"`) is 409 `invalid_incident_transition` and changes nothing. A `to` outside the three statuses is 422; an unknown id is 404. Resolving frees the processor for a new incident.

### `GET /analytics`

Figures for payments created in `[from, to)` (REL-37). Query: `from` and `to` (ISO 8601; a time without a zone is UTC; default the last 24 hours ending now), `processor` (`A` or `B`; keeps only payments with a `payment.routed` event for it, so a payment retried from A to B shows under both). `from` must be before `to` and the range at most 31 days; anything invalid is 422 `validation_failed`. The key is required.

Event-derived figures come from `payment_events`; amounts, currency and the handling processor are joined from `payments` (events carry no money, and terminal events have no processor). The success rate, end-to-end latency, rescue paths and explanation timings are the `app.reporting` functions ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)), so they equal the guardrail report for the same payments.

**Success rate (one definition, REL-57, [metrics](../product/metrics.md)):** captured payments divided by final payments, where final means captured, declined or failed, so declines count in the denominator. Per processor each final payment counts once under the processor that handled it (the processor of its final attempt), so `captured`, `failed` and `declined` add up to the final payments it handled; a payment still retrying is not final. The Grafana panel "Success rate by processor", `/analytics` and the guardrail report give the same figure for the same payments. When every payment is final, captured over final equals captured over created.

Response 200:

| Field | Type | Meaning |
|---|---|---|
| `window` | object | `from`, `to` (UTC) and `processor` (or null) as applied |
| `volume` | object | `payments` in the range and how many are `final` |
| `latency` | object | `count`, `p50_ms`, `p95_ms`, `p99_ms`: `payment.received` to `payment.final` over final payments (nearest rank) |
| `processors` | object | `A` and `B` (only the filtered one with `processor`), each: `volume` (payments routed to it), `captured`, `failed`, `declined`, `success_rate` (the one success-rate definition, below; null when the processor handled no final payment), `latency` (the same percentiles over final payments it handled, `payments.processor`), `call_latency` (`count` and percentiles of `latency_ms` in its `attempt.*` events) and `failure_reasons` (count per reason of its `payment.failed` and `payment.declined` events) |
| `revenue_recovered_by_rescue_path` | object | `retry`, `failover`, `redrive`, each `count` and `amount_minor_by_currency` (minor units, never mixed) |
| `time_to_explanation` | object | `{"available": false, "note": ...}` before any explanation exists; otherwise per `source` `count`, `p50_ms`, `p95_ms`, plus `all`, `fallback_rate`, `fallback_reasons` (count per stored `fallback_reason`), `backlog_max` and `backlog_end` |

### `GET /analytics/baseline`

The REL-30 headline figures, read from the results file named by the setting `BASELINE_RESULTS_PATH` (default `/app/baseline/results.json`; compose mounts `docs/evaluation/outage-demo/results.json` there read-only). Response 200: `available: true`, `label` ("synthetic data, static-routing baseline"), `synthetic`, `scenario`, `seed`, `run` (the headline run, 1), `run_date` (`generated_at` of the file, or null when the file records no date; a file timestamp would only be the checkout time), `baseline_description`, `success_rate_static_pct`, `success_rate_relay_pct`, `uplift_pp`, `revenue_recovered` (minor units per currency) and `revenue_by_rescue_path`. When the file is absent, unreadable or malformed the answer is still 200 `{"available": false}` (a malformed file also logs a warning); it never fails. The key is required.

## Webhooks (REL-39)

Decided in [ADR-0015](../decisions/0015-webhook-delivery-signing-and-target-allowlist.md). A subscriber registers a URL and the payment lifecycle event types it wants; Relay posts a signed JSON message to the URL each time a payment reaches one of them. The `webhooks` container does the sending, outside the payment path ([containers.md](containers.md)). Every endpoint below requires `X-API-Key`; the subscriber's own endpoint is never given the key.

### Subscription

| Field | Type | Meaning |
|---|---|---|
| `id` | string (UUID) | |
| `url` | string | `http` or `https`, host in `WEBHOOK_ALLOWED_HOSTS` (below) |
| `event_types` | array of strings | One or more of `payment.received`, `payment.authorized`, `payment.captured`, `payment.declined`, `payment.failed`, `payment.final` |
| `active` | boolean | False after `DELETE` |
| `created_at` | timestamp | |
| `secret` | string | The signing secret, generated by Relay. Only in the `POST` response; never returned again by any endpoint and never logged. Rotation is a later task: a lost secret means a new subscription |

`payment.failed` can fire before a retry; `payment.final` fires once per payment with the outcome in `data.status`. Internal events (`attempt.*`, `payment.routed`, `payment.retry_scheduled`, `payment.explained` and others) are never delivered and are not valid subscription types.

### `POST /webhooks/subscriptions`

Body `{"url": "...", "event_types": ["payment.final", ...]}`. Response 201, a Subscription including `secret`. Repeated event types are stored once; a field named `secret` in the request is ignored (the subscriber cannot choose it). Errors: 422 `webhook_target_not_allowed` when the URL is not `http` or `https` to an allowed host or carries credentials (nothing is stored and the URL is never fetched); 422 `validation_failed` for an empty or unknown event type or a missing field.

### `GET /webhooks/subscriptions`

Response 200 `{"items": [Subscription, ...]}`, newest first, without `secret`.

### `GET /webhooks/subscriptions/{id}`

Response 200, a Subscription without `secret`; an unknown or malformed id is 404 `not_found`.

### `DELETE /webhooks/subscriptions/{id}`

Deactivates the subscription: response 200 with the Subscription (`active: false`); repeating it is harmless; an unknown id is 404. No new deliveries are stored for it, and one still waiting is marked `failed` with `last_error` `subscription_inactive`, without a request.

### Delivery (the delivery log)

One entry per delivery: one event sent to one subscription. The entry is updated by every attempt, so it shows the number of attempts and the last response; `GET /webhooks/deliveries/{id}` lists every attempt.

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | |
| `subscription_id` | string (UUID) | |
| `event_id` | integer | The event's id, the same as `Relay-Event-Id` and the message `id` |
| `event_type` | string | |
| `attempt` | integer | Attempts made so far, 0 to 8 |
| `status` | string | `pending` (waiting for its first attempt or a retry), `delivered` or `failed` |
| `next_attempt_at` | timestamp or null | When the next attempt is due; only while `pending` |
| `last_status_code` | integer or null | The HTTP status of the last attempt; null when it had no response |
| `last_error` | string or null | `HTTP <status>` for a non-2xx answer; `ReadTimeout`, `ConnectError` or another error class name for a timeout or connection error; `target_not_allowed`, `subscription_inactive` or `event_missing` when no request was made |
| `created_at`, `updated_at` | timestamp | |

### `GET /webhooks/deliveries`

The delivery log, newest first (by `created_at`, then id). Query: `subscription_id`, `status` (`pending`, `delivered`, `failed`), `limit` (1 to 100, default 20: the page size, with no cap on the log itself), `cursor` (the opaque `next_cursor` of the previous page). Keyset pagination on `(created_at, id)` descending, as in `GET /payments`; the filters apply to every page. Response 200 `{"items": [Delivery, ...], "next_cursor": "<cursor>" | null}`; `next_cursor` is null on the last page. A bad `status`, `subscription_id` or `limit` is 422 `validation_failed`; a malformed `cursor` is 400 `malformed_request`. Rows that are `delivered` or `failed` are deleted after `WEBHOOK_LOG_RETENTION_DAYS` (default 7); `pending` rows are never deleted.

### `GET /webhooks/deliveries/summary`

The webhook delivery success rate (REL-40, owner decision 2026-11-05), computed from the delivery log. Query: `since` and `until` (ISO 8601, both optional; a time without a zone is UTC), `subscription_id` (optional). The window is `[since, until)`: a `delivered` or `failed` delivery falls in it by its `updated_at` (when it finished) and a `pending` one by its `created_at`. `since` must be before `until`; a bad timestamp or id, or an empty range, is 422 `validation_failed`. The key is required.

Response 200:

| Field | Type | Meaning |
|---|---|---|
| `delivered`, `failed`, `pending` | integer | Deliveries in the window by status |
| `success_rate` | number or null | `delivered / (delivered + failed)` rounded to 4 decimals; null when no delivery in the window is final (pending ones are not in the denominator, so zero failures with zero deliveries is null, not 1) |
| `since`, `until`, `subscription_id` | timestamp, timestamp, string or null | The window and filter as applied; null when not given |

The route is registered before `GET /webhooks/deliveries/{id}`, so `summary` is never parsed as an id. Rows deleted by the retention cleanup (`WEBHOOK_LOG_RETENTION_DAYS`) are no longer counted.

### `GET /webhooks/deliveries/{id}`

The delivery with every attempt. Response 200, a Delivery plus `attempts`, in order (attempt 1 first): each has `attempt` (1 to 8), `status_code` (integer, or null when there was no response), `error` (the same values as `last_error`: `HTTP <status>`, an error class name such as `ReadTimeout` or `ConnectError`, or `target_not_allowed`, `subscription_inactive`, `event_missing`; null on success), `duration_ms` (0 when no request was made) and `attempted_at`. A delivery that failed without a request has one attempt carrying the reason. An unknown id is 404 `not_found`; a non-integer id is 422 `validation_failed`. The list above stays a summary without `attempts`. Attempts are deleted with their delivery by the retention cleanup.

### The message Relay sends

`POST <url>` with `Content-Type: application/json` and a compact JSON body:

```
{"id": 1234, "type": "payment.final", "created_at": "2026-11-05T14:03:22.418Z",
 "data": {"payment_id": "<uuid>", "status": "captured", "amount_minor": 1250, "currency": "EUR"}}
```

`id` is the event id, `created_at` the event time and `data.status` the payment's status at that event (for `payment.final` the final status). The body never includes the free-text `description`. Headers:

| Header | Value |
|---|---|
| `Relay-Event-Id` | The event id (the same as the body `id`) |
| `Relay-Signature` | `t=<unix seconds>,v1=<hex HMAC-SHA256>` |

**Signature.** `v1` is the lowercase hex HMAC-SHA256, keyed with the subscription secret, of the text `<t>.<raw body>`: the decimal timestamp, a dot, and the exact bytes received. A subscriber recomputes it over the raw body (before any JSON parsing), compares in constant time, and rejects a timestamp older than its tolerance (for example 5 minutes) to stop replays. The reference implementation is `verify(secret, header, body, tolerance_seconds)` in `api/app/webhooks/signing.py`; the Phase 3 SDK mirrors it. A new `t` and signature are made for every attempt; the body and `Relay-Event-Id` stay the same.

**Duplicates.** The event stream is at-least-once, so a subscriber can receive the same event twice (a retry after a lost answer, or a crash between sending and recording). Relay stores one delivery per subscription and event, so a duplicate stream entry never makes a second delivery, but a subscriber must still drop repeats by `Relay-Event-Id`.

**Success and failure.** Any 2xx answer is success: the delivery becomes `delivered`. Anything else counts as a failed attempt: a non-2xx status (a redirect is never followed and counts as a failure), a timeout (`WEBHOOK_TIMEOUT_SECONDS`, default 5) or a connection error. The attempt is counted, the last response is stored, and the next attempt is scheduled by exponential backoff: after the n-th failed attempt the wait is `min(WEBHOOK_BACKOFF_BASE_SECONDS * WEBHOOK_BACKOFF_FACTOR ^ (n - 1), WEBHOOK_BACKOFF_MAX_SECONDS)`. With the defaults (2 s, factor 2, cap 60 s) the waits after attempts 1 to 7 are 2, 4, 8, 16, 32, 60 and 60 seconds. After the 8th failed attempt the delivery is `failed` and is not tried again (there is no manual replay yet); a subscriber that was down can read the log and fetch the payments through the API. A failing subscriber delays only its own deliveries: the sender posts several deliveries at once and nothing here is on the payment path.

**Target allowlist.** The URL must be `http` or `https` and its host must be one of the comma-separated exact hostnames in `WEBHOOK_ALLOWED_HOSTS` (default `webhook-sink,localhost,127.0.0.1`), so Relay cannot be pointed at its own database, api or simulator (server-side request forgery). It is checked when the subscription is created (422 `webhook_target_not_allowed`) and again at send time: a delivery to a host that is no longer allowed is marked `failed` with `last_error` `target_not_allowed` and no request is made. Real subscribers need their host added to the setting.

**Delivery semantics for operators.** A sender that dies after posting but before recording the answer sends the delivery again after a lease (the request timeout plus 30 s), so a subscriber can see a repeat; the log never loses a delivery. Counts are exported as `relay_webhook_deliveries_total{outcome}` (`delivered`, `retried`, `failed`) and the waiting count as `relay_webhook_pending` ([dashboard-spec-observability.md](dashboard-spec-observability.md)).

## Differences from the generated OpenAPI

Found when comparing this file with `GET /openapi.json` (REL-32). This file is the authority; the generated document is the weaker side in each case below, and none of them is a behaviour bug: each rule below was confirmed against the running api.

**Fixed in REL-40** (the document now matches this file, with no behaviour change; `api/app/openapi_schema.py`, tested in `api/tests/test_openapi_schema.py`): the `ApiKeyAuth` security scheme (`X-API-Key`, header) with a global `security` requirement; `Idempotency-Key` marked required on `POST /payments` in the schema only (the handler still answers a missing header with 400 before body validation); enums for `currency`, payment `status`, `display_status`, response `processor`, health `state`, event `source` and `trigger`, incident `source` and `status`, webhook `event_types` and delivery `status`; and per-operation error responses, so each operation lists only the codes it can return (401 and 500 on every endpoint, 503 on `/health` only). The generated reference is committed in [docs/guides](../guides/README.md).

What remains:

| Topic | This file | Generated OpenAPI | Resolution |
|---|---|---|---|
| Path parameter | `{id}` | `{payment_id}`, `{incident_id}`, `{subscription_id}`, `{delivery_id}` | Cosmetic; the same id. Left as is: renaming the code parameters would change nothing for clients |
| Event `from_status` and `to_status` | Payment statuses | `from_status` and `to_status` are plain nullable strings | Value set is the payment status list in the Payment resource table |
| `GET /health`, `GET /processors/health` | Described above | Short summaries only | Documented here |
| Error body examples | `details` only for 422 | `details` optional on every error response | The schema is shared; the table above says when `details` appears |

Fixed in this file (it said less or something stale): the Status paragraph now records the reconciliation. Everything else, including the field tables of Payment, Event and Explanation, the cursor and filter rules, the explanation status codes and the processor health response, matched the generated schemas field for field.

## Simulator APIs (synthetic environment, not part of Relay)

Processor API, internal port 8100, reachable only on the compose network:

| Endpoint | Request | Response |
|---|---|---|
| `POST /processors/{a,b}/authorize` | Header `Idempotency-Key: <payment_id>:<attempt_no>`; body `{"payment_id", "attempt_no", "amount_minor", "currency"}` plus optional `"reference"` (1 to 64 characters matching `^[A-Za-z0-9._-]{1,64}$`; otherwise 422 `validation_error`) | 200 `{"result": "approved" or "declined", "reason", "latency_ms"}`; 503 during an outage; 504 only after the worker's timeout for an injected timeout; 404, 409 and 422 as listed below |
| `POST /processors/{a,b}/capture` | Same key and body | 200 `{"result": "captured" or "failed", "reason", "latency_ms"}`; 409 `not_authorized` without an approved authorize; otherwise as authorize |

A repeated idempotency key returns the first result unchanged. Outcomes derive from `SIM_SEED`, the payment's `reference` (or its id when it has none) and the attempt number, not from arrival order; with references, runs with one seed repeat per payment ([ADR-0012](../decisions/0012-phase-1-review-decisions.md), REL-54).

Details fixed in REL-19 (`simulator/processors/`):

- Every draw is a SHA-256 hash of the seed, processor, payment id, attempt number and operation, so a run is reproducible whatever the arrival order, and a simulator restart gives the same outcomes for the same profiles. From REL-54 the draw uses the body's `reference` instead of the payment id when one is sent, so separate runs repeat too.
- `Idempotency-Key` must equal `<payment_id>:<attempt_no>` from the body; otherwise 422 `idempotency_key_mismatch`. A key reused with a different body, including a different or missing `reference`, is 409 `idempotency_key_reused`. Authorize and capture keep separate results.
- An injected timeout answers 504 `processor_timeout` only after `PROCESSOR_TIMEOUT_SECONDS` plus one second, so the worker has already timed out; a repeated key times out again.
- An outage answers 503 `processor_outage` for every call, including keys with a stored result, and stores nothing; after the outage the stored result is returned.
- An unknown processor is 404 `unknown_processor`; invalid bodies are 422 `validation_error`. Errors use the error shape above. The processor API has no key: it is reachable only on the compose network.
- Capture requires an approved authorize with the same key on the same processor; otherwise 409 `not_authorized`, which is not stored, so a capture sent after its authorize still succeeds.
- An answered call's `latency_ms` stays below the worker's timeout (capped at `PROCESSOR_TIMEOUT_SECONDS` minus 100 ms); only an injected timeout is slower.
- Results are kept in memory for the life of the simulator process; a restart forgets runtime profile changes, so a reproducibility run must set the same profiles each time.

Control API, `127.0.0.1:8101`, requires `X-API-Key`:

| Endpoint | Purpose |
|---|---|
| `GET /control/processors` | `{"processors": {"a": {"profile": {...}, "outage": false}, "b": {...}}}` |
| `PUT /control/processors/{a,b}/profile` | Body `{"latency_ms_p50", "latency_ms_p95", "decline_rate", "timeout_rate"}` plus optional `capture_failure_rate` (default 0); replaces the whole profile and returns the same shape as the GET |
| `POST /control/processors/{a,b}/outage` | Body `{"enabled": true}` or `{"enabled": false}`; returns the same shape as the GET |
| `GET /health` | Liveness |

Profiles are validated: latencies are positive with p95 at least p50, rates lie between 0 and 1, and neither `decline_rate` plus `timeout_rate` nor `capture_failure_rate` plus `timeout_rate` exceeds 1. Latency is log-normal with the profile's p50 and p95. Defaults (synthetic): A has p50 120 ms, p95 400 ms, decline 0.10, timeout 0.02, capture failure 0.01; B has p50 250 ms, p95 800 ms, decline 0.08, timeout 0.01, capture failure 0.01. Declines carry one of `insufficient_funds`, `do_not_honor` or `card_expired`; a failed capture carries `capture_failed`.

## Frontend server routes

The Next.js server routes mirror the reads (`/api/analytics`, `/api/analytics/baseline`, `/api/payments`, `/api/payments/[id]`, `/api/payments/[id]/explanation`, `/api/processors/health`) against the api, and the demo outage switch (`/api/demo/outage`) against the simulator control API, not the api (REL-28). They add `X-API-Key` on the server and pass the error shape through unchanged.

Access rule ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)): every server route answers only requests whose `Host` is `localhost` or `127.0.0.1` (any port), and returns 403 otherwise, which blocks DNS rebinding. The outage switch accepts only `POST`, and only from the app's own pages (`Sec-Fetch-Site: same-origin`, or an `Origin` equal to the app's origin); any other request gets 403, so another web page cannot drive the demo. Reads are `GET`. `GET /api/demo/state` reads `GET /control/processors` through the same server-side key and returns only `{"processors": {"a": {"outage": bool}, "b": {"outage": bool}}}` (no profiles); the list page's outage control uses it on load and the `POST /api/demo/outage` response (the full snapshot) after each action. A public demo (REL-46) runs read-only: no outage switch, no regeneration and a rate limit, with its own authentication decided in its hosting ADR.
