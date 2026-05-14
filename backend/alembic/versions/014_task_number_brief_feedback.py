"""Add task number and brief feedback"""

from alembic import op
import sqlalchemy as sa


revision = "014_task_number_brief_feedback"
down_revision = "013_result_comment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS tasks_task_number_seq START WITH 1000")
    op.add_column("tasks", sa.Column("task_number", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("brief_rating", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("brief_feedback", sa.Text(), nullable=True))

    op.execute(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) + 999 AS number
            FROM tasks
        )
        UPDATE tasks
        SET task_number = numbered.number
        FROM numbered
        WHERE tasks.id = numbered.id
        """
    )
    op.execute(
        """
        SELECT setval(
            'tasks_task_number_seq',
            GREATEST(COALESCE((SELECT MAX(task_number) FROM tasks), 999), 999)
        )
        """
    )
    op.execute("ALTER SEQUENCE tasks_task_number_seq OWNED BY tasks.task_number")
    op.alter_column(
        "tasks",
        "task_number",
        nullable=False,
        server_default=sa.text("nextval('tasks_task_number_seq'::regclass)"),
    )
    op.create_unique_constraint("uq_tasks_task_number", "tasks", ["task_number"])
    op.create_check_constraint(
        "ck_tasks_brief_rating_range",
        "tasks",
        "brief_rating IS NULL OR (brief_rating >= 1 AND brief_rating <= 5)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_brief_rating_range", "tasks", type_="check")
    op.drop_constraint("uq_tasks_task_number", "tasks", type_="unique")
    op.drop_column("tasks", "brief_feedback")
    op.drop_column("tasks", "brief_rating")
    op.drop_column("tasks", "task_number")
    op.execute("DROP SEQUENCE IF EXISTS tasks_task_number_seq")
