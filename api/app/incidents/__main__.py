"""Entry point of the incidents container: `python -m app.incidents` (REL-34, ADR-0014).

It reads only DATABASE_URL and REDIS_URL (and the optional heartbeat path and metrics port), never the API key.
"""

import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from types import FrameType

import sqlalchemy as sa
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.logging import configure_logging
from app.incidents.consumer import IncidentConsumer
from app.metrics import start_metrics_server_from_env

HEARTBEAT_PATH = "/tmp/incidents-heartbeat"  # noqa: S108 - container-local file, read by the health check
STARTUP_ATTEMPTS = 10


def main() -> int:
    configure_logging(None)
    log = logging.getLogger("relay.incidents")
    heartbeat = os.environ.get("INCIDENTS_HEARTBEAT_PATH", HEARTBEAT_PATH)
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=10, socket_connect_timeout=5)
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    consumer = IncidentConsumer(
        sessionmaker(engine, expire_on_commit=False), client, f"{socket.gethostname()}-{os.getpid()}"
    )
    try:
        for attempt in range(1, STARTUP_ATTEMPTS + 1):
            try:
                with engine.connect() as connection:
                    connection.execute(sa.text("SELECT 1"))
                consumer.ensure_group()
                break
            except Exception:
                log.warning("dependencies not reachable yet", extra={"attempt": attempt})
                if attempt == STARTUP_ATTEMPTS:
                    log.exception("giving up: database or stream unreachable at startup")
                    return 1
                time.sleep(2)
        start_metrics_server_from_env()
        Path(heartbeat).touch()
        log.info("incidents started", extra={"consumer": consumer.name})
        consumer.run(stop, heartbeat)
    except Exception:
        log.exception("incidents stopped by an unrecoverable error")
        return 1
    finally:
        client.close()
        engine.dispose()
    log.info("incidents stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
