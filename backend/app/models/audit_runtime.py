"""Durable state for the isolated canonical audit-tz runtime."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class AuditTZRun(Base):
    """One content-addressed canonical preflight for an immutable audit document."""

    __tablename__ = "audit_tz_runs"
    __table_args__ = (
        UniqueConstraint("run_key_hash", name="uq_audit_tz_runs_key"),
        CheckConstraint("mode = 'audit-only'", name="ck_audit_tz_runs_mode"),
        CheckConstraint(
            "source_binding IN ('contract_identifier', 'document_hash')",
            name="ck_audit_tz_runs_source_binding",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'preflight_pass', 'atomization_queued', "
            "'atomizing', 'draft_ready', 'committed', 'blocked', 'failed')",
            name="ck_audit_tz_runs_status",
        ),
        CheckConstraint("source_unit_count >= 0", name="ck_audit_tz_runs_source_units"),
        CheckConstraint("warning_count >= 0", name="ck_audit_tz_runs_warnings"),
        CheckConstraint("atom_count >= 0", name="ck_audit_tz_runs_atoms"),
        CheckConstraint("completed_batch_count >= 0", name="ck_audit_tz_runs_completed_batches"),
        CheckConstraint("total_batch_count >= 0", name="ck_audit_tz_runs_total_batches"),
        CheckConstraint(
            "completed_batch_count <= total_batch_count",
            name="ck_audit_tz_runs_batch_progress",
        ),
        Index("ix_audit_tz_runs_case_created_at", "case_id", "created_at"),
        Index("ix_audit_tz_runs_status", "status"),
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
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="audit-only")
    source_binding: Mapped[str] = mapped_column(String(24), nullable=False, default="document_hash")
    run_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifiers_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    current_phase: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    source_unit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    atom_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_ai_called: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safe_summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    audit_case = relationship("AuditCase")
    document = relationship("AuditDocument")
    skill_version = relationship("AuditAtomizationSkillVersion")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    jobs = relationship("AuditTZRuntimeJob", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship("AuditTZArtifact", back_populates="run", cascade="all, delete-orphan")


class AuditTZRuntimeJob(Base):
    """Lease-based work item consumed only by the audit runtime worker."""

    __tablename__ = "audit_tz_runtime_jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('skill_selftest', 'preflight', 'atomization')",
            name="ck_audit_tz_runtime_jobs_kind",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'blocked', 'failed')",
            name="ck_audit_tz_runtime_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_audit_tz_runtime_jobs_attempts"),
        CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_audit_tz_runtime_jobs_max_attempts"),
        CheckConstraint(
            "(kind = 'skill_selftest' AND run_id IS NULL) OR "
            "(kind IN ('preflight', 'atomization') AND run_id IS NOT NULL)",
            name="ck_audit_tz_runtime_jobs_target",
        ),
        Index(
            "uq_audit_tz_runtime_jobs_selftest",
            "skill_version_id",
            unique=True,
            postgresql_where=text("kind = 'skill_selftest'"),
        ),
        Index(
            "uq_audit_tz_runtime_jobs_preflight",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'preflight'"),
        ),
        Index(
            "uq_audit_tz_runtime_jobs_atomization",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'atomization'"),
        ),
        Index("ix_audit_tz_runtime_jobs_claim", "status", "available_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_atomization_skill_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_tz_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    skill_version = relationship("AuditAtomizationSkillVersion")
    run = relationship("AuditTZRun", back_populates="jobs")


class AuditTZArtifact(Base):
    """Content-addressed runtime artifact metadata; paths are never exposed by API."""

    __tablename__ = "audit_tz_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", name="uq_audit_tz_artifacts_run_kind"),
        CheckConstraint(
            "kind IN ('identity_report', 'gated_evidence_bundle', 'source_units', "
            "'primary_prompt', 'primary_atom_package')",
            name="ck_audit_tz_artifacts_kind",
        ),
        Index("ix_audit_tz_artifacts_run_created_at", "run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_tz_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(40), nullable=False, default="PREFLIGHT")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    path_rel: Mapped[str] = mapped_column(String(500), nullable=False)
    safe_summary_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    visible_to_user: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    run = relationship("AuditTZRun", back_populates="artifacts")
