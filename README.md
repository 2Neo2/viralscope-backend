# ViralScope backend

Бэкенд сервиса поиска виральных Reels: агент собирает видео из Instagram по нише клиента,
считает процент виральности и объясняет через Claude, почему ролик «залетел» и как снять свой.

**Статус:** этап 1 из 14 — каркас приложения. Готовы настройки, логирование, единый формат ошибок,
Docker-стек и сбор логов в Grafana. Бизнес-модули (вход, квиз, потоки, оплата, лента видео) — следующие этапы.

## Стек

| Слой | Технологии |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| Данные | PostgreSQL 16, Redis 7 (подключаются на этапах 2 и 8) |
| Логи | structlog → Docker → Grafana Alloy → Loki → Grafana |
| Тесты и качество | pytest, httpx, ruff |
| Инфраструктура | Docker, docker compose, Makefile |

## Быстрый старт

Нужны Python 3.12, Docker Desktop и `make`.

```bash
make setup   # окружение .venv, зависимости, .env с паролем Grafana
make up      # весь стек в Docker
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
| `make test` | Тесты |
| `make lint` / `make format` | Проверить / исправить код через ruff |
| `make check` | Линтер и тесты — **перед каждым коммитом** |
| `make up` / `make down` | Поднять / остановить Docker-стек |
| `make rebuild` | Пересобрать и перезапустить только API |
| `make ps` / `make logs` | Статус контейнеров / логи API (`make logs s=alloy` — другого сервиса) |
| `make docs` / `make grafana` | Открыть документацию / дашборд в браузере |
| `make migration m="..."` | Создать миграцию из изменений моделей (номер `0002`, `0003`… ставится сам) |
| `make migrate` / `make downgrade` | Применить новые миграции / откатить последнюю (`n=2` — две) |
| `make db-status` / `make history` | Версия базы и есть ли изменения без миграции / список миграций |
| `make sql` | SQL новых миграций без применения — проверить перед продакшеном |
| `make db` | Консоль PostgreSQL (`\q` — выход) |
| `make reset-data` | Удалить данные базы, логов и Grafana (спрашивает подтверждение) |

## Структура

```
app/
├── main.py              create_app(): настройки → логи → FastAPI → CORS → middleware → ошибки → /health
├── core/
│   ├── config.py        настройки из переменных окружения VS_* и .env
│   ├── logging.py       structlog: JSON или цветной вывод, контекст запроса, маскировка секретов
│   ├── errors.py        AppError и единый формат ошибок 404/405/409/422/500
│   └── middleware.py    request_id, X-Process-Time, лог request_finished
└── modules/             бизнес-модули (с этапа 3)
tests/                   pytest: настройки, логи, ошибки, /health, middleware
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
| `GRAFANA_ADMIN_PASSWORD` | — | **Обязателен** для `make up`. `make env` генерирует его сам |
| `API_PORT`, `POSTGRES_PORT`, `REDIS_PORT`, `GRAFANA_PORT`, `ALLOY_PORT` | 8000, 5432, 6379, 3001, 12345 | Порты на вашем компьютере. Поменяйте, если порт занят другим проектом |

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
| Запросы по статусам за час | `sum by (status) (count_over_time({service="api"} \| json \| event="request_finished" [1h]))` |

Метки в Loki — только `service`, `container`, `env`, `level`. `request_id`, `path`, `user_id` — поля JSON,
их не делают метками: Loki начнёт тормозить.

## Тесты

```bash
make test    # или make check — вместе с линтером
```

Тесты не зависят от вашего `.env` (`VS_ENV=test` задаётся в `tests/conftest.py`) и не требуют Docker.

## План разработки

1. **Каркас: настройки, логи, ошибки, Docker, Grafana** ← сейчас
2. База данных и миграции (SQLAlchemy 2, Alembic)
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
| Логи не видны в Grafana | Подождите 5–10 секунд; проверьте `make logs s=alloy` и http://localhost:12345 |
| Сменили пароль Grafana в `.env`, а он не подходит | Пароль задаётся при первом запуске: смените в профиле Grafana или `make reset-data` |
