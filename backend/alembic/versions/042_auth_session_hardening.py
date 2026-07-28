"""Harden password setup and JWT session invalidation

Revision ID: 042_auth_session_hardening
Revises: 041_task_review_events
"""

from alembic import op
from passlib.context import CryptContext
import sqlalchemy as sa


revision = "042_auth_session_hardening"
down_revision = "041_task_review_events"
branch_labels = None
depends_on = None


def _has_valid_active_admin_password() -> bool:
    bind = op.get_bind()
    total_users = bind.scalar(sa.text("SELECT count(*) FROM users"))
    if not total_users:
        return True

    password_hashes = bind.execute(
        sa.text(
            "SELECT password_hash FROM users "
            "WHERE is_active IS TRUE AND role = 'admin' AND password_hash IS NOT NULL"
        )
    ).scalars()
    bcrypt = CryptContext(schemes=["bcrypt"], deprecated="auto").handler()
    for password_hash in password_hashes:
        try:
            bcrypt.from_string(password_hash)
            return True
        except (TypeError, ValueError):
            continue
    return False


def upgrade() -> None:
    if not _has_valid_active_admin_password():
        raise RuntimeError(
            "Authentication hardening migration blocked: no active admin has a valid "
            "password hash. Restore one through the approved recovery procedure before upgrading."
        )

    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE users "
            "SET password_change_required = TRUE "
            "WHERE password_hash IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("users", "temporary_password_expires_at")
    op.drop_column("users", "password_change_required")
    op.drop_column("users", "auth_version")
