"""State machine for verified changes of the email login."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class EmailChangeRequest(Base):
    """A single pending or completed email-login change request."""

    __tablename__ = "email_change_requests"
    __table_args__ = (
        CheckConstraint(
            "request_kind IN ('self', 'admin_assisted')",
            name="ck_email_change_request_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'expired', 'superseded')",
            name="ck_email_change_request_status",
        ),
        CheckConstraint(
            "char_length(btrim(old_email)) BETWEEN 3 AND 255",
            name="ck_email_change_old_email",
        ),
        CheckConstraint(
            "char_length(btrim(new_email)) BETWEEN 3 AND 255",
            name="ck_email_change_new_email",
        ),
        CheckConstraint(
            "lower(btrim(old_email)) <> lower(btrim(new_email))",
            name="ck_email_change_distinct_emails",
        ),
        CheckConstraint(
            "auth_version_at_request >= 0",
            name="ck_email_change_auth_version",
        ),
        CheckConstraint(
            "request_kind <> 'admin_assisted' OR "
            "(reason IS NOT NULL AND char_length(btrim(reason)) BETWEEN 3 AND 500)",
            name="ck_email_change_admin_reason",
        ),
        Index(
            "uq_email_change_pending_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_email_change_pending_email",
            "new_email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_email_change_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_email_change_status_expires",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    old_email: Mapped[str] = mapped_column(String(255), nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    auth_version_at_request: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
