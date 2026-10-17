# Один образ на все процессы: api, migrate (миграции), позже worker и beat — отличается только команда.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1. Сначала только зависимости. Этот слой кэшируется и не пересобирается,
#    пока не изменился pyproject.toml, — поэтому правки кода собираются за секунды.
COPY pyproject.toml ./
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; open('/tmp/requirements.txt', 'w').write('\n'.join(deps))" \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# 2. Потом код и миграции.
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

# 3. Не запускаем приложение от root.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

# Docker сам проверяет, что API отвечает (в образе нет curl — используем Python).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
