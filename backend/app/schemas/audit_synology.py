"""API schemas for the admin-only Synology Audit connector."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


def _strip(value: str) -> str:
    return value.strip()


class AuditSynologySaveRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=500)
    account_name: str = Field(..., min_length=1, max_length=255)
    password: SecretStr | None = Field(None, min_length=1, max_length=1024)
    otp_code: SecretStr | None = Field(None, max_length=64)
    root_path: str = Field("/", min_length=1, max_length=1000)
    expected_config_version: int | None = Field(None, ge=1)

    @field_validator("display_name", "base_url", "account_name", "root_path", mode="before")
    @classmethod
    def clean_text(cls, value):
        return _strip(value) if isinstance(value, str) else value


class AuditSynologyActivateRequest(BaseModel):
    expected_config_version: int = Field(..., ge=1)
    session_token: str | None = Field(None, min_length=32, max_length=256)
    otp_code: SecretStr | None = Field(None, max_length=64)


class AuditSynologyConnectionRead(BaseModel):
    configured: bool
    id: UUID | None = None
    display_name: str | None = None
    base_url: str | None = None
    account_name: str | None = None
    root_path: str | None = None
    enabled: bool = False
    is_active: bool = False
    credential_saved: bool = False
    config_version: int | None = None
    last_tested_at: datetime | None = None
    last_test_status: str | None = None
    last_error_code: str | None = None
    allowed_origins_configured: bool = False
    encryption_key_configured: bool = False
    updated_at: datetime | None = None


class AuditSynologyConnectionListRead(BaseModel):
    items: list[AuditSynologyConnectionRead] = Field(default_factory=list)
    allowed_origins_configured: bool = False
    encryption_key_configured: bool = False


class AuditSynologyConnectRead(BaseModel):
    session_token: str
    expires_at: datetime
    connection: AuditSynologyConnectionRead


class AuditSynologyDisconnectRequest(BaseModel):
    session_token: str = Field(..., min_length=32, max_length=256)


class AuditSynologyFileRead(BaseModel):
    item_id: str
    path_token: str
    name: str
    is_dir: bool
    size_bytes: int
    modified_at: int
    extension: str
    selectable: bool
    already_imported: bool = False
    disabled_reason: str | None = None


class AuditSynologyBrowseRequest(BaseModel):
    session_token: str = Field(..., min_length=32, max_length=256)
    folder_token: str | None = Field(None, max_length=4096)
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=200)


class AuditSynologyBrowserRead(BaseModel):
    current_folder_name: str
    root_folder_name: str
    parent_token: str | None = None
    offset: int
    total: int
    items: list[AuditSynologyFileRead] = Field(default_factory=list)


class AuditSynologySelectionRequest(BaseModel):
    session_token: str = Field(..., min_length=32, max_length=256)
    file_tokens: list[str] = Field(..., min_length=1, max_length=20)

    @field_validator("file_tokens")
    @classmethod
    def unique_paths(cls, value: list[str]):
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Путь файла не может быть пустым")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Один файл выбран несколько раз")
        return cleaned


class AuditSynologyPreviewItem(BaseModel):
    file_token: str
    name: str
    size_bytes: int
    modified_at: int
    extension: str


class AuditSynologyPreviewRead(BaseModel):
    preview_token: str
    expires_in_seconds: int
    file_count: int
    total_size_bytes: int
    items: list[AuditSynologyPreviewItem]


class AuditSynologyCommitRequest(AuditSynologySelectionRequest):
    request_id: UUID
    preview_token: str = Field(..., min_length=32, max_length=65535)
    digital_product: str | None = Field(None, max_length=255)

    @field_validator("digital_product", mode="before")
    @classmethod
    def clean_product(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class AuditSynologyImportItemRead(BaseModel):
    case_id: UUID
    case_number: str
    document_id: UUID
    file_name: str
    size_bytes: int


class AuditSynologyImportRead(BaseModel):
    imported_count: int
    total_size_bytes: int
    items: list[AuditSynologyImportItemRead]
