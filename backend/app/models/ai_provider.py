"""Persistent configuration and redacted events for external AI providers."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (
        UniqueConstraint("provider_kind", name="uq_ai_provider_configs_kind"),
        CheckConstraint("provider_kind = 'openai_compatible'", name="ck_ai_provider_configs_kind"),
        CheckConstraint("config_version >= 1", name="ck_ai_provider_configs_version"),
        CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('ok', 'error')",
            name="ck_ai_provider_configs_test_status",
        ),
        CheckConstraint(
            "last_verified_config_version IS NULL OR last_verified_config_version >= 1",
            name="ck_ai_provider_configs_verified_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="openai_compatible")
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_verified_config_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    events = relationship("AIProviderEvent", back_populates="provider")


class AIProviderEvent(Base):
    __tablename__ = "ai_provider_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'error')", name="ck_ai_provider_events_outcome"),
        Index("ix_ai_provider_events_created_at", "created_at"),
        Index("ix_ai_provider_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_provider_configs.id", ondelete="SET NULL"),
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
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    provider = relationship("AIProviderConfig", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_id])


class AuditAtomizationSkill(Base):
    """Admin-installed declarative methodology; it never executes code."""

    __tablename__ = "audit_atomization_skills"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_audit_atomization_skills_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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

    versions = relationship(
        "AuditAtomizationSkillVersion",
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="AuditAtomizationSkillVersion.created_at.desc()",
    )


class AuditAtomizationSkillVersion(Base):
    """Immutable imported version of an audit atomization skill."""

    __tablename__ = "audit_atomization_skill_versions"
    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "version_label",
            name="uq_audit_atomization_skill_versions_label",
        ),
        UniqueConstraint(
            "content_sha256",
            name="uq_audit_atomization_skill_versions_sha",
        ),
        CheckConstraint("schema_version = '1.0'", name="ck_audit_atomization_skill_versions_schema"),
        Index(
            "uq_audit_atomization_skill_versions_active",
            "skill_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_atomization_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_label: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    instructions_text: Mapped[str] = mapped_column(Text, nullable=False)
    rules_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    skill = relationship("AuditAtomizationSkill", back_populates="versions")
    created_by = relationship("User", foreign_keys=[created_by_id])
