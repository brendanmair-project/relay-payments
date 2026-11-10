"""Entry point of the webhooks container: `python -m app.webhooks` (REL-39, ADR-0015).

It reads DATABASE_URL, REDIS_URL, the WEBHOOK_* settings and the optional heartbeat path and metrics port, never the
API key.
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

import httpx
import sqlalchemy as sa
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.logging import configure_logging
from app.metrics import start_metrics_server_from_env
from app.webhooks.config import get_webhook_settings
from app.webhooks.consumer import WebhookConsumer
from app.webhooks.sender import Sender

HEARTBEAT_PATH = "/tmp/webhooks-heartbeat"  # noqa: S108 - container-local file, read by the health check
STARTUP_ATTEMPTS = 10


def main() -> int:
    configure_logging(None)
    log = logging.getLogger("relay.webhooks")
    heartbeat = os.environ.get("WEBHOOKS_HEARTBEAT_PATH", HEARTBEAT_PATH)
    settings = get_webhook_settings()
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True, socket_timeout=10, socket_connect_timeout=5)
    http = httpx.Client(follow_redirects=False, timeout=settings.webhook_timeout_seconds)
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    factory = sessionmaker(engine, expire_on_commit=False)
    consumer = WebhookConsumer(factory, client, f"{socket.gethostname()}-{os.getpid()}")
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
        log.info("webhooks started", extra={"consumer": consumer.name})
        consumer.run(stop, heartbeat, Sender(factory, http, settings), settings)
    except Exception:
        log.exception("webhooks stopped by an unrecoverable error")
        return 1
    finally:
        http.close()
        client.close()
        engine.dispose()
    log.info("webhooks stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
