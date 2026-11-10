import os

from fastapi.testclient import TestClient

from app.apps import control_app, processor_app

processor = TestClient(processor_app)
control = TestClient(control_app)


def test_processor_health_is_open_on_the_internal_port():
    assert processor.get("/health").json() == {"status": "ok"}


def test_control_health_requires_the_key():
    assert control.get("/health").status_code == 401
    assert control.get("/health", headers={"X-API-Key": "wrong"}).status_code == 401
    response = control.get("/health", headers={"X-API-Key": os.environ["RELAY_API_KEY"]})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_control_401_uses_the_error_shape():
    assert control.get("/health").json()["error"]["code"] == "unauthorized"
