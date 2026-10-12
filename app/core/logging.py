"""Логирование проекта на structlog.

- В dev — цветной читаемый вывод, в остальных окружениях — JSON (его собирает Grafana Alloy в Loki).
- Контекст запроса (request_id, позже user_id) добавляется в каждую запись автоматически через contextvars.
- Секреты маскируются, email сокращается до a***@mail.ru.
- Логи uvicorn и сторонних библиотек проходят через тот же формат.
- Только stdout: файлы логов не пишем, их собирает Docker.

Как писать логи в модулях:
    log = get_logger(__name__)
    log.info("seat_reserved", launch=3, seats_left=11)

Имена событий — «существительное_глагол_в_прошедшем»: request_finished, payment_succeeded.
Коды ошибок пишите в поле error_code: поле с именем code маскируется (это код входа).
"""

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from app.core.config import Settings

MASK = "***"
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "old_password",
        "new_password",
        "code",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "secret",
        "jwt",
    }
)
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
NOISY_LOGGERS = ("httpx", "httpcore", "asyncio", "multipart")


def mask_email(text: str) -> str:
    return EMAIL_RE.sub(r"\1***\2", text)


def _mask(value: Any, key: str | None = None) -> Any:
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return MASK
    if isinstance(value, str):
        return mask_email(value)
    if isinstance(value, Mapping):
        return {k: _mask(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask(v) for v in value]
    return value


def mask_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Скрывает значения секретных полей (в том числе вложенных) и сокращает email."""
    for key, value in list(event_dict.items()):
        if key.startswith("_"):  # служебные поля structlog (_record, _from_structlog) не трогаем
            continue
        event_dict[key] = _mask(value, key)
    return event_dict


def add_app_info(settings: Settings) -> Processor:
    """Добавляет к каждой записи service, env и version — по ним фильтруем логи в Grafana."""

    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", settings.service)
        event_dict.setdefault("env", settings.env)
        event_dict.setdefault("version", settings.version)
        return event_dict

    return processor


def setup_logging(settings: Settings) -> None:
    """Настроить логи один раз при старте процесса (api, worker, beat)."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
        add_app_info(settings),
        mask_secrets,
    ]

    if settings.use_json_logs:
        render: list[Processor] = [
            structlog.processors.format_exc_info,  # трассировка ошибки — строкой в поле exception
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    else:
        render = [structlog.dev.ConsoleRenderer()]  # сам красиво печатает трассировку

    # Логи, которые пишем мы сами через structlog.
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # В тестах не кэшируем логгеры, иначе structlog.testing.capture_logs их не перехватит.
        cache_logger_on_first_use=settings.env != "test",
    )

    # Логи стандартного logging (uvicorn, библиотеки) проходят через тот же формат.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*shared, structlog.stdlib.ExtraAdder()],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *render],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn настраивает свои логгеры сам — перенаправляем их в наш общий обработчик.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # Каждый запрос логирует наша middleware (событие request_finished), access-лог uvicorn — дубль.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
