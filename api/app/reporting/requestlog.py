"""API 5xx rate from the api's structured request log lines (REL-52, docs/architecture/data-model.md "Retention")."""

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def parse_time(value: str) -> datetime:
    """ISO 8601 time; a time without an offset is read as UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_request_log(path: str) -> Iterator[str] | None:
    """Lines of the live request log and its rotated backups (`.2` oldest), or None when there is no live file."""
    live = Path(path)
    if not live.is_file():
        return None

    def lines() -> Iterator[str]:
        for candidate in (Path(f"{path}.2"), Path(f"{path}.1"), live):
            if candidate.is_file():
                with candidate.open(encoding="utf-8", errors="replace") as handle:
                    yield from handle

    return lines()


def summarize_request_log(lines: Iterable[str], since: datetime | None, until: datetime | None) -> dict[str, Any]:
    """5xx / total over lines whose `time` is in [since, until); unparseable lines are skipped and counted."""
    total = server_errors = malformed = 0
    for raw in lines:
        try:
            entry = json.loads(raw)
            status = entry["status"]
            moment = parse_time(entry["time"])
            if not isinstance(status, int) or isinstance(status, bool):
                raise ValueError("status is not an integer")
        except (ValueError, KeyError, TypeError):
            malformed += 1
            continue
        if (since is not None and moment < since) or (until is not None and moment >= until):
            continue
        total += 1
        server_errors += 500 <= status <= 599
    return {
        "available": True,
        "total": total,
        "server_errors": server_errors,
        "rate_5xx": round(server_errors / total, 4) if total else None,
        "malformed": malformed,
    }
