"""Transfer journal and durable, namespace-scoped source provenance."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.audit_legacy import utc_now


def json_type():
    return JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite")


class AuditLegacyTransfer(Base):
    __tablename__ = "audit_legacy_transfers"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'previewed', 'committed', 'rolled_back')", name="ck_audit_legacy_transfers_status"),
        CheckConstraint("revision >= 1", name="ck_audit_legacy_transfers_revision"),
        UniqueConstraint("commit_key", name="uq_audit_legacy_transfers_commit_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_legacy_imports.id", ondelete="RESTRICT"), nullable=False, index=True)
    namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config: Mapped[dict] = mapped_column(json_type(), nullable=False)
    preview: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    preview_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commit_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    committed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    committed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rolled_back_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AuditLegacyProvenance(Base):
    __tablename__ = "audit_legacy_provenance"
    __table_args__ = (
        UniqueConstraint("namespace", "kind", "source_key_hash", name="uq_audit_legacy_provenance_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_legacy_transfers.id", ondelete="RESTRICT"), nullable=False, index=True)
    namespace: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_table: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditLegacyTransferRow(Base):
    __tablename__ = "audit_legacy_transfer_rows"
    __table_args__ = (UniqueConstraint("transfer_id", "row_key", name="uq_audit_legacy_transfer_rows_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_legacy_transfers.id", ondelete="RESTRICT"), nullable=False, index=True)
    row_key: Mapped[str] = mapped_column(String(100), nullable=False)
    provenance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_legacy_provenance.id", ondelete="RESTRICT"), nullable=True, index=True)
    target_table: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    owned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    before: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    after: Mapped[dict | None] = mapped_column(json_type(), nullable=True)


class AuditLegacyMetric(Base):
    __tablename__ = "audit_legacy_metrics"
    __table_args__ = (
        UniqueConstraint("case_id", "metric_date", "metric_type", "actor_scope", name="uq_audit_legacy_metrics_coverage"),
        CheckConstraint("metric_type IN ('verified', 'alpha_reviewed', 'commission_reviewed')", name="ck_audit_legacy_metrics_type"),
        CheckConstraint("value >= 0", name="ck_audit_legacy_metrics_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transfer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_legacy_transfers.id", ondelete="RESTRICT"), nullable=False, index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audit_cases.id", ondelete="RESTRICT"), nullable=False, index=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
