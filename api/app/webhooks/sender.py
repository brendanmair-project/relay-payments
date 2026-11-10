"""The send loop's work: claim due deliveries, post them signed, record the result (ADR-0015).

No database transaction is open during the HTTP call: `claim_due` commits before the first request and
`record_attempt` opens a new transaction afterwards. Redirects are never followed (a redirect is a failed attempt), and
the allowlist is checked again here, at send time, so a host removed from the setting is never contacted.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.webhooks.config import WebhookSettings, get_webhook_settings
from app.webhooks.signing import sign
from app.webhooks.store import Claimed, claim_due, fail_without_request, record_attempt
from app.webhooks.targets import is_allowed_target, parse_allowed_hosts

logger = logging.getLogger("relay.webhooks")
LEASE_MARGIN_SECONDS = 30  # on top of the request timeout: how long a claimed delivery stays hidden from other senders
PARALLEL_SENDS = 8  # one slow subscriber must not hold up the others


class Sender:
    def __init__(
        self, factory: sessionmaker[Session], client: httpx.Client, settings: WebhookSettings | None = None
    ) -> None:
        self.factory = factory
        self.client = client
        self.settings = settings

    def send_due(self, limit: int = 20) -> int:
        """Send up to `limit` due deliveries; return how many were attempted."""
        settings = self.settings or get_webhook_settings()
        claimed = claim_due(self.factory, limit, settings.webhook_timeout_seconds + LEASE_MARGIN_SECONDS)
        if len(claimed) == 1:
            self._deliver(claimed[0], settings)
        elif claimed:
            with ThreadPoolExecutor(max_workers=min(PARALLEL_SENDS, len(claimed))) as pool:
                list(pool.map(lambda item: self._deliver(item, settings), claimed))
        return len(claimed)

    def _deliver(self, item: Claimed, settings: WebhookSettings) -> None:
        try:
            self._attempt(item, settings)
        except Exception:
            # Left as claimed: the lease runs out and the delivery is picked up again.
            logger.exception("delivery attempt failed unexpectedly", extra={"delivery_id": item.id})

    def _attempt(self, item: Claimed, settings: WebhookSettings) -> None:
        if not item.active:
            fail_without_request(self.factory, item, "subscription_inactive")
            return
        if not is_allowed_target(item.url, parse_allowed_hosts(settings.webhook_allowed_hosts)):
            fail_without_request(self.factory, item, "target_not_allowed")
            return
        if item.body is None:
            fail_without_request(self.factory, item, "event_missing")
            return
        headers = {
            "Content-Type": "application/json",
            "Relay-Event-Id": str(item.event_id),
            "Relay-Signature": sign(item.secret, item.body),
        }
        started = time.monotonic()
        status_code: int | None = None
        error: str | None = None
        try:
            response = self.client.post(
                item.url,
                content=item.body,
                headers=headers,
                timeout=settings.webhook_timeout_seconds,
                follow_redirects=False,
            )
            status_code = response.status_code
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            error = type(exc).__name__  # the class name only: messages can carry the URL
        outcome = record_attempt(
            self.factory, item, status_code, error, settings, int((time.monotonic() - started) * 1000)
        )
        logger.info(
            "webhook attempt",
            extra={"delivery_id": item.id, "event_id": item.event_id, "outcome": outcome, "status_code": status_code},
        )
