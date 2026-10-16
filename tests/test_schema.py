"""Схема моделей без базы: какие таблицы, колонки и ограничения увидит Alembic.

Поведение ограничений на настоящем PostgreSQL (дубль email, каскадное удаление) —
tests/test_models.py (шаг 9).
"""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app.models import Base
from app.modules.niches.models import QueryKind

ROOT = Path(__file__).resolve().parent.parent


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def constraint_names(name: str) -> set[str]:
    return {c.name for c in table(name).constraints}


def test_mappers_configure():
    # Ошибки в relationship (опечатка в back_populates) всплывают только здесь, а не при импорте
    configure_mappers()


def test_tables():
    assert set(Base.metadata.tables) == {"users", "niches", "niche_queries", "user_niches"}


def test_every_models_module_is_registered():
    """Модель, забытая в app/models.py, для Alembic не существует — autogenerate предложит удалить таблицу."""
    modules = sorted(
        "app." + ".".join(path.relative_to(ROOT / "app").with_suffix("").parts)
        for path in (ROOT / "app" / "modules").glob("*/models.py")
    )
    # Отдельный процесс: в этом модули могли быть уже импортированы другими тестами
    code = (
        "import importlib, app.models as m; before = set(m.Base.metadata.tables); "
        f"[importlib.import_module(name) for name in {modules!r}]; "
        "print(sorted(set(m.Base.metadata.tables) - before))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True
    )
    assert result.stdout.strip() == "[]", f"Импортируйте модели в app/models.py: {result.stdout}"


@pytest.mark.parametrize("name", ["users", "niches", "niche_queries", "user_niches"])
def test_timestamps_are_timezone_aware_and_last(name: str):
    columns = list(table(name).columns)
    assert columns[-1].name in {"created_at", "updated_at"}
    for column in columns:
        if column.name in {"created_at", "updated_at"}:
            assert column.type.timezone is True
            assert column.server_default is not None


def test_users_constraints():
    assert {
        "pk_users",
        "uq_users_email",
        "uq_users_telegram_id",
        "ck_users_has_login",
        "ck_users_email_lowercase",
    } <= constraint_names("users")
    assert str(table("users").c.id.type) == "BIGINT"
    assert table("users").c.id.identity is not None


def test_niche_queries_constraints():
    names = constraint_names("niche_queries")
    assert {"uq_niche_queries_niche_id_kind_value", "fk_niche_queries_niche_id_niches"} <= names
    kind_check = next(
        c for c in table("niche_queries").constraints if isinstance(c, CheckConstraint) and "kind" in c.name
    )
    assert kind_check.name == "ck_niche_queries_kind"
    fk = next(iter(table("niche_queries").c.niche_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_query_kind_stored_as_lowercase_values():
    assert [kind.value for kind in QueryKind] == ["hashtag", "account"]
    assert table("niche_queries").c.kind.type.enums == ["hashtag", "account"]
    assert table("niche_queries").c.kind.type.length == 16


def test_user_niches_primary_key_and_index():
    t = table("user_niches")
    assert [c.name for c in t.primary_key.columns] == ["user_id", "niche_id"]
    assert {ix.name for ix in t.indexes} == {"ix_user_niches_niche_id"}
    assert all(fk.ondelete == "CASCADE" for fk in t.foreign_keys)
    assert not any(isinstance(c, UniqueConstraint) for c in t.constraints)
