"""Подключение к базе без самой базы: настройки пула, сессия на запрос, закрытие пула.

Соединения открываются лениво, поэтому эти тесты не требуют PostgreSQL.
Тесты на настоящей базе — tests/test_models.py и tests/test_migrations.py (шаг 9).
"""

from datetime import UTC

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, UniqueConstraint, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.schema import CreateIndex, CreateTable
from structlog.testing import capture_logs

from app.core.db import NAMING_CONVENTION, Base, SessionDep, create_engine, utcnow
from app.main import create_app
from app.modules.users.models import User
from tests.conftest import make_settings


def test_engine_uses_settings():
    engine = create_engine(
        make_settings(
            database_url="postgresql+asyncpg://u:secret@db.example:6543/vs",
            db_pool_size=7,
            db_echo=True,
            service="worker",
        )
    )
    assert engine.url.host == "db.example"
    assert engine.url.port == 6543
    assert engine.url.database == "vs"
    assert engine.pool.size() == 7
    assert engine.echo is True


def test_db_settings_from_env(monkeypatch):
    monkeypatch.setenv("VS_DB_POOL_SIZE", "20")
    monkeypatch.setenv("VS_DB_ECHO", "true")
    settings = make_settings()
    assert settings.db_pool_size == 20
    assert settings.db_echo is True


def test_base_uses_naming_convention():
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_constraint_names_follow_convention():
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    Table("niches", metadata, Column("id", Integer, primary_key=True))
    queries = Table(
        "niche_queries",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("niche_id", ForeignKey("niches.id")),
        Column("kind", String),
        Column("value", String, index=True),
        UniqueConstraint("niche_id", "kind", "value"),
    )
    dialect = postgresql.dialect()
    ddl = str(CreateTable(queries).compile(dialect=dialect))
    assert "CONSTRAINT pk_niche_queries PRIMARY KEY" in ddl
    assert "CONSTRAINT fk_niche_queries_niche_id_niches FOREIGN KEY" in ddl
    assert "CONSTRAINT uq_niche_queries_niche_id_kind_value UNIQUE" in ddl
    index_ddl = str(CreateIndex(next(iter(queries.indexes))).compile(dialect=dialect))
    assert "ix_niche_queries_value" in index_ddl


def test_utcnow_is_timezone_aware():
    assert utcnow().tzinfo is UTC


def test_app_has_engine_and_sessionmaker(app: FastAPI):
    assert isinstance(app.state.engine, AsyncEngine)
    assert app.state.sessionmaker.kw["expire_on_commit"] is False


def test_each_request_gets_own_session(app: FastAPI):
    sessions: list[AsyncSession] = []

    @app.get("/session-probe")
    async def probe(session: SessionDep, same: SessionDep) -> dict:
        sessions.append(session)
        # В пределах одного запроса зависимость кешируется — это одна и та же сессия
        return {"type": type(session).__name__, "same": session is same}

    client = TestClient(app)
    assert client.get("/session-probe").json() == {"type": "AsyncSession", "same": True}
    client.get("/session-probe")
    assert sessions[0] is not sessions[1]


def test_lifespan_logs_db_without_password_and_disposes_pool(monkeypatch):
    app = create_app(make_settings(database_url="postgresql+asyncpg://u:secret@db.example:5432/vs"))
    disposed = []

    async def fake_dispose(self, close: bool = True) -> None:
        disposed.append(self)

    monkeypatch.setattr(AsyncEngine, "dispose", fake_dispose)

    with capture_logs() as logs, TestClient(app):
        pass

    started = next(entry for entry in logs if entry["event"] == "app_started")
    assert started["db"] == "postgresql+asyncpg://u:***@db.example:5432/vs"
    assert "secret" not in str(logs)
    assert disposed == [app.state.engine]


async def test_session_dep_works_with_real_database(db_app, db_client, db_session):
    """Запрос через SessionDep пишет в базу. commit() в обработчике виден тесту и откатится после него."""

    @db_app.post("/users-probe")
    async def create_user(session: SessionDep) -> dict:
        user = User(email="probe@test.ru")
        session.add(user)
        await session.commit()
        return {"id": user.id}

    response = await db_client.post("/users-probe")
    assert response.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
