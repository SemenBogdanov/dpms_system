"""Add dashboard performance indexes

Revision ID: 018_dashboard_perf
Revises: 017_new_employee_planning
"""

from alembic import op
import sqlalchemy as sa


revision = "018_dashboard_perf"
down_revision = "017_new_employee_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_notifications_type_link_created",
        "notifications",
        ["type", "link", "created_at"],
    )
    op.create_index(
        "ix_tasks_status_created",
        "tasks",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_tasks_due_open_overdue",
        "tasks",
        ["status", "is_overdue", "due_date"],
        postgresql_where=sa.text("due_date IS NOT NULL"),
    )
    op.create_index(
        "ix_tasks_focus_started_active",
        "tasks",
        ["focus_started_at"],
        postgresql_where=sa.text("focus_started_at IS NOT NULL"),
    )
    op.create_index(
        "ix_q_transactions_wallet_created_positive",
        "q_transactions",
        ["wallet_type", "created_at"],
        postgresql_where=sa.text("amount > 0"),
    )


def downgrade() -> None:
    op.drop_index("ix_q_transactions_wallet_created_positive", table_name="q_transactions")
    op.drop_index("ix_tasks_focus_started_active", table_name="tasks")
    op.drop_index("ix_tasks_due_open_overdue", table_name="tasks")
    op.drop_index("ix_tasks_status_created", table_name="tasks")
    op.drop_index("ix_notifications_type_link_created", table_name="notifications")
