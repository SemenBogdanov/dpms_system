"""Expand personal tasks into issue-lite tracker

Revision ID: 031_personal_tasks_tracker
Revises: 030_personal_tasks
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "031_personal_tasks_tracker"
down_revision = "030_personal_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS personal_tasks_task_number_seq START WITH 1000")
    op.add_column("personal_tasks", sa.Column("task_number", sa.Integer(), nullable=True))
    op.add_column("personal_tasks", sa.Column("category", sa.String(length=30), nullable=False, server_default="work"))
    op.add_column("personal_tasks", sa.Column("project", sa.String(length=200), nullable=True))
    op.add_column("personal_tasks", sa.Column("context", sa.String(length=200), nullable=True))
    op.add_column("personal_tasks", sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"))
    op.add_column("personal_tasks", sa.Column("acceptance_criteria", sa.Text(), nullable=True))
    op.add_column("personal_tasks", sa.Column("waiting_for", sa.String(length=200), nullable=True))
    op.add_column("personal_tasks", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column("personal_tasks", sa.Column("impact", sa.Integer(), nullable=True))
    op.add_column("personal_tasks", sa.Column("effort", sa.Integer(), nullable=True))
    op.add_column("personal_tasks", sa.Column("promoted_task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("personal_tasks", sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) + 999 AS number
            FROM personal_tasks
        )
        UPDATE personal_tasks
        SET task_number = numbered.number
        FROM numbered
        WHERE personal_tasks.id = numbered.id
        """
    )
    op.execute(
        """
        SELECT setval(
            'personal_tasks_task_number_seq',
            GREATEST(COALESCE((SELECT MAX(task_number) FROM personal_tasks), 999), 999)
        )
        """
    )
    op.execute("ALTER SEQUENCE personal_tasks_task_number_seq OWNED BY personal_tasks.task_number")
    op.alter_column(
        "personal_tasks",
        "task_number",
        nullable=False,
        server_default=sa.text("nextval('personal_tasks_task_number_seq'::regclass)"),
    )
    op.create_unique_constraint("uq_personal_tasks_task_number", "personal_tasks", ["task_number"])

    op.drop_constraint("ck_personal_tasks_status", "personal_tasks", type_="check")
    op.alter_column("personal_tasks", "status", server_default="inbox")
    op.create_check_constraint(
        "ck_personal_tasks_status",
        "personal_tasks",
        "status IN ('inbox', 'planned', 'next', 'in_progress', 'waiting', 'blocked', 'done', 'archived')",
    )
    op.drop_constraint("ck_personal_tasks_priority", "personal_tasks", type_="check")
    op.create_check_constraint(
        "ck_personal_tasks_priority",
        "personal_tasks",
        "priority IN ('low', 'medium', 'high', 'critical')",
    )
    op.create_check_constraint(
        "ck_personal_tasks_category",
        "personal_tasks",
        "category IN ('work', 'meeting', 'follow_up', 'research', 'decision', 'admin', 'other')",
    )
    op.create_check_constraint(
        "ck_personal_tasks_impact_range",
        "personal_tasks",
        "impact IS NULL OR (impact >= 1 AND impact <= 5)",
    )
    op.create_check_constraint(
        "ck_personal_tasks_effort_range",
        "personal_tasks",
        "effort IS NULL OR (effort >= 1 AND effort <= 5)",
    )
    op.create_foreign_key(
        "fk_personal_tasks_promoted_task_id_tasks",
        "personal_tasks",
        "tasks",
        ["promoted_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_personal_tasks_task_number", "personal_tasks", ["task_number"])
    op.create_index("ix_personal_tasks_category", "personal_tasks", ["category"])
    op.create_index("ix_personal_tasks_promoted_task_id", "personal_tasks", ["promoted_task_id"])


def downgrade() -> None:
    op.drop_index("ix_personal_tasks_promoted_task_id", table_name="personal_tasks")
    op.drop_index("ix_personal_tasks_category", table_name="personal_tasks")
    op.drop_index("ix_personal_tasks_task_number", table_name="personal_tasks")
    op.drop_constraint("fk_personal_tasks_promoted_task_id_tasks", "personal_tasks", type_="foreignkey")
    op.drop_constraint("ck_personal_tasks_effort_range", "personal_tasks", type_="check")
    op.drop_constraint("ck_personal_tasks_impact_range", "personal_tasks", type_="check")
    op.drop_constraint("ck_personal_tasks_category", "personal_tasks", type_="check")
    op.drop_constraint("ck_personal_tasks_priority", "personal_tasks", type_="check")
    op.execute("UPDATE personal_tasks SET priority = 'high' WHERE priority = 'critical'")
    op.create_check_constraint(
        "ck_personal_tasks_priority",
        "personal_tasks",
        "priority IN ('low', 'medium', 'high')",
    )
    op.drop_constraint("ck_personal_tasks_status", "personal_tasks", type_="check")
    op.alter_column("personal_tasks", "status", server_default="planned")
    op.execute(
        """
        UPDATE personal_tasks
        SET status = CASE
            WHEN status = 'archived' THEN 'archived'
            WHEN status = 'done' THEN 'done'
            WHEN status = 'in_progress' THEN 'in_progress'
            ELSE 'planned'
        END
        """
    )
    op.create_check_constraint(
        "ck_personal_tasks_status",
        "personal_tasks",
        "status IN ('planned', 'in_progress', 'done', 'archived')",
    )
    op.drop_constraint("uq_personal_tasks_task_number", "personal_tasks", type_="unique")
    op.drop_column("personal_tasks", "promoted_at")
    op.drop_column("personal_tasks", "promoted_task_id")
    op.drop_column("personal_tasks", "effort")
    op.drop_column("personal_tasks", "impact")
    op.drop_column("personal_tasks", "blocked_reason")
    op.drop_column("personal_tasks", "waiting_for")
    op.drop_column("personal_tasks", "acceptance_criteria")
    op.drop_column("personal_tasks", "tags")
    op.drop_column("personal_tasks", "context")
    op.drop_column("personal_tasks", "project")
    op.drop_column("personal_tasks", "category")
    op.drop_column("personal_tasks", "task_number")
    op.execute("DROP SEQUENCE IF EXISTS personal_tasks_task_number_seq")
