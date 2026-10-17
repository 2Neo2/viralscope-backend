"""Стартовые ниши: данные корректны, повторный запуск ничего не дублирует, правки админа не затираются."""

import re

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.niches.models import Niche, NicheQuery, QueryKind
from app.modules.niches.seed import NICHES, NicheSeed, seed_niches

TOTAL_HASHTAGS = sum(len(seed.hashtags) for seed in NICHES)


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# ---------- данные (без базы) ----------


def test_slugs_unique_and_url_safe():
    slugs = [seed.slug for seed in NICHES]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z][a-z0-9-]{1,63}", slug) for slug in slugs)


@pytest.mark.parametrize("seed", NICHES, ids=lambda seed: seed.slug)
def test_hashtags_normalized(seed: NicheSeed):
    """Хештеги — как их хранит база: без «#», без пробелов, в нижнем регистре, без дублей."""
    assert seed.hashtags, "у ниши должен быть хотя бы один хештег"
    assert len(seed.hashtags) == len(set(seed.hashtags))
    for hashtag in seed.hashtags:
        assert hashtag == hashtag.lower()
        assert re.fullmatch(r"\w{2,128}", hashtag), hashtag


# ---------- на базе ----------


async def test_first_run_creates_everything(db_session: AsyncSession):
    result = await seed_niches(db_session)

    assert result.niches_created == len(NICHES)
    assert result.queries_created == TOTAL_HASHTAGS
    assert await count(db_session, Niche) == len(NICHES)
    assert await count(db_session, NicheQuery) == TOTAL_HASHTAGS


async def test_second_run_changes_nothing(db_session: AsyncSession):
    await seed_niches(db_session)
    result = await seed_niches(db_session)

    assert (result.niches_created, result.niches_updated, result.queries_created) == (0, 0, 0)
    assert await count(db_session, Niche) == len(NICHES)
    assert await count(db_session, NicheQuery) == TOTAL_HASHTAGS


async def test_new_hashtag_and_title_in_seed_are_applied(db_session: AsyncSession):
    await seed_niches(db_session)
    changed = (NicheSeed("fitness", "Фитнес", (*NICHES[0].hashtags, "растяжка")),)

    result = await seed_niches(db_session, changed)

    assert (result.niches_updated, result.queries_created) == (1, 1)
    fitness = await db_session.scalar(select(Niche).where(Niche.slug == "fitness"))
    assert fitness.title == "Фитнес"


async def test_admin_changes_are_kept(db_session: AsyncSession):
    await seed_niches(db_session)
    fitness = await db_session.scalar(select(Niche).where(Niche.slug == "fitness"))
    fitness.is_active = False  # админ выключил нишу
    db_session.add(NicheQuery(niche_id=fitness.id, kind=QueryKind.ACCOUNT, value="coach.anna"))
    await db_session.flush()

    await seed_niches(db_session)

    await db_session.refresh(fitness)
    assert fitness.is_active is False
    assert await count(db_session, NicheQuery) == TOTAL_HASHTAGS + 1
