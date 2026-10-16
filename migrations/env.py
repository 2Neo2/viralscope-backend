"""Как Alembic подключается к базе и узнаёт схему моделей.

Запускается при каждой команде alembic (upgrade, downgrade, revision --autogenerate).
- Адрес базы — из настроек приложения (VS_DATABASE_URL / .env), а не из alembic.ini.
  Тесты могут подставить свой: config.attributes["database_url"] (шаг 9).
- Схема моделей — app.models.Base.metadata: autogenerate сравнивает её с базой и пишет разницу.
- Логи — наш structlog с service=migrate: в Docker они попадут в Grafana, как логи API.
"""

import asyncio
import logging

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.models import Base

config = context.config
settings = get_settings().model_copy(update={"service": "migrate"})


class DropAlembicChatter(logging.Filter):
    """Служебные строки Alembic при каждом запуске — шум. «Running upgrade ...» остаётся."""

    CHATTER = ("Context impl", "Will assume", "setting up autogenerate plugin")

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self.CHATTER)


# Не настраиваем логи, если:
# - Alembic вызван из кода (тесты) — там логи уже настроены;
# - режим --sql: SQL печатается в stdout, и логи смешались бы с ним (предупреждения уйдут в stderr).
if config.attributes.get("configure_logging", True) and not context.is_offline_mode():
    setup_logging(settings)
    for name in ("alembic.runtime.migration", "alembic.runtime.plugins"):
        logging.getLogger(name).addFilter(DropAlembicChatter())

target_metadata = Base.metadata


def database_url() -> str:
    return config.attributes.get("database_url") or settings.database_url


def configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,  # замечать смену типа колонки: String(100) → String(255)
        compare_server_default=True,  # и смену значения по умолчанию на стороне базы
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: не подключаться к базе, а напечатать SQL — для ревью или DBA."""
    configure(url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: миграции — разовая команда, держать пул соединений незачем
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        # Alembic синхронный, поэтому его код запускается внутри async-соединения через run_sync
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
