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

    # Database schema (optional, default: public)
    DB_SCHEMA: str | None = None

    # JWT
    DPMS_SECRET_KEY: str = "dev-secret-key-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 часов

    # Attachments
    UPLOAD_DIR: str = "/app/uploads"
    MAX_TASK_ATTACHMENT_BYTES: int = 10 * 1024 * 1024
    MAX_TASK_ATTACHMENTS: int = 5

    # External integrations. Synology origins are exact HTTPS origins,
    # for example: https://nas.example.org:5001
    SYNOLOGY_ALLOWED_ORIGINS: str = ""
    SYNOLOGY_CA_BUNDLE: str | None = None
    SYNOLOGY_CONNECT_TIMEOUT_SECONDS: float = 5.0
    SYNOLOGY_READ_TIMEOUT_SECONDS: float = 45.0
    # Dedicated encryption key for all external connector secrets/tokens.
    INTEGRATION_SECRET_KEY: str | None = None
    INTEGRATION_SECRET_KEY_FILE: str | None = None
    # Backward-compatible name used by the unfinished Audit connector branch.
    AUDIT_CONNECTOR_SECRET_KEY: str | None = None
    AI_PROVIDER_ALLOWED_ORIGINS: str = ""
    AI_PROVIDER_DEFAULT_DISPLAY_NAME: str = "ИИ-провайдер"
    AI_PROVIDER_DEFAULT_BASE_URL: str = ""
    AI_PROVIDER_DEFAULT_MODEL_NAME: str = ""
    AI_PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 5.0
    AI_PROVIDER_READ_TIMEOUT_SECONDS: float = 90.0


settings = Settings()
