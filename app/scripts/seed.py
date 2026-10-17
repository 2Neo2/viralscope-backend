"""Заполнить базу стартовыми данными: make seed (или python -m app.scripts.seed).

Пишет в базу из VS_DATABASE_URL. Повторный запуск ничего не дублирует.
"""

import asyncio
from dataclasses import asdict

from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import get_logger, setup_logging
from app.modules.niches.seed import seed_niches

log = get_logger("seed")


async def main() -> None:
    settings = get_settings().model_copy(update={"service": "seed"})
    setup_logging(settings)
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            result = await seed_niches(session)
            await session.commit()  # всё или ничего: при ошибке не останется половины ниш
        log.info("seed_finished", db=engine.url.render_as_string(hide_password=True), **asdict(result))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
