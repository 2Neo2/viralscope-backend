"""Ниши и то, по каким хештегам и аккаунтам собирать для них видео.

Связи (relationship) объявлены с lazy="raise": в async обращение к незагруженной связи
не может тихо сходить в базу. Вместо непонятной MissingGreenlet будет ясная ошибка,
а загружать связи нужно явно: select(Niche).options(selectinload(Niche.queries)).
"""

import enum

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, CreatedAtMixin, IntPK, TimestampMixin


class QueryKind(enum.StrEnum):
    HASHTAG = "hashtag"  # value без «#»: fitness
    ACCOUNT = "account"  # value без «@»: username автора


class Niche(TimestampMixin, Base):
    __tablename__ = "niches"

    id: Mapped[IntPK]
    slug: Mapped[str] = mapped_column(String(64), unique=True)  # fitness — для URL и квиза
    title: Mapped[str] = mapped_column(String(128))  # «Фитнес и ЗОЖ» — для людей
    # Выключенная ниша не показывается в квизе и не собирается, но выбор старых клиентов сохраняется
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    queries: Mapped[list["NicheQuery"]] = relationship(
        back_populates="niche",
        cascade="all, delete-orphan",  # удалили запрос из niche.queries — он удалится из базы
        passive_deletes=True,  # при удалении ниши запросы удалит сама база (ON DELETE CASCADE)
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"Niche(id={self.id}, slug={self.slug!r})"


class NicheQuery(CreatedAtMixin, Base):
    """Поисковое задание ниши: хештег или аккаунт, по которому собираем Reels (этап 7)."""

    __tablename__ = "niche_queries"
    __table_args__ = (UniqueConstraint("niche_id", "kind", "value"),)  # один хештег в нише — один раз

    id: Mapped[IntPK]
    # Без отдельного индекса: UNIQUE (niche_id, kind, value) уже ускоряет поиск по niche_id —
    # PostgreSQL использует составной индекс, если условие по его первой колонке
    niche_id: Mapped[int] = mapped_column(ForeignKey("niches.id", ondelete="CASCADE"))
    # VARCHAR + CHECK, а не ENUM PostgreSQL: новое значение добавляется простой миграцией,
    # а у ENUM типа ALTER TYPE не откатывается и не работает внутри транзакции в старых версиях
    kind: Mapped[QueryKind] = mapped_column(
        Enum(
            QueryKind,
            name="kind",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda kinds: [kind.value for kind in kinds],  # в базе "hashtag", а не "HASHTAG"
        )
    )
    value: Mapped[str] = mapped_column(String(128))

    niche: Mapped[Niche] = relationship(back_populates="queries", lazy="raise")

    def __repr__(self) -> str:
        return f"NicheQuery(id={self.id}, kind={self.kind}, value={self.value!r})"


class UserNiche(CreatedAtMixin, Base):
    """Ниша, которую клиент выбрал в квизе (этап 4). Ниш у клиента может быть несколько."""

    __tablename__ = "user_niches"

    # Составной первичный ключ: одна ниша у одного клиента — не больше одного раза
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Отдельный индекс: «сколько клиентов выбрали фитнес» — PK (user_id, niche_id) тут не поможет
    niche_id: Mapped[int] = mapped_column(
        ForeignKey("niches.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Уточнение клиента своими словами: «домашние тренировки для мам»
    direction: Mapped[str] = mapped_column(String(200), default="", server_default="")

    niche: Mapped[Niche] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"UserNiche(user_id={self.user_id}, niche_id={self.niche_id})"
