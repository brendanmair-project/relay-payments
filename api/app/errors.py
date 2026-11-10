"""The shared error shape from docs/architecture/api-contract.md: one body for every 4xx and 5xx response (REL-52)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core.correlation import get_correlation_id, resolve_correlation_id

logger = logging.getLogger("relay.errors")


class ErrorDetail(BaseModel):
    field: str
    issue: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None  # present only for 422
    correlation_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# Declared on the app so every operation lists the same error responses in the OpenAPI document.
ERROR_STATUSES = (400, 401, 404, 409, 422, 500, 503)
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": "Error"} for status in ERROR_STATUSES
}


class ApiError(Exception):
    """Raise from an endpoint to return the shared error body, for example ApiError(409, "payment_not_final", ...)."""

    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    cid = getattr(request.state, "correlation_id", None) or get_correlation_id()
    if cid is None:
        cid = resolve_correlation_id(request.headers.get("X-Correlation-ID"))
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    error["correlation_id"] = cid
    return JSONResponse(
        status_code=status, content={"error": error}, headers={**(headers or {}), "X-Correlation-ID": cid}
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(request, exc.status, exc.code, exc.message, headers=exc.headers)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    codes = {401: "unauthorized", 404: "not_found"}
    code = codes.get(exc.status_code, "malformed_request")
    message = "not found" if exc.status_code == 404 else str(exc.detail)
    return error_response(request, exc.status_code, code, message, headers=dict(exc.headers or {}))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    if any(e["type"] == "json_invalid" for e in errors):
        return error_response(request, 400, "malformed_request", "request body is not valid JSON")
    details = [
        {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "issue": e["type"]} for e in errors
    ]
    return error_response(request, 422, "validation_failed", "request validation failed", details=details)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled exception", exc_info=exc)
    return error_response(request, 500, "internal_error", "internal error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected)
