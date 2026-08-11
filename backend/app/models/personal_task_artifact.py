"""Versioned documents, links, and result artifacts for personal tasks."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PersonalTaskArtifact(Base):
    """Stable artifact identity whose payload changes through immutable versions."""

    __tablename__ = "personal_task_artifacts"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('document', 'link', 'result')",
            name="ck_personal_task_artifacts_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_personal_task_artifacts_status",
        ),
        CheckConstraint(
            "current_version >= 1",
            name="ck_personal_task_artifacts_current_version",
        ),
        CheckConstraint(
            "(status = 'active' AND archived_at IS NULL) "
            "OR (status = 'archived' AND archived_at IS NOT NULL)",
            name="ck_personal_task_artifacts_archive_state",
        ),
        Index(
            "ix_personal_task_artifacts_task_status_updated",
            "task_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personal_tasks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    current_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
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
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("now()"),
    )

    versions: Mapped[list["PersonalTaskArtifactVersion"]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by=lambda: PersonalTaskArtifactVersion.version_number.desc(),
    )


class PersonalTaskArtifactVersion(Base):
    """Immutable file or link payload for one artifact revision."""

    __tablename__ = "personal_task_artifact_versions"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('file', 'link')",
            name="ck_personal_task_artifact_versions_source_kind",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_personal_task_artifact_versions_number",
        ),
        CheckConstraint(
            "(source_kind = 'file' AND url IS NULL "
            "AND original_filename IS NOT NULL AND stored_filename IS NOT NULL "
            "AND content_type IS NOT NULL AND size_bytes IS NOT NULL "
            "AND sha256 IS NOT NULL) "
            "OR (source_kind = 'link' AND url IS NOT NULL "
            "AND original_filename IS NULL AND stored_filename IS NULL "
            "AND content_type IS NULL AND size_bytes IS NULL AND sha256 IS NULL)",
            name="ck_personal_task_artifact_versions_payload",
        ),
        UniqueConstraint(
            "artifact_id",
            "version_number",
            name="uq_personal_task_artifact_versions_number",
        ),
        Index(
            "ix_personal_task_artifact_versions_artifact_created",
            "artifact_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personal_task_artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=text("now()"),
    )

    artifact: Mapped[PersonalTaskArtifact] = relationship(back_populates="versions")
