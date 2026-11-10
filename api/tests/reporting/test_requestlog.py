"""REL-51: the API 5xx rate from the structured request log lines (REL-52 format)."""

import json
from datetime import UTC, datetime

from app.reporting.requestlog import summarize_request_log


def line(status: int, time: str = "2026-10-27T10:00:05.000Z") -> str:
    return json.dumps(
        {
            "time": time,
            "method": "GET",
            "path": "/payments",
            "status": status,
            "duration_ms": 3.2,
            "correlation_id": "c",
        }
    )


def test_five_xx_rate_over_all_lines() -> None:
    lines = [line(200), line(201), line(404), line(500), line(503), line(200), line(499), line(200)]
    assert summarize_request_log(lines, None, None) == {
        "available": True,
        "total": 8,
        "server_errors": 2,
        "rate_5xx": 0.25,
        "malformed": 0,
    }


def test_malformed_lines_are_ignored_and_counted() -> None:
    lines = [
        line(500),
        "not json",
        "[1, 2]",
        json.dumps({"time": "2026-10-27T10:00:00Z"}),
        '{"status": "x"}',
        "",
        line(200),
    ]
    result = summarize_request_log(lines, None, None)
    assert (result["total"], result["server_errors"], result["rate_5xx"], result["malformed"]) == (2, 1, 0.5, 5)


def test_window_filters_by_line_time() -> None:
    lines = [
        line(500, "2026-10-27T09:59:59.999Z"),
        line(500, "2026-10-27T10:00:00.000Z"),
        line(200, "2026-10-27T10:30:00.000Z"),
        line(200, "2026-10-27T11:00:00.000Z"),
    ]
    since = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
    until = datetime(2026, 10, 27, 11, 0, tzinfo=UTC)
    result = summarize_request_log(lines, since, until)
    # since is inclusive, until exclusive.
    assert (result["total"], result["server_errors"], result["rate_5xx"]) == (2, 1, 0.5)


def test_no_lines_gives_no_rate() -> None:
    assert summarize_request_log([], None, None) == {
        "available": True,
        "total": 0,
        "server_errors": 0,
        "rate_5xx": None,
        "malformed": 0,
    }
