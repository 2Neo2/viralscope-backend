import os

# До импорта приложения: тесты не должны зависеть от вашего локального .env
os.environ.setdefault("VS_ENV", "test")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{"env": "test", **overrides})


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False — ошибки 500 приходят ответом, как их увидит клиент
    return TestClient(app, raise_server_exceptions=False)
