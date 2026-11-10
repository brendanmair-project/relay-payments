# relay-sdk

Synchronous Python client for the Relay payments API: payments (create with an idempotency key, get, list with cursor paging) and webhooks (subscriptions, delivery log, delivery summary, signature verification). Installed from this repository; nothing is published to a package index.

```bash
pip install ./sdk/python
```

```python
import os

from relay_sdk import RelayClient

with RelayClient("http://127.0.0.1:8000", os.environ["RELAY_API_KEY"]) as client:
    result = client.create_payment(1999, "USD")
    print(result.payment.id, result.replayed)
```

The full guide is [docs/guides/sdk.md](../../docs/guides/sdk.md); examples are in `examples/`.

- Python 3.12 or newer; MIT licence (see the repository `LICENSE`).
- Runtime dependency: `httpx==0.28.1` only (BSD-3-Clause, licence checked 2026-11-05; same pin as the api, ADR-0011).
- Dev extras (`pip install ".[dev]"`): `pytest==9.1.1`, `ruff==0.16.9`, `mypy==2.3.1`, the api's versions.
- Checks: `docker compose --profile sdk run --rm sdk` from the repository root runs `ruff check .`, `ruff format --check .`, `mypy src` and `pytest`.
