"""Relay payments API: API-key check on every endpoint, shared error format, request log and GET /health."""

import hmac
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from redis import Redis
from sqlalchemy import create_engine, text

from .analytics.router import router as analytics_router
from .api.explanations import router as explanations_router
from .api.payments import router as payments_router
from .api.processors import router as processors_router
from .config import get_settings
from .core.correlation import bind_correlation_id, resolve_correlation_id
from .core.logging import configure_logging, log_request
from .errors import ERROR_RESPONSES, error_response, install_error_handlers
from .explain.model import OllamaClient
from .incidents.router import router as incidents_router
from .metrics import HTTP_DURATION, HTTP_REQUESTS, PAYMENTS_CREATED, start_metrics_server_from_env
from .openapi_schema import complete as complete_openapi
from .webhooks.router import router as webhooks_router

UNMATCHED_PATH = "<unmatched>"  # raw paths of unknown routes are unbounded and may hold ids, so they are not logged


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the engine and the Redis client once; /health reuses them."""
    settings = get_settings()
    configure_logging(settings.request_log_path)
    app.state.engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    app.state.redis = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
    app.state.model_client = OllamaClient(settings.ollama_url, settings.ollama_model, settings.explain_timeout_seconds)
    start_metrics_server_from_env()  # own port, inside the compose network only; never on the keyed API
    try:
        yield
    finally:
        app.state.engine.dispose()
        app.state.redis.close()


app = FastAPI(title="Relay", version="0.1.0", lifespan=lifespan, responses=ERROR_RESPONSES)
install_error_handlers(app)
app.include_router(payments_router)
app.include_router(explanations_router)
app.include_router(processors_router)
app.include_router(incidents_router)
app.include_router(analytics_router)
app.include_router(webhooks_router)

_generated_openapi = app.openapi


def openapi() -> dict[str, Any]:
    """FastAPI's document, completed once by `openapi_schema` (REL-40); later calls return the same object."""
    first = app.openapi_schema is None
    schema = _generated_openapi()
    if first:
        complete_openapi(schema)
    return schema


app.openapi = openapi  # type: ignore[method-assign]


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Correlation ID, API-key check (ADR-0009, constant-time compare), 500 mapping and the request log line."""
    cid = resolve_correlation_id(request.headers.get("X-Correlation-ID"))
    request.state.correlation_id = cid
    started = time.perf_counter()
    with bind_correlation_id(cid):
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied.encode(), get_settings().relay_api_key.encode()):
            response: Response = error_response(request, 401, "unauthorized", "missing or invalid X-API-Key")
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Starlette's outer handler would drop the correlation ID header, so the 500 is built here.
                logging.getLogger("relay.errors").exception("unhandled exception")
                response = error_response(request, 500, "internal_error", "internal error")
        response.headers["X-Correlation-ID"] = cid
        route = request.scope.get("route")
        path = getattr(route, "path", UNMATCHED_PATH)
        elapsed = time.perf_counter() - started
        log_request(
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=elapsed * 1000,
            correlation_id=cid,
        )
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_DURATION.labels(path).observe(elapsed)
        created = request.method == "POST" and path == "/payments" and response.status_code == 201
        if created and "Idempotent-Replayed" not in response.headers:
            PAYMENTS_CREATED.inc()
    return response


def _database_ok() -> bool:
    try:
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _redis_ok() -> bool:
    try:
        return bool(app.state.redis.ping())
    except Exception:
        return False


@app.get("/health")
def health(request: Request) -> JSONResponse:
    database, redis = _database_ok(), _redis_ok()
    if database and redis:
        return JSONResponse({"status": "ok", "database": "ok", "redis": "ok"})
    failing = [name for name, ok in (("database", database), ("redis", redis)) if not ok]
    return error_response(request, 503, "dependency_unavailable", "unavailable: " + ", ".join(failing))
