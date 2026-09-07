"""Public contract for checking uploaded workbooks, never importing their rows."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


AuditLegacyKind = Literal["cases", "atoms", "assignments", "events", "daily_totals"]
AuditLegacyField = Literal[
    "case_key", "digital_product", "contract_date", "atom_key", "title",
    "source_clause", "work_type", "object_type", "state", "alpha_result",
    "alpha_date", "commission_result", "commission_date", "system_url",
    "assignee_email", "actor_name", "assigned_at", "is_current", "occurred_at",
    "event_key", "event_type", "metric_date", "metric_type", "value",
    "workflow_stage", "contract_reference", "source_evidence_text", "notes",
    "alpha_comment", "previous_state", "ended_at", "assignment_key",
]
ColumnLetter = Annotated[str, Field(pattern=r"^[A-Z]{1,3}$")]


class AuditLegacyColumn(BaseModel):
    column: ColumnLetter
    label: str


class AuditLegacySuggestedMapping(BaseModel):
    kind: AuditLegacyKind
    fields: dict[AuditLegacyField, ColumnLetter]


class AuditLegacySheet(BaseModel):
    id: str
    name: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    formula_count: int = Field(ge=0)
    header_row: int = Field(ge=1)
    columns: list[AuditLegacyColumn]
    suggested_mapping: AuditLegacySuggestedMapping


class AuditLegacyInspection(BaseModel):
    parser_version: str
    sheets: list[AuditLegacySheet]


class AuditLegacyMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_id: str = Field(min_length=1, max_length=512)
    header_row: int = Field(ge=1, le=1048576, strict=True)
    kind: AuditLegacyKind
    fields: dict[AuditLegacyField, ColumnLetter] = Field(max_length=35)

    @field_validator("fields")
    @classmethod
    def valid_columns(cls, fields: dict) -> dict:
        for column in fields.values():
            number = 0
            for letter in column:
                number = number * 26 + ord(letter) - ord("A") + 1
            if number > 16384:
                raise ValueError("Column is outside the XLSX range")
        return fields


class AuditLegacyMappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1, strict=True)
    mapping: AuditLegacyMapping


class AuditLegacyIssue(BaseModel):
    row: int | None
    column: str | None
    code: str
    severity: Literal["error", "warning"]
    message: str


class AuditLegacyPreviewRow(BaseModel):
    row: int
    values: dict[str, str | None]


class AuditLegacyReport(BaseModel):
    sheet_id: str
    header_row: int
    kind: AuditLegacyKind
    total_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    error_rows: int = Field(ge=0)
    warning_rows: int = Field(ge=0)
    duplicate_rows: int = Field(ge=0)
    issues: list[AuditLegacyIssue]
    issue_count: int = Field(ge=0)
    preview_rows: list[AuditLegacyPreviewRow]
    columns: list[AuditLegacyColumn]
    unmapped_columns: list[str]
    ready_for_import: Literal[False]


class AuditLegacyBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sha256: str
    size_bytes: int
    status: Literal["uploaded", "checked"]
    created_at: datetime
    updated_at: datetime
    revision: int
    inspection: AuditLegacyInspection
    mapping: AuditLegacyMapping | None
    report: AuditLegacyReport | None

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
