"""The synchronous Relay client: payments and webhooks on one `httpx.Client`."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from relay_sdk.errors import RelayError
from relay_sdk.models import (
    Delivery,
    DeliveryDetail,
    DeliveryPage,
    DeliverySummary,
    Payment,
    PaymentCreated,
    PaymentPage,
    Subscription,
    SubscriptionCreated,
)

Params = dict[str, Any]


def _clean(params: Params) -> Params:
    return {key: value for key, value in params.items() if value is not None}


def _time(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _path(segment: str | int) -> str:
    return quote(str(segment), safe="")


def _error(response: httpx.Response) -> RelayError:
    header_id = response.headers.get("X-Correlation-ID")
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("error") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return RelayError(
            response.status_code,
            str(detail.get("code") or "http_error"),
            str(detail.get("message") or response.reason_phrase),
            detail.get("correlation_id") or header_id,
            detail.get("details"),
        )
    return RelayError(response.status_code, "http_error", response.text[:200] or response.reason_phrase, header_id)


class RelayClient:
    """Client for the Relay API. Use as a context manager, or call `close()`.

    `transport` lets tests pass `httpx.MockTransport`. Non-2xx answers raise `RelayError`; transport errors
    (`httpx.TransportError`) propagate unchanged.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> RelayClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = self._http.request(method, path, params=_clean(params or {}) or None, json=json, headers=headers)
        if response.is_success:
            return response
        raise _error(response)

    # Payments

    def create_payment(
        self,
        amount_minor: int,
        currency: str,
        description: str | None = None,
        reference: str | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentCreated:
        """Create a payment.

        A UUID4 `Idempotency-Key` is generated unless one is given; pass your own to retry safely.
        """
        body = _clean(
            {"amount_minor": amount_minor, "currency": currency, "description": description, "reference": reference}
        )
        key = idempotency_key or str(uuid.uuid4())
        response = self._request("POST", "/payments", json=body, headers={"Idempotency-Key": key})
        replayed = response.headers.get("Idempotent-Replayed", "").lower() == "true"
        return PaymentCreated(Payment.from_dict(response.json()), replayed)

    def get_payment(self, payment_id: str) -> Payment:
        """A payment with its timeline in `events`."""
        return Payment.from_dict(self._request("GET", f"/payments/{_path(payment_id)}").json())

    def list_payments(
        self,
        status: str | list[str] | None = None,
        processor: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        is_final: bool | None = None,
    ) -> PaymentPage:
        """One page of payments, newest first; pass `next_cursor` back as `cursor` for the next page."""
        params = {"status": status, "processor": processor, "is_final": is_final, "limit": limit, "cursor": cursor}
        return PaymentPage.from_dict(self._request("GET", "/payments", params=params).json())

    def iter_payments(
        self,
        status: str | list[str] | None = None,
        processor: str | None = None,
        limit: int | None = None,
        is_final: bool | None = None,
    ) -> Iterator[Payment]:
        """Every matching payment, newest first, fetching pages lazily by following `next_cursor`."""
        cursor: str | None = None
        while True:
            page = self.list_payments(status, processor, limit, cursor, is_final)
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    # Webhooks

    def create_subscription(self, url: str, event_types: list[str]) -> SubscriptionCreated:
        """Subscribe `url` to payment events. The returned `secret` is shown only here: store it."""
        response = self._request("POST", "/webhooks/subscriptions", json={"url": url, "event_types": event_types})
        return SubscriptionCreated.from_dict(response.json())

    def list_subscriptions(self) -> list[Subscription]:
        items = self._request("GET", "/webhooks/subscriptions").json()["items"]
        return [Subscription.from_dict(s) for s in items]

    def get_subscription(self, subscription_id: str) -> Subscription:
        return Subscription.from_dict(self._request("GET", f"/webhooks/subscriptions/{_path(subscription_id)}").json())

    def delete_subscription(self, subscription_id: str) -> Subscription:
        """Deactivate a subscription; returns it with `active` false."""
        response = self._request("DELETE", f"/webhooks/subscriptions/{_path(subscription_id)}")
        return Subscription.from_dict(response.json())

    def list_deliveries(
        self,
        subscription_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> DeliveryPage:
        """One page of the delivery log, newest first; `status` is `pending`, `delivered` or `failed`.

        Pass `next_cursor` back as `cursor` for the next page (None on the last page).
        """
        params = {"subscription_id": subscription_id, "status": status, "limit": limit, "cursor": cursor}
        return DeliveryPage.from_dict(self._request("GET", "/webhooks/deliveries", params=params).json())

    def iter_deliveries(
        self,
        subscription_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> Iterator[Delivery]:
        """Every matching delivery, newest first, fetching pages lazily by following `next_cursor`."""
        cursor: str | None = None
        while True:
            page = self.list_deliveries(subscription_id, status, limit, cursor)
            yield from page.items
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    def get_delivery(self, delivery_id: int) -> DeliveryDetail:
        """A delivery with every attempt."""
        return DeliveryDetail.from_dict(self._request("GET", f"/webhooks/deliveries/{_path(delivery_id)}").json())

    def delivery_summary(
        self,
        since: datetime | str | None = None,
        until: datetime | str | None = None,
        subscription_id: str | None = None,
    ) -> DeliverySummary:
        """Delivered, failed and pending counts and the success rate in `[since, until)`."""
        params = {"since": _time(since), "until": _time(until), "subscription_id": subscription_id}
        return DeliverySummary.from_dict(self._request("GET", "/webhooks/deliveries/summary", params=params).json())
