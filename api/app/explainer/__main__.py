"""Entry point of the explainer container: `python -m app.explainer` (REL-25.9, ADR-0012).

It starts and keeps running with no Ollama reachable: every explanation then comes from the rules with
`fallback_reason=model_unreachable`.
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

from app.config import get_settings
from app.core.logging import configure_logging
from app.explain.model import OllamaClient
from app.explainer.consumer import ExplainerConsumer

HEARTBEAT_PATH = "/tmp/explainer-heartbeat"  # noqa: S108 - container-local file, read by the health check
STARTUP_ATTEMPTS = 10


def main() -> int:
    configure_logging(None)
    log = logging.getLogger("relay.explainer")
    settings = get_settings()
    heartbeat = os.environ.get("EXPLAINER_HEARTBEAT_PATH", HEARTBEAT_PATH)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=10, socket_connect_timeout=5)
    model = OllamaClient(settings.ollama_url, settings.ollama_model, settings.explain_timeout_seconds)
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    consumer = ExplainerConsumer(
        sessionmaker(engine, expire_on_commit=False), client, model, f"{socket.gethostname()}-{os.getpid()}"
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
        Path(heartbeat).touch()
        log.info("explainer started", extra={"consumer": consumer.name, "model": settings.ollama_model})
        consumer.run(stop, heartbeat)
    except Exception:
        log.exception("explainer stopped by an unrecoverable error")
        return 1
    finally:
        client.close()
        engine.dispose()
    log.info("explainer stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
