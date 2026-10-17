import os

# До импорта приложения: тесты не должны зависеть от вашего локального .env
os.environ.setdefault("VS_ENV", "test")

import asyncio  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402
from pathlib import Path  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import URL, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.models  # noqa: E402, F401 — все модели и связи зарегистрированы до первого запроса
from app.core.config import Settings  # noqa: E402
from app.core.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{"env": "test", **overrides})


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False — ошибки 500 приходят ответом, как их увидит клиент
    return TestClient(app, raise_server_exceptions=False)


# ---------- Настоящий PostgreSQL ----------
#
# Тесты с фикстурами db_session / db_client / database_url идут в отдельную базу viralscope_test
# на том же PostgreSQL, что и разработка (make up). Ваши данные в базе viralscope не трогаются.
#
# - База пересоздаётся при каждом запуске pytest, затем к ней применяются миграции:
#   тесты проверяют схему, которую реально создают миграции, а не Base.metadata.create_all().
# - Каждый тест — внутри транзакции, которая откатывается в конце. Даже session.commit() в тесте
#   фиксирует только SAVEPOINT. Тесты не видят данных друг друга и не требуют чистки.
# - PostgreSQL не запущен → такие тесты пропускаются с подсказкой. В CI задайте VS_TEST_REQUIRE_DB=1,
#   чтобы вместо пропуска они падали.
# - Другой сервер: VS_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/viralscope_test

DB_FIXTURES = {"database_url", "migrations_database_url"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Пометить тесты базы маркером db: `pytest -m "not db"` запускает всё остальное без Docker."""
    for item in items:
        if DB_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.db)


def make_test_database_url(suffix: str = "") -> URL:
    explicit = os.environ.get("VS_TEST_DATABASE_URL")
    # Без явного адреса — хост, порт и пароль как у разработки (из .env), но своя база
    url = make_url(explicit or Settings().database_url)
    name = (url.database if explicit else "viralscope_test") + suffix
    # База удаляется целиком — защита от опечатки, которая снесла бы рабочую базу
    if "test" not in name:
        raise RuntimeError(f"Тестовая база должна содержать «test» в имени, а не {name!r}")
    return url.set(database=name)


async def recreate_database(url: URL) -> None:
    """DROP + CREATE через служебную базу postgres: к удаляемой базе подключаться нельзя."""
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    conn = await asyncpg.connect(admin, timeout=3)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


def fresh_database(url: URL) -> str:
    try:
        asyncio.run(recreate_database(url))
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        if os.environ.get("VS_TEST_REQUIRE_DB"):
            raise
        pytest.skip(f"PostgreSQL недоступен ({type(exc).__name__}). Запустите: make up")
    return url.render_as_string(hide_password=False)


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False  # логи тестов уже настроены
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    """Свежая база viralscope_test со всеми миграциями. Одна на весь запуск pytest."""
    url = fresh_database(make_test_database_url())
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def migrations_database_url() -> str:
    """Пустая база для тестов самих миграций — своя на каждый тест, viralscope_test не трогает."""
    return fresh_database(make_test_database_url("_migrations"))


@pytest.fixture
async def db_engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    # NullPool и движок на каждый тест: у pytest-asyncio свой event loop на тест,
    # а соединение asyncpg нельзя переносить между loop-ами
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Сессия внутри внешней транзакции, которая откатывается после теста."""
    async with db_engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            # commit() и rollback() в тесте работают с SAVEPOINT, внешняя транзакция остаётся открытой
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def db_app(db_session: AsyncSession, db_engine: AsyncEngine) -> FastAPI:
    """Приложение, у которого SessionDep отдаёт тестовую сессию, а /health/ready ходит в тестовую базу."""
    application = create_app(make_settings())

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    application.dependency_overrides[get_session] = override_session
    application.state.engine = db_engine
    return application


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    # Асинхронный клиент, а не TestClient: TestClient запускает приложение в другом потоке и loop-е,
    # а тестовая сессия привязана к loop-у теста
    async with AsyncClient(transport=ASGITransport(app=db_app), base_url="http://test") as client:
        yield client
