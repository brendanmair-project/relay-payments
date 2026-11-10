"""At-least-once publishing (REL-20): every committed event reaches the stream, a crash before the mark duplicates."""

import threading
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.events import insert_event
from app.db.models import PaymentEvent
from app.outbox import publisher
from app.outbox.publisher import STREAM, publish_batch, run_loop
from app.outbox.reader import fetch_unpublished
from app.services.transitions import create_payment


def _make_events(factory: sessionmaker[Session], count: int) -> list[int]:
    with factory.begin() as session:
        for index in range(count):
            create_payment(session, amount_minor=100 + index, currency="USD", reference=f"ref-{index}")
        return list(session.scalars(sa.select(PaymentEvent.id).order_by(PaymentEvent.id)))


def _published_ids(factory: sessionmaker[Session]) -> list[int]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(PaymentEvent.id).where(PaymentEvent.published_at.is_not(None)).order_by(PaymentEvent.id)
            )
        )


def _stream_event_ids(client: Redis) -> list[int]:
    return [int(fields["event_id"]) for _, fields in client.xrange(STREAM)]


def test_every_committed_event_is_published_in_id_order(factory: sessionmaker[Session], redis_client: Redis) -> None:
    ids = _make_events(factory, 5)
    assert publish_batch(factory, redis_client, batch_size=100) == 5
    assert _stream_event_ids(redis_client) == ids
    assert _published_ids(factory) == ids
    _, fields = redis_client.xrange(STREAM)[0]
    assert set(fields) == {"event_id", "payment_id", "seq", "attempt_no", "type", "correlation_id"}
    assert fields["type"] == "payment.received"
    assert fields["seq"] == "1"
    assert fields["correlation_id"] == "corr-test"


def test_batches_cover_everything_across_passes(factory: sessionmaker[Session], redis_client: Redis) -> None:
    ids = _make_events(factory, 5)
    assert publish_batch(factory, redis_client, batch_size=2) == 2
    assert publish_batch(factory, redis_client, batch_size=2) == 2
    assert publish_batch(factory, redis_client, batch_size=2) == 1
    assert _stream_event_ids(redis_client) == ids


def test_marked_events_are_not_resent(factory: sessionmaker[Session], redis_client: Redis) -> None:
    _make_events(factory, 3)
    assert publish_batch(factory, redis_client) == 3
    assert publish_batch(factory, redis_client) == 0
    assert redis_client.xlen(STREAM) == 3


def test_crash_after_xadd_before_mark_republishes_without_loss(
    factory: sessionmaker[Session], redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _make_events(factory, 3)

    def crash(session: Session, event_ids: object) -> int:
        raise RuntimeError("publisher died before the mark was stored")

    monkeypatch.setattr(publisher, "mark_published", crash)
    with pytest.raises(RuntimeError):
        publish_batch(factory, redis_client)
    assert _stream_event_ids(redis_client) == ids  # already on the stream
    assert _published_ids(factory) == []  # but not marked, because the transaction rolled back

    monkeypatch.undo()  # the restarted publisher
    assert publish_batch(factory, redis_client) == 3
    assert _stream_event_ids(redis_client) == ids + ids  # duplicates allowed, nothing lost
    assert _published_ids(factory) == ids


def test_stream_is_trimmed_with_approximate_maxlen(factory: sessionmaker[Session], redis_client: Redis) -> None:
    with factory.begin() as session:
        payment_id = create_payment(session, amount_minor=100, currency="USD", reference="trim")
        for seq in range(2, 301):
            insert_event(
                session, payment_id=payment_id, seq=seq, attempt_no=0, type="payment.received", correlation_id="c"
            )
    assert publish_batch(factory, redis_client, batch_size=500, maxlen=10) == 300
    length = redis_client.xlen(STREAM)
    assert 10 <= length < 300  # approximate trimming removes whole nodes only
    assert _stream_event_ids(redis_client)[-1] == 300


def test_recovery_does_not_depend_on_old_stream_entries(factory: sessionmaker[Session], redis_client: Redis) -> None:
    _make_events(factory, 2)
    redis_client.delete(STREAM)  # the stream was lost or trimmed away; the database still knows what is unpublished
    assert publish_batch(factory, redis_client) == 2
    assert redis_client.xlen(STREAM) == 2


def test_concurrent_publishers_skip_rows_locked_by_each_other(
    factory: sessionmaker[Session], redis_client: Redis
) -> None:
    ids = _make_events(factory, 6)
    with factory() as holder:  # another publisher mid-batch: it has locked the first three rows
        locked = fetch_unpublished(holder, 3)
        assert [event.id for event in locked] == ids[:3]
        assert publish_batch(factory, redis_client, batch_size=3) == 3
        assert _stream_event_ids(redis_client) == ids[3:]
        holder.rollback()
    assert publish_batch(factory, redis_client, batch_size=10) == 3
    assert sorted(_stream_event_ids(redis_client)) == ids


def test_run_loop_publishes_and_writes_the_heartbeat(
    factory: sessionmaker[Session], redis_client: Redis, tmp_path: Path
) -> None:
    ids = _make_events(factory, 3)
    heartbeat = tmp_path / "heartbeat"
    stop = threading.Event()
    thread = threading.Thread(
        target=run_loop, args=(stop, factory, redis_client), kwargs={"heartbeat_path": heartbeat, "poll_interval": 0.05}
    )
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (heartbeat.exists() and _published_ids(factory) == ids):
            time.sleep(0.05)
        assert heartbeat.exists()
        assert _published_ids(factory) == ids
        first = heartbeat.stat().st_mtime_ns
        time.sleep(0.3)
        assert heartbeat.stat().st_mtime_ns > first  # refreshed while idle
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_stop_set_before_a_pass_publishes_nothing_and_returns(
    factory: sessionmaker[Session], redis_client: Redis, tmp_path: Path
) -> None:
    _make_events(factory, 2)
    stop = threading.Event()
    stop.set()
    run_loop(stop, factory, redis_client, heartbeat_path=tmp_path / "heartbeat")
    assert _stream_event_ids(redis_client) == []
    assert _published_ids(factory) == []  # the rows stay unpublished for the next publisher


def test_stop_during_a_batch_finishes_it_then_the_loop_ends(
    factory: sessionmaker[Session], redis_client: Redis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _make_events(factory, 3)
    stop = threading.Event()
    real = publisher.publish_batch

    def stopping(*args: object, **kwargs: object) -> int:
        stop.set()  # SIGTERM arrives while the batch is in hand
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(publisher, "publish_batch", stopping)
    run_loop(stop, factory, redis_client, heartbeat_path=tmp_path / "heartbeat", batch_size=100)
    assert _published_ids(factory) == ids  # the batch in hand was completed and marked, never half-sent
    assert _stream_event_ids(redis_client) == ids
