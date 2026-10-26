"""Schemas for declarative audit skills and human-reviewed AI atom drafts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AuditAtomizationSkillPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    slug: str = Field(..., min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(..., min_length=2, max_length=160)
    version: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(None, max_length=2000)
    instructions: str = Field(..., min_length=50, max_length=10_000)
    rules: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("slug", "name", "version", "description", "instructions", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("rules", mode="before")
    @classmethod
    def clean_rules(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @field_validator("rules")
    @classmethod
    def validate_rules(cls, value: list[str]) -> list[str]:
        if any(len(item) > 1000 for item in value):
            raise ValueError("Каждое правило skill должно быть не длиннее 1000 символов")
        return value


class AuditAtomizationSkillVersionRead(BaseModel):
    id: UUID
    skill_id: UUID
    slug: str
    name: str
    description: str | None = None
    version: str
    schema_version: str
    content_sha256: str
    source_filename: str
    is_enabled: bool
    is_active: bool
    created_at: datetime
    activated_at: datetime | None = None


class AuditAtomizationSkillList(BaseModel):
    items: list[AuditAtomizationSkillVersionRead] = Field(default_factory=list)


class AuditAIAtomizationStart(BaseModel):
    document_id: UUID
    skill_version_id: UUID
    request_id: UUID
    data_transfer_confirmed: bool = False

    @model_validator(mode="after")
    def require_consent(self):
        if not self.data_transfer_confirmed:
            raise ValueError("Подтвердите передачу текста документа выбранному ИИ-провайдеру")
        return self


class AuditAISourceRefRead(BaseModel):
    source_unit_id: str
    locator: str
    excerpt: str


class AuditAIAtomDraftRead(BaseModel):
    id: UUID
    title: str
    digital_product: str
    work_type: str | None = None
    object_type: str | None = None
    source_clause: str
    notes: str | None = None
    confidence_percent: int | None = None
    review_status: str
    sort_order: int
    source_refs: list[AuditAISourceRefRead] = Field(default_factory=list)


class AuditAIAtomizationAttemptRead(BaseModel):
    id: UUID
    case_id: UUID
    document_id: UUID
    skill_version_id: UUID
    skill_name: str
    skill_version: str
    status: str
    config_version: int
    model_name: str
    document_sha256: str
    skill_sha256: str
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    drafts: list[AuditAIAtomDraftRead] = Field(default_factory=list)
    created_at: datetime
    committed_at: datetime | None = None


class AuditAIAtomDraftCommitItem(BaseModel):
    id: UUID
    included: bool = True
    title: str = Field(..., min_length=1, max_length=500)
    digital_product: str = Field(..., min_length=1, max_length=255)
    work_type: str | None = Field(None, max_length=255)
    object_type: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=4000)

    @field_validator("title", "digital_product", "work_type", "object_type", "notes", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class AuditAIAtomizationCommit(BaseModel):
    request_id: UUID
    expected_config_version: int = Field(..., ge=1)
    drafts: list[AuditAIAtomDraftCommitItem] = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_selected_draft(self):
        if not any(item.included for item in self.drafts):
            raise ValueError("Выберите хотя бы один атом")
        ids = [item.id for item in self.drafts]
        if len(set(ids)) != len(ids):
            raise ValueError("Черновик атома передан несколько раз")
        return self


class AuditAIAtomizationCommitRead(BaseModel):
    attempt_id: UUID
    case_id: UUID
    atoms_created: int
    atom_ids: list[UUID] = Field(default_factory=list)
    already_committed: bool = False
