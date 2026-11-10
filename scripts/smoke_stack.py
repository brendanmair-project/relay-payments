"""Smoke test for the running Relay stack (REL-12; the payment flow was added in REL-21).

Run after `docker compose up -d --wait` from the repository root:

    python scripts/smoke_stack.py

Standard library only. Reads RELAY_API_KEY from the environment or `.env`.
Besides the health checks it creates a payment through the API and waits for it to reach a final state.
Exits 0 when every check passes, 1 otherwise, printing one line per check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Every default-profile service with a restart policy (migrate is a one-shot, checked below);
# api/tests/test_smoke_stack.py compares this tuple with docker-compose.yml.
HEALTHY_SERVICES = (
    "postgres",
    "redis",
    "api",
    "publisher",
    "worker",
    "explainer",
    "incidents",
    "webhooks",
    "simulator",
    "frontend",
)
PAYMENT_TIMEOUT_SECONDS = 60


def setting(name: str, default: str | None = None) -> str | None:
    """Environment first, then .env (the same file docker compose reads)."""
    value = os.environ.get(name)
    env_file = ROOT / ".env"
    if value is None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name:
                value = raw.strip().strip('"').strip("'")
    return value if value else default


def api_key() -> str:
    key = setting("RELAY_API_KEY")
    if not key:
        sys.exit("FAIL RELAY_API_KEY is not set in the environment or .env")
    return key


API = "http://127.0.0.1:" + setting("API_HOST_PORT", "8000")
FRONTEND = "http://127.0.0.1:" + setting("FRONTEND_HOST_PORT", "3000")
SIM_CONTROL = "http://127.0.0.1:" + setting("SIM_CONTROL_HOST_PORT", "8101")


def get(url: str, key: str | None) -> tuple[int, str]:
    # Every URL here is an http://127.0.0.1 address built from the host ports above, never user input.
    request = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except OSError as error:
        return 0, str(error)


def compose_states() -> dict[str, dict]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--all", "--format", "json"],  # noqa: S607 - docker from PATH is intended
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    rows = (
        json.loads(lines[0]) if len(lines) == 1 and lines[0].startswith("[") else [json.loads(line) for line in lines]
    )
    return {row.get("Service"): row for row in rows}


def create_payment(key: str) -> tuple[int, dict]:
    """POST /payments with a fresh Idempotency-Key; returns (status, body)."""
    body = json.dumps({"amount_minor": 1999, "currency": "USD", "reference": "smoke-" + uuid.uuid4().hex[:12]})
    request = urllib.request.Request(  # noqa: S310 - http://127.0.0.1 address built from the host port above
        f"{API}/payments",
        data=body.encode("utf-8"),
        method="POST",
        headers={"X-API-Key": key, "Idempotency-Key": uuid.uuid4().hex, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (OSError, json.JSONDecodeError):
        return 0, {}


def wait_for_final(key: str, payment_id: str) -> dict:
    """Poll GET /payments/{id} until is_final is true or PAYMENT_TIMEOUT_SECONDS pass; returns the last body."""
    deadline = time.monotonic() + PAYMENT_TIMEOUT_SECONDS
    body: dict = {}
    while time.monotonic() < deadline:
        status, text = get(f"{API}/payments/{payment_id}", key)
        if status == 200:
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                body = {}
            if body.get("is_final") is True:
                return body
        time.sleep(1)
    return body


def main() -> int:
    key = api_key()
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))
        failures += 0 if ok else 1

    states = compose_states()
    for service in HEALTHY_SERVICES:
        row = states.get(service, {})
        check(f"{service} container healthy", row.get("Health") == "healthy", row.get("Status", "not running"))
    migrate = states.get("migrate", {})
    check(
        "migrate completed",
        migrate.get("State") == "exited" and migrate.get("ExitCode") == 0,
        migrate.get("Status", "not run"),
    )

    status, body = get(f"{API}/health", key)
    healthy = False
    if status == 200:
        try:
            data = json.loads(body)
            healthy = data.get("database") == "ok" and data.get("redis") == "ok"
        except json.JSONDecodeError:
            pass
    check("GET /health returns 200 with database and redis ok", healthy, f"status {status}: {body[:120]}")
    status, _ = get(f"{API}/health", None)
    check("GET /health without X-API-Key returns 401", status == 401, f"status {status}")
    status, _ = get(f"{SIM_CONTROL}/health", key)
    check("simulator control GET /health returns 200", status == 200, f"status {status}")
    status, _ = get(FRONTEND + "/", None)
    check("frontend GET / returns 200", status == 200, f"status {status}")
    status, body = create_payment(key)
    created = status == 201 and "id" in body
    check("POST /payments returns 201", created, f"status {status}")
    if created:
        final = wait_for_final(key, body["id"])
        check(
            f"payment reaches a final state within {PAYMENT_TIMEOUT_SECONDS} s",
            final.get("is_final") is True,
            f"status {final.get('status')}, attempt {final.get('attempt_no')}",
        )

    print("SMOKE_STACK=" + ("PASS" if failures == 0 else f"FAIL FAILURES={failures}"))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
