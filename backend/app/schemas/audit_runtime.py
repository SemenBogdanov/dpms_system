"""API contracts for canonical audit-tz preflight runs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditTZRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    document_id: UUID
    skill_version_id: UUID


class AuditTZArtifactRead(BaseModel):
    kind: Literal[
        "identity_report",
        "gated_evidence_bundle",
        "source_units",
        "primary_prompt",
        "primary_atom_package",
    ]
    sha256: str
    safe_summary: dict = Field(default_factory=dict)


class AuditTZRunRead(BaseModel):
    id: UUID
    case_id: UUID
    document_id: UUID
    skill_version_id: UUID
    skill_name: str
    skill_version: str
    status: Literal[
        "queued",
        "running",
        "preflight_pass",
        "atomization_queued",
        "atomizing",
        "draft_ready",
        "committed",
        "blocked",
        "failed",
    ]
    current_phase: str
    source_unit_count: int = 0
    warning_count: int = 0
    atom_count: int = 0
    completed_batch_count: int = 0
    total_batch_count: int = 0
    safe_summary: dict = Field(default_factory=dict)
    error_code: str | None = None
    artifacts: list[AuditTZArtifactRead] = Field(default_factory=list)
    external_ai_called: bool = False
    ai_attempt_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AuditTZRunList(BaseModel):
    items: list[AuditTZRunRead] = Field(default_factory=list)


class AuditTZAtomizationPreviewRead(BaseModel):
    consent_token: str
    provider_id: UUID
    provider_name: str
    model_name: str
    source_unit_count: int
    outbound_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AuditTZAtomizationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    provider_id: UUID
    consent_token: str = Field(..., min_length=40, max_length=4096)
    data_transfer_confirmed: bool = False

    @model_validator(mode="after")
    def require_transfer_confirmation(self):
        if not self.data_transfer_confirmed:
            raise ValueError("Подтвердите передачу обезличенных фрагментов выбранному ИИ-провайдеру")
        return self
