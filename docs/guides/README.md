# Relay developer guides

Relay is a payments API with one timeline per payment, plain-language failure explanations and failover between two processors. These guides take a developer from a clean clone to a signed webhook. Everything runs locally on synthetic data.

| Guide | Read it to |
|---|---|
| [quickstart.md](quickstart.md) | Start the stack and make a first payment, read its timeline and see it finish |
| [authentication-and-idempotency.md](authentication-and-idempotency.md) | Send the API key, retry safely with `Idempotency-Key`, and read error bodies |
| [webhooks.md](webhooks.md) | Subscribe, verify signatures, handle retries and duplicates, and read the delivery success rate |
| [sdk.md](sdk.md) | Use the Python SDK: payments, paging, errors, webhook verification and runnable examples |
| [api-reference.md](api-reference.md) | Look up every endpoint, parameter, enum value and error code (generated) |
| [openapi.json](openapi.json) | Feed the OpenAPI document to a client generator (generated) |

`api-reference.md` and `openapi.json` are generated from the running code by `python -m app.docs_export`, and a test fails when they are out of date, so they always match the API. The design behind them is in [api-contract.md](../architecture/api-contract.md), which stays the authority when a sentence here seems to disagree.

To regenerate them after an API change, run `cd api && python -m app.docs_export`. Without a local Python environment, run this from the repository root: `docker compose run --rm --no-deps -v ./docs:/docs api python -m app.docs_export`.
