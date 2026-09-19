"""Preserve canonical atomization checkpoints per model lane.

Revision ID: 094_audit_lane_checkpoints
Revises: 093_calendar_windows_guide
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "094_audit_lane_checkpoints"
down_revision = "093_calendar_windows_guide"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "uq_audit_ai_attempts_canonical_run",
        table_name="audit_ai_atomization_attempts",
    )
    op.create_index(
        "uq_audit_ai_attempts_canonical_lane",
        "audit_ai_atomization_attempts",
        ["canonical_run_id", "provider_config_id", "provider_config_version", "model_name"],
        unique=True,
        postgresql_where=sa.text("canonical_run_id IS NOT NULL"),
    )

    op.add_column(
        "audit_tz_runtime_jobs",
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_tz_runtime_jobs_attempt",
        "audit_tz_runtime_jobs",
        "audit_ai_atomization_attempts",
        ["attempt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_audit_tz_runtime_jobs_attempt_id",
        "audit_tz_runtime_jobs",
        ["attempt_id"],
    )
    op.execute(
        sa.text(
            """
            UPDATE audit_tz_runtime_jobs AS job
            SET attempt_id = attempt.id
            FROM audit_ai_atomization_attempts AS attempt
            WHERE job.kind = 'atomization'
              AND job.run_id = attempt.canonical_run_id
            """
        )
    )
    op.drop_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        "(kind = 'skill_selftest' AND run_id IS NULL AND attempt_id IS NULL) OR "
        "(kind = 'preflight' AND run_id IS NOT NULL AND attempt_id IS NULL) OR "
        "(kind = 'atomization' AND run_id IS NOT NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE audit_ai_atomization_attempts IN SHARE ROW EXCLUSIVE MODE"
        )
    )
    has_multiple_lanes = bind.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM audit_ai_atomization_attempts
                WHERE canonical_run_id IS NOT NULL
                GROUP BY canonical_run_id
                HAVING count(*) > 1
            )
            """
        )
    ).scalar_one()
    if has_multiple_lanes:
        raise RuntimeError(
            "Cannot downgrade audit model lanes without losing historical checkpoints"
        )
    op.drop_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        "(kind = 'skill_selftest' AND run_id IS NULL) OR "
        "(kind IN ('preflight', 'atomization') AND run_id IS NOT NULL)",
    )
    op.drop_index("ix_audit_tz_runtime_jobs_attempt_id", table_name="audit_tz_runtime_jobs")
    op.drop_constraint(
        "fk_audit_tz_runtime_jobs_attempt",
        "audit_tz_runtime_jobs",
        type_="foreignkey",
    )
    op.drop_column("audit_tz_runtime_jobs", "attempt_id")

    op.drop_index(
        "uq_audit_ai_attempts_canonical_lane",
        table_name="audit_ai_atomization_attempts",
    )
    op.create_index(
        "uq_audit_ai_attempts_canonical_run",
        "audit_ai_atomization_attempts",
        ["canonical_run_id"],
        unique=True,
        postgresql_where=sa.text("canonical_run_id IS NOT NULL"),
    )
