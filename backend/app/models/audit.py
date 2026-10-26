"""Models for audit atomization slice."""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class AuditCase(Base):
    """Audit case grouped around one contract reference."""

    __tablename__ = "audit_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'atomization', 'ready', 'archived')",
            name="ck_audit_cases_status",
        ),
        Index(
            "uq_audit_cases_contract_reference_fingerprint",
            "contract_reference_fingerprint",
            unique=True,
            postgresql_where=text("contract_reference_fingerprint IS NOT NULL"),
        ),
        Index("ix_audit_cases_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('audit_case_sequence_seq'::regclass)"),
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    digital_product: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contract_reference_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_reference_mask: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    workflow_stage: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="unassigned",
        server_default="unassigned",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    created_by = relationship("User", foreign_keys=[created_by_id])
    responsible_user = relationship("User", foreign_keys=[responsible_user_id])
    atoms = relationship(
        "AuditAtom",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="AuditAtom.sort_order.asc(), AuditAtom.item_code.asc()",
    )
    events = relationship(
        "AuditEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="AuditEvent.created_at.asc()",
    )
    documents = relationship(
        "AuditDocument",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="AuditDocument.created_at.desc()",
    )

    @property
    def case_number(self) -> str:
        if self.case_sequence is None:
            return "AUD-NEW"
        return f"AUD-{self.case_sequence:04d}"

    @property
    def code(self) -> str:
        return self.case_number


class AuditImportBatch(Base):
    """Immutable import batch metadata."""

    __tablename__ = "audit_import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('committed')", name="ck_audit_import_batches_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_sheet: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="committed")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    created_by = relationship("User", foreign_keys=[created_by_id])
    atoms = relationship("AuditAtom", back_populates="import_batch")
    events = relationship("AuditEvent", back_populates="import_batch")


class AuditTeamMember(Base):
    """Employee explicitly included in the shared audit workspace."""

    __tablename__ = "audit_team_members"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_audit_team_members_user_id"),
        CheckConstraint("role IN ('leader', 'member')", name="ck_audit_team_members_role"),
        Index("ix_audit_team_members_role", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    added_by = relationship("User", foreign_keys=[added_by_id])


class AuditAssignment(Base):
    """A contract scheduled for one audit team member on one calendar date."""

    __tablename__ = "audit_assignments"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_audit_assignments_case_id"),
        Index("ix_audit_assignments_date_assignee", "scheduled_date", "assignee_id"),
        Index("ix_audit_assignments_case_date", "case_id", "scheduled_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    audit_case = relationship("AuditCase")
    assignee = relationship("User", foreign_keys=[assignee_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])


class AuditDocument(Base):
    """Immutable source document attached to one audit case."""

    __tablename__ = "audit_documents"
    __table_args__ = (
        UniqueConstraint("case_id", "sha256", name="uq_audit_documents_case_sha256"),
        CheckConstraint(
            "kind IN ('technical_spec', 'atom_register', 'audit_result', 'protocol', 'other')",
            name="ck_audit_documents_kind",
        ),
        Index("ix_audit_documents_case_created_at", "case_id", "created_at"),
        Index("ix_audit_documents_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="technical_spec")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    case = relationship("AuditCase", back_populates="documents")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])


class AuditSynologyConnection(Base):
    """Encrypted server-side connection used only by system administrators."""

    __tablename__ = "audit_synology_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "display_name",
            name="uq_audit_synology_connections_provider_name",
        ),
        CheckConstraint("provider = 'synology'", name="ck_audit_synology_connections_provider"),
        CheckConstraint("config_version >= 1", name="ck_audit_synology_connections_version"),
        CheckConstraint(
            "NOT is_active OR (enabled AND password_ciphertext IS NOT NULL)",
            name="ck_audit_synology_connections_active_ready",
        ),
        CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('ok', 'error')",
            name="ck_audit_synology_connections_test_status",
        ),
        Index(
            "uq_audit_synology_connections_active_provider",
            "provider",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="synology")
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    imports = relationship(
        "AuditSynologyImport",
        back_populates="connection",
        passive_deletes=True,
    )
    import_batches = relationship(
        "AuditSynologyImportBatch",
        back_populates="connection",
        passive_deletes=True,
    )
    events = relationship("AuditSynologyEvent", back_populates="connection")


class AuditSynologyImportBatch(Base):
    """Idempotent result of one confirmed multi-file import."""

    __tablename__ = "audit_synology_import_batches"
    __table_args__ = (
        UniqueConstraint("request_key_hash", name="uq_audit_synology_import_batches_request_key"),
        CheckConstraint("status = 'committed'", name="ck_audit_synology_import_batches_status"),
        Index("ix_audit_synology_import_batches_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_synology_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="committed")
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    connection = relationship("AuditSynologyConnection", back_populates="import_batches")
    imported_by = relationship("User", foreign_keys=[imported_by_id])
    imports = relationship("AuditSynologyImport", back_populates="batch")


class AuditSynologyImport(Base):
    """Non-sensitive provenance for one immutable Synology file import."""

    __tablename__ = "audit_synology_imports"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_audit_synology_imports_document_id"),
        UniqueConstraint(
            "remote_path_fingerprint",
            "remote_size",
            "remote_mtime",
            name="uq_audit_synology_imports_remote_version",
        ),
        CheckConstraint("remote_size >= 0", name="ck_audit_synology_imports_remote_size"),
        CheckConstraint("remote_mtime >= 0", name="ck_audit_synology_imports_remote_mtime"),
        Index("ix_audit_synology_imports_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_synology_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_synology_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_path_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    remote_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remote_mtime: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    connection = relationship("AuditSynologyConnection", back_populates="imports")
    batch = relationship("AuditSynologyImportBatch", back_populates="imports")
    audit_case = relationship("AuditCase")
    document = relationship("AuditDocument")
    imported_by = relationship("User", foreign_keys=[imported_by_id])


class AuditSynologyEvent(Base):
    """Redacted administrative audit trail for connector operations."""

    __tablename__ = "audit_synology_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'error')", name="ck_audit_synology_events_outcome"),
        Index("ix_audit_synology_events_created_at", "created_at"),
        Index("ix_audit_synology_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_synology_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    connection = relationship("AuditSynologyConnection", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_id])


class AuditAtom(Base):
    """Atomic auditable item."""

    __tablename__ = "audit_atoms"
    __table_args__ = (
        CheckConstraint("state IN ('draft', 'ready', 'excluded')", name="ck_audit_atoms_state"),
        CheckConstraint(
            "alpha_result IS NULL OR alpha_result IN ('present', 'not_present', 'partial', 'not_applicable', 'needs_clarification')",
            name="ck_audit_atoms_alpha_result",
        ),
        CheckConstraint(
            "commission_result IS NULL OR commission_result IN ('confirmed', 'not_confirmed', 'deferred', 'not_applicable')",
            name="ck_audit_atoms_commission_result",
        ),
        Index("uq_audit_atoms_case_item_code", "case_id", "item_code", unique=True),
        Index(
            "uq_audit_atoms_case_source_fingerprint",
            "case_id",
            "source_fingerprint",
            unique=True,
            postgresql_where=text("source_fingerprint IS NOT NULL"),
        ),
        Index("ix_audit_atoms_case_sort_order", "case_id", "sort_order"),
        Index(
            "uq_audit_atoms_ai_atomization_draft_id",
            "ai_atomization_draft_id",
            unique=True,
            postgresql_where=text("ai_atomization_draft_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    digital_product: Mapped[str] = mapped_column(String(255), nullable=False)
    work_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_clause: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    source_sheet: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ai_atomization_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_ai_atom_drafts.id", ondelete="SET NULL"),
        nullable=True,
    )
    alpha_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    alpha_result_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)
    alpha_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    commission_result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    commission_result_raw: Mapped[str | None] = mapped_column(String(500), nullable=True)
    commission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    case = relationship("AuditCase", back_populates="atoms")
    import_batch = relationship("AuditImportBatch", back_populates="atoms")
    events = relationship("AuditEvent", back_populates="atom")


class AuditAIAtomizationAttempt(Base):
    """One content-addressed AI draft generation attempt."""

    __tablename__ = "audit_ai_atomization_attempts"
    __table_args__ = (
        UniqueConstraint("request_key_hash", name="uq_audit_ai_attempts_request_key"),
        UniqueConstraint("commit_key_hash", name="uq_audit_ai_attempts_commit_key"),
        CheckConstraint(
            "status IN ('running', 'draft_ready', 'failed', 'committed')",
            name="ck_audit_ai_attempts_status",
        ),
        CheckConstraint("config_version >= 1", name="ck_audit_ai_attempts_version"),
        Index("ix_audit_ai_attempts_case_created_at", "case_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_atomization_skill_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_provider_configs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_manifest_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    coverage_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    commit_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    committed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    consent_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    audit_case = relationship("AuditCase")
    document = relationship("AuditDocument")
    skill_version = relationship("AuditAtomizationSkillVersion")
    provider_config = relationship("AIProviderConfig")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    committed_by = relationship("User", foreign_keys=[committed_by_id])
    drafts = relationship(
        "AuditAIAtomDraft",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="AuditAIAtomDraft.sort_order.asc()",
    )


class AuditAIAtomDraft(Base):
    """Validated, editable AI proposal that is not yet an AuditAtom."""

    __tablename__ = "audit_ai_atom_drafts"
    __table_args__ = (
        UniqueConstraint("attempt_id", "source_fingerprint", name="uq_audit_ai_drafts_fingerprint"),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'committed')",
            name="ck_audit_ai_drafts_review_status",
        ),
        CheckConstraint(
            "confidence_percent IS NULL OR (confidence_percent >= 0 AND confidence_percent <= 100)",
            name="ck_audit_ai_drafts_confidence",
        ),
        Index("ix_audit_ai_drafts_attempt_order", "attempt_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_ai_atomization_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    digital_product: Mapped[str] = mapped_column(String(255), nullable=False)
    work_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_clause: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_refs_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    attempt = relationship("AuditAIAtomizationAttempt", back_populates="drafts")


class AuditEvent(Base):
    """Append-only audit trail."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_case_created_at", "case_id", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    atom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_atoms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_import_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    case = relationship("AuditCase", back_populates="events")
    atom = relationship("AuditAtom", back_populates="events")
    import_batch = relationship("AuditImportBatch", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_id])
