# ADR-0015: Webhook delivery in its own consumer, signed, with a target allowlist

Template: claude/decision@1

Status: Accepted  
Decision owner: Brendan  
Date: 2026-11-04  
Supersedes: None (refines REL-39)  
Superseded by: None

## Context and forces

Phase 3 adds webhooks (REL-39): subscribers register for payment event types and receive a signed message when a payment reaches that state. The REL-38 plan review (workspace `evaluations/relay-plan-review-2026-11-04-phase3.md`) found three decisions in the task that change public interfaces or security controls.

- Constraint: nothing may delay payment processing (ADR-0012, ADR-0014). The event stream is at-least-once (ADR-0003), so a subscriber can receive the same event twice.
- Security: a subscriber URL is fetched by Relay itself. An unrestricted URL lets anyone with the API key make Relay call internal services (the database, the api or the simulator control API): server-side request forgery.
- Public interface: the payload, the signature header and the retry schedule are what an outside developer builds against (REL-40 docs, REL-41 SDK), so they must be decided, not drifted into.
- Secrets: each subscription needs a signing secret that Relay can use but that must not leak through the API or the logs.

## Decision

1. **Own consumer, crash-safe deliveries.** A `webhooks` container reads the event stream with its own consumer group, so it is never on the payment path.
   - **Storage:** each matching event becomes a stored delivery row (subscription, event id, attempt, status, next attempt time, last response code). The row is written in the same transaction as the consumer's bookkeeping, and the stream entry is acknowledged after the commit, so a crash loses nothing.
   - **Sending:** a send loop picks due deliveries.
2. **Signed, deduplicable messages.**
   - **Headers:** every delivery carries `Relay-Event-Id` (the event id, so a subscriber can drop duplicates) and `Relay-Signature: t=<unix seconds>,v1=<hex>`.
   - **Signature:** `v1` is HMAC-SHA256 over `<t>.<raw body>` with the subscription's secret.
   - **Body:** a JSON object with the event type, the payment id, the status, the amount in minor units with its currency, and the event time. It never carries the free-text `description`.
3. **Retries.** On a non-2xx answer, a timeout or a connection error, the delivery is retried with exponential backoff. The base interval, the factor and the cap are settings; the defaults are short enough for the local demo. After at most 8 attempts the delivery is marked `failed`. All attempts are visible in a delivery log, which keeps rows for a configurable retention.
4. **Target allowlist.** A subscription URL must be `http` or `https`, and its host must match the `WEBHOOK_ALLOWED_HOSTS` setting. The default allows the local demo sink and `localhost`. The host is checked when the subscription is created and again at send time; any other target is rejected with 422 and is never fetched.
5. **Secrets shown once.** Relay generates a random secret when a subscription is created and returns it only in that response. It stores the secret to sign deliveries, and never returns it from any other endpoint nor writes it to a log. Rotation is a later task.

6. **Subscribable event types.** Subscribers choose from the payment lifecycle only: `payment.received`, `payment.authorized`, `payment.captured`, `payment.declined`, `payment.failed` and `payment.final`. `payment.failed` can fire before a retry; `payment.final` fires once with the outcome. Internal events (`attempt.*`, `payment.routed`, `payment.retry_scheduled`, `payment.explained` and others) are never delivered. The owner chose this on 2026-11-05 (REL-39).

The owner chose these on 2026-11-04.

## Alternatives considered

| Option | Benefits | Costs and risks | Decision |
|---|---|---|---|
| Own consumer, signed, allowlist | Off the payment path; crash-safe; no request forgery by default | One more container; real subscribers need their host added to the setting | Chosen |
| Same, but block private address ranges instead of an allowlist | Open to any public subscriber | DNS rebinding and IPv6 edge cases are easy to get wrong; blocks the local demo sink unless excepted | Rejected |
| Deliver from the payment worker | Least code | Subscriber latency and failures on the payment path, against ADR-0012 and ADR-0014 | Rejected |
| Subscriber-supplied secrets | Subscriber controls the value | Weak secrets possible | Rejected |

## Consequences

Positive:

- A slow or failing subscriber never delays a payment, a crash never loses or silently repeats a delivery, and Relay cannot be pointed at its own internal services.

Negative and tradeoffs:

- Subscribers must handle duplicates, using `Relay-Event-Id`, as with any at-least-once webhook.
- A lost secret means a new subscription until rotation exists.

Operational impact:

- REL-39 adds the `webhooks` container (restart policy, health check, per-service variables, covered by `api/tests/test_compose_stack.py`), the subscription and delivery tables, the keyed subscription API, a demo sink under a compose profile, and metrics for deliveries by outcome.
- REL-40 documents the payload, the signature check and the retry schedule.
- REL-41's SDK verifies the signature.

## Validation and review

- Validate with REL-39 tests: a signed delivery verifies; a duplicate stream entry produces one delivery; a crash between commit and ack loses nothing; the retry schedule and the final `failed` state; a disallowed host is rejected at creation and at send time; the secret appears only in the create response and never in logs.
- Revisit when: real external subscribers need open targets, secrets need rotation, or delivery volume needs batching.
- Owner: Brendan.
