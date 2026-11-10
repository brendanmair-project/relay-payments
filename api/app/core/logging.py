"""Structured JSON logs. Every record carries the current correlation ID; the request log is a separate stream."""

import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, datetime
from typing import Any

from .correlation import get_correlation_id

APP_LOGGER = "relay"
REQUEST_LOGGER = "relay.requests"
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def utc_timestamp(epoch: float | None = None) -> str:
    moment = datetime.fromtimestamp(epoch, UTC) if epoch is not None else datetime.now(UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": utc_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED and k not in entry})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def _reset(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_logging(
    request_log_path: str | None, *, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 2
) -> None:
    """Install JSON logging on stdout; the request log also appends to a rotating file when a path is given.

    Safe to call again. The file keeps 3 files of 10 MB (the live file plus two backups). Other processes (worker,
    publisher) call it with None to log JSON to stdout only.
    """
    app_logger = logging.getLogger(APP_LOGGER)
    _reset(app_logger)
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter())
    app_logger.addHandler(stdout)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    # Request lines are already JSON, so these handlers write the message as is.
    request_logger = logging.getLogger(REQUEST_LOGGER)
    _reset(request_logger)
    plain = logging.Formatter("%(message)s")
    line_stdout = logging.StreamHandler(sys.stdout)
    line_stdout.setFormatter(plain)
    request_logger.addHandler(line_stdout)
    if request_log_path:
        os.makedirs(os.path.dirname(request_log_path) or ".", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            request_log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(plain)
        request_logger.addHandler(file_handler)
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False


def log_request(*, method: str, path: str, status: int, duration_ms: float, correlation_id: str) -> None:
    line = {
        "time": utc_timestamp(),
        "method": method,
        "path": path,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "correlation_id": correlation_id,
    }
    logging.getLogger(REQUEST_LOGGER).info(json.dumps(line))
