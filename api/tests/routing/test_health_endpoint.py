"""GET /processors/health (REL-22): API key, shape, same numbers as the worker computation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.routing.health import compute_health
from tests.routing.conftest import seed

Factory = sessionmaker[Session]


def key() -> dict[str, str]:
    return {"X-API-Key": get_settings().relay_api_key}


def test_requires_the_api_key(client: TestClient) -> None:
    response = client.get("/processors/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_shape_and_values_match_the_worker_computation(client: TestClient, factory: Factory) -> None:
    seed(factory, "A", routed=10, failed=8)
    seed(factory, "B", routed=3)
    seed(factory, "A", routed=50, failed=50, age_seconds=300)  # outside the window
    response = client.get("/processors/health", headers=key())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"strategy", "window_seconds", "error_threshold", "processors", "computed_at"}
    assert (body["strategy"], body["window_seconds"], body["error_threshold"]) == ("rules", 60, 0.5)
    assert body["computed_at"].endswith("Z")
    assert body["processors"] == [
        {"name": "A", "attempts": 10, "errors": 8, "error_rate": 0.8, "state": "avoided"},
        {"name": "B", "attempts": 3, "errors": 0, "error_rate": 0.0, "state": "unknown"},
    ]
    with factory() as session:
        worker_view = compute_health(session)
    assert body["processors"][0]["state"] == worker_view["A"].state


def test_reports_the_static_strategy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    body = client.get("/processors/health", headers=key()).json()
    assert body["strategy"] == "static"
    assert [p["state"] for p in body["processors"]] == ["unknown", "unknown"]
