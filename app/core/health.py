"""Проверки здоровья сервиса.

/health        — процесс жив и отвечает. Ничего внешнего не проверяет, поэтому всегда быстрый.
                 Его опрашивает Docker (HEALTHCHECK): если не отвечает — контейнер завис.
/health/ready  — сервис готов принимать запросы: база доступна. Если нет — 503, и балансировщик
                 перестаёт слать сюда трафик, пока база не вернётся. Перезапуск API тут не поможет.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["system"])

CheckStatus = Literal["ok", "error"]


class HealthOut(BaseModel):
    status: Literal["ok"]
    env: str
    version: str


class ReadyChecks(BaseModel):
    database: CheckStatus


class ReadyOut(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: ReadyChecks


@router.get("", response_model=HealthOut, summary="Проверка, что сервис жив")
async def health(request: Request) -> HealthOut:
    settings = request.app.state.settings
    return HealthOut(status="ok", env=settings.env, version=settings.version)


async def check_database(engine: AsyncEngine, timeout: float) -> CheckStatus:
    """SELECT 1 с ограничением по времени: зависшая база не должна вешать проверку."""
    try:
        async with asyncio.timeout(timeout), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # любая причина — «база недоступна»: нет сети, неверный пароль, таймаут
        # Без exc_info: при упавшей базе проверка вызывается каждые несколько секунд, трейсбэки забьют логи
        log.warning("readiness_check_failed", check="database", error_type=type(exc).__name__, error=str(exc))
        return "error"
    return "ok"


@router.get(
    "/ready",
    response_model=ReadyOut,
    summary="Проверка, что сервис готов: база доступна",
    responses={503: {"model": ReadyOut, "description": "Сервис не готов: база недоступна"}},
)
async def ready(request: Request, response: Response) -> ReadyOut:
    settings = request.app.state.settings
    database = await check_database(request.app.state.engine, settings.db_health_timeout)
    if database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyOut(status="unavailable", checks=ReadyChecks(database=database))
    return ReadyOut(status="ok", checks=ReadyChecks(database=database))
