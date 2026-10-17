# Короткие команды для разработки ViralScope.
# Список всех команд:  make  (или make help)
#
# Окружение .venv включать не нужно: команды берут python, pytest, ruff и uvicorn прямо из .venv.

# Порты из .env (если файла нет — значения по умолчанию)
-include .env
API_PORT ?= 8000
GRAFANA_PORT ?= 3001
POSTGRES_USER ?= viralscope
POSTGRES_DB ?= viralscope

PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
COMPOSE := docker compose
ALEMBIC := $(BIN)/alembic
s ?= api
n ?= 1

# Номер следующей миграции: 0001, 0002, ... — по самому большому номеру в migrations/versions.
# Через «=», а не «:=»: считается только когда нужен (в make migration), а не при каждом вызове make.
NEXT_REV = $(shell $(BIN)/python -c "import pathlib, re; nums = [int(m.group()) for p in pathlib.Path('migrations/versions').glob('*.py') if (m := re.match(r'[0-9]+', p.name))]; print(f'{max(nums, default=0) + 1:04d}')")

.DEFAULT_GOAL := help
.PHONY: help setup venv install env run test cov lint format check up down restart rebuild ps logs \
	test-fast docs grafana migrate migration downgrade db-status history sql seed db clean reset-data

help: ## Показать этот список
	@echo "Команды ViralScope backend:"
	@grep -hE '^[a-zA-Z_-]+:.*?## ' Makefile | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36mmake %-12s\033[0m %s\n", $$1, $$2}'

# ---------- Подготовка ----------

setup: ## Всё с нуля: окружение, зависимости, .env
	@$(MAKE) install env

venv: ## Создать виртуальное окружение .venv (если его нет)
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)

install: ## Установить/обновить зависимости в .venv
	@$(MAKE) venv
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

env: ## Создать .env из шаблона и сгенерировать пароль Grafana
	@test -f .env || (cp .env.example .env && echo "Создан .env из .env.example")
	@grep -qE '^GRAFANA_ADMIN_PASSWORD=.+' .env || \
		( sed -i '' '/^GRAFANA_ADMIN_PASSWORD=$$/d' .env && \
		  echo "GRAFANA_ADMIN_PASSWORD=$$($(PYTHON) -c 'import secrets; print(secrets.token_urlsafe(18))')" >> .env && \
		  echo "Пароль Grafana сгенерирован и записан в .env" )

# ---------- Разработка ----------

run: ## Запустить API локально с автоперезагрузкой
	$(BIN)/uvicorn app.main:app --reload --port $(API_PORT)

test: ## Все тесты. Тесты базы идут в отдельную viralscope_test — нужен make up, иначе они пропускаются
	$(BIN)/pytest -q

test-fast: ## Тесты без базы данных — не нужен Docker
	$(BIN)/pytest -q -m "not db"

lint: ## Проверить код: ruff (ошибки и стиль) + формат
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Исправить код автоматически: ruff --fix + форматирование
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

check: ## Всё перед коммитом: линтер и тесты
	@$(MAKE) lint test

# ---------- Docker ----------

up: ## Поднять весь стек в фоне (миграции применятся сами перед стартом api)
	$(COMPOSE) up --build -d
	@echo "API:     http://localhost:$(API_PORT)/docs"
	@echo "Grafana: http://localhost:$(GRAFANA_PORT)/d/api-overview  (admin / пароль из .env)"

down: ## Остановить стек (данные сохраняются)
	$(COMPOSE) down

restart: ## Перезапустить сервисы
	$(COMPOSE) restart

rebuild: ## Пересобрать и перезапустить api (сначала применятся новые миграции)
	$(COMPOSE) up --build -d api

ps: ## Статус контейнеров
	$(COMPOSE) ps

logs: ## Логи сервиса в реальном времени: make logs s=alloy (по умолчанию api)
	$(COMPOSE) logs -f $(s)

docs: ## Открыть документацию API в браузере
	open http://localhost:$(API_PORT)/docs

grafana: ## Открыть дашборд API overview в Grafana
	open http://localhost:$(GRAFANA_PORT)/d/api-overview

# ---------- База данных и миграции ----------
# Команды работают с базой из VS_DATABASE_URL (.env) — по умолчанию PostgreSQL из docker compose.
# Сначала поднимите её: make up.

migrate: ## Применить все новые миграции к базе
	$(ALEMBIC) upgrade head

migration: ## Создать миграцию из изменений моделей: make migration m="add login codes"
	@test -n "$(m)" || { echo 'Укажите описание: make migration m="add login codes"'; exit 1; }
	@if [ -z "$(empty)" ] && $(ALEMBIC) check >/dev/null 2>&1; then \
		echo "Модели и база совпадают — генерировать нечего."; \
		echo 'Пустая миграция (например, для переноса данных): make migration m="..." empty=1'; \
		exit 1; \
	fi
	$(ALEMBIC) revision $(if $(empty),,--autogenerate) -m "$(m)" --rev-id $(NEXT_REV)
	@echo ""
	@echo "Готово. Дальше:"
	@echo "  1. Прочитайте файл в migrations/versions/ — autogenerate ошибается (переименования, лишние CHECK)"
	@echo "  2. make migrate — применить;  make downgrade — откатить, если что-то не так"

downgrade: ## Откатить последнюю миграцию (make downgrade n=2 — две). Данные в удаляемых таблицах пропадут
	@echo "Текущая версия базы:"; $(ALEMBIC) current 2>/dev/null
	@read -p "Откатить миграций: $(n). Продолжить? [y/N] " answer; \
	if [ "$$answer" = "y" ]; then $(ALEMBIC) downgrade -$(n); else echo "Отменено."; fi

db-status: ## Версия базы и есть ли изменения моделей без миграции
	@echo "Версия базы:"; $(ALEMBIC) current 2>/dev/null
	@$(ALEMBIC) check >/dev/null 2>&1 \
		&& echo "Модели и база совпадают." \
		|| echo "Есть изменения моделей без миграции (или база недоступна): make migration m=\"...\""

history: ## Список миграций
	$(ALEMBIC) history --indicate-current

sql: ## Показать SQL новых миграций, не применяя их (для проверки перед продакшеном)
	@current=$$($(ALEMBIC) current 2>/dev/null | grep -oE '^[0-9a-z]+' || echo base); \
	head=$$($(ALEMBIC) heads 2>/dev/null | grep -oE '^[0-9a-z]+'); \
	if [ "$$current" = "$$head" ]; then echo "Новых миграций нет: база уже на $$current (head)."; \
	else $(ALEMBIC) upgrade $$current:head --sql; fi

seed: ## Заполнить базу стартовыми нишами и хештегами (повторный запуск ничего не дублирует)
	$(BIN)/python -m app.scripts.seed

db: ## Открыть консоль PostgreSQL (psql) в контейнере. Выход: \q
	$(COMPOSE) exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# ---------- Уборка ----------

clean: ## Удалить кэши Python, pytest и ruff
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

reset-data: ## ОПАСНО: остановить стек и удалить данные (база, логи, Grafana)
	@echo "Будут удалены данные PostgreSQL, Loki и Grafana этого проекта."
	@read -p "Точно удалить? Введите yes: " answer && [ "$$answer" = "yes" ]
	$(COMPOSE) down -v
