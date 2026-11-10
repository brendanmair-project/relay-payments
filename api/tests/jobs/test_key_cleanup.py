"""REL-47: key expiry (controllable clock) and the cleanup job (data-model.md "idempotency_keys", ADR-0008).

`now` is passed explicitly, so no test sleeps.
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.errors import ApiError
from app.idempotency.service import Claimed, claim, create_once, request_hash
from app.jobs.key_cleanup import cleanup_expired_keys
from app.worker.sweeper import SweepConfig, run_loop

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BODY_A = {"amount_minor": 100, "currency": "EUR", "description": None, "reference": "r-1"}
BODY_B = {**BODY_A, "amount_minor": 200}


def do_claim(engine: Engine, body: dict[str, Any], now: datetime, name: str = "k") -> Any:
    return claim(engine, name, request_hash(body), ttl_hours=24, lease_seconds=30, now=now)


def seed(engine: Engine, name: str, expires_at: datetime, *, lease_ends: datetime, state: str = "completed") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO idempotency_keys (key, request_hash, state, lease_token, lease_expires_at, expires_at,"
                " response_body) VALUES (:k, repeat('a', 64), :s, gen_random_uuid(), :lease, :exp,"
                " CASE WHEN :s = 'completed' THEN '{}'::jsonb END)"
            ),
            {"k": name, "s": state, "lease": lease_ends, "exp": expires_at},
        )


def names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {row.key for row in connection.execute(text("SELECT key FROM idempotency_keys"))}


@pytest.fixture
def sf(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def test_before_expiry_a_different_body_is_409_reused(engine: Engine) -> None:
    assert isinstance(do_claim(engine, BODY_A, T0), Claimed)
    with pytest.raises(ApiError) as caught:
        do_claim(engine, BODY_B, T0 + timedelta(hours=23, minutes=59))
    assert (caught.value.status, caught.value.code) == (409, "idempotency_key_reused")


def test_past_expiry_a_different_body_starts_again(engine: Engine) -> None:
    first = do_claim(engine, BODY_A, T0)
    second = do_claim(engine, BODY_B, T0 + timedelta(hours=24, seconds=1))
    assert isinstance(second, Claimed)
    assert second.token != first.token


def test_cleanup_deletes_only_expired_keys(engine: Engine, sf: sessionmaker[Session]) -> None:
    seed(engine, "old", T0 - timedelta(seconds=1), lease_ends=T0 - timedelta(hours=1))
    seed(engine, "edge", T0, lease_ends=T0 - timedelta(hours=1))  # expires_at == now is not yet expired
    seed(engine, "fresh", T0 + timedelta(hours=1), lease_ends=T0 - timedelta(hours=1))
    assert cleanup_expired_keys(sf, now=T0, batch_size=100) == 1
    assert names(engine) == {"edge", "fresh"}


def test_cleanup_keeps_an_expired_row_whose_lease_is_still_valid(engine: Engine, sf: sessionmaker[Session]) -> None:
    seed(engine, "live", T0 - timedelta(seconds=1), state="in_progress", lease_ends=T0 + timedelta(seconds=30))
    seed(engine, "dead", T0 - timedelta(seconds=1), state="in_progress", lease_ends=T0 - timedelta(seconds=1))
    assert cleanup_expired_keys(sf, now=T0, batch_size=100) == 1
    assert names(engine) == {"live"}


def test_cleanup_respects_the_batch_limit_oldest_first(engine: Engine, sf: sessionmaker[Session]) -> None:
    for i in range(5):
        seed(engine, f"k{i}", T0 - timedelta(hours=5 - i), lease_ends=T0 - timedelta(days=1))
    assert cleanup_expired_keys(sf, now=T0, batch_size=2) == 2
    assert names(engine) == {"k2", "k3", "k4"}
    assert cleanup_expired_keys(sf, now=T0, batch_size=2) == 2
    assert cleanup_expired_keys(sf, now=T0, batch_size=2) == 1
    assert names(engine) == set()


def test_cleanup_deletes_rows_of_the_table_never_payments(engine: Engine, sf: sessionmaker[Session]) -> None:
    first = do_claim(engine, BODY_A, T0)
    create_once(engine, "k", first.token, fields=BODY_A, correlation_id="c", render=lambda p: {"id": str(p.id)})
    with engine.begin() as connection:
        connection.execute(text("UPDATE idempotency_keys SET expires_at = :e"), {"e": T0 - timedelta(hours=1)})
    assert cleanup_expired_keys(sf, now=T0, batch_size=10) == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM payments")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM payment_events")).scalar_one() == 1


def test_concurrent_cleaners_delete_each_row_once(engine: Engine, sf: sessionmaker[Session]) -> None:
    for i in range(60):
        seed(engine, f"k{i}", T0 - timedelta(minutes=i + 1), lease_ends=T0 - timedelta(days=1))
    counts: list[int] = []
    barrier = threading.Barrier(3)

    def clean() -> None:
        barrier.wait()
        total = 0
        while (n := cleanup_expired_keys(sf, now=T0, batch_size=7)) > 0:
            total += n
        counts.append(total)

    threads = [threading.Thread(target=clean) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sum(counts) == 60
    assert names(engine) == set()


def test_the_sweeper_loop_runs_the_cleanup(engine: Engine, sf: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    seed(engine, "old", now - timedelta(hours=1), lease_ends=now - timedelta(days=1))
    seed(engine, "fresh", now + timedelta(hours=1), lease_ends=now - timedelta(days=1))
    config = SweepConfig(interval_seconds=0.05, key_cleanup_interval_seconds=0.05)
    stop = threading.Event()
    thread = threading.Thread(target=run_loop, args=(sf, config, stop))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "old" in names(engine):
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=10)
    assert names(engine) == {"fresh"}
