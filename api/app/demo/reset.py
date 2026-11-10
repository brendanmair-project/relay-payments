"""`python -m app.demo.reset`: the documented reset every demo run starts from (REL-30, ADR-0012).

It leaves the system as freshly migrated:

1. `TRUNCATE ... RESTART IDENTITY CASCADE` on every application table in one transaction. The append-only trigger on
   `payment_events` rejects DELETE, but not TRUNCATE (docs/architecture/data-model.md, "Retention").
2. Deletes the stream `relay:payment-events` and recreates the consumer groups `processing` (worker) and
   `explanations` (explainer) on a new empty stream, so no old trigger is replayed. The orchestrator also restarts the
   worker, publisher and explainer so they hold no state from the old stream.
3. Truncates the request log at `REQUEST_LOG_PATH` and deletes its rotated files (`.1`, `.2`), so the 5xx rate of a run
   covers that run only. The log stays open in the api process; it writes in append mode, so it continues at the start.

Resetting the simulator's outage switches and profiles is done through its control API by `scripts/outage_demo.py`.
Needs `DATABASE_URL` and `REDIS_URL`; run it inside the api image, for example
`docker compose exec -T api python -m app.demo.reset`.
"""

import os
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from redis import Redis
from sqlalchemy.engine import Engine

from app.db.models import Base
from app.explainer.consumer import GROUP as EXPLAIN_GROUP
from app.worker.consumer import GROUP as PROCESS_GROUP
from app.worker.consumer import STREAM

GROUPS = (PROCESS_GROUP, EXPLAIN_GROUP)
DEFAULT_REQUEST_LOG = "/var/log/relay/api-requests.jsonl"


def application_tables(engine: Engine | None = None) -> set[str]:
    """Every application table, from the models (the migration test keeps models and schema equal)."""
    return {table.name for table in Base.metadata.sorted_tables}


def truncate_tables(engine: Engine) -> list[str]:
    names = sorted(application_tables(engine))
    quoted = ", ".join(f'"{name}"' for name in names)
    with engine.begin() as connection:
        # Table names come from the models, never from input; TRUNCATE has no SQLAlchemy construct.
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        statement = sa.text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")  # noqa: S608
        connection.execute(statement)
    return names


def reset_stream(client: Redis) -> None:
    client.delete(STREAM)
    for group in GROUPS:
        client.xgroup_create(STREAM, group, id="0", mkstream=True)


def truncate_request_log(path: str | None) -> bool:
    """Empty the log and drop its rotated files; False when there is no log file."""
    if not path:
        return False
    log = Path(path)
    for rotated in log.parent.glob(log.name + ".*"):
        rotated.unlink()
    if not log.exists():
        return False
    log.write_text("", encoding="utf-8")
    return True


def reset_all(engine: Engine, client: Redis, request_log_path: str | None) -> dict[str, Any]:
    tables = truncate_tables(engine)
    reset_stream(client)
    return {
        "tables_truncated": tables,
        "stream": STREAM,
        "groups": list(GROUPS),
        "request_log_truncated": truncate_request_log(request_log_path),
    }


def main() -> int:
    engine = sa.create_engine(os.environ["DATABASE_URL"])
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        summary = reset_all(engine, client, os.environ.get("REQUEST_LOG_PATH", DEFAULT_REQUEST_LOG))
    finally:
        engine.dispose()
        client.close()
    print(
        f"reset: truncated {', '.join(summary['tables_truncated'])}; stream {STREAM} recreated with groups "
        f"{', '.join(GROUPS)}; request log {'truncated' if summary['request_log_truncated'] else 'not found'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
