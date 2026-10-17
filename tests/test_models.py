"""Модели на настоящем PostgreSQL: значения по умолчанию, ограничения, связи, каскадное удаление.

Каждый тест работает в своей транзакции, которая откатывается в конце (фикстура db_session в conftest.py).
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import utcnow
from app.modules.niches.models import Niche, NicheQuery, QueryKind, UserNiche
from app.modules.users.models import User


async def add(session: AsyncSession, *objects: object) -> None:
    session.add_all(objects)
    await session.flush()  # отправить INSERT в базу, не завершая транзакцию: ошибки ограничений — здесь


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def make_niche(session: AsyncSession, slug: str = "fitness") -> Niche:
    niche = Niche(
        slug=slug,
        title="Фитнес",
        queries=[
            NicheQuery(kind=QueryKind.HASHTAG, value="fitness"),
            NicheQuery(kind=QueryKind.ACCOUNT, value="coach.anna"),
        ],
    )
    await add(session, niche)
    return niche


# ---------- users ----------


async def test_user_gets_id_and_server_defaults(db_session: AsyncSession):
    user = User(email="ivan@mail.ru")
    await add(db_session, user)
    await db_session.refresh(user)  # перечитать строку: created_at и updated_at поставила база

    assert isinstance(user.id, int)
    assert user.is_admin is False
    assert user.created_at.tzinfo is not None
    assert abs(user.created_at - utcnow()) < timedelta(minutes=1)
    assert user.updated_at == user.created_at


async def test_telegram_only_user_is_allowed(db_session: AsyncSession):
    await add(db_session, User(telegram_id=5_000_000_000, telegram_username="ivan"))  # больше 2^31


@pytest.mark.parametrize(
    ("user", "constraint"),
    [
        (User(name="Без входа"), "ck_users_has_login"),
        (User(email="Ivan@Mail.ru"), "ck_users_email_lowercase"),
    ],
    ids=["no-login", "uppercase-email"],
)
async def test_user_checks(db_session: AsyncSession, user: User, constraint: str):
    with pytest.raises(IntegrityError, match=constraint):
        await add(db_session, user)


async def test_duplicate_email_rejected(db_session: AsyncSession):
    await add(db_session, User(email="ivan@mail.ru"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        await add(db_session, User(email="ivan@mail.ru"))


async def test_duplicate_telegram_id_rejected(db_session: AsyncSession):
    await add(db_session, User(telegram_id=42))
    with pytest.raises(IntegrityError, match="uq_users_telegram_id"):
        await add(db_session, User(telegram_id=42))


async def test_updated_at_changes_on_orm_update(db_session: AsyncSession):
    user = User(email="ivan@mail.ru")
    await add(db_session, user)
    # now() в PostgreSQL — время начала транзакции, а тест весь в одной транзакции.
    # Поэтому сдвигаем created_at назад вручную и проверяем, что ORM-обновление поставит updated_at заново.
    await db_session.execute(
        text("UPDATE users SET created_at = now() - interval '1 day', updated_at = now() - interval '1 day'")
    )
    await db_session.refresh(user)
    old_updated_at = user.updated_at

    user.name = "Иван"
    await db_session.flush()
    await db_session.refresh(user)
    assert user.updated_at > old_updated_at


# ---------- niches ----------


async def test_niche_with_queries_loaded_explicitly(db_session: AsyncSession):
    niche = await make_niche(db_session)
    db_session.expunge_all()  # забыть объекты: дальше читаем из базы, а не из памяти сессии

    loaded = await db_session.scalar(
        select(Niche).where(Niche.id == niche.id).options(selectinload(Niche.queries))
    )
    assert loaded.is_active is True
    assert {(q.kind, q.value) for q in loaded.queries} == {
        (QueryKind.HASHTAG, "fitness"),
        (QueryKind.ACCOUNT, "coach.anna"),
    }
    assert isinstance(loaded.queries[0].kind, QueryKind)  # из базы приходит enum, а не строка


async def test_relationship_not_loaded_raises_instead_of_hidden_query(db_session: AsyncSession):
    niche = await make_niche(db_session)
    db_session.expunge_all()

    loaded = await db_session.get(Niche, niche.id)
    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = loaded.queries


async def test_duplicate_slug_rejected(db_session: AsyncSession):
    await make_niche(db_session, "fitness")
    with pytest.raises(IntegrityError, match="uq_niches_slug"):
        await add(db_session, Niche(slug="fitness", title="Другой фитнес"))


async def test_duplicate_query_in_niche_rejected(db_session: AsyncSession):
    niche = await make_niche(db_session)
    with pytest.raises(IntegrityError, match="uq_niche_queries_niche_id_kind_value"):
        await add(db_session, NicheQuery(niche_id=niche.id, kind=QueryKind.HASHTAG, value="fitness"))


async def test_same_value_allowed_for_different_kind_or_niche(db_session: AsyncSession):
    fitness = await make_niche(db_session, "fitness")
    yoga = await make_niche(db_session, "yoga")  # тот же хештег fitness, но в другой нише
    await add(db_session, NicheQuery(niche_id=fitness.id, kind=QueryKind.ACCOUNT, value="fitness"))
    assert yoga.id != fitness.id


async def test_unknown_query_kind_rejected_by_database(db_session: AsyncSession):
    niche = await make_niche(db_session)
    # Python не даст записать неизвестный kind, поэтому проверяем саму базу — сырым SQL
    with pytest.raises(IntegrityError, match="ck_niche_queries_kind"):
        await db_session.execute(
            text("INSERT INTO niche_queries (niche_id, kind, value) VALUES (:id, 'tiktok', 'x')"),
            {"id": niche.id},
        )


async def test_deleting_niche_cascades_to_queries_and_user_choices(db_session: AsyncSession):
    niche = await make_niche(db_session)
    user = User(email="ivan@mail.ru")
    await add(db_session, user)
    await add(db_session, UserNiche(user_id=user.id, niche_id=niche.id, direction="домашние тренировки"))

    await db_session.delete(niche)
    await db_session.flush()

    assert await count(db_session, NicheQuery) == 0
    assert await count(db_session, UserNiche) == 0
    assert await count(db_session, User) == 1  # пользователь остался


async def test_deleting_user_cascades_to_choices_only(db_session: AsyncSession):
    niche = await make_niche(db_session)
    user = User(email="ivan@mail.ru")
    await add(db_session, user)
    await add(db_session, UserNiche(user_id=user.id, niche_id=niche.id))

    await db_session.delete(user)
    await db_session.flush()

    assert await count(db_session, UserNiche) == 0
    assert await count(db_session, Niche) == 1


async def test_same_niche_twice_for_user_rejected(db_session: AsyncSession):
    niche = await make_niche(db_session)
    user = User(email="ivan@mail.ru")
    await add(db_session, user)
    await add(db_session, UserNiche(user_id=user.id, niche_id=niche.id))
    with pytest.raises(IntegrityError, match="pk_user_niches"):
        await add(db_session, UserNiche(user_id=user.id, niche_id=niche.id))


# ---------- изоляция тестов ----------


@pytest.mark.parametrize("attempt", [1, 2])
async def test_committed_data_does_not_leak_between_tests(db_session: AsyncSession, attempt: int):
    """Оба запуска сохраняют одну и ту же почту с commit(). Без отката второй упал бы на дубле."""
    assert await count(db_session, User) == 0
    db_session.add(User(email="same@test.ru"))
    await db_session.commit()
    assert await count(db_session, User) == 1
