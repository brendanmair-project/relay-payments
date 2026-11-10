"""The generated OpenAPI document, completed after FastAPI builds it (REL-40, api-contract.md).

Schema only, no behaviour: the key check stays in the middleware, `Idempotency-Key` stays checked by the handler (so
its absence is still 400 before body validation, never FastAPI's 422), and the enums are documented here rather than
enforced by new types. Each section below patches one finding of the Phase 1 exit review.
"""

import copy
from typing import Any

from app.api.payments import DISPLAY_STATUS
from app.db.models import STATUSES as PAYMENT_STATUSES
from app.domain.money import CURRENCY_DIGITS
from app.webhooks.types import DELIVERY_STATUSES, WEBHOOK_EVENT_TYPES

API_KEY_SCHEME = "ApiKeyAuth"

CURRENCIES = list(CURRENCY_DIGITS)
# Failed and Retrying are the two displays of a `failed` payment (final or not); see payment_body.
DISPLAY_STATUSES = [*dict.fromkeys(DISPLAY_STATUS.values()), "Failed", "Retrying"]
PROCESSORS = ["A", "B"]

_PAYMENT_ENUMS: dict[str, list[str]] = {
    "currency": CURRENCIES,
    "status": list(PAYMENT_STATUSES),
    "display_status": DISPLAY_STATUSES,
    "processor": PROCESSORS,
}
_SUBSCRIPTION_ENUMS: dict[str, list[str]] = {"event_types": list(WEBHOOK_EVENT_TYPES)}
_DELIVERY_ENUMS: dict[str, list[str]] = {"status": list(DELIVERY_STATUSES), "event_type": list(WEBHOOK_EVENT_TYPES)}
_INCIDENT_ENUMS: dict[str, list[str]] = {
    "processor": PROCESSORS,
    "source": ["rule", "manual"],
    "status": ["detected", "triaged", "resolved"],
}

# Schema title -> property -> allowed values. Value sets come from the code (or the CHECK constraints it mirrors).
ENUMS: dict[str, dict[str, list[str]]] = {
    "PaymentCreate": {"currency": CURRENCIES},
    "PaymentResponse": _PAYMENT_ENUMS,
    "PaymentDetailResponse": _PAYMENT_ENUMS,
    "AffectedPayment": {k: v for k, v in _PAYMENT_ENUMS.items() if k != "display_status"},
    "ProcessorHealthItem": {"name": PROCESSORS, "state": ["preferred", "avoided", "unknown"]},
    "ExplanationResponse": {"source": ["model", "rules"], "trigger": ["final_failure", "on_request", "regenerate"]},
    "SummaryResponse": {"source": ["model", "rules"], "trigger": ["on_request", "regenerate"]},
    "IncidentResponse": _INCIDENT_ENUMS,
    "IncidentListItem": _INCIDENT_ENUMS,
    "IncidentDetailResponse": _INCIDENT_ENUMS,
    "SubscriptionCreate": _SUBSCRIPTION_ENUMS,
    "SubscriptionResponse": _SUBSCRIPTION_ENUMS,
    "SubscriptionCreated": _SUBSCRIPTION_ENUMS,
    "DeliveryResponse": _DELIVERY_ENUMS,
    "DeliveryDetailResponse": _DELIVERY_ENUMS,
}

# What each operation can return besides its success response, from the error table in api-contract.md: status ->
# codes. 401 and 500 are on every keyed endpoint; 503 only on /health (a database failure elsewhere is a 500).
_KEY = {401: ["unauthorized"]}
_INTERNAL = {500: ["internal_error"]}
_NOT_FOUND = {404: ["not_found"]}
_INVALID = {422: ["validation_failed"]}
_MALFORMED = {400: ["malformed_request"]}
_NOT_FINAL = {409: ["payment_not_final"]}

ERRORS: dict[tuple[str, str], dict[int, list[str]]] = {
    ("get", "/health"): {**_KEY, **_INTERNAL, 503: ["dependency_unavailable"]},
    ("post", "/payments"): {
        400: ["idempotency_key_missing", "malformed_request"],
        **_KEY,
        409: ["idempotency_key_reused", "idempotency_request_in_progress"],
        **_INVALID,
        **_INTERNAL,
    },
    ("get", "/payments"): {**_MALFORMED, **_KEY, **_INVALID, **_INTERNAL},
    ("get", "/payments/{payment_id}"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("get", "/payments/{payment_id}/explanation"): {**_KEY, **_NOT_FOUND, **_NOT_FINAL, **_INTERNAL},
    ("post", "/payments/{payment_id}/explanation/regenerate"): {**_KEY, **_NOT_FOUND, **_NOT_FINAL, **_INTERNAL},
    ("get", "/processors/health"): {**_KEY, **_INTERNAL},
    ("get", "/incidents"): {**_KEY, **_INVALID, **_INTERNAL},
    ("post", "/incidents"): {**_MALFORMED, **_KEY, 409: ["incident_already_open"], **_INVALID, **_INTERNAL},
    ("get", "/incidents/{incident_id}"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("get", "/incidents/{incident_id}/summary"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("post", "/incidents/{incident_id}/summary/regenerate"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("post", "/incidents/{incident_id}/transitions"): {
        **_MALFORMED,
        **_KEY,
        **_NOT_FOUND,
        409: ["invalid_incident_transition"],
        **_INVALID,
        **_INTERNAL,
    },
    ("get", "/analytics"): {**_KEY, **_INVALID, **_INTERNAL},
    ("get", "/analytics/baseline"): {**_KEY, **_INTERNAL},
    ("post", "/webhooks/subscriptions"): {
        **_MALFORMED,
        **_KEY,
        422: ["validation_failed", "webhook_target_not_allowed"],
        **_INTERNAL,
    },
    ("get", "/webhooks/subscriptions"): {**_KEY, **_INTERNAL},
    ("get", "/webhooks/subscriptions/{subscription_id}"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("delete", "/webhooks/subscriptions/{subscription_id}"): {**_KEY, **_NOT_FOUND, **_INTERNAL},
    ("get", "/webhooks/deliveries"): {**_MALFORMED, **_KEY, **_INVALID, **_INTERNAL},
    ("get", "/webhooks/deliveries/summary"): {**_KEY, **_INVALID, **_INTERNAL},
    ("get", "/webhooks/deliveries/{delivery_id}"): {**_KEY, **_NOT_FOUND, **_INVALID, **_INTERNAL},
}


def _restrict(prop: dict[str, Any], values: list[str]) -> None:
    """Add the enum to a string property, looking inside the `anyOf` of a nullable one and the items of an array."""
    if prop.get("type") == "array":
        _restrict(prop["items"], values)
    elif "anyOf" in prop:
        for member in prop["anyOf"]:
            if member.get("type") == "string":
                member["enum"] = values
    elif "enum" not in prop:
        prop["enum"] = values


def _add_enums(node: Any) -> None:
    if isinstance(node, dict):
        wanted = ENUMS.get(node.get("title", "")) if "properties" in node else None
        for name, values in (wanted or {}).items():
            if name in node["properties"]:
                _restrict(node["properties"][name], values)
        for child in node.values():
            _add_enums(child)
    elif isinstance(node, list):
        for child in node:
            _add_enums(child)


def _set_errors(spec: dict[str, Any]) -> None:
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            wanted = ERRORS[(method, path)]  # a new endpoint without an entry fails here, loudly
            responses = operation["responses"]
            template = next(r for s, r in responses.items() if int(s) >= 400)  # the shared ErrorResponse entry
            for status in [s for s in responses if int(s) >= 400]:
                del responses[status]
            for status, codes in wanted.items():
                entry = copy.deepcopy(template)
                entry["description"] = "Error " + " or ".join(f"`{c}`" for c in codes)
                responses[str(status)] = entry
            operation["responses"] = dict(sorted(responses.items()))


def _set_security(spec: dict[str, Any]) -> None:
    spec.setdefault("components", {})["securitySchemes"] = {
        API_KEY_SCHEME: {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "The static API key (RELAY_API_KEY). Every endpoint requires it; a missing or wrong key "
            "is 401 `unauthorized`.",
        }
    }
    spec["security"] = [{API_KEY_SCHEME: []}]


def _require_idempotency_key(spec: dict[str, Any]) -> None:
    """Required in the document only: the handler still answers a missing header with 400, before body validation."""
    for param in spec["paths"]["/payments"]["post"]["parameters"]:
        if param["name"] == "Idempotency-Key":
            param["required"] = True
            param["schema"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 255,
                "title": "Idempotency-Key",
                "description": param["schema"]["description"],
            }
    spec["paths"]["/payments"]["post"]["description"] += (
        " Without `Idempotency-Key` the answer is 400 `idempotency_key_missing`."
    )


def complete(spec: dict[str, Any]) -> dict[str, Any]:
    _set_security(spec)
    _require_idempotency_key(spec)
    _add_enums(spec)
    _set_errors(spec)
    return spec
