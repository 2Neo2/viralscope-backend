# ViralScope backend

Бэкенд сервиса поиска виральных Reels: агент собирает видео из Instagram по нише клиента,
считает процент виральности и объясняет через Claude, почему ролик «залетел» и как снять свой.

**Статус:** этап 2 из 14 — база данных и миграции. Готовы каркас (настройки, логи, ошибки, Docker, Grafana),
PostgreSQL с миграциями Alembic, первые таблицы (пользователи и ниши) и тесты на настоящей базе.
Бизнес-модули (вход, квиз, потоки, оплата, лента видео) — следующие этапы.

## Стек

| Слой | Технологии |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| Данные | PostgreSQL 16, SQLAlchemy 2 (async) + asyncpg, Alembic; Redis 7 (с этапа 8) |
| Логи | structlog → Docker → Grafana Alloy → Loki → Grafana |
| Тесты и качество | pytest, httpx, ruff |
| Инфраструктура | Docker, docker compose, Makefile |

## Быстрый старт

Нужны Python 3.12, Docker Desktop и `make`.

```bash
make setup   # окружение .venv, зависимости, .env с паролем Grafana
make up      # весь стек в Docker; миграции применятся сами
make seed    # стартовые ниши (один раз)
```

| Что | Адрес |
|---|---|
| Документация API | http://localhost:8000/docs |
| Проверка API | http://localhost:8000/health — процесс жив |
| Готовность API | http://localhost:8000/health/ready — база доступна, иначе 503 |
| Grafana (дашборд API) | http://localhost:3001/d/api-overview — логин `admin`, пароль `GRAFANA_ADMIN_PASSWORD` из `.env` |
| Интерфейс Alloy | http://localhost:12345 |

Остановить: `make down` (данные сохраняются).

## Команды

Полный список — `make` или `make help`. Включать `.venv` не нужно.

| Команда | Что делает |
|---|---|
| `make run` | API локально, без Docker, с автоперезагрузкой |
| `make test` / `make test-fast` | Все тесты (нужен `make up`) / только тесты без базы |
| `make lint` / `make format` | Проверить / исправить код через ruff |
| `make check` | Линтер и тесты — **перед каждым коммитом** |
| `make up` / `make down` | Поднять / остановить Docker-стек |
| `make rebuild` | Пересобрать и перезапустить API (сначала применятся новые миграции) |
| `make ps` / `make logs` | Статус контейнеров / логи API (`make logs s=alloy` — другого сервиса) |
| `make docs` / `make grafana` | Открыть документацию / дашборд в браузере |
| `make migration m="..."` | Создать миграцию из изменений моделей (номер `0002`, `0003`… ставится сам) |
| `make migrate` / `make downgrade` | Применить новые миграции / откатить последнюю (`n=2` — две) |
| `make db-status` / `make history` | Версия базы и есть ли изменения без миграции / список миграций |
| `make sql` | SQL новых миграций без применения — проверить перед продакшеном |
| `make db` | Консоль PostgreSQL (`\q` — выход) |
| `make seed` | Стартовые ниши и хештеги для первого потока. Повторный запуск ничего не дублирует и не затирает правки админа |
| `make reset-data` | Удалить данные базы, логов и Grafana (спрашивает подтверждение) |

## Структура

```
app/
├── main.py              create_app(): настройки → логи → база → FastAPI → CORS → middleware → ошибки → /health
├── models.py            реестр всех моделей для Alembic — новую модель импортируйте сюда
├── core/
│   ├── config.py        настройки из переменных окружения VS_* и .env
│   ├── db.py            Base, движок, SessionDep, медленные SQL в лог
│   ├── health.py        /health и /health/ready
│   ├── logging.py       structlog: JSON или цветной вывод, контекст запроса, маскировка секретов
│   ├── errors.py        AppError и единый формат ошибок 404/405/409/422/500
│   └── middleware.py    request_id, X-Process-Time, лог request_finished
├── modules/
│   ├── users/models.py  User
│   └── niches/          Niche, NicheQuery, UserNiche; seed.py — стартовые ниши
└── scripts/seed.py      make seed
migrations/              Alembic: env.py, шаблон, versions/0001_users_and_niches.py
alembic.ini
tests/                   pytest: настройки, логи, ошибки, /health, middleware, модели и миграции на PostgreSQL
observability/
├── alloy/config.alloy   сбор логов контейнеров проекта → Loki
└── grafana/             источник Loki и дашборд API overview (подключаются автоматически)
```

## Настройки

Все переменные — в [`.env.example`](.env.example). Свои значения храните в `.env` (в git не попадает).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VS_ENV` | `dev` | `dev` / `test` / `prod`. В `prod` закрыта документация `/docs` |
| `VS_LOG_LEVEL` | `INFO` | Уровень логов |
| `VS_LOG_JSON` | — | Пусто: JSON везде, кроме `dev`. `true` / `false` — принудительно |
| `VS_CORS_ORIGINS` | `["http://localhost:3000"]` | Сайты, которым можно ходить в API из браузера (JSON-список) |
| `VS_DATABASE_URL`, `VS_REDIS_URL` | localhost | Адреса для локального запуска. В Docker подставляются автоматически |
| `VS_DB_POOL_SIZE`, `VS_DB_MAX_OVERFLOW`, `VS_DB_POOL_TIMEOUT` | 5, 10, 30 | Пул соединений с базой |
| `VS_DB_ECHO` | `false` | Печатать каждый SQL-запрос — только для отладки |
| `VS_DB_HEALTH_TIMEOUT` | 2 | Секунд на проверку базы в `/health/ready` |
| `VS_DB_SLOW_QUERY_MS` | 200 | SQL дольше — в лог как `slow_query`; `0` — выключить |
| `VS_TEST_DATABASE_URL`, `VS_TEST_REQUIRE_DB` | — | Своя база для тестов / падать, а не пропускать тесты без PostgreSQL |
| `GRAFANA_ADMIN_PASSWORD` | — | **Обязателен** для `make up`. `make env` генерирует его сам |
| `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `GRAFANA_PORT`, `ALLOY_PORT` | 8000, 5432, 6379, 3001, 12345 | Порты на вашем компьютере. Поменяйте, если порт занят другим проектом |

## База данных и миграции

PostgreSQL 16 в Docker, SQLAlchemy 2 в асинхронном режиме, миграции — Alembic.

**Как устроено**

- Модели лежат в модулях: `app/modules/<модуль>/models.py`. Все наследуются от `Base` из `app/core/db.py` —
  у неё правила имён ограничений (`pk_users`, `uq_users_email`, `fk_user_niches_user_id_users`).
- Первичный ключ — `id: Mapped[IntPK]` (BIGINT, автоинкремент). Время — `CreatedAtMixin` / `TimestampMixin`:
  `created_at` и `updated_at` с часовым поясом, значения ставит база.
- В обработчике сессия берётся из зависимости: `async def handler(session: SessionDep)`. Своя на каждый запрос.
- **Изменения сохраняются только после `await session.commit()`.** Без commit или при ошибке всё откатится.
- Связи — с `lazy="raise"`: подгружайте их явно, `select(Niche).options(selectinload(Niche.queries))`.
  Обращение к незагруженной связи — понятная ошибка, а не скрытый запрос в базу.
- Правила данных проверяет сама база: уникальность, `CHECK`, каскадное удаление. Ошибка в коде не испортит данные.

**Порядок запуска в Docker:** `postgres` → `migrate` (`alembic upgrade head`, затем завершается) → `api`.
Миграция упала — API не стартует: новый код не работает со старой схемой.

**Как изменить схему**

1. Поменяйте модель. Новую модель импортируйте в `app/models.py` — иначе Alembic её не увидит.
2. `make migration m="add login codes"` — файл `migrations/versions/0002_add_login_codes.py`.
3. **Прочитайте файл.** Autogenerate ошибается: переименование колонки видит как «удалить + создать»
   (данные пропадут), может задвоить `CHECK`. Поправьте руками.
4. `make migrate` — применить, `make downgrade` — откатить и попробовать снова.
5. `make test` — тесты проверят, что миграции применяются, откатываются и совпадают с моделями.

**Таблицы сейчас**

| Таблица | Что хранит |
|---|---|
| `users` | Клиенты. Вход по почте или Telegram — одно из двух обязательно, почта в нижнем регистре |
| `niches` | Ниши для квиза и сбора видео |
| `niche_queries` | Хештеги и аккаунты, по которым собираются видео ниши (`kind`: `hashtag` / `account`) |
| `user_niches` | Какие ниши выбрал клиент и его уточнение своими словами |

Остальные таблицы добавляются на своих этапах: коды входа (3), квиз (4), потоки (5), оплата (6), видео (7–9).

**Медленные запросы.** SQL дольше 200 мс пишется в лог как `slow_query` — с текстом запроса и `request_id`,
но без значений параметров. На дашборде API overview — панели «Медленные запросы к базе».

## Ошибки API

Любая ошибка приходит в одном формате:

```json
{"error": {"code": "no_seats", "message": "Места в потоке закончились"}}
```

- `code` — машинный код, по нему фронтенд решает, что показать.
- 422 дополнительно содержит `fields`: `[{"field", "location", "message"}]`.
- 500 содержит только общий текст и `request_id`; подробности — в логах.

В коде: `raise AppError(409, "no_seats", "Места в потоке закончились")`.

## Логи

Каждый ответ API содержит заголовок `X-Request-ID`. По нему в Grafana находится вся история запроса.

**Правила логирования:**

- Логгер в модуле: `log = get_logger(__name__)`, запись: `log.info("seat_reserved", launch=3, seats_left=11)`.
- Имена событий — `существительное_глагол_в_прошедшем`: `request_finished`, `payment_succeeded`, `video_analyzed`.
- Уровни: `debug` — подробности для разработки, `info` — нормальные события, `warning` — странно, но работает,
  `error` — операция не удалась.
- **Нельзя логировать** пароли, коды входа, токены, cookie, данные карт. Поля `password`, `code`, `token`,
  `authorization`, `cookie`, `api_key` маскируются автоматически, email сокращается до `i***@mail.ru`.
- Коды ошибок пишите в поле `error_code` — поле `code` всегда маскируется.
- Деньги и токены Claude логируются всегда (`cost_usd`, `input_tokens`) — из них строятся дашборды расходов.

**Полезные запросы** (Grafana → Explore → Loki → режим Code):

| Что ищем | LogQL |
|---|---|
| Все логи API | `{service="api"}` |
| Ошибки и предупреждения | `{service="api", level=~"warning\|error"}` |
| Один запрос по id | `{service="api"} \| json \| request_id="..."` |
| Медленные запросы | `{service="api"} \| json \| event="request_finished" \| duration_ms > 500` |
| Медленные SQL-запросы (дольше `VS_DB_SLOW_QUERY_MS`, 200 мс) | `{service="api"} \| json \| event="slow_query"` |
| Запросы по статусам за час | `sum by (status) (count_over_time({service="api"} \| json \| event="request_finished" [1h]))` |

Метки в Loki — только `service`, `container`, `env`, `level`. `request_id`, `path`, `user_id` — поля JSON,
их не делают метками: Loki начнёт тормозить.

## Тесты

```bash
make up         # PostgreSQL для тестов базы
make test       # все тесты (make check — вместе с линтером)
make test-fast  # только тесты без базы — Docker не нужен
```

- Тесты базы работают с **настоящим PostgreSQL** в отдельной базе `viralscope_test`, ваша база `viralscope` не трогается.
  При каждом запуске `viralscope_test` пересоздаётся, и к ней применяются миграции.
- Каждый тест — в транзакции, которая откатывается в конце: тесты не видят данных друг друга.
- Миграции проверяются отдельно: применяются, откатываются по одной и совпадают с моделями
  (`tests/test_migrations.py`). Забыли `make migration` после изменения модели — тест упадёт.
- PostgreSQL не запущен — тесты базы пропускаются с подсказкой `make up`. `VS_TEST_REQUIRE_DB=1` — падать вместо пропуска (для CI).
- Остальные тесты не зависят от вашего `.env` (`VS_ENV=test` задаётся в `tests/conftest.py`).

## План разработки

1. Каркас: настройки, логи, ошибки, Docker, Grafana ✓
2. **База данных и миграции (SQLAlchemy 2, Alembic)** ✓ ← сейчас
3. Вход: код на почту, Telegram, роли
4. Квиз и ниши
5. Потоки и лист ожидания
6. Тарифы, оплата, лимиты
7. Сбор видео и формула виральности
8. Лента, поиск, избранное
9. Разбор видео в Claude
10. Фоновые задачи (Celery)
11. Уведомления (Telegram, email)
12. Админка и аналитика
13. Продакшен, метрики Prometheus, оповещения
14. CI/CD и первый поток клиентов (бета)

## Частые проблемы

| Проблема | Решение |
|---|---|
| `No module named 'app'` | `make install` |
| `make up`: «задайте GRAFANA_ADMIN_PASSWORD» | `make env` |
| `make up`: `service "migrate" didn't complete successfully` | Миграция упала, API не запущен: причина в `make logs s=migrate` |
| Порт уже занят | Поменяйте `*_PORT` в `.env` (и `VS_REDIS_URL` / `VS_DATABASE_URL` для локального запуска) |
| `Target database is not up to date` при `make migration` | Сначала `make migrate`, затем снова `make migration` |
| Тесты базы пропущены (`skipped`) | PostgreSQL не запущен: `make up` |
| `InvalidRequestError: ... lazy='raise'` | Связь не загружена: добавьте `.options(selectinload(...))` в запрос |
| Логи не видны в Grafana | Подождите 5–10 секунд; проверьте `make logs s=alloy` и http://localhost:12345 |
| Сменили пароль Grafana в `.env`, а он не подходит | Пароль задаётся при первом запуске: смените в профиле Grafana или `make reset-data` |
