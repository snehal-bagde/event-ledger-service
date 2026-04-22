from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    SECRET_KEY: str = "change-me"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/event_ledger"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = True

    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_EVENTS_POST: str = "500/minute"

    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # How many hours before a 'processed' transaction is flagged as stale
    PROCESSED_STALE_HOURS: int = 24

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
