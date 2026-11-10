"""REL-40: the generated OpenAPI document declares the key scheme, the required header, enums and per-endpoint errors.

The fixes change the document only: the behaviour tests below prove that the order of checks and the error bodies are
the same as before.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

CURRENCIES = ["USD", "EUR", "GBP", "JPY"]
PAYMENT_STATUSES = ["received", "routed", "authorized", "captured", "declined", "failed"]
DISPLAY_STATUSES = ["Received", "Processing", "Captured", "Declined", "Failed", "Retrying"]
EVENT_TYPES = [
    "payment.received",
    "payment.authorized",
    "payment.captured",
    "payment.declined",
    "payment.failed",
    "payment.final",
]

# The statuses each operation documents besides its success response, from the error table in api-contract.md:
# 401 and 500 on every keyed endpoint, 503 on /health only (a database failure elsewhere surfaces as 500).
EXPECTED_ERRORS: dict[tuple[str, str], set[int]] = {
    ("get", "/health"): {401, 500, 503},
    ("post", "/payments"): {400, 401, 409, 422, 500},
    ("get", "/payments"): {400, 401, 422, 500},
    ("get", "/payments/{payment_id}"): {401, 404, 500},
    ("get", "/payments/{payment_id}/explanation"): {401, 404, 409, 500},
    ("post", "/payments/{payment_id}/explanation/regenerate"): {401, 404, 409, 500},
    ("get", "/processors/health"): {401, 500},
    ("get", "/incidents"): {401, 422, 500},
    ("post", "/incidents"): {400, 401, 409, 422, 500},
    ("get", "/incidents/{incident_id}"): {401, 404, 500},
    ("get", "/incidents/{incident_id}/summary"): {401, 404, 500},
    ("post", "/incidents/{incident_id}/summary/regenerate"): {401, 404, 500},
    ("post", "/incidents/{incident_id}/transitions"): {400, 401, 404, 409, 422, 500},
    ("get", "/analytics"): {401, 422, 500},
    ("get", "/analytics/baseline"): {401, 500},
    ("post", "/webhooks/subscriptions"): {400, 401, 422, 500},
    ("get", "/webhooks/subscriptions"): {401, 500},
    ("get", "/webhooks/subscriptions/{subscription_id}"): {401, 404, 500},
    ("delete", "/webhooks/subscriptions/{subscription_id}"): {401, 404, 500},
    ("get", "/webhooks/deliveries"): {400, 401, 422, 500},
    ("get", "/webhooks/deliveries/summary"): {401, 422, 500},
    ("get", "/webhooks/deliveries/{delivery_id}"): {401, 404, 422, 500},
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    document: dict[str, Any] = app.openapi()
    return document


def schema(spec: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = spec["components"]["schemas"][name]
    return found


def enum_of(prop: dict[str, Any]) -> list[str] | None:
    """The enum of a property, looking inside the `anyOf` of a nullable one."""
    if "enum" in prop:
        values: list[str] = prop["enum"]
        return values
    for member in prop.get("anyOf", []):
        if "enum" in member:
            values = member["enum"]
            return values
    return None


def test_the_api_key_scheme_is_declared_and_required_globally(spec: dict[str, Any]) -> None:
    schemes = spec["components"]["securitySchemes"]
    assert len(schemes) == 1
    ((name, scheme),) = schemes.items()
    assert scheme["type"] == "apiKey" and scheme["in"] == "header" and scheme["name"] == "X-API-Key"
    assert spec["security"] == [{name: []}]


def test_idempotency_key_is_required_in_the_schema_of_post_payments(spec: dict[str, Any]) -> None:
    params = spec["paths"]["/payments"]["post"]["parameters"]
    (header,) = [p for p in params if p["name"] == "Idempotency-Key"]
    assert header["in"] == "header" and header["required"] is True
    assert header["schema"]["type"] == "string"
    assert header["schema"]["minLength"] == 1 and header["schema"]["maxLength"] == 255


def test_a_missing_idempotency_key_is_still_400_before_body_validation(client: TestClient) -> None:
    headers = {"X-API-Key": get_settings().relay_api_key}
    response = client.post("/payments", json={"currency": "nope"}, headers=headers)  # an invalid body as well
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_missing"


def test_an_unsupported_currency_is_still_422_validation_failed(client: TestClient) -> None:
    headers = {"X-API-Key": get_settings().relay_api_key, "Idempotency-Key": "rel40-currency-check"}
    response = client.post("/payments", json={"amount_minor": 100, "currency": "XXX"}, headers=headers)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["message"] == "currency must be one of USD, EUR, GBP, JPY"
    assert error["details"] == [{"field": "currency", "issue": "not_supported"}]


@pytest.mark.parametrize(
    ("component", "prop", "values"),
    [
        ("PaymentResponse", "currency", CURRENCIES),
        ("PaymentResponse", "status", PAYMENT_STATUSES),
        ("PaymentResponse", "display_status", DISPLAY_STATUSES),
        ("PaymentResponse", "processor", ["A", "B"]),
        ("PaymentDetailResponse", "currency", CURRENCIES),
        ("PaymentDetailResponse", "status", PAYMENT_STATUSES),
        ("PaymentDetailResponse", "display_status", DISPLAY_STATUSES),
        ("PaymentDetailResponse", "processor", ["A", "B"]),
        ("AffectedPayment", "currency", CURRENCIES),
        ("AffectedPayment", "status", PAYMENT_STATUSES),
        ("ProcessorHealthItem", "state", ["preferred", "avoided", "unknown"]),
        ("ExplanationResponse", "source", ["model", "rules"]),
        ("ExplanationResponse", "trigger", ["final_failure", "on_request", "regenerate"]),
        ("SummaryResponse", "source", ["model", "rules"]),
        ("SummaryResponse", "trigger", ["on_request", "regenerate"]),
        ("IncidentResponse", "source", ["rule", "manual"]),
        ("IncidentResponse", "status", ["detected", "triaged", "resolved"]),
        ("DeliveryResponse", "status", ["pending", "delivered", "failed"]),
        ("DeliveryResponse", "event_type", EVENT_TYPES),
        ("DeliveryDetailResponse", "status", ["pending", "delivered", "failed"]),
    ],
)
def test_response_properties_use_enums(spec: dict[str, Any], component: str, prop: str, values: list[str]) -> None:
    assert enum_of(schema(spec, component)["properties"][prop]) == values


def test_the_request_currency_is_an_enum(spec: dict[str, Any]) -> None:
    body = spec["paths"]["/payments"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert enum_of(body["properties"]["currency"]) == CURRENCIES


def test_webhook_event_types_are_enums_in_request_and_responses(spec: dict[str, Any]) -> None:
    for name in ("SubscriptionCreate", "SubscriptionResponse", "SubscriptionCreated"):
        items = schema(spec, name)["properties"]["event_types"]["items"]
        assert items["enum"] == EVENT_TYPES, name


def test_every_operation_lists_exactly_the_errors_it_can_return(spec: dict[str, Any]) -> None:
    actual: dict[tuple[str, str], set[int]] = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            actual[(method, path)] = {int(s) for s in operation["responses"] if int(s) >= 400}
    assert actual == EXPECTED_ERRORS


def test_documented_errors_use_the_shared_error_body(spec: dict[str, Any]) -> None:
    for item in spec["paths"].values():
        for operation in item.values():
            for status, response in operation["responses"].items():
                if int(status) >= 400:
                    ref = response["content"]["application/json"]["schema"]["$ref"]
                    assert ref == "#/components/schemas/ErrorResponse"
                    assert response["description"].startswith("Error `")  # names the codes, not just "Error"


def test_the_document_is_built_once_and_has_no_unused_validation_schemas(spec: dict[str, Any]) -> None:
    assert app.openapi() is spec
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_the_export_command_writes_both_generated_files(tmp_path: Path) -> None:
    from app.docs_export import OPENAPI_FILE, REFERENCE_FILE, generate, main

    assert main(["--out", str(tmp_path)]) == 0
    expected = generate(app.openapi())
    for name in (OPENAPI_FILE, REFERENCE_FILE):
        assert (tmp_path / name).read_bytes().decode("utf-8") == expected[name]
