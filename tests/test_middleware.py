import logging

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs


@pytest.fixture
def app_with_routes(app: FastAPI) -> FastAPI:
    @app.get("/items/{item_id}")
    async def get_item(item_id: int):
        return {"id": item_id}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("provider is down")

    return app


@pytest.fixture
def client(app_with_routes: FastAPI) -> TestClient:
    return TestClient(app_with_routes, raise_server_exceptions=False)


def captured(client: TestClient, path: str, **kwargs) -> tuple:
    # merge_contextvars — чтобы в перехваченных логах был request_id, как в настоящих
    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        response = client.get(path, **kwargs)
    return response, logs


def finished(logs: list[dict]) -> dict:
    return next(r for r in logs if r["event"] == "request_finished")


def test_request_finished_log(client):
    response, logs = captured(client, "/items/9817")
    record = finished(logs)
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert record["method"] == "GET"
    assert record["path"] == "/items/{item_id}"  # шаблон, а не /items/9817
    assert record["status"] == 200
    assert record["log_level"] == "info"
    assert record["duration_ms"] >= 0


@pytest.mark.parametrize(
    "path, status, level",
    [("/health", 200, "debug"), ("/items/abc", 422, "warning"), ("/nope", 404, "warning")],
)
def test_log_level_by_status(client, path, status, level):
    response, logs = captured(client, path)
    assert response.status_code == status
    assert finished(logs)["log_level"] == level


def test_wrong_method_uses_route_template(client):
    with capture_logs() as logs:
        response = client.post("/items/5")
    assert response.status_code == 405
    assert finished(logs)["path"] == "/items/{item_id}"


def test_unhandled_error_is_logged_with_same_request_id(client):
    response, logs = captured(client, "/boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-500"
    assert response.json()["error"]["request_id"] == "req-500"

    record = finished(logs)
    assert record["status"] == 500 and record["log_level"] == "error"
    error = next(r for r in logs if r["event"] == "unhandled_error")
    assert error["request_id"] == "req-500"
    assert isinstance(error["exc_info"], RuntimeError)


def test_requests_do_not_share_request_id(client):
    first, logs_first = captured(client, "/items/1")
    second, logs_second = captured(client, "/items/2")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert finished(logs_second)["request_id"] == second.headers["X-Request-ID"]


def test_lifespan_logs_start_and_stop(app_with_routes, caplog):
    with capture_logs() as logs, TestClient(app_with_routes):
        pass
    events = [r["event"] for r in logs]
    assert events[0] == "app_started" and events[-1] == "app_stopped"
    assert logging.getLogger("uvicorn.access").disabled
