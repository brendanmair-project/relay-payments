# Quickstart: your first payment

You will start Relay, create a payment, read it back with its event timeline, and watch it reach a final state. The first `docker compose up` downloads base images and builds the Relay images, so it needs network access and takes several minutes; later starts take well under a minute.

## Prerequisites

- Docker with Compose v2 (`docker compose version` works)
- git
- curl (bash), or PowerShell 5.1 or newer on Windows (the PowerShell steps use `Invoke-RestMethod`)
- Free local ports 8000 (api), 3000 (web UI) and 8101 (simulator control); see Troubleshooting to move them

## 1. Clone and set the API key

Every endpoint needs one static key, `RELAY_API_KEY`. Put a plain value in your shell; Compose passes it to the services. (Alternatively, copy the committed example file `.env.example` to a file named `.env` in the repository root and set the key there.)

bash:

```bash
git clone https://github.com/brendanmair-project/relay.git
cd relay
export RELAY_API_KEY=local-demo-key-1
```

PowerShell:

```powershell
git clone https://github.com/brendanmair-project/relay.git
cd relay
$env:RELAY_API_KEY = "local-demo-key-1"
```

## 2. Start the stack

```bash
docker compose up -d --wait
```

This builds the images, starts PostgreSQL, Valkey, the api, the worker and the simulated processors, and returns when every service is healthy. The api listens on `http://127.0.0.1:8000`.

Check it. bash:

```bash
curl -s http://127.0.0.1:8000/health -H "X-API-Key: $RELAY_API_KEY"
```

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }
```

Expect `{"status":"ok","database":"ok","redis":"ok"}`. Without the key you get 401 `unauthorized`.

Relay also serves interactive docs at `/docs` and `/openapi.json`, but they need the key too, so a browser cannot open them. Use [api-reference.md](api-reference.md) and [openapi.json](openapi.json) instead.

## 3. Create a payment

`POST /payments` needs an `Idempotency-Key` header: any 1 to 255 printable ASCII characters that you choose. Repeating a request with the same key and body returns the first payment instead of creating a second one. Amounts are integers in minor units (1999 is 19.99 USD); currencies are `USD`, `EUR`, `GBP` and `JPY`.

bash:

```bash
curl -s -i -X POST http://127.0.0.1:8000/payments \
  -H "X-API-Key: $RELAY_API_KEY" \
  -H "Idempotency-Key: quickstart-0001" \
  -H "Content-Type: application/json" \
  -d '{"amount_minor": 1999, "currency": "USD", "description": "Order 4471"}'
```

Expect `HTTP/1.1 201 Created`, a `Location: /payments/<id>` header and a JSON body with `"status":"received"`. Now save the payment id. This repeats the same request with the same key, so it is a replay: it creates nothing new and answers `201 Created` again with the header `Idempotent-Replayed: true` and the body of the first response (still `"status":"received"`, not the payment's current state). The command below prints only the id; add `-i` after `curl` to see the header.

```bash
PAYMENT_ID=$(curl -s -X POST http://127.0.0.1:8000/payments \
  -H "X-API-Key: $RELAY_API_KEY" -H "Idempotency-Key: quickstart-0001" -H "Content-Type: application/json" \
  -d '{"amount_minor": 1999, "currency": "USD", "description": "Order 4471"}' | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
echo $PAYMENT_ID
```

PowerShell (one request; it also saves the id):

```powershell
$headers = @{ "X-API-Key" = $env:RELAY_API_KEY; "Idempotency-Key" = "quickstart-0001" }
$body = '{"amount_minor": 1999, "currency": "USD", "description": "Order 4471"}'
$payment = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/payments -Headers $headers -ContentType "application/json" -Body $body
$payment
$PAYMENT_ID = $payment.id
```

## 4. Read the payment back

bash:

```bash
curl -s http://127.0.0.1:8000/payments/$PAYMENT_ID -H "X-API-Key: $RELAY_API_KEY"
```

PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/payments/$PAYMENT_ID -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }
```

The answer is the payment plus `events`, its timeline in order.

## 5. List its events

The events are the `events` array of the payment above. The worker moves payments on within a second or two, so what you see depends on when you look: the list may be short or already complete. Each has a `seq`, a `type` such as `payment.received`, `payment.routed` or `payment.captured`, the `processor`, a `reason` for failures and `occurred_at`. To print just the types, bash:

```bash
curl -s http://127.0.0.1:8000/payments/$PAYMENT_ID -H "X-API-Key: $RELAY_API_KEY" | grep -o '"type":"[^"]*"'
```

PowerShell:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/payments/$PAYMENT_ID -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }).events | Select-Object seq, type, processor, reason
```

## 6. See it reach a final state

The worker sends the payment to a simulated processor, so it reaches a final state (`captured`, `declined` or `failed`, with `"is_final":true`) within seconds. Poll until it does. bash:

```bash
for i in $(seq 1 30); do
  curl -s http://127.0.0.1:8000/payments/$PAYMENT_ID -H "X-API-Key: $RELAY_API_KEY" | grep -q '"is_final":true' && break
  sleep 1
done
curl -s http://127.0.0.1:8000/payments/$PAYMENT_ID -H "X-API-Key: $RELAY_API_KEY"
```

PowerShell:

```powershell
for ($i = 0; $i -lt 30; $i++) {
  $p = Invoke-RestMethod http://127.0.0.1:8000/payments/$PAYMENT_ID -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }
  if ($p.is_final) { break }
  Start-Sleep -Seconds 1
}
$p | Select-Object id, status, display_status, is_final, processor
```

Look at `status` and `display_status`. A failed payment that is retrying shows `Retrying` and is not final yet. Once a payment is final you can read its plain-language explanation:

```bash
curl -s http://127.0.0.1:8000/payments/$PAYMENT_ID/explanation -H "X-API-Key: $RELAY_API_KEY"
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/payments/$PAYMENT_ID/explanation -Headers @{ "X-API-Key" = $env:RELAY_API_KEY }
```

If a local Ollama model is reachable the text comes from the model (`"source":"model"`, and the first call can take several seconds); otherwise it comes from deterministic rules and is labelled `"source":"rules"`. Both are valid answers.

## 7. Stop

```bash
docker compose down -v
```

`-v` also deletes the data.

## Troubleshooting

- Compose complains that `RELAY_API_KEY` is not set: set it in the shell you run `docker compose` from.
- 401 `unauthorized`: the `X-API-Key` header is missing or differs from `RELAY_API_KEY`.
- 400 `idempotency_key_missing`: add the `Idempotency-Key` header to `POST /payments`.
- A port is busy: set `API_HOST_PORT` (api), `FRONTEND_HOST_PORT` (web UI) or `SIM_CONTROL_HOST_PORT` (simulator control) to a free port before `docker compose up`, and use the api port in the URLs.

## Clean-room run

2026-11-05: a developer with no knowledge of the project (a fresh agent that read only this page) cloned the repository and followed the bash steps exactly on Windows with Docker Desktop. Every step worked as written; the first successful call (`201 Created` on `POST /payments`) came 43 seconds after the clone. The Docker build cache was warm, so the first-build time was not measured. The gaps it found (the replay's status code and body, timing-dependent event lists, the model or rules explanation, other host ports) are fixed above. The PowerShell steps were then run as written in PowerShell 7 on the same machine; all worked, and the polling loop was changed to stop at the final state.

Next: webhooks. Continue with [webhooks.md](webhooks.md) to receive a signed message when a payment finishes, then read [authentication-and-idempotency.md](authentication-and-idempotency.md). To call the API from Python instead of curl, use the [Python SDK](sdk.md).
