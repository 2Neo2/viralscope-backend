"""Единый формат ошибок API.

Любая ошибка возвращается клиенту так:
    {"error": {"code": "no_seats", "message": "Места в потоке закончились", ...}}

- code — машинный код: по нему фронтенд решает, что показать (кнопку тарифов, форму входа…).
- message — текст для человека.
- Дополнительно: fields (ошибки валидации), request_id (для 500), details (что угодно ещё).

Как бросать ошибку в модулях:
    raise AppError(409, "no_seats", "Места в потоке закончились")
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)

# Коды для стандартных HTTP-ошибок, которые FastAPI/Starlette возвращают сами (нет маршрута, не тот метод…)
HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "too_many_requests",
}


class AppError(Exception):
    """Ошибка бизнес-логики. Её бросают сервисы и зависимости: им достаточно знать код статуса."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = dict(details) if details else None
        self.headers = dict(headers) if headers else None


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    *,
    headers: Mapping[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body = {"error": {"code": error_code, "message": message, **extra}}
    return JSONResponse(status_code=status_code, content=body, headers=dict(headers) if headers else None)


def _request_id(request: Request) -> str | None:
    # request_id кладёт middleware (шаг 7). Пока её нет — None.
    return getattr(request.state, "request_id", None)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    extra = {"details": exc.details} if exc.details else {}
    return error_response(exc.status_code, exc.error_code, exc.message, headers=exc.headers, **extra)


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404 для несуществующего адреса, 405 для неверного метода, а также HTTPException из кода."""
    code = HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422: список полей с понятными сообщениями вместо стандартного ответа FastAPI."""
    fields = []
    for err in exc.errors():
        location, *path = err["loc"]  # ("body", "email") → место "body", поле "email"
        fields.append(
            {
                "field": ".".join(str(p) for p in path) or str(location),
                "location": str(location),
                "message": err["msg"],
            }
        )
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Проверьте введённые данные",
        fields=fields,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """500: подробности — только в лог (с трассировкой), клиенту — общий текст и request_id."""
    request_id = _request_id(request)
    log.error(
        "unhandled_error",
        exc_info=exc,
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Что-то пошло не так. Мы уже разбираемся",
        headers={"X-Request-ID": request_id} if request_id else None,
        request_id=request_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
