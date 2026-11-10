"""Error mapping (REL-41)."""

from collections.abc import Callable

import httpx
import pytest
from conftest import Handler, Recorder, json_response

from relay_sdk import RelayError

BODY = {
    "error": {
        "code": "validation_failed",
        "message": "currency must be one of USD, EUR, GBP, JPY",
        "details": [{"field": "currency", "issue": "not_supported"}],
        "correlation_id": "body-corr-1",
    }
}


def test_a_json_error_body_becomes_a_relay_error(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(BODY, 422))
    with pytest.raises(RelayError) as info:
        rec.client.create_payment(1, "XXX")
    assert len(rec.requests) == 1
    error = info.value
    assert error.status == 422
    assert error.code == "validation_failed"
    assert error.message == "currency must be one of USD, EUR, GBP, JPY"
    assert error.correlation_id == "body-corr-1"
    assert error.details == [{"field": "currency", "issue": "not_supported"}]
    assert "422" in str(error)
    assert "validation_failed" in str(error)


def test_the_correlation_header_is_used_when_the_body_has_none(make: Callable[[Handler], Recorder]) -> None:
    body = {"error": {"code": "not_found", "message": "Payment not found", "correlation_id": ""}}
    rec = make(lambda request: json_response(body, 404, {"X-Correlation-ID": "hdr-corr-2"}))
    with pytest.raises(RelayError) as info:
        rec.client.get_payment("x")
    assert len(rec.requests) == 1
    assert info.value.correlation_id == "hdr-corr-2"
    assert info.value.status == 404


def test_a_non_json_error_body_still_raises_relay_error_with_the_status(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: httpx.Response(502, text="<html>Bad Gateway</html>", headers={"X-Correlation-ID": "c3"}))
    with pytest.raises(RelayError) as info:
        rec.client.list_payments()
    assert len(rec.requests) == 1
    assert info.value.status == 502
    assert info.value.correlation_id == "c3"
    assert info.value.code == "http_error"
    assert "Bad Gateway" in info.value.message


def test_json_that_is_not_the_error_shape_still_raises_relay_error(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(["unexpected"], 500))
    with pytest.raises(RelayError) as info:
        rec.client.list_payments()
    assert len(rec.requests) == 1
    assert info.value.status == 500


def test_every_non_2xx_status_raises(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: json_response(BODY, 409))
    with pytest.raises(RelayError) as info:
        rec.client.list_subscriptions()
    assert len(rec.requests) == 1
    assert info.value.status == 409


def test_a_malformed_success_body_is_not_hidden(make: Callable[[Handler], Recorder]) -> None:
    rec = make(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(ValueError):  # noqa: PT011 - json.JSONDecodeError is a ValueError
        rec.client.list_payments()
    assert len(rec.requests) == 1


def test_transport_errors_are_not_swallowed(make: Callable[[Handler], Recorder]) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    rec = make(boom)
    with pytest.raises(httpx.ConnectError):
        rec.client.list_payments()
    assert len(rec.requests) == 1
