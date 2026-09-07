"""Admin-only A1.9 transfer contract. Row keys are returned by preview, not guessed by clients."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.audit_legacy import AuditLegacyKind, AuditLegacyMapping, ColumnLetter


TransferField = Literal[
    "case_key", "digital_product", "contract_date", "atom_key", "title",
    "source_clause", "work_type", "object_type", "state", "previous_state",
    "alpha_result", "alpha_date", "commission_result", "commission_date",
    "system_url", "assignee_email", "actor_name", "assigned_at", "is_current",
    "occurred_at", "event_key", "event_type", "metric_date", "metric_type", "value",
    "assignment_key", "ended_at",
    "workflow_stage", "contract_reference", "source_evidence_text", "notes", "alpha_comment",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransferDataset(AuditLegacyMapping):
    fields: dict[TransferField, ColumnLetter] = Field(default_factory=dict, max_length=40)
    defaults: dict[TransferField, str] = Field(default_factory=dict, max_length=40)
    value_maps: dict[TransferField, dict[str, str]] = Field(default_factory=dict, max_length=40)
    atom_key_mode: Literal["column", "content"] = "column"
    row_from: int | None = Field(default=None, ge=1, le=1048576, strict=True)
    row_to: int | None = Field(default=None, ge=1, le=1048576, strict=True)


class TransferCaseDecision(StrictModel):
    mode: Literal["existing", "create"]
    target_case_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    digital_product: str | None = Field(default=None, min_length=1, max_length=255)
    contract_date: date | None = None
    fill_empty: list[Literal["title", "digital_product", "contract_date"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def target_matches_mode(self):
        if (self.mode == "existing") != (self.target_case_id is not None):
            raise ValueError("existing requires target_case_id; create forbids it")
        if self.mode == "create" and self.fill_empty:
            raise ValueError("fill_empty applies to an existing case only")
        return self


class TransferActorDecision(StrictModel):
    mode: Literal["user", "historical"]
    user_id: UUID | None = None
    historical_name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def actor_matches_mode(self):
        if self.mode == "user" and (self.user_id is None or self.historical_name is not None):
            raise ValueError("user requires user_id only")
        if self.mode == "historical" and (self.user_id is not None or not (self.historical_name or "").strip()):
            raise ValueError("historical requires a nonblank historical_name only")
        return self


class TransferRowDecision(StrictModel):
    action: Literal["create", "reuse", "fill_empty", "skip"]
    target_id: UUID | None = None
    fill_empty: list[Literal[
        "title", "digital_product", "work_type", "object_type", "source_clause",
        "system_url", "alpha_result", "alpha_date", "commission_result", "commission_date",
        "source_evidence_text", "notes", "alpha_comment",
    ]] = Field(default_factory=list)

    @model_validator(mode="after")
    def action_matches_target(self):
        if self.action in ("reuse", "fill_empty") and self.target_id is None:
            raise ValueError("reuse/fill_empty requires target_id")
        if self.action in ("create", "skip") and self.target_id is not None:
            raise ValueError("create/skip forbids target_id")
        if self.action != "fill_empty" and self.fill_empty:
            raise ValueError("fill_empty fields require the fill_empty action")
        return self


class TransferConfig(StrictModel):
    namespace: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    datasets: list[TransferDataset] = Field(min_length=1, max_length=50)
    cases: dict[str, TransferCaseDecision] = Field(default_factory=dict, max_length=30000)
    actors: dict[str, TransferActorDecision] = Field(default_factory=dict, max_length=30000)
    row_decisions: dict[str, TransferRowDecision] = Field(default_factory=dict, max_length=30000)
    apply_current_assignments: bool = Field(default=False, strict=True)


class TransferCreate(StrictModel):
    source_id: UUID
    config: TransferConfig


class TransferRevision(StrictModel):
    revision: int = Field(ge=1, strict=True)


class TransferConfigUpdate(TransferRevision):
    config: TransferConfig


class TransferCommit(TransferRevision):
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: bool = Field(strict=True)

    @model_validator(mode="after")
    def confirmed(self):
        if not self.confirm:
            raise ValueError("explicit confirmation is required")
        return self


class TransferRollback(TransferRevision):
    reason: str = Field(min_length=3, max_length=1000)
    confirm: bool = Field(strict=True)

    @model_validator(mode="after")
    def confirmed(self):
        if not self.confirm or len(self.reason.strip()) < 3:
            raise ValueError("explicit confirmation and a nonblank reason are required")
        return self


class TransferIssue(StrictModel):
    sheet_id: str | None = None
    row: int | None = None
    field: str | None = None
    code: str
    severity: Literal["error", "warning"]
    message: str


class TransferPreviewRow(StrictModel):
    row_key: str
    kind: AuditLegacyKind
    sheet_id: str
    row: int | None
    source_key: str
    outcome: Literal["create", "reuse", "fill_empty", "duplicate", "skip", "blocked"]
    target_id: UUID | None = None
    changes: dict = Field(default_factory=dict)
    issues: list[TransferIssue] = Field(default_factory=list)


class TransferPreview(StrictModel):
    revision: int
    preview_hash: str
    ready: bool
    counts: dict[str, int]
    issues: list[TransferIssue]
    rows: list[TransferPreviewRow]
    total_rows: int
    next_offset: int | None


class TransferPreviewPage(StrictModel):
    revision: int
    preview_hash: str
    rows: list[TransferPreviewRow]
    total_rows: int
    next_offset: int | None


class TransferRead(StrictModel):
    id: UUID
    source_id: UUID
    namespace: str
    status: Literal["draft", "previewed", "committed", "rolled_back"]
    revision: int
    config: TransferConfig
    preview: TransferPreview | None
    summary: dict
    committed_at: datetime | None
    rolled_back_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TransferOptions(StrictModel):
    source_id: UUID | None
    inspection: dict | None
    cases: list[dict]
    users: list[dict]
    kinds: list[str]
    fields: list[str]
    canonical_labels: dict[str, list[str]]
