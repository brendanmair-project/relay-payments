from app.config import get_settings


def key() -> dict:
    return {"X-API-Key": get_settings().relay_api_key}


def test_health_ok_with_key(client):
    response = client.get("/health", headers=key())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}
    assert response.headers["X-Correlation-ID"]


def test_health_without_key_is_401_with_error_shape(client):
    response = client.get("/health")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthorized"
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]


def test_wrong_key_is_401(client):
    assert client.get("/health", headers={"X-API-Key": "wrong"}).status_code == 401


def test_correlation_id_is_echoed(client):
    response = client.get("/health", headers={**key(), "X-Correlation-ID": "abc-123"})
    assert response.headers["X-Correlation-ID"] == "abc-123"


def test_tests_use_the_test_database(client):
    assert get_settings().database_url.rsplit("/", 1)[-1].endswith("_test")


def test_dependency_down_is_503_with_error_shape(client, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_redis_ok", lambda: False)
    response = client.get("/health", headers=key())
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "dependency_unavailable"
    assert "redis" in error["message"]
    assert error["correlation_id"] == response.headers["X-Correlation-ID"]
