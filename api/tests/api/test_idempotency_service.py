"""Unit tests for the idempotency claim, takeover and completion logic (data-model.md create flow)."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.errors import ApiError
from app.idempotency import service
from app.idempotency.service import Claimed, Replay, claim, create_once, request_hash

FIELDS: dict[str, Any] = {"amount_minor": 100, "currency": "EUR", "description": None, "reference": "r-1"}


def render(payment: Any) -> dict[str, Any]:
    return {"id": str(payment.id), "amount_minor": payment.amount_minor}


def do_claim(engine: Engine, **kwargs: Any) -> Claimed | Replay:
    return claim(engine, "k", request_hash(FIELDS), ttl_hours=24, lease_seconds=30, **kwargs)


def sql(engine: Engine, statement: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement))


def test_request_hash_is_sha256_of_canonical_json() -> None:
    canonical = b'{"amount_minor":100,"currency":"EUR","description":null,"reference":"r-1"}'
    expected = hashlib.sha256(canonical).hexdigest()
    assert request_hash(FIELDS) == expected
    assert request_hash(dict(reversed(FIELDS.items()))) == expected
    assert request_hash({**FIELDS, "reference": "r-2"}) != expected


def test_first_claim_inserts_in_progress(engine: Engine) -> None:
    result = do_claim(engine)
    assert isinstance(result, Claimed)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT state, lease_token::text AS token, request_hash FROM idempotency_keys")
        ).one()
    assert (row.state, row.token, row.request_hash) == ("in_progress", str(result.token), request_hash(FIELDS))


def test_live_lease_is_in_progress(engine: Engine) -> None:
    do_claim(engine)
    with pytest.raises(ApiError) as caught:
        do_claim(engine)
    assert (caught.value.status, caught.value.code) == (409, "idempotency_request_in_progress")
    assert caught.value.headers == {"Retry-After": "1"}


def test_other_hash_is_reused_whatever_the_state(engine: Engine) -> None:
    do_claim(engine)
    with pytest.raises(ApiError) as caught:
        claim(engine, "k", request_hash({**FIELDS, "amount_minor": 1}), ttl_hours=24, lease_seconds=30)
    assert caught.value.code == "idempotency_key_reused"


def test_completed_key_replays(engine: Engine) -> None:
    first = do_claim(engine)
    assert isinstance(first, Claimed)
    body = create_once(engine, "k", first.token, fields=FIELDS, correlation_id="c", render=render)
    assert do_claim(engine) == Replay(201, body)


def test_expired_lease_is_taken_over_with_a_new_token(engine: Engine) -> None:
    first = do_claim(engine)
    assert isinstance(first, Claimed)
    second = do_claim(engine, now=datetime.now(UTC) + timedelta(seconds=31))
    assert isinstance(second, Claimed)
    assert second.token != first.token


def test_takeover_of_a_completed_expired_key_clears_the_response(engine: Engine) -> None:
    first = do_claim(engine)
    assert isinstance(first, Claimed)
    create_once(engine, "k", first.token, fields=FIELDS, correlation_id="c", render=render)
    second = do_claim(engine, now=datetime.now(UTC) + timedelta(hours=25))
    assert isinstance(second, Claimed)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT state, payment_id, response_body FROM idempotency_keys")).one()
    assert tuple(row) == ("in_progress", None, None)


def test_lost_takeover_race_rereads_and_decides_again(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rival takes the key over between our read and our UPDATE: zero rows change, we re-read and see a live lease."""
    do_claim(engine)
    sql(engine, "UPDATE idempotency_keys SET lease_expires_at = now() - interval '1 second'")
    real_read = service._read
    reads: list[int] = []

    def read_then_rival_wins(conn: Any, key: str) -> Any:
        row = real_read(conn, key)
        reads.append(1)
        if len(reads) == 1:
            sql(
                engine,
                "UPDATE idempotency_keys SET lease_token = gen_random_uuid(),"
                " lease_expires_at = now() + interval '30 seconds'",
            )
        return row

    monkeypatch.setattr(service, "_read", read_then_rival_wins)
    with pytest.raises(ApiError) as caught:
        do_claim(engine)
    assert caught.value.code == "idempotency_request_in_progress"
    assert len(reads) == 2


def test_row_removed_after_the_conflict_is_claimed_again(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cleanup job (REL-47) deletes the row between the conflicting insert and the read: the insert is retried."""
    do_claim(engine)
    real_read = service._read
    calls: list[int] = []

    def delete_then_read(conn: Any, key: str) -> Any:
        calls.append(1)
        if len(calls) == 1:
            sql(engine, "DELETE FROM idempotency_keys")
        return real_read(conn, key)

    monkeypatch.setattr(service, "_read", delete_then_read)
    assert isinstance(do_claim(engine), Claimed)


def test_create_once_rolls_back_when_the_lease_is_lost(engine: Engine) -> None:
    first = do_claim(engine)
    assert isinstance(first, Claimed)
    sql(engine, "UPDATE idempotency_keys SET lease_token = gen_random_uuid()")
    with pytest.raises(ApiError) as caught:
        create_once(engine, "k", first.token, fields=FIELDS, correlation_id="c", render=render)
    assert caught.value.code == "idempotency_request_in_progress"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM payments")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM payment_events")).scalar_one() == 0
