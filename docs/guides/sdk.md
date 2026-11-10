# Python SDK

`relay-sdk` is a small synchronous Python client for the payments and webhooks parts of the API. It sends the API key, generates idempotency keys, parses responses into typed dataclasses, raises one exception type for API errors, and verifies webhook signatures exactly as [ADR-0015](../decisions/0015-webhook-delivery-signing-and-target-allowlist.md) defines them. Other endpoints (incidents, analytics, explanations, processor health) stay HTTP-only: use [api-reference.md](api-reference.md).

The SDK lives in `sdk/python/` and is installed from the repository. Nothing is published to a package index.

## Install

Python 3.12 or newer. From the repository root:

```bash
pip install ./sdk/python
```

```powershell
pip install .\sdk\python
```

Its only dependency is `httpx`, pinned to `0.28.1` (the version the api already uses; BSD-3-Clause licence, checked 2026-11-05). The SDK itself is MIT licensed. Test tools are the `dev` extra (`pip install "./sdk/python[dev]"`), pinned to the api's pytest, ruff and mypy versions.

## The client

```python
import os

from relay_sdk import RelayClient

with RelayClient("http://127.0.0.1:8000", os.environ["RELAY_API_KEY"]) as client:
    created = client.create_payment(1999, "USD", description="Order 4471", reference="order-4471")
    payment = client.get_payment(created.payment.id)
    print(payment.display_status, [event.type for event in payment.events])
```

`RelayClient(base_url, api_key, timeout=10.0, transport=None)` wraps one `httpx.Client` and sends `X-API-Key` on every request. Use it as a context manager or call `close()`. Pass `transport=httpx.MockTransport(handler)` in your own tests to avoid the network. Models are frozen dataclasses with the field names of [openapi.json](openapi.json); timestamps are timezone-aware `datetime` values and unknown response fields are ignored, so a newer API does not break an older SDK.

## Payments

- `create_payment(amount_minor, currency, description=None, reference=None, idempotency_key=None)` returns a `PaymentCreated` with `.payment` and `.replayed`. When no `idempotency_key` is given, a fresh UUID4 is generated, which is right for a new payment. To retry safely after a timeout, keep your own key and pass the same one again; `replayed` is `True` when Relay answered from the stored first response (the `Idempotent-Replayed` header, see [authentication-and-idempotency.md](authentication-and-idempotency.md)).
- `get_payment(payment_id)` returns the `Payment` with its timeline in `.events`.
- `list_payments(status=None, processor=None, limit=None, cursor=None, is_final=None)` returns a `PaymentPage` (`.items`, `.next_cursor`), newest first. `status` may be one value or a list.
- `iter_payments(status=None, processor=None, limit=None, is_final=None)` follows `next_cursor` for you and yields every matching payment, fetching pages lazily.

```python
for payment in client.iter_payments(status=["failed", "declined"], processor="A", limit=50):
    print(payment.id, payment.display_status)
```

## Errors

Any non-2xx answer raises `RelayError` with `status`, `code`, `message`, `correlation_id` and, for validation failures, `details`. The code and message come from the shared error body; the correlation id falls back to the `X-Correlation-ID` header. A reply that is not the error shape (for example an HTML page from a proxy) still raises `RelayError` with `code == "http_error"`. Network failures are not wrapped: `httpx.TransportError` and its subclasses propagate.

```python
from relay_sdk import RelayError

try:
    client.get_payment("00000000-0000-4000-8000-000000000000")
except RelayError as error:
    print(error.status, error.code, error.correlation_id)
```

## Webhooks

- `create_subscription(url, event_types)` returns a `SubscriptionCreated`; its `.secret` is shown only here and is left out of `repr`, so store it at once. The URL host must be on the target allowlist ([webhooks.md](webhooks.md)).
- `list_subscriptions()`, `get_subscription(id)` and `delete_subscription(id)` (which deactivates and returns the subscription).
- `list_deliveries(subscription_id=None, status=None, limit=None, cursor=None)` returns one page of the delivery log, newest first, as a `DeliveryPage` with `.items` and `.next_cursor` (`None` on the last page); pass `next_cursor` back as `cursor` for the next page. `iter_deliveries(subscription_id=None, status=None, limit=None)` yields every matching delivery by following the cursors. `get_delivery(id)` adds every attempt in `.attempts`.
- `delivery_summary(since=None, until=None, subscription_id=None)` returns the delivered, failed and pending counts and the success rate (`None` when nothing is final). `since` and `until` take a `datetime` or an ISO 8601 string.

### Verify a delivery

Verify the raw request body before parsing it:

```python
from relay_sdk import SignatureVerificationError, parse_event, verify_signature

def handle(secret: str, signature_header: str, raw_body: bytes) -> None:
    try:
        verify_signature(secret, signature_header, raw_body, tolerance_seconds=300)
    except SignatureVerificationError as error:
        raise PermissionError(error.reason) from error  # answer 400 or 401
    event = parse_event(raw_body)
    print(event.id, event.type, event.data["payment_id"])
```

`verify_signature` returns `None` on success and raises `SignatureVerificationError` otherwise; its `reason` is `malformed_header` (no `t`, a non-numeric `t`, or no `v1`), `timestamp_outside_tolerance` or `no_matching_signature`. A header with several `v1` values is accepted when any one matches, and the comparison is constant-time. `is_valid_signature(...)` takes the same arguments and returns a `bool`. `now` can be passed in tests. Drop duplicates by remembering `event.id` (the `Relay-Event-Id` header), because delivery is at-least-once.

The same algorithm is Relay's own `verify` in `api/app/webhooks/signing.py`; `api/tests/test_sdk_signature_agreement.py` checks that both give the same answer for good, tampered, wrong-secret, old-timestamp, multiple-`v1` and malformed messages.

## Examples

Both live in `sdk/python/examples/` and read `RELAY_API_URL` (default `http://127.0.0.1:8000`) and `RELAY_API_KEY` from the environment.

- `create_and_list.py` creates a payment, polls until it is final, prints its timeline and lists the five most recent payments.
- `verify_webhook.py` starts a small standard-library receiver, subscribes it, creates a payment and verifies the signed `payment.final` delivery with the SDK. Relay posts from its own container, so the receiver's host must be on the allowlist: start the stack with `WEBHOOK_ALLOWED_HOSTS=webhook-sink,localhost,127.0.0.1,host.docker.internal` and run the script on the host (see its docstring for the other settings).

```bash
pip install ./sdk/python
export RELAY_API_KEY=<the key the stack runs with>
python sdk/python/examples/create_and_list.py
python sdk/python/examples/verify_webhook.py
```

Without installing anything, run the first one in the SDK container on the compose network:

```bash
docker compose --profile sdk run --rm -e RELAY_API_URL=http://api:8000 -e RELAY_API_KEY sdk python examples/create_and_list.py
```

## Tests and checks

`docker compose --profile sdk run --rm sdk` runs `ruff check .`, `ruff format --check .`, `mypy src` and `pytest` (all with a mock transport, no network). Run only the tests with `docker compose --profile sdk run --rm sdk pytest`. CI runs the same four commands in the `sdk` job when `sdk/` changes.
