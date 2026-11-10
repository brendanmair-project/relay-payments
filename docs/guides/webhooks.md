# Webhooks

Relay posts a signed JSON message to a URL you register each time a payment reaches a lifecycle state you chose. Sending happens in its own container, never on the payment path, so a slow or failing endpoint of yours never delays a payment. The decisions behind this page are in [ADR-0015](../decisions/0015-webhook-delivery-signing-and-target-allowlist.md); the endpoint details are in [api-reference.md](api-reference.md).

## Subscribe

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/subscriptions \
  -H "X-API-Key: $RELAY_API_KEY" -H "Content-Type: application/json" \
  -d '{"url": "http://webhook-sink:8200/hook", "event_types": ["payment.final"]}'
```

```powershell
$h = @{ "X-API-Key" = $env:RELAY_API_KEY }
$sub = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/webhooks/subscriptions -Headers $h -ContentType "application/json" -Body '{"url": "http://webhook-sink:8200/hook", "event_types": ["payment.final"]}'
$sub
```

The `201` response carries `secret`, the key Relay signs with. **It is shown once**: no other endpoint returns it and it is never logged. Store it now; a lost secret means a new subscription. `GET /webhooks/subscriptions` lists subscriptions without secrets, and `DELETE /webhooks/subscriptions/{id}` deactivates one.

**Target allowlist.** The URL must be `http` or `https`, must not carry credentials, and its host must be one of the exact hostnames in the `WEBHOOK_ALLOWED_HOSTS` setting (default `webhook-sink,localhost,127.0.0.1`), so Relay cannot be pointed at its own database or api. Anything else is `422 webhook_target_not_allowed` and nothing is stored or fetched. The host is checked again at send time. A real subscriber's host must be added to the setting.

## Event types

Choose from the payment lifecycle only: `payment.received`, `payment.authorized`, `payment.captured`, `payment.declined`, `payment.failed` and `payment.final`. `payment.failed` can fire before a retry; `payment.final` fires once per payment with the outcome in `data.status` (`captured`, `declined` or `failed`). Internal events are never delivered.

## The message

```
POST <your url>
Content-Type: application/json
Relay-Event-Id: 1234
Relay-Signature: t=1793890000,v1=<64 hex characters>

{"id": 1234, "type": "payment.final", "created_at": "2026-11-05T14:03:22.418Z",
 "data": {"payment_id": "<uuid>", "status": "captured", "amount_minor": 1250, "currency": "EUR"}}
```

`id` is the event id, the same as the `Relay-Event-Id` header. The body never contains the free-text `description`. Answer with any `2xx` status to confirm delivery; redirects are not followed.

## Verify the signature

`v1` is the lowercase hex HMAC-SHA256, keyed with your subscription secret, of the text `<t>.<raw body>`: the decimal timestamp from the header, a dot, and the exact bytes received. Compute it over the raw body before any JSON parsing, compare in constant time, and reject a timestamp far from your clock (five minutes is a good tolerance) so a captured message cannot be replayed later. A new `t` and signature are made for every attempt; the body and `Relay-Event-Id` stay the same. A header may carry several `v1` values; accept the message if any matches.

```python
import hashlib
import hmac
import time


def verify_signature(secret, header, body, tolerance_seconds, now=None):
    """True when `header` carries a valid signature of the raw `body` made within `tolerance_seconds` of now."""
    stamp = None
    candidates = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                stamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:
            candidates.append(value)
    if stamp is None or not candidates:
        return False
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance_seconds:
        return False
    signed = f"{stamp}.".encode() + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in candidates)
```

Call it with the raw request body as bytes, the `Relay-Signature` header and your secret; return a non-2xx status when it is `False`. The snippet is the same algorithm as Relay's own `verify` in `api/app/webhooks/signing.py`, and a test keeps the two in step.

## Retries

A delivery succeeds on any `2xx`. A non-2xx answer, a timeout (5 seconds by default) or a connection error is a failed attempt, retried with exponential backoff: after the n-th failed attempt the wait is `min(2 s * 2^(n-1), 60 s)`. With the defaults the waits after attempts 1 to 7 are 2, 4, 8, 16, 32, 60 and 60 seconds. After the 8th failed attempt the delivery is `failed` and is not tried again; read the delivery log and fetch the payments through the API to catch up. The base, factor and cap are settings (`WEBHOOK_BACKOFF_BASE_SECONDS`, `WEBHOOK_BACKOFF_FACTOR`, `WEBHOOK_BACKOFF_MAX_SECONDS`).

## Duplicates

The event stream is at-least-once, so you can receive the same event twice (for example when a retry follows an answer that was lost). Relay stores one delivery per subscription and event, but you must still drop repeats: remember the `Relay-Event-Id` values you have processed and ignore a second one.

## The delivery log and the success rate

`GET /webhooks/deliveries` is the delivery log, newest first, filtered by `subscription_id` and `status` (`pending`, `delivered`, `failed`). It pages like `GET /payments`: `limit` is the page size (1 to 100, default 20), the answer has `items` and `next_cursor`, and you pass `next_cursor` back as `cursor` until it is `null`; the filters apply to every page, so the whole log can be read. `GET /webhooks/deliveries/{id}` adds every attempt with its HTTP status, error and duration. Finished rows are kept for `WEBHOOK_LOG_RETENTION_DAYS` (7 by default).

**Success rate** = delivered divided by final deliveries (delivered plus failed) in a window, computed from the delivery log. Pending deliveries are still being retried, so they are not in the denominator. Read it from the keyed summary endpoint:

```bash
curl -s "http://127.0.0.1:8000/webhooks/deliveries/summary" -H "X-API-Key: $RELAY_API_KEY"
curl -s "http://127.0.0.1:8000/webhooks/deliveries/summary?since=2026-11-05T00:00:00Z&until=2026-11-06T00:00:00Z" -H "X-API-Key: $RELAY_API_KEY"
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/webhooks/deliveries/summary?since=2026-11-05T00:00:00Z" -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }
```

```json
{"delivered": 18, "failed": 2, "pending": 1, "success_rate": 0.9,
 "since": "2026-11-05T00:00:00.000Z", "until": null, "subscription_id": null}
```

`success_rate` is `null`, not zero, when no delivery is final in the window. The window is `[since, until)`, both optional ISO 8601 times (a time without a zone is UTC). A delivered or failed delivery falls in the window by when it finished (`updated_at`), a pending one by when it was created (`created_at`). Add `subscription_id=<uuid>` to look at one subscription. A bad timestamp is `422 validation_failed`.

## Try it locally

The `webhooks-demo` profile adds a sink that records what it receives, checks signatures and can fail on demand. It listens on `http://127.0.0.1:8200`, and Relay reaches it as `http://webhook-sink:8200`.

1. Start the stack with the sink: `docker compose --profile webhooks-demo up -d --wait --build`
2. Subscribe as shown above and copy the `secret` from the response.
3. Give the sink the secret so it can verify: `curl -s -X POST http://127.0.0.1:8200/config -H "Content-Type: application/json" -d '{"secret": "<the secret>"}'`
4. Create a payment as in the [quickstart](quickstart.md), or run a short seeded load: `docker compose run --rm simulator python -m generator --scenario processor-a-outage --seed 41 --count 20 --rate 4 --api-url http://api:8000 --control-url http://simulator:8101`
5. See what arrived: `curl -s http://127.0.0.1:8200/received`; each entry has `signature_valid: true`. When a secret is set the sink answers `401` to a message whose signature does not verify (a malformed or non-ASCII one included) and records it with `signature_valid: false`.
6. See the log and the rate: `GET /webhooks/deliveries` and `GET /webhooks/deliveries/summary`. The counts in the summary equal the counts by `status` in the log.
7. Make the sink fail the next three deliveries to watch retries: `curl -s -X POST http://127.0.0.1:8200/config -H "Content-Type: application/json" -d '{"fail_next": 3}'`, create a payment, and open its delivery with `GET /webhooks/deliveries/{id}` to see the attempts and waits.

Stop with `docker compose --profile webhooks-demo down -v`.
