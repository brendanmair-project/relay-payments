# Relay - Data model (Phase 1)

## Status

Design for Phase 1, written in REL-53 and amended by [ADR-0012](../decisions/0012-phase-1-review-decisions.md) (`payments.reference`, decided reason values, late results); REL-15 implements it as the first Alembic migration, and REL-25 adds `payment_explanations`. PostgreSQL 16 is the source of truth ([ADR-0003](../decisions/0003-payment-event-history.md)); Valkey (Redis-compatible, ADR-0012) holds only the event stream. Rules come from [payment-lifecycle.md](payment-lifecycle.md) and [ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md); the API view is in [api-contract.md](api-contract.md). Reconciled with `api/app/db/models.py`, both migrations and the live schema (`\d` in the running stack) at the Phase 1 exit review (REL-32, 2026-11-02): columns, types, `CHECK` constraints, indexes, the append-only trigger, the 13 event types and the reason values all agree; the differences found are listed under "Differences found in REL-32" at the end.

## Conventions

- Every timestamp is `timestamptz`, written in UTC.
- Money is `amount_minor BIGINT` plus `currency`; no float or numeric money column exists.
- Value sets are enforced with `CHECK` constraints, so a bad value fails in the database as well as in code.
- Primary keys: UUID for payments (created by the api); `BIGINT GENERATED ALWAYS AS IDENTITY` for append-only tables.

## Tables

### `payments`

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `uuid` | no | Primary key |
| `amount_minor` | `bigint` | no | `CHECK (amount_minor BETWEEN 1 AND 1000000000000)` |
| `currency` | `char(3)` | no | `CHECK (currency IN ('USD','EUR','GBP','JPY'))` |
| `description` | `varchar(200)` | yes | Never sent to the model |
| `reference` | `varchar(64)` | yes | `CHECK (reference ~ '^[A-Za-z0-9._-]{1,64}$')`; the merchant's order reference, not unique; the simulator seeds its draws on it (ADR-0012) |
| `status` | `text` | no | `CHECK (status IN ('received','routed','authorized','captured','declined','failed'))` |
| `processor` | `char(1)` | yes | `CHECK (processor IN ('A','B'))`; the current attempt's processor |
| `attempt_no` | `smallint` | no | Default 0; `CHECK (attempt_no BETWEEN 0 AND 2)` |
| `is_final` | `boolean` | no | Default false |
| `correlation_id` | `varchar(64)` | no | From the creating request |
| `created_at` | `timestamptz` | no | Default `now()` |
| `status_changed_at` | `timestamptz` | no | Set on every state change; the sweeper reads it |
| `last_driven_at` | `timestamptz` | yes | Set when the sweeper re-drives the payment; not a state change |
| `final_at` | `timestamptz` | yes | Set when `is_final` becomes true |

Row-level checks:

- `CHECK ((attempt_no = 0) = (status = 'received'))`: routing always starts attempt 1.
- `CHECK (NOT is_final OR status IN ('captured','declined','failed'))`.
- `CHECK ((final_at IS NULL) = (NOT is_final))`.
- `CHECK ((processor IS NULL) = (attempt_no = 0))`.

Indexes:

| Index | Serves |
|---|---|
| `(status, processor, created_at)` | List filters (REL-18) and reporting (REL-51) |
| `(status, status_changed_at)` | The sweeper's stalled and timed-out scans (REL-50) |
| `(created_at DESC, id DESC)` | Keyset pagination of `GET /payments` |

Updates happen only through the state-transition function (REL-14, REL-16): it locks the row (`SELECT ... FOR UPDATE`), checks the expected `status` and `attempt_no`, applies one allowed transition from the lifecycle table, and inserts the matching event in the same transaction. A mismatch writes nothing. The only other update is the sweeper setting `last_driven_at` together with its `payment.redriven` event.

The sweeper re-drives a payment in `received` or retrying `failed` only when both `status_changed_at` and `last_driven_at` (if set) are older than `REDRIVE_AFTER_SECONDS`, so one stalled payment gets at most one re-drive per threshold, not one per sweep (REL-50 idempotent sweep).

### `payment_events`

The append-only history and the transactional outbox ([ADR-0003](../decisions/0003-payment-event-history.md)).

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `bigint` identity | no | Primary key; global insert order, which the publisher follows |
| `payment_id` | `uuid` | no | References `payments(id)` |
| `seq` | `integer` | no | 1, 2, 3 ... per payment. Every writer of any event, state change or not (worker results, late results, sweeper, explainer), first locks the payment row with `SELECT ... FOR UPDATE` and assigns `seq` inside that lock, so writers never collide on `UNIQUE (payment_id, seq)` |
| `attempt_no` | `smallint` | no | `CHECK (attempt_no BETWEEN 0 AND 2)` |
| `type` | `text` | no | One of the event types below (`CHECK`) |
| `from_status`, `to_status` | `text` | yes | `to_status` set for every state change; `from_status` set for every state change except `payment.received`; both null for other events: `CHECK (to_status IS NOT NULL OR from_status IS NULL)` |
| `processor` | `char(1)` | yes | `CHECK (processor IN ('A','B'))`; required on `payment.routed`, `payment.failed` and `attempt.*` events: `CHECK (type NOT IN ('payment.routed','payment.failed','attempt.authorize_result','attempt.capture_result','attempt.late_result') OR processor IS NOT NULL)`, because processor health counts by it |
| `reason` | `text` | yes | One of the decided values in "Reason values" below: `CHECK (reason IS NULL OR reason IN ('initial','failover','retry','static','adaptive','insufficient_funds','do_not_honor','card_expired','timeout','outage','capture_failed','stale_attempt','after_timeout'))`; which value fits which event type is enforced by the shared enum in code (REL-14) |
| `data` | `jsonb` | no | Default `'{}'` |
| `correlation_id` | `varchar(64)` | no | |
| `occurred_at` | `timestamptz` | no | Default `now()` |
| `published_at` | `timestamptz` | yes | Null until the publisher has added the event to the stream |

Constraints and indexes:

- `UNIQUE (payment_id, seq)`: the timeline order, and the `(payment_id, seq)` index REL-15 requires.
- Partial index `(id) WHERE published_at IS NULL`: the publisher's scan stays small.
- `(type, processor, occurred_at)`: the rolling processor error rate for routing and `GET /processors/health` ([ADR-0008](../decisions/0008-payment-attempts-and-processing-reliability.md) decision 7).
- Append-only: a trigger rejects `DELETE`, and rejects any `UPDATE` except setting `published_at` from null to a time. Application code has no update or delete path.

Event types:

| Type | State change | Written by | Triggers |
|---|---|---|---|
| `payment.received` | none to `received` | api | worker (`processing`) |
| `payment.routed` | to `routed` (attempt 1, or 2 on retry); `reason` is `initial`, `failover`, `retry`, `static` or `adaptive` | worker | - |
| `attempt.authorize_result` | none; `data` has `result`, `latency_ms` | worker | - |
| `payment.authorized` | `routed` to `authorized` | worker | - |
| `attempt.capture_result` | none; `data` has `result`, `latency_ms` | worker | - |
| `payment.captured` | `authorized` to `captured` (final) | worker | - |
| `payment.declined` | `routed` to `declined` (final) | worker | - |
| `payment.failed` | to `failed`; `reason` is `timeout`, `outage` or `capture_failed`; final or retrying per the lifecycle | worker, sweeper | - |
| `payment.retry_scheduled` | none; the other processor is chosen next; written in the same transaction as a non-final `payment.failed`, by whichever writer made it | worker, sweeper | worker (`processing`) |
| `payment.final` | none; marks `is_final` with `data.outcome` | worker, sweeper | explainer (`explanations`) when the outcome is `declined` or `failed` |
| `attempt.late_result` | none; a processor result whose attempt or expected state no longer matches: `reason=stale_attempt` when the attempt is no longer current, `reason=after_timeout` when the sweeper already failed the current attempt (a late approval is an orphaned authorization); no result is ever dropped (ADR-0012) | worker | - |
| `payment.redriven` | none; the sweeper re-publishes a trigger for a stalled payment | sweeper | worker (`processing`) |
| `payment.explained` | none; `data` has the explanation id, source and trigger; one event for every stored explanation | explainer (`final_failure`), api (`on_request`, `regenerate`) | - |

`data` content seen in a live run of 300 payments (REL-32): `attempt.authorize_result` and `attempt.capture_result` carry `result` and `latency_ms`; `payment.final` carries `outcome`; `payment.explained` carries `explanation_id`, `source` and `trigger`; `payment.routed` carries `health` (the per-processor `state`, `errors` and `attempts` the router saw when it chose, for example `{"A": {"state": "preferred", "errors": 2, "attempts": 82}, "B": {...}}`); every other type has an empty object. Only `payment.received` has no amount or currency: those live in `payments` (immutable), so a consumer that needs money joins `payments`. The `processor` column is set only on `payment.routed`, `payment.failed` and the three `attempt.*` types; `payment.authorized`, `payment.captured`, `payment.declined` and `payment.final` have it null, so the processor of a terminal outcome is the one of the latest `payment.routed` event (equal to `payments.processor`).

A state change and its `payment.final` event (when it makes the payment final) are written in the same transaction, so `payments.final_at` equals the final event's `occurred_at`.

Reason values (decided list, [ADR-0012](../decisions/0012-phase-1-review-decisions.md)). Processor health counts errors by these exact strings, so no other value is allowed:

| Event type | Allowed `reason` |
|---|---|
| `payment.routed` | `initial`, `failover`, `retry`, `static`, `adaptive` |
| `payment.declined` | `insufficient_funds`, `do_not_honor`, `card_expired` |
| `payment.failed` | `timeout`, `outage`, `capture_failed` |
| `attempt.authorize_result` | null when approved; a decline reason when declined; `timeout` or `outage` when the call failed |
| `attempt.capture_result` | null when captured; `capture_failed`, `timeout` or `outage` otherwise |
| `attempt.late_result` | `stale_attempt`, `after_timeout` |
| every other type | null |

### `idempotency_keys`

| Column | Type | Null | Rule |
|---|---|---|---|
| `key` | `varchar(255)` | no | Primary key (the unique key ADR-0008 requires) |
| `request_hash` | `char(64)` | no | SHA-256 hex of the canonical JSON body |
| `state` | `text` | no | `CHECK (state IN ('in_progress','completed'))` |
| `lease_token` | `uuid` | no | New random value on every claim or takeover; only the request holding it may complete the key |
| `lease_expires_at` | `timestamptz` | no | While `in_progress`, other requests get 409; after it passes, a new request may take the key over |
| `payment_id` | `uuid` | yes | References `payments(id)`; set when completed |
| `response_status` | `smallint` | yes | Set when completed |
| `response_body` | `jsonb` | yes | The stored first response, returned on replay |
| `created_at` | `timestamptz` | no | Default `now()` |
| `expires_at` | `timestamptz` | no | `created_at` plus 24 hours |

- `CHECK ((state = 'completed') = (response_body IS NOT NULL))`.
- Index `(expires_at)`: the cleanup job deletes rows past it (REL-47).

Create flow:

Validation (401, 400, 422) happens before step 1, so a rejected request never holds a key.

1. **Claim (short transaction):** `INSERT ... ON CONFLICT (key) DO NOTHING` with `state='in_progress'` and a new `lease_token`. When the insert returns nothing, read the row and decide in this order:
   - past `expires_at` (24 hours): take it over;
   - a different `request_hash`: 409 `idempotency_key_reused`;
   - `completed`: return the stored response (replay);
   - `in_progress` with a live lease: 409 `idempotency_request_in_progress`;
   - `in_progress` with an expired lease: take it over.
   A takeover is one `UPDATE ... WHERE key = $1 AND lease_token = <token read>` that resets every column (`request_hash`, `state='in_progress'`, new `lease_token`, `lease_expires_at`, `created_at`, `expires_at`, and nulls `payment_id`, `response_status`, `response_body`); zero rows updated means another request won, so re-read and decide again.
2. **Create (one transaction):** insert the payment and its `payment.received` event, then `UPDATE idempotency_keys SET state='completed', payment_id=..., response_status=201, response_body=... WHERE key = $1 AND state = 'in_progress' AND lease_token = <this request's token>`. Zero rows updated means the lease was taken over: roll back the whole transaction (no payment is created) and return 409 `idempotency_request_in_progress`.

Because the claim commits before the create starts, a concurrent request sees `in_progress` and gets 409, as ADR-0008 decision 6 requires. A crash between the two steps leaves an `in_progress` key whose lease expires, so the client's retry succeeds, and a stalled first request that wakes after a takeover cannot complete the key, so one key never creates two payments (REL-17).

### `payment_explanations`

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `bigint` identity | no | Primary key |
| `payment_id` | `uuid` | no | References `payments(id)` |
| `source` | `text` | no | `CHECK (source IN ('model','rules'))` |
| `model` | `text` | yes | `CHECK ((source = 'model') = (model IS NOT NULL))` |
| `text` | `text` | no | |
| `cited_event_seqs` | `integer[]` | no | Each value is a `seq` of this payment's events |
| `trigger` | `text` | no | `CHECK (trigger IN ('final_failure','on_request','regenerate'))` |
| `fallback_reason` | `text` | yes | For example `model_timeout`, `model_unreachable`, `model_error`, `citation_check_failed`, `cause_mismatch` |
| `final_event_at` | `timestamptz` | no | The `payment.final` event time |
| `generated_at` | `timestamptz` | no | |

- Index `(payment_id, generated_at DESC)`: the endpoint returns the latest row.
- Time to explanation (north-star metric, [ADR-0009](../decisions/0009-phase-1-owner-decisions.md)) is `generated_at - final_event_at` of each payment's first row with `trigger = 'final_failure'`.
- A partial unique index `(payment_id) WHERE trigger = 'final_failure'` keeps the automatic explanation to one per payment: the insert uses `ON CONFLICT DO NOTHING`, and the `payment.explained` event is written only when a row was inserted, so a redelivered `payment.final` event creates nothing.

### `incidents`

Written by the `incidents` container (source `rule`) and by `POST /incidents` (source `manual`) (REL-34, [ADR-0014](../decisions/0014-phase-2-incident-detection-and-observability-profile.md)).

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `uuid` | no | Primary key, generated by the application |
| `processor` | `char(1)` | yes | `CHECK (processor IN ('A','B'))`; null for a manual incident that names no processor |
| `source` | `text` | no | `CHECK (source IN ('rule','manual'))` |
| `status` | `text` | no | `CHECK (status IN ('detected','triaged','resolved'))`; only detected, then triaged, then resolved |
| `title` | `text` | no | 1 to 200 characters (API rule) |
| `opened_at` | `timestamptz` | no | The `occurred_at` of the event that opened a rule incident; the request time of a manual one |
| `opened_by_event_id` | `bigint` | yes | `payment_events.id` of that event; null for a manual incident. Not a foreign key, so a demo reset cannot be blocked by it |
| `recovered_at` | `timestamptz` | yes | Set once by the detector, from the first later `payment.routed` event whose health for the processor is `preferred` (`unknown` is not recovery: an avoided processor gets no traffic, so its failures age out while it may still be down); the incident stays open. Never set on a manual incident |
| `triaged_at` | `timestamptz` | yes | Set by the detected to triaged transition |
| `resolved_at` | `timestamptz` | yes | Set by the triaged to resolved transition: only an analyst resolves |
| `created_at` | `timestamptz` | no | Default `now()` |

- A unique partial index `uq_incidents_open_per_processor` on `(processor) WHERE status <> 'resolved' AND processor IS NOT NULL` allows at most one open incident per processor, whoever opened it. The detector inserts with `ON CONFLICT DO NOTHING` against that index; the API turns a conflict into 409 `incident_already_open`.
- Index `(opened_at DESC)` serves the newest-first list.

### `incident_detector_state`

Bookkeeping of the detector, one row per processor, created on first use.

| Column | Type | Null | Rule |
|---|---|---|---|
| `processor` | `char(1)` | no | Primary key, `CHECK (processor IN ('A','B'))` |
| `last_event_id` | `bigint` | no | The id of the last `payment.routed` event applied for this processor |

The detector locks the row (`SELECT ... FOR UPDATE`), ignores any event whose id is not greater than `last_event_id`, and updates it in the same transaction as the incident change; the stream entry is acknowledged only after the commit. A redelivered or late entry therefore cannot reopen a resolved incident or move `recovered_at`, two detectors cannot both open an incident, and a crash between commit and acknowledgement is harmless.

### `incident_payments`

The payments affected by an incident (REL-35). Written by the detector in the same transaction as its bookkeeping, and by `POST /incidents` for a manual incident that names a processor.

| Column | Type | Null | Rule |
|---|---|---|---|
| `incident_id` | `uuid` | no | Foreign key to `incidents.id`; part of the primary key |
| `payment_id` | `uuid` | no | Foreign key to `payments.id`; part of the primary key |
| `linked_at` | `timestamptz` | no | Default `now()` |
| `first_event_id` | `bigint` | no | `payment_events.id` of the payment's first failure event in the linked window (not a foreign key) |

- The primary key `(incident_id, payment_id)` makes linking idempotent: every link is an `INSERT ... ON CONFLICT DO NOTHING`, so a duplicate, redelivered or late stream entry adds nothing twice (late entries are also skipped by `incident_detector_state.last_event_id`).
- A failure on a processor is a `payment.failed` event for it, or an `attempt.authorize_result` or `attempt.capture_result` event for it with reason `timeout` or `outage`.
- At open the detector links every payment with a failure on the incident's processor in `[opened_at - HEALTH_WINDOW_SECONDS, opened_at]`: the failures that made routing avoid it. While the incident is open and not recovered, each later `payment.routed` event links the failures up to its own `occurred_at`; the event that records recovery links before it sets `recovered_at`. A resolved or recovered incident links nothing more. A manual incident without a processor links nothing; one with a processor links the same lookback when it is created, then follows the same rule (it never recovers, so it links until resolved).
- The incident detail reads the links back with the payments' failure events on that processor between `opened_at - HEALTH_WINDOW_SECONDS` and `recovered_at` (or `resolved_at`).

### `incident_summaries`

Stored incident summaries (REL-35), like `payment_explanations`: append-only, and the endpoint reads the latest row.

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `bigint` | no | `GENERATED ALWAYS AS IDENTITY`, primary key |
| `incident_id` | `uuid` | no | Foreign key to `incidents.id` |
| `source` | `text` | no | `CHECK (source IN ('model','rules'))` |
| `model` | `text` | yes | The model name; `CHECK ((source = 'model') = (model IS NOT NULL))` |
| `text` | `text` | no | The summary shown to the analyst |
| `cited_event_ids` | `bigint[]` | no | `payment_events.id` values, all linked to the incident (empty only for `no_linked_events`) |
| `cause` | `text` | no | `CHECK (cause IN ('outage','timeouts','mixed','none'))`: the rules cause; `none` when nothing is linked |
| `fallback_reason` | `text` | yes | Null when `source = 'model'`; else `citation_check_failed`, `model_timeout`, `model_unreachable`, `model_error`, `cause_mismatch` or `no_linked_events` |
| `generated_at` | `timestamptz` | no | |
| `trigger` | `text` | no | `CHECK (trigger IN ('on_request','regenerate'))` |

- Index `(incident_id, generated_at DESC)`: the endpoint returns the latest row.
- The model call runs with no database transaction open: the facts are read and released, the summary is generated, then one short transaction inserts the row.
- The rules cause comes from the linked failure events: only `outage` is `outage`, only `timeout` is `timeouts`, anything else (including `capture_failed`) is `mixed`. A model summary is kept only when every cited id is a linked event and its cause equals the rules cause (ADR-0005, ADR-0013); `no_linked_events` skips the model.

### `webhook_subscriptions`

A webhook subscription (REL-39, [ADR-0015](../decisions/0015-webhook-delivery-signing-and-target-allowlist.md)). Written by the api; read by the api and the `webhooks` container.

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `uuid` | no | Primary key, created by the api |
| `url` | `text` | no | `http` or `https` to an allowed host; checked by the api at creation and again by the sender (not a `CHECK`: the allowlist is a setting) |
| `event_types` | `text[]` | no | `CHECK (cardinality(event_types) >= 1 AND event_types <@ ARRAY[the six lifecycle types])`: `payment.received`, `payment.authorized`, `payment.captured`, `payment.declined`, `payment.failed`, `payment.final` |
| `secret` | `text` | no | The signing secret generated by Relay. Stored in clear because Relay must sign with it; returned only by the create response and never logged |
| `active` | `boolean` | no | Default true; `DELETE` sets it false (rows are not deleted) |
| `created_at` | `timestamptz` | no | Default `now()` |

- Index `(created_at DESC)` serves the list.

### `webhook_deliveries`

The delivery log: one row per event and subscription, updated by every attempt (REL-39). Written by the `webhooks` container; read by the api (`GET /webhooks/deliveries`).

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `bigint` | no | `GENERATED ALWAYS AS IDENTITY`, primary key |
| `subscription_id` | `uuid` | no | Foreign key to `webhook_subscriptions.id` |
| `event_id` | `bigint` | no | `payment_events.id` (not a foreign key) |
| `event_type` | `text` | no | `CHECK` to the six lifecycle types |
| `attempt` | `smallint` | no | Attempts made so far; default 0; `CHECK (attempt BETWEEN 0 AND 8)` |
| `status` | `text` | no | `CHECK (status IN ('pending','delivered','failed'))`; default `pending` |
| `next_attempt_at` | `timestamptz` | no | Default `now()`; when the next attempt is due (for a claimed delivery, when its lease ends) |
| `last_status_code` | `integer` | yes | The last attempt's HTTP status; null when it had no response |
| `last_error` | `text` | yes | `HTTP <status>`, an error class name (`ReadTimeout`, `ConnectError`), or `target_not_allowed`, `subscription_inactive`, `event_missing`; null after success |
| `created_at`, `updated_at` | `timestamptz` | no | Default `now()`; `updated_at` is set by every attempt |

- Unique `(subscription_id, event_id)`: a duplicate or redelivered stream entry inserts nothing (`INSERT ... ON CONFLICT DO NOTHING`), so one event is one delivery per subscription.
- Partial index `(next_attempt_at) WHERE status = 'pending'` serves the send loop; index `(created_at DESC, id DESC)` the log; index `(status, updated_at)` the retention cleanup.
- Sending takes due rows with `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)` that pushes `next_attempt_at` out by a lease and commits, posts with no transaction open, then records the answer in a second transaction (`WHERE status = 'pending'`). A sender that dies in between leaves the row to be picked up again after the lease.
- The row holds the attempt count and the last response; each attempt also has a row in `webhook_delivery_attempts`. Retention: delivered and failed rows (and, by cascade, their attempts) are deleted `WEBHOOK_LOG_RETENTION_DAYS` (default 7) after `updated_at` by a cleanup step in the `webhooks` container; pending rows are kept.

### `webhook_delivery_attempts`

The per-attempt log (REL-39): one row per attempt of a delivery, so every attempt is visible. Written by the `webhooks` container in the same transaction that records the delivery's result (including the no-request cases `target_not_allowed`, `subscription_inactive` and `event_missing`, which count as an attempt with no status code); read by `GET /webhooks/deliveries/{id}`.

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `bigint` | no | `GENERATED ALWAYS AS IDENTITY`, primary key |
| `delivery_id` | `bigint` | no | Foreign key to `webhook_deliveries.id` with `ON DELETE CASCADE` |
| `attempt` | `smallint` | no | The delivery's attempt number; `CHECK (attempt BETWEEN 1 AND 8)` |
| `status_code` | `integer` | yes | The HTTP status; null when there was no response |
| `error` | `text` | yes | The same values as `webhook_deliveries.last_error`; null on a 2xx answer |
| `duration_ms` | `integer` | no | `CHECK (duration_ms >= 0)`; 0 when no request was made |
| `attempted_at` | `timestamptz` | no | Default `now()` (the time the result was recorded) |

- Index `(delivery_id)` serves the detail endpoint. The retention cleanup deletes only deliveries; the cascade removes their attempts.

### `webhook_consumer_state`

The consumer's bookkeeping (REL-39): a single row (`id = 1`, enforced by a `CHECK`) holding `last_event_id bigint`, the highest event id the `webhooks` consumer has applied. It is updated in the same transaction as the deliveries it stores (`GREATEST` of the old and the new id), and the stream entry is acknowledged after the commit. Unlike `incident_detector_state` it is never used to skip an entry: the stream is not strictly ordered by event id, so skipping a lower id could lose a delivery; the unique key above is what makes a repeat harmless.

## Valkey (Redis-compatible stream server)

Valkey 9.1.2 replaces Redis 7 ([ADR-0012](../decisions/0012-phase-1-review-decisions.md)); the protocol, redis-py, the compose service name `redis` and the `REDIS_URL` variables stay the same. Its data lives in the `valkeydata` volume, because Valkey cannot read data written by Redis 7.4.

| Key | Type | Content | Retention |
|---|---|---|---|
| `relay:payment-events` | Stream | One entry per published event: `event_id`, `payment_id`, `seq`, `attempt_no`, `type`, `correlation_id` | `XADD ... MAXLEN ~ 10000`; append-only persistence on |
| Consumer group `processing` | Group | Worker processing consumers | Pending entries reclaimed with `XAUTOCLAIM` after `RECLAIM_IDLE_MS` |
| Consumer group `explanations` | Group | Explanation consumer in the `explainer` container (ADR-0012) | Same |
| Consumer group `incidents` | Group | Incident detector in the `incidents` container (ADR-0014); created again by the detector if the demo reset deletes the stream | Same |
| Consumer group `webhooks` | Group | Webhook deliveries in the `webhooks` container (ADR-0015); created again by the consumer if the demo reset deletes the stream | Same |

Stream entries carry ids, not payment data; consumers read the current state from PostgreSQL under a row lock.

## Retention

- API response counts are not stored in PostgreSQL. The api writes one JSON line per request (time, method, path template, status, duration_ms, correlation_id) to stdout and appends the same line to `/var/log/relay/api-requests.jsonl` on the named volume `api-logs` (REL-52). The reporting command mounts that volume read-only and computes the API 5xx rate from it; every other REL-51 measure comes from stored events. The demo reset (REL-30) truncates the file.
- `payments`, `payment_events`, `payment_explanations`, `incidents`, `incident_detector_state` and `webhook_subscriptions`: kept (synthetic data). A documented reset command empties them before each demo run (REL-30) with `TRUNCATE ... RESTART IDENTITY CASCADE`, because the append-only trigger rejects `DELETE` on `payment_events` (row triggers do not fire on `TRUNCATE`). REL-30 saves each run's per-reference outcomes to a file before the next reset, so runs can be compared payment by payment.
- `idempotency_keys`: deleted after `expires_at` (REL-47).
- `webhook_deliveries`: delivered and failed rows are deleted after `WEBHOOK_LOG_RETENTION_DAYS` (REL-39); the demo reset empties all four webhook tables with the others.
- Stream: trimmed by `MAXLEN`; nothing depends on old entries.

## Test database

Tests use the `relay_test` database created by the Postgres init script and never the development database (REL-12). Each test run migrates `relay_test` to head and truncates the tables between tests.

## Differences found in REL-32

| Difference | Resolution |
|---|---|
| `fallback_reason` examples omitted `model_error` (the model answered with an error status or an unusable body, `api/app/explain/model.py`) | Added to the `payment_explanations` table above |
| The `data` content of events was not documented; `payment.routed.data.health` existed in the code only | Documented under the event types table |
| The doc did not say which events carry `processor` or money | Documented under the event types table (Phase 2 consumers need it, see the REL-32 review, section 4) |
| Everything else (tables, columns, `CHECK`s, indexes, trigger, stream keys and groups `processing` and `explanations`) | Matched; no change |
