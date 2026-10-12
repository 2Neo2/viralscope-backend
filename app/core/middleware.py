"""Middleware контекста запроса.

Для каждого HTTP-запроса:
- берёт X-Request-ID из заголовка (если он корректный) или создаёт новый;
- кладёт его в request.state.request_id и в контекст логов — дальше он попадает в каждую запись сам;
- добавляет к ответу заголовки X-Request-ID и X-Process-Time (мс);
- пишет одно событие request_finished: метод, шаблон пути, статус, время, IP.

Написана как «чистая» ASGI-middleware, а не через @app.middleware("http") (BaseHTTPMiddleware):
так контекст логов не теряется, ответ не буферизуется, а запрос логируется даже при ошибке 500.
"""

import logging
import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# Чужой request_id принимаем, только если он короткий и без спецсимволов (иначе через него портят логи)
VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Служебные адреса, которые дёргают каждые несколько секунд (healthcheck Docker): успешные — только в debug
QUIET_PATHS = frozenset({"/health"})


def resolve_request_id(scope: Scope) -> str:
    incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if incoming and VALID_REQUEST_ID.match(incoming):
        return incoming
    return uuid.uuid4().hex


def route_template(scope: Scope) -> str:
    """Шаблон маршрута (/videos/{video_id}) вместо реального пути (/videos/9817):
    так в Grafana статистика группируется по эндпоинтам, а не по каждому id."""
    app = scope.get("app")
    router = getattr(app, "router", None)
    for route in getattr(router, "routes", []):
        match, _ = route.matches(scope)
        if match != Match.NONE:  # FULL — совпал путь и метод, PARTIAL — путь совпал, метод нет (405)
            return getattr(route, "path", scope["path"])
    return scope["path"]  # маршрута нет (404) — пишем как есть


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan, websocket — пропускаем как есть
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id  # = request.state.request_id
        # Каждый запрос — отдельная задача asyncio, поэтому контекст не «протекает» между запросами.
        # Очищаем на всякий случай и не очищаем в конце: обработчик ошибки 500 пишет лог уже после нас.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers["X-Process-Time"] = f"{(time.perf_counter() - started) * 1000:.1f}"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            status_code = 500  # ответ 500 соберёт обработчик ошибок (app/core/errors.py) снаружи
            raise
        finally:
            self._log_request(scope, status_code, started)

    @staticmethod
    def _log_request(scope: Scope, status_code: int, started: float) -> None:
        path = route_template(scope)
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        elif path in QUIET_PATHS:
            level = logging.DEBUG
        else:
            level = logging.INFO
        client = scope.get("client")
        log.log(
            level,
            "request_finished",
            method=scope["method"],
            path=path,
            status=status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            client_ip=client[0] if client else None,
        )
