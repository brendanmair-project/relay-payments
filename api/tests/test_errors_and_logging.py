"""REL-52: one error shape, correlation IDs from request to logs and context, the request log, startup resources."""

import io
import json
import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request
from pydantic import BaseModel

from app.config import get_settings
from app.core.correlation import bind_correlation_id, get_correlation_id
from app.core.logging import JsonFormatter, configure_logging
from app.errors import ApiError
from app.main import app


class Body(BaseModel):
    amount_minor: int


# Test-only routes, hidden from the OpenAPI document.
@app.get("/_t/error/{status}/{code}", include_in_schema=False)
def _raise_api_error(status: int, code: str) -> None:
    raise ApiError(status, code, "boom " + code)


@app.get("/_t/crash", include_in_schema=False)
def _crash() -> None:
    raise RuntimeError("secret internal detail")


@app.get("/_t/items/{item_id}", include_in_schema=False)
def _item(item_id: str, request: Request) -> dict[str, str | None]:
    logging.getLogger("relay.test").info("inside handler")
    return {"item_id": item_id, "context": get_correlation_id()}


@app.get("/_t/limit", include_in_schema=False)
def _limit(limit: int) -> dict[str, int]:
    return {"limit": limit}


@app.post("/_t/body", include_in_schema=False)
def _body(body: Body) -> dict[str, int]:
    return {"amount_minor": body.amount_minor}


def key() -> dict[str, str]:
    return {"X-API-Key": get_settings().relay_api_key}


def request_log_lines() -> list[dict]:
    path = Path(get_settings().request_log_path)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# --- error shape -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "idempotency_key_missing"),
        (400, "malformed_request"),
        (409, "idempotency_key_reused"),
        (409, "idempotency_request_in_progress"),
        (409, "payment_not_final"),
        (503, "dependency_unavailable"),
    ],
)
def test_api_error_uses_the_shared_shape(client, status, code):
    response = client.get(f"/_t/error/{status}/{code}", headers=key())
    assert response.status_code == status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "correlation_id"}
    assert error["code"] == code
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]


def test_401_shape(client):
    response = client.get("/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_404_unknown_path_is_not_found(client):
    response = client.get("/nope", headers=key())
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]


def test_422_has_details_with_field_and_issue(client):
    response = client.get("/_t/limit?limit=abc", headers=key())
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"][0]["field"] == "limit"
    assert error["details"][0]["issue"]
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]


def test_422_missing_body_field(client):
    response = client.post("/_t/body", json={}, headers=key())
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "amount_minor"


def test_invalid_json_body_is_400_malformed_request(client):
    response = client.post("/_t/body", content=b"{not json", headers={**key(), "Content-Type": "application/json"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "malformed_request"
    assert "details" not in error


def test_500_hides_internals_and_keeps_correlation_id(client):
    response = client.get("/_t/crash", headers={**key(), "X-Correlation-ID": "crash-1"})
    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "crash-1"
    error = response.json()["error"]
    assert error == {"code": "internal_error", "message": "internal error", "correlation_id": "crash-1"}
    assert "secret" not in response.text


def test_details_only_for_422(client):
    assert "details" not in client.get("/nope", headers=key()).json()["error"]


def test_openapi_declares_the_error_responses(client):
    spec = client.get("/openapi.json", headers=key()).json()
    operation = spec["paths"]["/health"]["get"]
    # REL-40: each operation lists only the errors it can return; /health: the key, a failure, a dependency
    assert {s for s in operation["responses"] if int(s) >= 400} == {"401", "500", "503"}
    for status in ("401", "500", "503"):
        ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorResponse")
    props = spec["components"]["schemas"]["ErrorBody"]["properties"]
    assert set(props) == {"code", "message", "details", "correlation_id"}


# --- correlation ID --------------------------------------------------------------------------------------------


def test_valid_correlation_id_is_echoed_and_in_context(client):
    response = client.get("/_t/items/7", headers={**key(), "X-Correlation-ID": "abc_123-X"})
    assert response.headers["X-Correlation-ID"] == "abc_123-X"
    assert response.json()["context"] == "abc_123-X"


def test_missing_correlation_id_is_generated(client):
    response = client.get("/_t/items/7", headers=key())
    cid = response.headers["X-Correlation-ID"]
    assert len(cid) >= 32
    assert response.json()["context"] == cid


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "semi;colon", "ünï"])
def test_invalid_correlation_id_is_replaced_not_rejected(client, bad):
    response = client.get("/_t/items/7", headers={**key(), "X-Correlation-ID": bad.encode("utf-8")})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != bad


def test_64_character_correlation_id_is_accepted(client):
    cid = "a" * 64
    assert client.get("/_t/items/7", headers={**key(), "X-Correlation-ID": cid}).headers["X-Correlation-ID"] == cid


def test_correlation_id_reaches_json_logs(client):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("relay.test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        client.get("/_t/items/7", headers={**key(), "X-Correlation-ID": "log-cid"})
    finally:
        logger.removeHandler(handler)
    record = json.loads(stream.getvalue().strip())
    assert record["message"] == "inside handler"
    assert record["correlation_id"] == "log-cid"
    assert record["level"] == "INFO"
    assert record["time"].endswith("Z")


def test_bind_correlation_id_scopes_the_context_for_workers():
    assert get_correlation_id() is None
    with bind_correlation_id("worker-1"):
        assert get_correlation_id() == "worker-1"
    assert get_correlation_id() is None


def test_formatter_includes_bound_id_outside_requests():
    record = logging.LogRecord("relay.worker", logging.INFO, __file__, 1, "published", None, None)
    with bind_correlation_id("evt-9"):
        assert json.loads(JsonFormatter().format(record))["correlation_id"] == "evt-9"


# --- request log -----------------------------------------------------------------------------------------------


def test_one_request_log_line_per_request(client):
    before = len(request_log_lines())
    client.get("/_t/items/42", headers={**key(), "X-Correlation-ID": "req-log-1"})
    lines = request_log_lines()
    assert len(lines) == before + 1
    line = lines[-1]
    assert set(line) == {"time", "method", "path", "status", "duration_ms", "correlation_id"}
    assert line["method"] == "GET"
    assert line["path"] == "/_t/items/{item_id}"  # the template, not the raw path
    assert line["status"] == 200
    assert line["correlation_id"] == "req-log-1"
    assert isinstance(line["duration_ms"], int | float)
    assert line["time"].endswith("Z")


def test_request_log_covers_errors(client):
    client.get("/health")
    client.get("/_t/crash", headers=key())
    unauthorized, crashed = request_log_lines()[-2:]
    assert (unauthorized["status"], crashed["status"]) == (401, 500)
    assert crashed["path"] == "/_t/crash"


def test_unmatched_path_is_logged_without_the_raw_path(client):
    client.get("/secret/abc123", headers=key())
    line = request_log_lines()[-1]
    assert line["status"] == 404
    assert "abc123" not in json.dumps(line)


def test_request_log_goes_to_stdout_and_a_size_capped_file(client):
    handlers = logging.getLogger("relay.requests").handlers
    rotating = [h for h in handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == 10 * 1024 * 1024
    assert rotating[0].backupCount == 2  # the live file plus two backups: 3 files of 10 MB
    streams = [h for h in handlers if type(h) is logging.StreamHandler]
    assert len(streams) == 1


@pytest.fixture
def restore_logging() -> Iterator[None]:
    yield
    configure_logging(get_settings().request_log_path)


def test_file_rotates_at_the_cap(tmp_path, restore_logging):
    path = tmp_path / "log" / "api-requests.jsonl"
    configure_logging(str(path), max_bytes=300, backup_count=2)
    logger = logging.getLogger("relay.requests")
    for i in range(40):
        logger.info(json.dumps({"n": i, "pad": "x" * 40}))
    names = sorted(p.name for p in path.parent.iterdir())
    assert names == ["api-requests.jsonl", "api-requests.jsonl.1", "api-requests.jsonl.2"]
    assert all(p.stat().st_size <= 300 for p in path.parent.iterdir())


def test_configure_logging_is_idempotent(restore_logging):
    configure_logging(get_settings().request_log_path)
    configure_logging(get_settings().request_log_path)
    assert len(logging.getLogger("relay.requests").handlers) == 2


# --- startup resources -----------------------------------------------------------------------------------------


def test_engine_and_redis_client_are_created_once_and_reused(client):
    engine, redis = app.state.engine, app.state.redis
    for _ in range(3):
        assert client.get("/health", headers=key()).status_code == 200
    assert app.state.engine is engine
    assert app.state.redis is redis


def test_health_reports_unavailable_when_the_redis_client_fails(client, monkeypatch):
    def fail() -> bool:
        raise ConnectionError

    monkeypatch.setattr(app.state.redis, "ping", fail)
    response = client.get("/health", headers=key())
    assert response.status_code == 503
    assert "redis" in response.json()["error"]["message"]
