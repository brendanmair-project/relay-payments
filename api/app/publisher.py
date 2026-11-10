"""Entry point of the publisher container: `python -m app.publisher` (docs/architecture/containers.md)."""

import logging
import os
import signal
import threading
from types import FrameType

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.logging import configure_logging
from app.metrics import start_metrics_server_from_env
from app.outbox.publisher import run_loop

DEFAULT_HEARTBEAT_PATH = "/tmp/publisher-heartbeat"  # noqa: S108 - container-local file, read by the health check


def main() -> None:
    configure_logging(None)
    log = logging.getLogger("relay.publisher")
    # Read here, not through app.config: the publisher needs only these values (STREAM_MAXLEN default per .env.example).
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
    start_metrics_server_from_env()
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        stop.set()  # the current batch finishes, then the loop exits

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    log.info("publisher started")
    try:
        run_loop(
            stop,
            sessionmaker(engine, expire_on_commit=False),
            client,
            heartbeat_path=os.environ.get("PUBLISHER_HEARTBEAT_PATH", DEFAULT_HEARTBEAT_PATH),
            maxlen=int(os.environ.get("STREAM_MAXLEN", "10000")),
        )
    finally:
        client.close()
        engine.dispose()
        log.info("publisher stopped")


if __name__ == "__main__":
    main()
