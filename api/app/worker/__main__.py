"""Entry point of the worker container: `python -m app.worker` (docs/architecture/containers.md)."""

import logging
import os
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

import sqlalchemy as sa
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.logging import configure_logging
from app.metrics import start_metrics_server_from_env
from app.worker.consumer import Consumer
from app.worker.processor import ProcessorClient
from app.worker.sweeper import SweepConfig
from app.worker.sweeper import run_loop as run_sweeper

DEFAULT_HEARTBEAT_PATH = "/tmp/worker-heartbeat"  # noqa: S108 - container-local file, read by the health check
STARTUP_ATTEMPTS = 10


@dataclass(frozen=True)
class Settings:
    """Read here, not through app.config: the worker needs only these values (defaults per .env.example)."""

    database_url: str
    redis_url: str
    simulator_url: str
    processor_timeout_seconds: float
    reclaim_idle_ms: int
    heartbeat_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            redis_url=os.environ["REDIS_URL"],
            simulator_url=os.environ.get("SIMULATOR_URL", "http://simulator:8100"),
            processor_timeout_seconds=float(os.environ.get("PROCESSOR_TIMEOUT_SECONDS", "5")),
            reclaim_idle_ms=int(os.environ.get("RECLAIM_IDLE_MS", "30000")),
            heartbeat_path=os.environ.get("WORKER_HEARTBEAT_PATH", DEFAULT_HEARTBEAT_PATH),
        )


def main() -> int:
    configure_logging(None)
    log = logging.getLogger("relay.worker")
    settings = Settings.from_env()
    start_metrics_server_from_env()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=10, socket_connect_timeout=5)
    processors = ProcessorClient(settings.simulator_url, settings.processor_timeout_seconds)
    stop = threading.Event()

    def request_stop(signum: int, _frame: FrameType | None) -> None:
        stop.set()  # the current entry finishes (or stays pending for reclaim), then the loop exits

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    factory = sessionmaker(engine, expire_on_commit=False)
    consumer = Consumer(
        factory,
        client,
        processors,
        f"{socket.gethostname()}-{os.getpid()}",
        reclaim_idle_ms=settings.reclaim_idle_ms,
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
        Path(settings.heartbeat_path).touch()
        log.info("worker started", extra={"consumer": consumer.name})
        sweep_config = SweepConfig.from_env()
        sweeper = threading.Thread(target=run_sweeper, args=(factory, sweep_config, stop), name="sweeper", daemon=True)
        sweeper.start()
        try:
            consumer.run(stop, settings.heartbeat_path)
        finally:
            stop.set()  # the consumer ended (signal or error): let the sweep loop finish its pass
            sweeper.join(timeout=10)
    except Exception:
        log.exception("worker stopped by an unrecoverable error")
        return 1
    finally:
        processors.close()
        client.close()
        engine.dispose()
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
