"""Подключение к PostgreSQL: базовый класс моделей, движок, сессия на запрос.

Как это устроено:
- engine — пул соединений с базой. Один на приложение, создаётся в create_app и закрывается при остановке.
- sessionmaker — фабрика сессий. Сессия — «рабочий блокнот» запроса: копит изменения до commit().
- SessionDep — зависимость FastAPI: каждый запрос получает свою сессию, после ответа она закрывается.

Транзакции фиксирует код сервиса явным `await session.commit()`. Если commit не вызван или
случилась ошибка, при закрытии сессии изменения откатываются — в базу не попадёт половина операции.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings

# Правила имён для индексов и ограничений. Без них PostgreSQL придумывает имена сам,
# и Alembic не может надёжно их найти, чтобы изменить или удалить в следующей миграции.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс всех моделей. Base.metadata — схема всех таблиц, по ней Alembic строит миграции."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Текущее время в UTC с таймзоной. В базе храним timestamptz, показываем — в часовом поясе клиента."""
    return datetime.now(UTC)


class TimestampMixin:
    """Колонки created_at и updated_at со временем базы (now()), а не сервера приложения.

    updated_at обновляется при изменении объекта через ORM. Ручной UPDATE в SQL его не трогает.
    """

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def create_engine(settings: Settings) -> AsyncEngine:
    """Пул соединений. Соединения открываются лениво — при первом запросе, а не здесь."""
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,  # проверить соединение перед выдачей: база могла перезапуститься
        pool_recycle=1800,  # пересоздавать соединения раз в 30 минут
        # Имя приложения видно в pg_stat_activity: понятно, кто держит соединения — api или worker
        connect_args={"server_settings": {"application_name": f"viralscope-{settings.service}"}},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: после commit объекты остаются читаемыми без нового запроса в базу.
    # В async это обязательно — ленивая подгрузка после commit упала бы с ошибкой MissingGreenlet.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI: одна сессия на один запрос, закрывается после ответа."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
