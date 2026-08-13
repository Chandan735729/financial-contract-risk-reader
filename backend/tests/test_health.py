from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_health_response_has_no_extra_fields():
    response = client.get("/health")
    assert set(response.json().keys()) == {"status", "environment"}


def test_health_does_not_leak_internal_details():
    response = client.get("/health")
    text = response.text.lower()
    for forbidden in ("secret", "password", "database_url", "api_key", "traceback", "c:\\", "/users/"):
        assert forbidden not in text


def test_health_sets_request_id_header():
    response = client.get("/health")
    assert "x-request-id" in {k.lower() for k in response.headers}


def test_unknown_route_returns_standard_error_shape():
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body["error"].keys()) == {"code", "user_message", "request_id"}
    assert body["error"]["code"] == "access_denied"


def test_readiness_reports_ready_when_dependencies_are_reachable():
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert set(body["checks"].keys()) == {"database", "vector_store"}
    assert body["checks"]["database"] == {"ok": True}
    assert body["checks"]["vector_store"] == {"ok": True}


def test_readiness_does_not_leak_internal_details():
    response = client.get("/health/ready")
    text = response.text.lower()
    for forbidden in ("secret", "password", "database_url", "api_key", "traceback", "c:\\", "/users/"):
        assert forbidden not in text


def test_readiness_returns_503_when_database_is_unreachable():
    from app.db.session import get_db
    from app.main import app as fastapi_app

    def _broken_get_db():
        class _BrokenSession:
            def execute(self, *args, **kwargs):
                raise RuntimeError("simulated database outage")

        yield _BrokenSession()

    fastapi_app.dependency_overrides[get_db] = _broken_get_db
    try:
        response = client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["database"] == {"ok": False}
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
