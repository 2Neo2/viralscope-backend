"""Точка входа приложения.

Запуск для разработки:  uvicorn app.main:app --reload
Документация:            http://127.0.0.1:8000/docs (в prod выключена)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware

log = get_logger(__name__)


class HealthOut(BaseModel):
    status: Literal["ok"]
    env: str
    version: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Фабрика приложения: тесты создают свежее приложение со своими настройками."""
    settings = settings or get_settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info("app_started", app_name=settings.app_name)
        yield
        log.info("app_stopped")

    docs_enabled = not settings.is_prod
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Порядок важен: middleware, добавленная последней, выполняется первой (оборачивает остальные).
    # RequestContextMiddleware — снаружи, чтобы request_id и лог были у любого ответа, включая CORS preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # cookie сессии (этап 3)
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, "X-Process-Time"],  # чтобы фронтенд мог прочитать request_id
    )
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)

    @app.get("/health", response_model=HealthOut, tags=["system"], summary="Проверка, что сервис жив")
    async def health() -> HealthOut:
        return HealthOut(status="ok", env=settings.env, version=settings.version)

    return app


app = create_app()
