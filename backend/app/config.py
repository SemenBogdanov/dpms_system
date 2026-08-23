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

    # Provider-neutral email outbox. Production delivery stays disabled until
    # the operator explicitly configures a provider in runtime environment.
    PUBLIC_APP_URL: str = "http://localhost:5173"
    EMAIL_DELIVERY_MODE: str = "disabled"
    EMAIL_FROM_ADDRESS: str = "noreply@localhost.invalid"
    EMAIL_FROM_NAME: str = "Простосделал.рф"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True
    SMTP_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 20
    EMAIL_WORKER_POLL_SECONDS: float = 5.0
    EMAIL_WORKER_BATCH_SIZE: int = 20
    EMAIL_WORKER_LEASE_SECONDS: int = 120
    EMAIL_WORKER_MAX_ATTEMPTS: int = 5
    EMAIL_MESSAGE_DELAY_SECONDS: int = 60 * 60
    EMAIL_RETRY_MAX_SECONDS: int = 900

    # Attachments
    UPLOAD_DIR: str = "/app/uploads"
    MAX_TASK_ATTACHMENT_BYTES: int = 10 * 1024 * 1024
    MAX_TASK_ATTACHMENTS: int = 5
    MAX_PERSONAL_TASK_ARTIFACTS: int = 20
    MAX_PERSONAL_TASK_ARTIFACT_VERSIONS: int = 20

    # External integrations. Origins are exact HTTPS origins without paths.
    SYNOLOGY_ALLOWED_ORIGINS: str = ""
    SYNOLOGY_CA_BUNDLE: str | None = None
    SYNOLOGY_CONNECT_TIMEOUT_SECONDS: float = 5.0
    SYNOLOGY_READ_TIMEOUT_SECONDS: float = 45.0
    INTEGRATION_SECRET_KEY: str | None = None
    INTEGRATION_SECRET_KEY_FILE: str | None = None
    AUDIT_CONNECTOR_SECRET_KEY: str | None = None
    AI_PROVIDER_ALLOWED_ORIGINS: str = ""
    AI_PROVIDER_DEFAULT_DISPLAY_NAME: str = "ИИ-провайдер"
    AI_PROVIDER_DEFAULT_BASE_URL: str = ""
    AI_PROVIDER_DEFAULT_MODEL_NAME: str = ""
    AI_PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 5.0
    AI_PROVIDER_READ_TIMEOUT_SECONDS: float = 90.0


settings = Settings()
