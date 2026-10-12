import logging

import pytest
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from structlog.testing import capture_logs

from app.core.config import Settings
from app.core.errors import AppError, register_error_handlers
from app.core.logging import setup_logging


class Item(BaseModel):
    name: str = Field(min_length=2)
    price: int = Field(gt=0)


@pytest.fixture
def client() -> TestClient:
    """Маленькое приложение только с обработчиками ошибок — main.py появится на шаге 8."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/conflict")
    def conflict():
        raise AppError(409, "no_seats", "Места в потоке закончились")

    @app.get("/limited")
    def limited():
        raise AppError(
            429,
            "search_limit",
            "Лимит поисков исчерпан",
            details={"limit": 30},
            headers={"Retry-After": "60"},
        )

    @app.post("/items")
    def create_item(item: Item):
        return item

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"id": item_id}

    @app.get("/forbidden")
    def forbidden():
        raise HTTPException(status_code=403, detail="Доступно с тарифа Pro")

    @app.get("/boom")
    def boom(request: Request):
        request.state.request_id = "req-500"  # на шаге 7 это сделает middleware
        raise RuntimeError("provider token abc123 is invalid")

    # raise_server_exceptions=False — получаем ответ 500, как его увидит клиент
    return TestClient(app, raise_server_exceptions=False)


def test_app_error_format(client):
    response = client.get("/conflict")
    assert response.status_code == 409
    assert response.json() == {"error": {"code": "no_seats", "message": "Места в потоке закончились"}}


def test_app_error_with_details_and_headers(client):
    response = client.get("/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["details"] == {"limit": 30}


def test_validation_error_lists_fields(client):
    response = client.post("/items", json={"name": "a", "price": 0})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {f["field"] for f in error["fields"]} == {"name", "price"}
    assert all(f["location"] == "body" and f["message"] for f in error["fields"])


def test_validation_error_in_path(client):
    error = client.get("/items/abc").json()["error"]
    [field] = error["fields"]
    assert field["field"] == "item_id" and field["location"] == "path" and field["message"]


def test_unknown_route_and_wrong_method(client):
    assert client.get("/nope").json()["error"]["code"] == "not_found"
    response = client.post("/conflict")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_http_exception_uses_same_format(client):
    response = client.get("/forbidden")
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "forbidden", "message": "Доступно с тарифа Pro"}}


def test_unhandled_error_hides_details(client):
    with capture_logs() as logs:
        response = client.get("/boom")
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-500"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Что-то пошло не так. Мы уже разбираемся",
            "request_id": "req-500",
        }
    }
    assert "abc123" not in response.text and "RuntimeError" not in response.text

    record = next(r for r in logs if r["event"] == "unhandled_error")
    assert record["log_level"] == "error"
    assert record["error_type"] == "RuntimeError"
    assert isinstance(record["exc_info"], RuntimeError)
    assert record["path"] == "/boom"


def test_uvicorn_duplicate_error_log_is_dropped(capsys):
    setup_logging(Settings(_env_file=None, env="test"))
    try:
        uvicorn_logger = logging.getLogger("uvicorn.error")
        uvicorn_logger.error("Exception in ASGI application")
        uvicorn_logger.error("Address already in use")
        output = capsys.readouterr().out
        assert "Exception in ASGI application" not in output
        assert "Address already in use" in output
    finally:
        structlog.reset_defaults()
        logging.getLogger().handlers.clear()
