"""Exception handler tests — API_and_Data_Models.md SS4.

Unhandled exceptions must never leak stack traces, internal file paths, or
the raw exception message (which could incidentally contain sensitive
values from local variables) to the client.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.errors import install_exception_handlers


@pytest.fixture()
def error_test_app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4()
        return await call_next(request)

    @app.get("/boom")
    def boom():
        secret_value = "sk-ant-super-secret-should-never-leak"
        raise RuntimeError(f"internal failure while holding {secret_value}")

    @app.get("/ok")
    def ok():
        return {"fine": True}

    return app


def test_unhandled_exception_returns_generic_body(error_test_app: FastAPI):
    client = TestClient(error_test_app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert set(body["error"].keys()) == {"code", "user_message", "request_id"}


def test_unhandled_exception_does_not_leak_secret_or_traceback(error_test_app: FastAPI):
    client = TestClient(error_test_app, raise_server_exceptions=False)
    response = client.get("/boom")

    text = response.text
    assert "sk-ant-super-secret-should-never-leak" not in text
    assert "RuntimeError" not in text
    assert "Traceback" not in text
    assert "test_errors.py" not in text


def test_healthy_route_unaffected_by_handler_registration(error_test_app: FastAPI):
    client = TestClient(error_test_app)
    response = client.get("/ok")
    assert response.status_code == 200
    assert response.json() == {"fine": True}
