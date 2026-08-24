"""Schemas for audit atomization slice."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


AuditCaseStatus = Literal["draft", "atomization", "ready", "archived"]
AuditWorkflowStage = Literal[
    "unassigned",
    "atomization",
    "alpha_review",
    "commission_pending",
    "fixes_required",
    "fixing",
    "recommission_pending",
    "ready",
]
AuditAtomState = Literal["draft", "ready", "excluded"]
AuditAlphaResult = Literal["present", "not_present", "partial", "not_applicable", "needs_clarification"]
AuditCommissionResult = Literal["confirmed", "not_confirmed", "deferred", "not_applicable"]
AuditTeamRole = Literal["leader", "member"]
AuditDocumentKind = Literal["technical_spec", "atom_register", "audit_result", "protocol", "other"]


def _strip_or_none(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class AuditAtomBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    digital_product: str = Field(..., min_length=1, max_length=255)
    work_type: str | None = Field(None, max_length=255)
    object_type: str | None = Field(None, max_length=255)
    source_clause: str | None = Field(None, max_length=500)
    system_url: str | None = Field(None, max_length=1000)
    notes: str | None = None
    state: AuditAtomState = "draft"
    source_sheet: str | None = Field(None, max_length=255)
    source_row: int | None = Field(None, ge=1)
    alpha_result: AuditAlphaResult | None = None
    alpha_result_raw: str | None = Field(None, max_length=500)
    alpha_date: date | None = None
    commission_result: AuditCommissionResult | None = None
    commission_result_raw: str | None = Field(None, max_length=500)
    commission_date: date | None = None
    sort_order: int = Field(default=100, ge=0)

    @field_validator(
        "title",
        "digital_product",
        "work_type",
        "object_type",
        "source_clause",
        "system_url",
        "notes",
        "source_sheet",
        "alpha_result_raw",
        "commission_result_raw",
        mode="before",
    )
    @classmethod
    def clean_text(cls, value):
        return _strip_or_none(value)


class AuditAtomCreate(AuditAtomBase):
    item_code: str | None = Field(None, max_length=40)

    @field_validator("item_code", mode="before")
    @classmethod
    def clean_item_code(cls, value):
        return _strip_or_none(value)


class AuditAtomUpdate(BaseModel):
    item_code: str | None = Field(None, max_length=40)
    title: str | None = Field(None, min_length=1, max_length=500)
    digital_product: str | None = Field(None, min_length=1, max_length=255)
    work_type: str | None = Field(None, max_length=255)
    object_type: str | None = Field(None, max_length=255)
    source_clause: str | None = Field(None, max_length=500)
    system_url: str | None = Field(None, max_length=1000)
    notes: str | None = None
    state: AuditAtomState | None = None
    source_sheet: str | None = Field(None, max_length=255)
    source_row: int | None = Field(None, ge=1)
    alpha_result: AuditAlphaResult | None = None
    alpha_result_raw: str | None = Field(None, max_length=500)
    alpha_date: date | None = None
    commission_result: AuditCommissionResult | None = None
    commission_result_raw: str | None = Field(None, max_length=500)
    commission_date: date | None = None
    sort_order: int | None = Field(None, ge=0)

    @field_validator(
        "item_code",
        "title",
        "digital_product",
        "work_type",
        "object_type",
        "source_clause",
        "system_url",
        "notes",
        "source_sheet",
        "alpha_result_raw",
        "commission_result_raw",
        mode="before",
    )
    @classmethod
    def clean_text(cls, value):
        return _strip_or_none(value)


class AuditAtomBulkStatusUpdate(BaseModel):
    atom_ids: list[UUID] = Field(..., min_length=1, max_length=1000)
    state: AuditAtomState

    @field_validator("atom_ids")
    @classmethod
    def unique_atom_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Атом выбран несколько раз")
        return values


class AuditAtomBulkStatusRead(BaseModel):
    case_id: UUID
    state: AuditAtomState
    updated_count: int
    atom_ids: list[UUID] = Field(default_factory=list)


class AuditAtomRead(BaseModel):
    id: UUID
    case_id: UUID
    item_code: str
    title: str
    digital_product: str
    work_type: str | None = None
    object_type: str | None = None
    source_clause: str | None = None
    source_evidence_text: str | None = None
    source_refs_json: list[dict] = Field(default_factory=list)
    system_url: str | None = None
    notes: str | None = None
    state: str
    source_sheet: str | None = None
    source_row: int | None = None
    source_fingerprint: str | None = None
    import_batch_id: UUID | None = None
    alpha_result: str | None = None
    alpha_result_raw: str | None = None
    alpha_date: date | None = None
    commission_result: str | None = None
    commission_result_raw: str | None = None
    commission_date: date | None = None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditCaseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    digital_product: str = Field(..., min_length=1, max_length=255)
    contract_reference: str | None = Field(None, max_length=255)
    contract_date: date | None = None
    status: AuditCaseStatus = "draft"
    workflow_stage: AuditWorkflowStage = "unassigned"
    notes: str | None = None

    @field_validator("title", "digital_product", "contract_reference", "notes", mode="before")
    @classmethod
    def clean_text(cls, value):
        return _strip_or_none(value)


class AuditCaseUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    digital_product: str | None = Field(None, min_length=1, max_length=255)
    contract_reference: str | None = Field(None, max_length=255)
    contract_date: date | None = None
    status: AuditCaseStatus | None = None
    workflow_stage: AuditWorkflowStage | None = None
    notes: str | None = None

    @field_validator("title", "digital_product", "contract_reference", "notes", mode="before")
    @classmethod
    def clean_text(cls, value):
        return _strip_or_none(value)


class AuditCaseDeleteRequest(BaseModel):
    confirmation_code: str = Field(..., min_length=1, max_length=20)
    reason: str | None = Field(None, max_length=500)

    @field_validator("confirmation_code", mode="before")
    @classmethod
    def normalize_confirmation_code(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value):
        return _strip_or_none(value)


class AuditCaseDeleteResponse(BaseModel):
    id: UUID
    case_number: str
    deleted_documents_count: int
    deleted_atoms_count: int


class AuditCaseListItem(BaseModel):
    id: UUID
    case_number: str
    code: str
    created_by_id: UUID | None = None
    responsible_user_id: UUID | None = None
    responsible_name: str | None = None
    responsible_email: str | None = None
    title: str
    digital_product: str
    contract_reference_mask: str | None = None
    contract_date: date | None = None
    status: str
    workflow_stage: AuditWorkflowStage
    notes: str | None = None
    atoms_count: int = 0
    ready_atoms_count: int = 0
    draft_atoms_count: int = 0
    excluded_atoms_count: int = 0
    alpha_passed_count: int = 0
    commission_passed_count: int = 0
    documents_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditCaseRead(AuditCaseListItem):
    atoms: list[AuditAtomRead] = Field(default_factory=list)


class AuditResponsibleUpdate(BaseModel):
    user_id: UUID | None = None


class AuditTeamMemberCreate(BaseModel):
    user_id: UUID
    role: AuditTeamRole = "member"


class AuditTeamMemberUpdate(BaseModel):
    role: AuditTeamRole


class AuditTeamMemberRead(BaseModel):
    id: UUID
    user_id: UUID
    full_name: str
    email: str
    role: AuditTeamRole
    is_active: bool
    audit_enabled: bool
    added_by_id: UUID | None = None
    created_at: datetime


class AuditTeamCandidateRead(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    is_active: bool
    audit_enabled: bool


class AuditAssignmentRead(BaseModel):
    id: UUID
    case_id: UUID
    case_number: str
    case_title: str
    digital_product: str
    case_status: AuditCaseStatus
    workflow_stage: AuditWorkflowStage
    atoms_count: int = 0
    assignee_id: UUID
    assignee_name: str
    scheduled_date: date
    assigned_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AuditAssignmentListRead(BaseModel):
    date_from: date
    date_to: date
    items: list[AuditAssignmentRead] = Field(default_factory=list)


class AuditAssignmentCellUpdate(BaseModel):
    scheduled_date: date
    assignee_id: UUID
    expected_case_ids: list[UUID] = Field(default_factory=list, max_length=200)
    case_ids: list[UUID] = Field(default_factory=list, max_length=200)
    transfer_case_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @field_validator("expected_case_ids", "case_ids", "transfer_case_ids")
    @classmethod
    def unique_case_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Договор указан несколько раз")
        return value

    @field_validator("transfer_case_ids")
    @classmethod
    def transfers_are_selected(cls, value: list[UUID], info) -> list[UUID]:
        selected = set(info.data.get("case_ids", []))
        if not set(value).issubset(selected):
            raise ValueError("Передать можно только выбранный договор")
        return value


class AuditDocumentRead(BaseModel):
    id: UUID
    case_id: UUID
    uploaded_by_id: UUID | None = None
    uploaded_by_name: str | None = None
    kind: AuditDocumentKind
    display_name: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class AuditDocumentUploadItem(BaseModel):
    case: AuditCaseRead
    document: AuditDocumentRead


class AuditDocumentBatchResponse(BaseModel):
    items: list[AuditDocumentUploadItem]


class AuditEventRead(BaseModel):
    id: UUID
    case_id: UUID
    atom_id: UUID | None = None
    import_batch_id: UUID | None = None
    actor_id: UUID | None = None
    actor_name: str | None = None
    event_type: str
    message: str
    payload_json: dict | None = None
    created_at: datetime


class AuditImportIssue(BaseModel):
    row_number: int
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"


class AuditImportPreviewRow(BaseModel):
    group_id: str
    row_number: int
    item_code: str
    contract_reference_mask: str | None = None
    contract_date: date | None = None
    title: str | None = None
    digital_product: str | None = None
    work_type: str | None = None
    object_type: str | None = None
    source_clause: str | None = None
    system_url_mask: str | None = None
    state: AuditAtomState = "draft"
    source_sheet: str | None = None
    source_row: int | None = None
    alpha_result: str | None = None
    alpha_result_raw: str | None = None
    alpha_date: date | None = None
    commission_result: str | None = None
    commission_result_raw: str | None = None
    commission_date: date | None = None
    issues: list[AuditImportIssue] = Field(default_factory=list)


class AuditImportPreviewGroup(BaseModel):
    group_id: str
    contract_reference_mask: str
    total_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int = 0
    digital_products: list[str] = Field(default_factory=list)


class AuditImportPreview(BaseModel):
    sha256: str
    source_sheet: str
    total_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int = 0
    has_errors: bool
    grouped_counts: list[AuditImportPreviewGroup] = Field(default_factory=list)
    rows: list[AuditImportPreviewRow] = Field(default_factory=list)


class AuditImportCommitCase(BaseModel):
    case_id: UUID
    case_number: str
    contract_reference_mask: str | None = None
    digital_product: str
    created: bool
    atoms_created: int
    atoms_reused: int


class AuditImportCommitResponse(BaseModel):
    batch_id: UUID
    sha256: str
    already_committed: bool = False
    case_count: int
    created_case_count: int
    created_atom_count: int
    reused_atom_count: int
    cases: list[AuditImportCommitCase] = Field(default_factory=list)
