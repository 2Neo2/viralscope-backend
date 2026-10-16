from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Настройки приложения.

    Значения берутся из переменных окружения с префиксом VS_ (например, VS_ENV=prod)
    или из файла .env. Списки передаются в формате JSON: VS_CORS_ORIGINS='["https://viralscope.ru"]'.
    """

    model_config = SettingsConfigDict(
        env_prefix="VS_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # VS_LOG_JSON= (пусто) — значит «не задано», берём значение по умолчанию
        extra="ignore",
    )

    # Приложение
    env: Env = "dev"
    service: str = "api"  # имя процесса в логах: api, worker, beat
    app_name: str = "ViralScope API"
    version: str = "0.1.0"

    # Логи
    log_level: LogLevel = "INFO"
    log_json: bool | None = None  # None — JSON везде, кроме dev; true/false — принудительно

    # Сайт, которому разрешено ходить в API из браузера
    cors_origins: list[str] = ["http://localhost:3000"]

    # База данных
    database_url: str = "postgresql+asyncpg://viralscope:viralscope@localhost:5432/viralscope"
    db_echo: bool = False  # печатать каждый SQL-запрос — только для отладки
    db_pool_size: int = 5  # постоянных соединений в пуле
    db_max_overflow: int = 10  # дополнительных соединений при пиковой нагрузке
    db_pool_timeout: int = 30  # секунд ждать свободное соединение, затем ошибка
    db_health_timeout: float = 2.0  # секунд на проверку базы в /health/ready

    # Redis (используется с этапа 8)
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("log_level", mode="before")
    @classmethod
    def upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def use_json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else not self.is_dev


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за жизнь процесса. В тестах подменяются через dependency_overrides."""
    return Settings()
