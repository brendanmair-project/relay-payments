"""Demo webhook sink (REL-39): a tiny app that records deliveries, verifies signatures and can fail on demand.

Run as the compose service `webhook-sink` under the profile `webhooks-demo` (see containers.md). It keeps everything in
memory, holds no key and no database, and is meant for the local demo only: the endpoints that configure it are not
authenticated, so it publishes a port on 127.0.0.1 only.

- `POST /hook`: the subscriber endpoint. Records the request and answers 200, or 503 while `fail_next` is above zero,
  or 401 when a secret is configured and the signature is invalid (a malformed or non-ASCII one included).
- `GET /received`: what was received, with `signature_valid` (true or false; null while no secret is configured).
- `POST /config`: `{"secret": "<the subscription secret>", "fail_next": N}`; either field may be given.
- `DELETE /received`: forget what was received.
"""

import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.schemas import iso_utc
from app.webhooks.signing import verify

TOLERANCE_SECONDS = 300
MAX_KEPT = 500


class SinkConfig(BaseModel):
    secret: str | None = None
    fail_next: int | None = Field(default=None, ge=0, le=1000)


def create_app(secret: str | None = None) -> FastAPI:
    state: dict[str, Any] = {"secret": secret, "fail_next": 0, "items": []}
    app = FastAPI(title="Relay webhook sink")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/hook")
    async def hook(request: Request) -> Response:
        body = await request.body()
        failing = state["fail_next"] > 0
        if failing:
            state["fail_next"] -= 1
        try:
            parsed: Any = json.loads(body)
        except ValueError:
            parsed = body.decode(errors="replace")
        signature = request.headers.get("Relay-Signature", "")
        valid = None if state["secret"] is None else verify(state["secret"], signature, body, TOLERANCE_SECONDS)
        status = 503 if failing else 401 if valid is False else 200
        state["items"].append(
            {
                "received_at": iso_utc(datetime.now(UTC)),
                "event_id": request.headers.get("Relay-Event-Id"),
                "signature_valid": valid,
                "status": status,
                "body": parsed,
            }
        )
        del state["items"][:-MAX_KEPT]
        return JSONResponse({"received": True}, status_code=status)

    @app.get("/received")
    def received() -> dict[str, Any]:
        return {
            "items": list(state["items"]),
            "fail_next": state["fail_next"],
            "secret_set": state["secret"] is not None,
        }

    @app.post("/config")
    def configure(config: SinkConfig) -> dict[str, Any]:
        if "secret" in config.model_fields_set:
            state["secret"] = config.secret
        if "fail_next" in config.model_fields_set and config.fail_next is not None:
            state["fail_next"] = config.fail_next
        return {"secret_set": state["secret"] is not None, "fail_next": state["fail_next"]}

    @app.delete("/received")
    def clear() -> dict[str, int]:
        state["items"].clear()
        return {"cleared": 1}

    return app


app = create_app(os.environ.get("WEBHOOK_SINK_SECRET") or None)
