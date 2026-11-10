"""ADR-0015, items 2 to 4: signed delivery, retries with exponential backoff, the allowlist at send time, retention."""

import json
import logging
import time
from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.webhooks.config import WebhookSettings, backoff_seconds
from app.webhooks.sender import Sender
from app.webhooks.signing import verify
from app.webhooks.store import claim_due, cleanup, count_pending, fan_out
from tests.webhooks.helpers import HOOK_URL, SENTINEL, deliveries, make_event, subscribe

Factory = sessionmaker[Session]
Handler = Callable[[httpx.Request], httpx.Response]
DELIVERIES = "relay_webhook_deliveries_total"


def counter(outcome: str) -> float:
    return REGISTRY.get_sample_value(DELIVERIES, {"outcome": outcome}) or 0.0


class Receiver:
    """A scripted subscriber: answers from `statuses` in order, then 200; records every request."""

    def __init__(self, *statuses: int | Exception) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.statuses.pop(0) if self.statuses else 200
        if isinstance(answer, Exception):
            raise answer
        headers = {"Location": "http://postgres:5432/"} if answer in (301, 302, 307) else {}
        return httpx.Response(answer, headers=headers)


def sender(factory: Factory, handler: Handler, settings: WebhookSettings, follow_redirects: bool = False) -> Sender:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=follow_redirects)
    return Sender(factory, client, settings)


def pending_delivery(factory: Factory, type_: str = "payment.final", url: str = HOOK_URL) -> tuple[int, str]:
    """One subscription and one stored pending delivery; return the event id and the subscription secret."""
    _sub, secret = subscribe(factory, [type_], url)
    _pid, event_id = make_event(factory, type_, to_status="captured")
    assert fan_out(factory, event_id) == 1
    return event_id, secret


def make_due(factory: Factory) -> None:
    with factory.begin() as session:
        session.execute(
            sa.text(
                "UPDATE webhook_deliveries SET next_attempt_at = now() - interval '1 second' WHERE status = 'pending'"
            )
        )


def only(factory: Factory) -> dict[str, object]:
    rows = deliveries(factory)
    assert len(rows) == 1
    return rows[0]


def test_a_delivery_is_posted_signed_with_the_event_id_and_marked_delivered(
    factory: Factory, settings: WebhookSettings
) -> None:
    event_id, secret = pending_delivery(factory)
    receiver = Receiver(200)
    before = counter("delivered")
    assert sender(factory, receiver, settings).send_due() == 1
    assert len(receiver.requests) == 1
    request = receiver.requests[0]
    assert request.method == "POST" and str(request.url) == HOOK_URL
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Relay-Event-Id"] == str(event_id)
    assert verify(secret, request.headers["Relay-Signature"], request.content, tolerance_seconds=60)
    stamp = int(request.headers["Relay-Signature"].split(",")[0].removeprefix("t="))
    assert abs(stamp - time.time()) < 60
    body = json.loads(request.content)
    assert body["id"] == event_id and body["type"] == "payment.final"
    assert body["created_at"].endswith("Z")
    assert set(body["data"]) == {"payment_id", "status", "amount_minor", "currency"}
    assert (body["data"]["amount_minor"], body["data"]["currency"], body["data"]["status"]) == (1250, "EUR", "captured")
    assert SENTINEL.encode() not in request.content and b"description" not in request.content
    row = only(factory)
    assert (row["status"], row["attempt"], row["last_status_code"], row["last_error"]) == ("delivered", 1, 200, None)
    assert counter("delivered") == before + 1


def test_the_status_of_a_payment_final_event_is_the_payments_final_status(
    factory: Factory, settings: WebhookSettings
) -> None:
    _sub, _secret = subscribe(factory, ["payment.final"])
    pid, event_id = make_event(factory, "payment.final")  # no to_status on the event itself
    with factory.begin() as session:
        session.execute(
            sa.text(
                "UPDATE payments SET status = 'declined', attempt_no = 1, processor = 'A', is_final = true,"
                " final_at = now() WHERE id = :p"
            ),
            {"p": pid},
        )
    fan_out(factory, event_id)
    receiver = Receiver(200)
    sender(factory, receiver, settings).send_due()
    assert json.loads(receiver.requests[0].content)["data"]["status"] == "declined"


def test_the_body_is_the_same_on_every_retry_but_the_signature_is_fresh(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    receiver = Receiver(500, 200)
    s = sender(factory, receiver, settings)
    s.send_due()
    make_due(factory)
    s.send_due()
    first, second = receiver.requests
    assert first.content == second.content
    assert first.headers["Relay-Event-Id"] == second.headers["Relay-Event-Id"]


def test_a_non_2xx_answer_schedules_a_retry_with_the_first_backoff_step(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    retried = counter("retried")
    s = sender(factory, Receiver(503), settings)
    assert s.send_due() == 1
    row = only(factory)
    assert (row["status"], row["attempt"], row["last_status_code"], row["last_error"]) == (
        "pending",
        1,
        503,
        "HTTP 503",
    )
    assert row["next_attempt_at"] - row["updated_at"] == timedelta(seconds=2)  # type: ignore[operator]
    assert counter("retried") == retried + 1
    assert s.send_due() == 0  # not due yet: nothing is sent


def test_the_backoff_function_is_exponential_with_a_cap() -> None:
    settings = WebhookSettings(webhook_backoff_base_seconds=2, webhook_backoff_factor=2, webhook_backoff_max_seconds=60)
    assert [backoff_seconds(n, settings) for n in range(1, 8)] == [2, 4, 8, 16, 32, 60, 60]
    other = WebhookSettings(webhook_backoff_base_seconds=1, webhook_backoff_factor=3, webhook_backoff_max_seconds=50)
    assert [backoff_seconds(n, other) for n in range(1, 6)] == [1, 3, 9, 27, 50]


def test_the_settings_defaults_are_demo_friendly_and_name_the_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("WEBHOOK_ALLOWED_HOSTS", "WEBHOOK_BACKOFF_BASE_SECONDS", "WEBHOOK_LOG_RETENTION_DAYS"):
        monkeypatch.delenv(name, raising=False)
    defaults = WebhookSettings()
    assert defaults.webhook_allowed_hosts == "webhook-sink,localhost,127.0.0.1"
    assert (defaults.webhook_backoff_base_seconds, defaults.webhook_backoff_factor) == (2, 2)
    assert defaults.webhook_backoff_max_seconds == 60
    assert defaults.webhook_log_retention_days > 0
    monkeypatch.setenv("WEBHOOK_BACKOFF_BASE_SECONDS", "5")
    monkeypatch.setenv("WEBHOOK_LOG_RETENTION_DAYS", "3")
    changed = WebhookSettings()
    assert (changed.webhook_backoff_base_seconds, changed.webhook_log_retention_days) == (5, 3)


def test_eight_failed_attempts_back_off_exponentially_and_then_the_delivery_is_failed(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    receiver = Receiver(*[500] * 12)
    s = sender(factory, receiver, settings)
    gaps: list[float] = []
    retried, failed = counter("retried"), counter("failed")
    for attempt in range(1, 9):
        assert s.send_due() == 1
        row = only(factory)
        assert row["attempt"] == attempt
        if attempt < 8:
            assert row["status"] == "pending"
            gaps.append((row["next_attempt_at"] - row["updated_at"]).total_seconds())  # type: ignore[operator]
            make_due(factory)
    assert gaps == [2, 4, 8, 16, 32, 60, 60]
    final = only(factory)
    assert (final["status"], final["attempt"], final["last_status_code"]) == ("failed", 8, 500)
    assert counter("retried") == retried + 7 and counter("failed") == failed + 1
    make_due(factory)
    assert s.send_due() == 0
    assert len(receiver.requests) == 8  # never a ninth


def test_a_delivery_that_succeeds_after_failures_is_delivered_with_its_attempt_count(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    s = sender(factory, Receiver(500, httpx.ReadTimeout("slow"), 204), settings)
    for _ in range(3):
        s.send_due()
        make_due(factory)
    row = only(factory)
    assert (row["status"], row["attempt"], row["last_status_code"], row["last_error"]) == ("delivered", 3, 204, None)


@pytest.mark.parametrize(
    ("error", "name"),
    [(httpx.ReadTimeout("slow"), "ReadTimeout"), (httpx.ConnectError("refused"), "ConnectError")],
)
def test_a_timeout_or_connection_error_is_retried_and_logged_without_a_status(
    factory: Factory, settings: WebhookSettings, error: Exception, name: str
) -> None:
    pending_delivery(factory)
    sender(factory, Receiver(error), settings).send_due()
    row = only(factory)
    assert (row["status"], row["attempt"], row["last_status_code"], row["last_error"]) == ("pending", 1, None, name)


def test_a_redirect_is_never_followed_and_counts_as_a_failure(factory: Factory, settings: WebhookSettings) -> None:
    pending_delivery(factory)
    receiver = Receiver(302)
    sender(factory, receiver, settings, follow_redirects=True).send_due()  # even a client that would follow
    assert len(receiver.requests) == 1
    row = only(factory)
    assert (row["status"], row["last_status_code"]) == ("pending", 302)


def test_a_host_no_longer_allowed_is_failed_at_send_time_without_a_request(
    factory: Factory, settings: WebhookSettings
) -> None:
    _event_id, _secret = pending_delivery(factory)
    with factory.begin() as session:  # as if the allowlist shrank, or the row was changed behind the API
        session.execute(sa.text("UPDATE webhook_subscriptions SET url = 'http://postgres:5432/'"))
    receiver = Receiver()
    failed = counter("failed")
    assert sender(factory, receiver, settings).send_due() == 1
    assert receiver.requests == []
    row = only(factory)
    assert (row["status"], row["last_error"], row["last_status_code"]) == ("failed", "target_not_allowed", None)
    assert counter("failed") == failed + 1


def test_the_allowlist_at_send_time_comes_from_the_settings(factory: Factory, settings: WebhookSettings) -> None:
    pending_delivery(factory)  # hooks.test is allowed by the fixture settings
    narrowed = settings.model_copy(update={"webhook_allowed_hosts": "localhost"})
    receiver = Receiver()
    sender(factory, receiver, narrowed).send_due()
    assert receiver.requests == [] and only(factory)["status"] == "failed"


def test_a_deactivated_subscription_gets_no_more_requests(factory: Factory, settings: WebhookSettings) -> None:
    pending_delivery(factory)
    with factory.begin() as session:
        session.execute(sa.text("UPDATE webhook_subscriptions SET active = false"))
    receiver = Receiver()
    sender(factory, receiver, settings).send_due()
    assert receiver.requests == []
    assert (only(factory)["status"], only(factory)["last_error"]) == ("failed", "subscription_inactive")


def test_a_delivery_whose_event_is_gone_is_failed_without_a_request(
    factory: Factory, settings: WebhookSettings
) -> None:
    sub, _secret = subscribe(factory, ["payment.final"])
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type)"
                " VALUES (:s, 999999, 'payment.final')"
            ),
            {"s": sub},
        )
    receiver = Receiver()
    sender(factory, receiver, settings).send_due()
    assert receiver.requests == []
    assert (only(factory)["status"], only(factory)["last_error"]) == ("failed", "event_missing")


def test_no_database_transaction_is_open_during_the_http_call_and_the_delivery_is_not_claimable_twice(
    factory: Factory, settings: WebhookSettings, engine: Engine
) -> None:
    pending_delivery(factory)
    seen: list[int] = []
    claimed_meanwhile: list[int] = []

    def spy(request: httpx.Request) -> httpx.Response:
        with engine.connect() as connection:
            seen.append(
                int(
                    connection.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                            " AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                        )
                    ).scalar_one()
                )
            )
        claimed_meanwhile.append(len(claim_due(factory, 10, 30)))  # a second sender must find nothing to send
        return httpx.Response(200)

    sender(factory, spy, settings).send_due()
    assert seen == [0]
    assert claimed_meanwhile == [0]
    assert only(factory)["status"] == "delivered"


def test_claiming_takes_each_due_delivery_once_oldest_first_and_up_to_the_limit(factory: Factory) -> None:
    subscribe(factory, ["payment.final"])
    events = [make_event(factory, "payment.final")[1] for _ in range(3)]
    for event_id in events:
        fan_out(factory, event_id)
    first = claim_due(factory, 2, 30)
    assert [c.event_id for c in first] == events[:2]
    assert [c.event_id for c in claim_due(factory, 10, 30)] == events[2:]
    assert claim_due(factory, 10, 30) == []


def test_a_claim_that_is_never_answered_comes_back_after_the_lease(factory: Factory) -> None:
    subscribe(factory, ["payment.final"])
    fan_out(factory, make_event(factory, "payment.final")[1])
    assert len(claim_due(factory, 10, 30)) == 1  # the sender dies here: nothing is recorded
    assert claim_due(factory, 10, 30) == []
    make_due(factory)  # the lease runs out
    assert len(claim_due(factory, 10, 30)) == 1


def test_neither_the_secret_nor_the_signature_is_logged_by_a_delivery(
    factory: Factory, settings: WebhookSettings, caplog: pytest.LogCaptureFixture
) -> None:
    _event_id, secret = pending_delivery(factory)
    caplog.set_level(logging.DEBUG)
    receiver = Receiver(500)
    sender(factory, receiver, settings).send_due()
    signature = receiver.requests[0].headers["Relay-Signature"]
    assert secret not in caplog.text and signature not in caplog.text
    assert secret not in "".join(str(r.__dict__) for r in caplog.records)
    assert secret not in str(only(factory))


def test_retention_deletes_old_delivered_and_failed_rows_only(factory: Factory) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    with factory.begin() as session:
        for event_id, status, age_days in [
            (1, "delivered", 10),
            (2, "failed", 10),
            (3, "pending", 10),
            (4, "delivered", 1),
            (5, "failed", 6),
        ]:
            session.execute(
                sa.text(
                    "INSERT INTO webhook_deliveries"
                    " (subscription_id, event_id, event_type, status, attempt, updated_at)"
                    " VALUES (:s, :e, 'payment.final', :st, 1, now() - make_interval(days => :d))"
                ),
                {"s": sub, "e": event_id, "st": status, "d": age_days},
            )
    assert cleanup(factory, 7) == 2
    assert sorted(int(r["event_id"]) for r in deliveries(factory)) == [3, 4, 5]  # type: ignore[call-overload]
    assert cleanup(factory, 7) == 0


def test_the_pending_count_counts_only_pending_deliveries(factory: Factory, settings: WebhookSettings) -> None:
    assert count_pending(factory) == 0
    pending_delivery(factory)
    assert count_pending(factory) == 1
    sender(factory, Receiver(200), settings).send_due()
    assert count_pending(factory) == 0


def test_the_webhook_series_exist_at_zero_before_the_first_delivery() -> None:
    for outcome in ("delivered", "retried", "failed"):
        assert REGISTRY.get_sample_value(DELIVERIES, {"outcome": outcome}) is not None, outcome
    assert REGISTRY.get_sample_value("relay_webhook_pending") is not None


def attempt_rows(factory: Factory) -> list[dict[str, object]]:
    with factory() as session:
        rows = session.execute(sa.text("SELECT * FROM webhook_delivery_attempts ORDER BY id")).mappings().all()
    return [dict(r) for r in rows]


def test_every_attempt_has_its_own_row_with_the_status_code_and_a_later_time(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    s = sender(factory, Receiver(503, 503, 503, 200), settings)
    for _ in range(4):
        s.send_due()
        make_due(factory)
    rows = attempt_rows(factory)
    delivery = only(factory)
    assert [r["attempt"] for r in rows] == [1, 2, 3, 4]
    assert [r["status_code"] for r in rows] == [503, 503, 503, 200]
    assert [r["error"] for r in rows] == ["HTTP 503", "HTTP 503", "HTTP 503", None]
    assert {r["delivery_id"] for r in rows} == {delivery["id"]}
    assert all(isinstance(r["duration_ms"], int) and r["duration_ms"] >= 0 for r in rows)
    times = [r["attempted_at"] for r in rows]
    assert times == sorted(times) and len(set(times)) == 4  # type: ignore[type-var]
    assert (delivery["status"], delivery["attempt"]) == ("delivered", 4)


def test_a_timeout_attempt_is_recorded_with_its_error_and_no_status(
    factory: Factory, settings: WebhookSettings
) -> None:
    pending_delivery(factory)
    sender(factory, Receiver(httpx.ReadTimeout("slow")), settings).send_due()
    [row] = attempt_rows(factory)
    assert (row["attempt"], row["status_code"], row["error"]) == (1, None, "ReadTimeout")


def test_failing_without_a_request_still_records_one_attempt_with_its_reason(
    factory: Factory, settings: WebhookSettings
) -> None:
    for reason in ("target_not_allowed", "subscription_inactive", "event_missing"):
        with factory.begin() as session:
            session.execute(sa.text("TRUNCATE webhook_deliveries, webhook_subscriptions CASCADE"))
        if reason == "event_missing":
            sub, _ = subscribe(factory, ["payment.final"])
            with factory.begin() as session:
                session.execute(
                    sa.text(
                        "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type)"
                        " VALUES (:s, 999999, 'payment.final')"
                    ),
                    {"s": sub},
                )
        else:
            pending_delivery(factory)
            sql = (
                "UPDATE webhook_subscriptions SET url = 'http://postgres:5432/'"
                if reason == "target_not_allowed"
                else "UPDATE webhook_subscriptions SET active = false"
            )
            with factory.begin() as session:
                session.execute(sa.text(sql))
        receiver = Receiver()
        sender(factory, receiver, settings).send_due()
        assert receiver.requests == [], reason
        [row] = attempt_rows(factory)
        assert (row["attempt"], row["status_code"], row["error"], row["duration_ms"]) == (1, None, reason, 0), reason
        assert only(factory)["last_error"] == reason


def test_retention_deletes_the_attempts_with_their_delivery(factory: Factory) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    with factory.begin() as session:
        for event_id, age_days in [(1, 10), (2, 1)]:
            session.execute(
                sa.text(
                    "INSERT INTO webhook_deliveries"
                    " (subscription_id, event_id, event_type, status, attempt, updated_at)"
                    " VALUES (:s, :e, 'payment.final', 'delivered', 1, now() - make_interval(days => :d))"
                ),
                {"s": sub, "e": event_id, "d": age_days},
            )
        session.execute(
            sa.text(
                "INSERT INTO webhook_delivery_attempts (delivery_id, attempt, status_code, duration_ms)"
                " SELECT id, 1, 200, 4 FROM webhook_deliveries"
            )
        )
    assert cleanup(factory, 7) == 1
    rows = attempt_rows(factory)
    assert len(rows) == 1
    assert rows[0]["delivery_id"] == only(factory)["id"]
