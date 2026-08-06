"""Explicit execution contract between a project operation and a global Q task."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkEntityExecutionContract(Base):
    """Immutable bridge from one project operation to one Q execution task."""

    __tablename__ = "work_entity_execution_contracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_work_entity_execution_contracts_status",
        ),
        CheckConstraint(
            "source IN ('linked_existing', 'created_from_operation')",
            name="ck_work_entity_execution_contracts_source",
        ),
        CheckConstraint(
            "planned_starts_at IS NULL OR planned_due_at IS NULL "
            "OR planned_due_at > planned_starts_at",
            name="ck_work_entity_execution_contracts_dates",
        ),
        CheckConstraint(
            "(status = 'active' AND released_at IS NULL AND release_reason IS NULL) "
            "OR (status = 'released' AND released_at IS NOT NULL "
            "AND release_reason IS NOT NULL)",
            name="ck_work_entity_execution_contracts_release_state",
        ),
        ForeignKeyConstraint(
            ["entity_id", "operation_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_execution_contracts_operation",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_work_entity_execution_contracts_idempotency_key",
        ),
        Index(
            "uq_work_entity_execution_contracts_active_operation",
            "entity_id",
            "operation_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_work_entity_execution_contracts_active_task",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    acceptance_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    planned_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    planned_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    released_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
