"""Лог медленных SQL-запросов (slow_query) на настоящем PostgreSQL.

pg_sleep — искусственно медленный запрос.
"""

from collections.abc import AsyncGenerator

import pytest
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from app.core.db import SessionDep, create_engine
from app.main import create_app
from tests.conftest import make_settings

SLOW_SQL = "SELECT pg_sleep(0.06)"  # 60 мс при пороге 50 мс


def slow_logs(logs: list[dict]) -> list[dict]:
    return [entry for entry in logs if entry["event"] == "slow_query"]


@pytest.fixture
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_engine(make_settings(database_url=database_url, db_slow_query_ms=50))
    yield engine
    await engine.dispose()


async def test_slow_query_logged(engine: AsyncEngine):
    with capture_logs() as logs:
        async with engine.connect() as conn:
            await conn.execute(text(SLOW_SQL))

    [entry] = slow_logs(logs)
    assert entry["log_level"] == "warning"
    assert entry["duration_ms"] >= 50
    assert entry["threshold_ms"] == 50
    assert entry["statement"] == SLOW_SQL


async def test_fast_query_not_logged(engine: AsyncEngine):
    with capture_logs() as logs:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    assert slow_logs(logs) == []


async def test_parameter_values_never_logged(engine: AsyncEngine):
    with capture_logs() as logs:
        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT pg_sleep(0.06), CAST(:email AS text)"), {"email": "secret.person@mail.ru"}
            )
    [entry] = slow_logs(logs)
    assert "secret.person" not in str(entry)
    assert "$1" in entry["statement"]  # вместо значения — плейсхолдер asyncpg


async def test_multiline_statement_collapsed_and_truncated(engine: AsyncEngine):
    long_tail = " ".join(f"{n} AS c{n}," for n in range(400))
    sql = f"SELECT\n    {long_tail}\n    pg_sleep(0.06)"
    with capture_logs() as logs:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    [entry] = slow_logs(logs)
    assert "\n" not in entry["statement"]
    assert len(entry["statement"]) == 1000


async def test_failed_query_does_not_break_timing(engine: AsyncEngine):
    with capture_logs() as logs:
        async with engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                await conn.execute(text("SELECT * FROM no_such_table"))
            await conn.rollback()
            await conn.execute(text(SLOW_SQL))
    [entry] = slow_logs(logs)
    assert entry["statement"] == SLOW_SQL


async def test_disabled_when_threshold_zero(database_url: str):
    engine = create_engine(make_settings(database_url=database_url, db_slow_query_ms=0))
    with capture_logs() as logs:
        async with engine.connect() as conn:
            await conn.execute(text(SLOW_SQL))
    await engine.dispose()
    assert slow_logs(logs) == []


async def test_slow_query_has_request_id_of_api_request(database_url: str):
    """По request_id из лога slow_query находится запрос API, который тормозил."""
    app = create_app(make_settings(database_url=database_url, db_slow_query_ms=50))

    @app.get("/slow")
    async def slow(session: SessionDep) -> dict:
        await session.execute(text(SLOW_SQL))
        return {"ok": True}

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/slow", headers={"X-Request-ID": "slow-req-1"})
    await app.state.engine.dispose()

    assert response.status_code == 200
    [entry] = slow_logs(logs)
    assert entry["request_id"] == "slow-req-1"
