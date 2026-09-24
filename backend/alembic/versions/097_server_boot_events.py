"""Add immutable host boot events and per-source importer status.

Revision ID: 097_server_boot_events
Revises: 096_graph_documents
"""
from alembic import op
import sqlalchemy as sa


revision = "097_server_boot_events"
down_revision = "096_graph_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_boot_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("boot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uptime_seconds", sa.Float(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("source_id", "event_id", name="uq_server_boot_events_source_event"),
        sa.CheckConstraint("uptime_seconds >= 0", name="ck_server_boot_events_uptime"),
    )
    op.create_index(
        "ix_server_boot_events_boot_time", "server_boot_events", ["boot_time", "event_id", "source_id"],
    )
    op.create_table(
        "server_boot_import_status",
        sa.Column("source_id", sa.String(100), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("invalid_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflicting_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(32)),
        sa.CheckConstraint("invalid_files >= 0", name="ck_server_boot_import_invalid"),
        sa.CheckConstraint("conflicting_files >= 0", name="ck_server_boot_import_conflicting"),
        sa.CheckConstraint("checked_files >= 0", name="ck_server_boot_import_checked"),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('directory_missing', 'directory_unreadable', 'scan_failed', "
            "'invalid_files', 'conflicting_files', 'too_many_files')",
            name="ck_server_boot_import_error_code",
        ),
    )


def downgrade() -> None:
    op.drop_table("server_boot_import_status")
    op.drop_table("server_boot_events")
