"""Schemas for the admin-managed OpenAI-compatible provider."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


class AIProviderUpsert(BaseModel):
    display_name: str = Field("ИИ-провайдер", min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=500)
    model_name: str = Field(..., min_length=1, max_length=255)
    api_key: SecretStr | None = Field(None, min_length=1, max_length=4096)
    enabled: bool = True
    expected_config_version: int | None = Field(None, ge=1)

    @field_validator("display_name", "base_url", "model_name", mode="before")
    @classmethod
    def clean_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class AIProviderRead(BaseModel):
    configured: bool
    id: UUID | None = None
    provider_kind: str = "openai_compatible"
    display_name: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    enabled: bool = False
    api_key_configured: bool = False
    config_version: int | None = None
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_verified_config_version: int | None = None
    ready_for_use: bool = False
    last_error_code: str | None = None
    allowed_origins_configured: bool = False
    encryption_key_configured: bool = False
    updated_at: datetime | None = None


class AIProviderList(BaseModel):
    items: list[AIProviderRead] = Field(default_factory=list)
    allowed_origins_configured: bool = False
    encryption_key_configured: bool = False


class AIProviderTestRead(BaseModel):
    ok: bool
    model_name: str
    message: str
    tested_at: datetime
