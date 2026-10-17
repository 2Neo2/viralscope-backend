"""Стартовые ниши для первого потока и хештеги, по которым для них собираются видео.

Запуск: make seed. Повторный запуск безопасен:
- новой ниши нет в базе → создаётся вместе с хештегами;
- ниша есть → обновляется только название, если его поменяли здесь;
- недостающие хештеги добавляются, лишние (добавленные админом) остаются;
- is_active не трогаем: если админ выключил нишу, seed её не включит.

Аккаунты авторов (kind=account) сюда не кладём — их подбирают вручную под каждую нишу (этап 7).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.niches.models import Niche, NicheQuery, QueryKind


@dataclass(frozen=True)
class NicheSeed:
    slug: str
    title: str
    hashtags: tuple[str, ...]  # без «#», в нижнем регистре


NICHES: tuple[NicheSeed, ...] = (
    NicheSeed(
        "fitness",
        "Фитнес и тренировки",
        ("фитнес", "тренировкидома", "похудение", "fitness", "workout", "fitnessmotivation"),
    ),
    NicheSeed(
        "beauty",
        "Красота и уход",
        ("макияж", "уходзакожей", "бьюти", "makeup", "skincare", "beautytips"),
    ),
    NicheSeed(
        "experts",
        "Эксперты и личный бренд",
        ("личныйбренд", "эксперт", "психология", "коучинг", "personalbrand"),
    ),
    NicheSeed(
        "food",
        "Еда и рецепты",
        ("рецепты", "простыерецепты", "пп", "вкусно", "recipes", "foodreels"),
    ),
    NicheSeed(
        "business",
        "Бизнес и маркетинг",
        ("бизнес", "маркетинг", "smm", "предприниматель", "smallbusiness", "marketingtips"),
    ),
    NicheSeed(
        "fashion",
        "Мода и стиль",
        ("стиль", "мода", "образдня", "стилист", "fashion", "outfitideas"),
    ),
    NicheSeed(
        "parenting",
        "Мамы и дети",
        ("мама", "материнство", "дети", "воспитание", "momlife"),
    ),
    NicheSeed(
        "travel",
        "Путешествия",
        ("путешествия", "путешествуемсдетьми", "отдых", "travel", "travelreels"),
    ),
    NicheSeed(
        "realestate",
        "Недвижимость",
        ("недвижимость", "риелтор", "ремонт", "дизайнинтерьера", "realestate"),
    ),
    NicheSeed(
        "education",
        "Обучение и языки",
        ("английский", "английскийязык", "обучение", "саморазвитие", "studygram"),
    ),
)


@dataclass
class SeedResult:
    niches_created: int = 0
    niches_updated: int = 0
    queries_created: int = 0


async def seed_niches(session: AsyncSession, niches: tuple[NicheSeed, ...] = NICHES) -> SeedResult:
    """Добавить недостающие ниши и хештеги. Не делает commit — это решает вызывающий код."""
    result = SeedResult()
    existing = {niche.slug: niche for niche in await session.scalars(select(Niche))}
    existing_queries = {
        (query.niche_id, query.kind, query.value) for query in await session.scalars(select(NicheQuery))
    }

    for seed in niches:
        niche = existing.get(seed.slug)
        if niche is None:
            niche = Niche(slug=seed.slug, title=seed.title)
            session.add(niche)
            await session.flush()  # нужен niche.id для хештегов
            result.niches_created += 1
        elif niche.title != seed.title:
            niche.title = seed.title
            result.niches_updated += 1

        for hashtag in seed.hashtags:
            if (niche.id, QueryKind.HASHTAG, hashtag) not in existing_queries:
                session.add(NicheQuery(niche_id=niche.id, kind=QueryKind.HASHTAG, value=hashtag))
                result.queries_created += 1

    await session.flush()
    return result
