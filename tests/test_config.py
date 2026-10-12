import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**overrides) -> Settings:
    # _env_file=None — не читаем локальный .env, чтобы тест не зависел от вашего компьютера
    return Settings(_env_file=None, **overrides)


def test_defaults_for_development(monkeypatch):
    monkeypatch.delenv("VS_ENV", raising=False)  # conftest.py задаёт VS_ENV=test для всех тестов
    settings = make_settings()
    assert settings.env == "dev"
    assert settings.is_dev and not settings.is_prod
    assert settings.use_json_logs is False


def test_values_from_environment(monkeypatch):
    monkeypatch.setenv("VS_ENV", "prod")
    monkeypatch.setenv("VS_CORS_ORIGINS", '["https://viralscope.ru"]')
    monkeypatch.setenv("VS_LOG_LEVEL", "warning")
    settings = make_settings()
    assert settings.is_prod
    assert settings.cors_origins == ["https://viralscope.ru"]
    assert settings.log_level == "WARNING"  # регистр не важен
    assert settings.use_json_logs is True


def test_empty_value_means_default(monkeypatch):
    monkeypatch.setenv("VS_LOG_JSON", "")
    assert make_settings().log_json is None


def test_log_json_can_be_forced():
    assert make_settings(log_json=True).use_json_logs is True
    assert make_settings(env="prod", log_json=False).use_json_logs is False


@pytest.mark.parametrize("field, value", [("env", "staging"), ("log_level", "LOUD")])
def test_invalid_values_fail_at_startup(field, value):
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
