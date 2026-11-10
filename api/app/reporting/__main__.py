"""`python -m app.reporting`: print the guardrail metrics for a run and optionally save them as JSON (REL-51)."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.reporting.report import Window, build_report, render_table
from app.reporting.requestlog import parse_time
from app.worker.sweeper import SweepConfig

DEFAULT_REQUEST_LOG = "/var/log/relay/api-requests.jsonl"


def _time(value: str) -> datetime:
    try:
        return parse_time(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 time: {value!r}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.reporting", description=__doc__)
    parser.add_argument("--since", type=_time, help="ISO time; payments created at or after it (default: no limit)")
    parser.add_argument("--until", type=_time, help="ISO time; payments created before it (default: no limit)")
    parser.add_argument("--reference-prefix", help="load-generator run selector, for example '<scenario>-<seed>-'")
    parser.add_argument("--json-out", help="write the report to this JSON file")
    parser.add_argument("--request-log", default=os.environ.get("REQUEST_LOG_PATH", DEFAULT_REQUEST_LOG))
    parser.add_argument("--as-of", type=_time, help="reference time for 'not final' (default: now)")
    parser.add_argument(
        "--stuck-after-seconds",
        type=float,
        help="default: the sweeper's timeout plus grace plus re-drive threshold (env PROCESSOR_TIMEOUT_SECONDS etc.)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.stuck_after_seconds is not None:
        stuck_after = timedelta(seconds=args.stuck_after_seconds)
    else:
        config = SweepConfig.from_env()
        stuck_after = config.timeout_after + config.redrive_after
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(engine) as session:
            report = build_report(
                session,
                Window(args.since, args.until, args.reference_prefix),
                as_of=args.as_of or datetime.now(UTC),
                stuck_after=stuck_after,
                request_log_path=args.request_log,
            )
    finally:
        engine.dispose()
    sys.stdout.write(render_table(report))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
