"""Настройки приложения (pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация DPMS."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # База данных
    DATABASE_URL: str = "postgresql+asyncpg://dpms_user:dpms_pass@localhost:5432/dpms"

    # Приложение
    APP_TITLE: str = "DPMS API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # JWT
    DPMS_SECRET_KEY: str = "dev-secret-key-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 часов


settings = Settings()
