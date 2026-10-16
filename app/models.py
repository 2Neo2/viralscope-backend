"""Реестр всех моделей.

Alembic видит только те таблицы, чьи модели импортированы к моменту сравнения схемы.
Поэтому каждую новую модель импортируйте здесь — иначе autogenerate решит, что таблицу нужно удалить.

    from app.modules.users.models import User  # noqa: F401
"""

from app.core.db import Base

__all__ = ["Base"]
