# Короткие команды для разработки ViralScope.
# Список всех команд:  make  (или make help)
#
# Окружение .venv включать не нужно: команды берут python, pytest, ruff и uvicorn прямо из .venv.

# Порты из .env (если файла нет — значения по умолчанию)
-include .env
API_PORT ?= 8000
GRAFANA_PORT ?= 3001

PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
COMPOSE := docker compose
s ?= api

.DEFAULT_GOAL := help
.PHONY: help setup venv install env run test cov lint format check up down restart rebuild ps logs \
	docs grafana clean reset-data

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

test: ## Запустить тесты
	$(BIN)/pytest -q

lint: ## Проверить код: ruff (ошибки и стиль) + формат
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Исправить код автоматически: ruff --fix + форматирование
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

check: ## Всё перед коммитом: линтер и тесты
	@$(MAKE) lint test

# ---------- Docker ----------

up: ## Поднять весь стек в фоне (api, postgres, redis, loki, alloy, grafana)
	$(COMPOSE) up --build -d
	@echo "API:     http://localhost:$(API_PORT)/docs"
	@echo "Grafana: http://localhost:$(GRAFANA_PORT)/d/api-overview  (admin / пароль из .env)"

down: ## Остановить стек (данные сохраняются)
	$(COMPOSE) down

restart: ## Перезапустить сервисы
	$(COMPOSE) restart

rebuild: ## Пересобрать и перезапустить только api
	$(COMPOSE) up --build -d api

ps: ## Статус контейнеров
	$(COMPOSE) ps

logs: ## Логи сервиса в реальном времени: make logs s=alloy (по умолчанию api)
	$(COMPOSE) logs -f $(s)

docs: ## Открыть документацию API в браузере
	open http://localhost:$(API_PORT)/docs

grafana: ## Открыть дашборд API overview в Grafana
	open http://localhost:$(GRAFANA_PORT)/d/api-overview

# ---------- Уборка ----------

clean: ## Удалить кэши Python, pytest и ruff
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

reset-data: ## ОПАСНО: остановить стек и удалить данные (база, логи, Grafana)
	@echo "Будут удалены данные PostgreSQL, Loki и Grafana этого проекта."
	@read -p "Точно удалить? Введите yes: " answer && [ "$$answer" = "yes" ]
	$(COMPOSE) down -v
