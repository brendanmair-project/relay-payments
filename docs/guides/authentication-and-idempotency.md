# Authentication, idempotency and errors

## The API key

Every endpoint, reads and `GET /health` included, needs the header `X-API-Key: <RELAY_API_KEY>`. The key is the static value you set when you started the stack. A missing or wrong key is `401` with the code `unauthorized`; the request never reaches the endpoint. The OpenAPI document declares this as the `ApiKeyAuth` security scheme, so client generators add the header for you. The interactive `/docs` page and `/openapi.json` need the key as well, so a browser cannot open them; use [api-reference.md](api-reference.md) and [openapi.json](openapi.json).

## Idempotency-Key

`POST /payments` requires an `Idempotency-Key` header so a retry after a timeout never charges twice.

- **Format:** 1 to 255 printable ASCII characters (space to `~`). Generate a fresh random value, such as a UUID, for each new payment. A missing key is `400 idempotency_key_missing`; a key that is too long or has other characters is `400 malformed_request`.
- **Replay:** the same key with the same body returns the stored first response, with status `201` and the header `Idempotent-Replayed: true`. The body is the payment as it was when first created, not its current state; read `GET /payments/{id}` for that.
- **Different body:** the same key with a different body is `409 idempotency_key_reused`. Bodies are compared by their canonical JSON (keys sorted, no insignificant whitespace), so key order and spacing do not matter.
- **Still running:** the same key while the first request is still being processed is `409 idempotency_request_in_progress` with `Retry-After: 1`; wait and send the same request again.
- **Expiry:** a key is remembered for 24 hours. After that the same key starts a new payment.

## Order of checks

For `POST /payments` the checks run in this order, and the first failure answers:

1. The API key (401).
2. The `Idempotency-Key` header (400), even when the body is also wrong.
3. The body (400 for invalid JSON, 422 for invalid fields).
4. The key is claimed: a different body is 409 `idempotency_key_reused`, an unfinished first request is 409 `idempotency_request_in_progress`, a finished one is replayed.

A request rejected in steps 1 to 3 never holds a key, so you can correct it and resend with the same key.

## Query parameters

Each endpoint reads only the query parameters it documents, and **unknown query parameters are ignored**: a misspelt filter returns the unfiltered answer, not an error. The names are not the same everywhere. `GET /analytics` takes `from` and `to`, while `GET /webhooks/deliveries/summary` takes `since` and `until`. Check the parameter names in [api-reference.md](api-reference.md) before relying on a filter.

## Error body

Every 4xx and 5xx response has the same shape, and carries an `X-Correlation-ID` response header with the same id. Quote that id when you report a problem.

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

`details` appears only for 422. You may send your own `X-Correlation-ID` (1 to 64 letters, digits, `-` or `_`); an invalid one is replaced, not rejected.

## Error codes

| HTTP | `code` | When |
|---|---|---|
| 400 | `idempotency_key_missing` | `POST /payments` without `Idempotency-Key` |
| 400 | `malformed_request` | The body is not valid JSON, a header has an invalid format, or a cursor is malformed |
| 401 | `unauthorized` | Missing or wrong `X-API-Key` |
| 404 | `not_found` | Unknown payment, incident, subscription or delivery id, or an unknown path |
| 409 | `idempotency_key_reused` | Same key with a different request body |
| 409 | `idempotency_request_in_progress` | Same key while the first request is still being processed; sent with `Retry-After: 1` |
| 409 | `payment_not_final` | An explanation was requested for a payment that is not final |
| 409 | `incident_already_open` | `POST /incidents` for a processor that already has an open incident |
| 409 | `invalid_incident_transition` | An incident transition other than detected to triaged or triaged to resolved |
| 422 | `validation_failed` | A field is missing, has the wrong type or an unsupported value, or is out of range |
| 422 | `webhook_target_not_allowed` | A webhook URL is not http or https to an allowed host |
| 500 | `internal_error` | Unexpected failure; no internals are revealed |
| 503 | `dependency_unavailable` | `GET /health` found PostgreSQL or the stream server unreachable |

Each operation in the [API reference](api-reference.md) lists exactly the codes it can return. Server errors (5xx) and timeouts are safe to retry for `POST /payments` as long as you resend the same `Idempotency-Key` and body.

Next: [webhooks.md](webhooks.md).
