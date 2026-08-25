"""Add cooperative pause and queue priority to audit atomization.

Revision ID: 075_audit_runtime_queue_control
Revises: 074_audit_atom_review
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "075_audit_runtime_queue_control"
down_revision = "074_audit_atom_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_audit_tz_runs_status", "audit_tz_runs", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_runs_status",
        "audit_tz_runs",
        "status IN ('queued', 'running', 'preflight_pass', 'atomization_queued', "
        "'atomizing', 'paused', 'draft_ready', 'committed', 'blocked', 'failed')",
    )

    op.drop_index("ix_audit_tz_runtime_jobs_claim", table_name="audit_tz_runtime_jobs")
    op.drop_constraint(
        "ck_audit_tz_runtime_jobs_status", "audit_tz_runtime_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_status",
        "audit_tz_runtime_jobs",
        "status IN ('queued', 'running', 'paused', 'succeeded', 'blocked', 'failed')",
    )
    op.add_column(
        "audit_tz_runtime_jobs",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_tz_runtime_jobs",
        sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "audit_tz_runtime_jobs",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "audit_tz_runtime_jobs",
        sa.Column(
            "pause_requested_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_audit_tz_runtime_jobs_pause_requested_by",
        "audit_tz_runtime_jobs",
        "users",
        ["pause_requested_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_audit_tz_runtime_jobs_pause_requested_by_id",
        "audit_tz_runtime_jobs",
        ["pause_requested_by_id"],
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_priority",
        "audit_tz_runtime_jobs",
        "priority BETWEEN 0 AND 100",
    )
    op.create_index(
        "ix_audit_tz_runtime_jobs_claim",
        "audit_tz_runtime_jobs",
        ["status", "priority", "available_at", "created_at"],
    )


def downgrade() -> None:
    op.execute(
        "UPDATE audit_tz_runtime_jobs SET status = 'queued', pause_requested_at = NULL, "
        "paused_at = NULL, pause_requested_by_id = NULL, priority = 0 WHERE status = 'paused'"
    )
    op.execute(
        "UPDATE audit_tz_runs SET status = 'atomization_queued', "
        "current_phase = 'atomization_queued' WHERE status = 'paused'"
    )
    op.drop_index("ix_audit_tz_runtime_jobs_claim", table_name="audit_tz_runtime_jobs")
    op.drop_constraint(
        "ck_audit_tz_runtime_jobs_priority", "audit_tz_runtime_jobs", type_="check"
    )
    op.drop_index(
        "ix_audit_tz_runtime_jobs_pause_requested_by_id",
        table_name="audit_tz_runtime_jobs",
    )
    op.drop_constraint(
        "fk_audit_tz_runtime_jobs_pause_requested_by",
        "audit_tz_runtime_jobs",
        type_="foreignkey",
    )
    op.drop_column("audit_tz_runtime_jobs", "pause_requested_by_id")
    op.drop_column("audit_tz_runtime_jobs", "paused_at")
    op.drop_column("audit_tz_runtime_jobs", "pause_requested_at")
    op.drop_column("audit_tz_runtime_jobs", "priority")
    op.drop_constraint(
        "ck_audit_tz_runtime_jobs_status", "audit_tz_runtime_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_status",
        "audit_tz_runtime_jobs",
        "status IN ('queued', 'running', 'succeeded', 'blocked', 'failed')",
    )
    op.create_index(
        "ix_audit_tz_runtime_jobs_claim",
        "audit_tz_runtime_jobs",
        ["status", "available_at", "created_at"],
    )

    op.drop_constraint("ck_audit_tz_runs_status", "audit_tz_runs", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_runs_status",
        "audit_tz_runs",
        "status IN ('queued', 'running', 'preflight_pass', 'atomization_queued', "
        "'atomizing', 'draft_ready', 'committed', 'blocked', 'failed')",
    )
