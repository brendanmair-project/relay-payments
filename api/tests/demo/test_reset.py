"""REL-30.8/30.9: the demo reset empties every table (TRUNCATE ... RESTART IDENTITY CASCADE), the stream and the log."""

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.demo.reset import application_tables, reset_all
from app.domain.reasons import EventType
from app.explainer.consumer import GROUP as EXPLAIN_GROUP
from app.services.transitions import append_event, create_payment
from app.worker.consumer import GROUP as PROCESS_GROUP
from app.worker.consumer import STREAM

Factory = sessionmaker[Session]


def populate(factory: Factory) -> uuid.UUID:
    """One row in every application table."""
    with factory.begin() as session:
        pid = create_payment(session, amount_minor=1250, currency="USD", reference="reset-1")
        append_event(session, pid, EventType.PAYMENT_EXPLAINED, data={"source": "rules"})
        session.execute(
            sa.text(
                "INSERT INTO idempotency_keys (key, request_hash, state, lease_token, lease_expires_at, payment_id, "
                "expires_at) VALUES ('reset-key', :h, 'in_progress', :t, now(), :pid, now())"
            ),
            {"h": "0" * 64, "t": uuid.uuid4(), "pid": pid},
        )
        session.execute(
            sa.text(
                "INSERT INTO payment_explanations (payment_id, source, text, cited_event_seqs, trigger, "
                "final_event_at, generated_at) VALUES (:pid, 'rules', 'x', '{}', 'final_failure', now(), now())"
            ),
            {"pid": pid},
        )
        session.execute(
            sa.text(
                "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
                " VALUES (:i, 'A', 'rule', 'detected', 't', now())"
            ),
            {"i": uuid.uuid4()},
        )
        session.execute(sa.text("INSERT INTO incident_detector_state (processor, last_event_id) VALUES ('A', 5)"))
        incident = session.scalar(sa.text("SELECT id FROM incidents LIMIT 1"))
        session.execute(
            sa.text("INSERT INTO incident_payments (incident_id, payment_id, first_event_id) VALUES (:i, :p, 1)"),
            {"i": incident, "p": pid},
        )
        session.execute(
            sa.text(
                "INSERT INTO incident_summaries"
                " (incident_id, source, text, cited_event_ids, cause, trigger, generated_at)"
                " VALUES (:i, 'rules', 'x', '{}', 'mixed', 'on_request', now())"
            ),
            {"i": incident},
        )
        subscription = uuid.uuid4()
        session.execute(
            sa.text(
                "INSERT INTO webhook_subscriptions (id, url, event_types, secret)"
                " VALUES (:i, 'http://localhost/x', '{payment.final}', 'reset-test')"
            ),
            {"i": subscription},
        )
        session.execute(
            sa.text(
                "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type) VALUES (:i, 1, 'payment.final')"
            ),
            {"i": subscription},
        )
        session.execute(sa.text("INSERT INTO webhook_consumer_state (id, last_event_id) VALUES (1, 1)"))
        session.execute(
            sa.text(
                "INSERT INTO webhook_delivery_attempts (delivery_id, attempt, status_code, duration_ms)"
                " SELECT id, 1, 200, 5 FROM webhook_deliveries"
            )
        )
    return pid


def counts(engine: Engine) -> dict[str, int]:
    """Row count of every table in the database, found independently of the code under test."""
    with engine.connect() as connection:
        names = connection.execute(
            sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
        ).scalars()
        return {
            name: connection.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar_one()  # noqa: S608
            for name in sorted(names)
        }


def test_every_application_table_is_found(engine: Engine) -> None:
    assert application_tables(engine) == {
        "payments",
        "payment_events",
        "idempotency_keys",
        "payment_explanations",
        "incidents",
        "incident_detector_state",
        "incident_payments",
        "incident_summaries",
        "webhook_subscriptions",
        "webhook_deliveries",
        "webhook_consumer_state",
        "webhook_delivery_attempts",
    }


def test_reset_empties_every_table_despite_the_append_only_trigger(
    engine: Engine, factory: Factory, redis_client: Redis, tmp_path: Path
) -> None:
    populate(factory)
    before = counts(engine)
    assert len(before) == 12 and all(n >= 1 for n in before.values()), before
    with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError):
        connection.execute(sa.text("DELETE FROM payment_events"))  # why the reset must TRUNCATE
    reset_all(engine, redis_client, str(tmp_path / "api-requests.jsonl"))
    assert counts(engine) == dict.fromkeys(before, 0)


def test_reset_restarts_identity_columns(engine: Engine, factory: Factory, redis_client: Redis, tmp_path: Path) -> None:
    populate(factory)
    reset_all(engine, redis_client, None)
    populate(factory)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT min(id) FROM payment_events")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT min(id) FROM payment_explanations")).scalar_one() == 1


def test_reset_deletes_the_stream_and_recreates_both_groups(
    engine: Engine, redis_client: Redis, tmp_path: Path
) -> None:
    redis_client.xadd(STREAM, {"payment_id": "x"})
    redis_client.xgroup_create(STREAM, PROCESS_GROUP, id="0")
    assert redis_client.xlen(STREAM) == 1
    reset_all(engine, redis_client, None)
    assert redis_client.xlen(STREAM) == 0
    groups = {g["name"]: g for g in redis_client.xinfo_groups(STREAM)}
    assert set(groups) == {PROCESS_GROUP, EXPLAIN_GROUP}
    assert all(g["pending"] == 0 and g["consumers"] == 0 for g in groups.values())


def test_reset_truncates_the_request_log_and_its_rotated_files(
    engine: Engine, redis_client: Redis, tmp_path: Path
) -> None:
    log = tmp_path / "api-requests.jsonl"
    log.write_text('{"status": 200}\n', encoding="utf-8")
    rotated = tmp_path / "api-requests.jsonl.1"
    rotated.write_text('{"status": 500}\n', encoding="utf-8")
    reset_all(engine, redis_client, str(log))
    assert log.exists() and log.read_text(encoding="utf-8") == ""
    assert not rotated.exists()


def test_reset_tolerates_a_missing_request_log(engine: Engine, redis_client: Redis, tmp_path: Path) -> None:
    summary = reset_all(engine, redis_client, str(tmp_path / "absent.jsonl"))
    assert summary["request_log_truncated"] is False
