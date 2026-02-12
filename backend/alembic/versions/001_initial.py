"""Initial schema: users, catalog_items, tasks, q_transactions.

Revision ID: 001
Revises:
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаём enum типы один раз (checkfirst=True для повторного запуска)
    league_enum = postgresql.ENUM("C", "B", "A", name="league", create_type=True)
    user_role_enum = postgresql.ENUM(
        "executor", "teamlead", "admin", name="userrole", create_type=True
    )
    catalog_category_enum = postgresql.ENUM(
        "widget", "etl", "api", "docs", name="catalogcategory", create_type=True
    )
    complexity_enum = postgresql.ENUM("S", "M", "L", "XL", name="complexity", create_type=True)
    task_type_enum = postgresql.ENUM(
        "widget", "etl", "api", "docs", name="tasktype", create_type=True
    )
    task_status_enum = postgresql.ENUM(
        "new", "estimated", "in_queue", "in_progress", "review", "done", "cancelled",
        name="taskstatus", create_type=True,
    )
    task_priority_enum = postgresql.ENUM(
        "low", "medium", "high", "critical", name="taskpriority", create_type=True
    )
    wallet_type_enum = postgresql.ENUM("main", "karma", name="wallettype", create_type=True)

    league_enum.create(op.get_bind(), checkfirst=True)
    user_role_enum.create(op.get_bind(), checkfirst=True)
    catalog_category_enum.create(op.get_bind(), checkfirst=True)
    complexity_enum.create(op.get_bind(), checkfirst=True)
    task_type_enum.create(op.get_bind(), checkfirst=True)
    task_status_enum.create(op.get_bind(), checkfirst=True)
    task_priority_enum.create(op.get_bind(), checkfirst=True)
    wallet_type_enum.create(op.get_bind(), checkfirst=True)

    # Для колонок используем create_type=False, чтобы не создавать тип повторно
    league_t = postgresql.ENUM("C", "B", "A", name="league", create_type=False)
    user_role_t = postgresql.ENUM("executor", "teamlead", "admin", name="userrole", create_type=False)
    catalog_category_t = postgresql.ENUM("widget", "etl", "api", "docs", name="catalogcategory", create_type=False)
    complexity_t = postgresql.ENUM("S", "M", "L", "XL", name="complexity", create_type=False)
    task_type_t = postgresql.ENUM("widget", "etl", "api", "docs", name="tasktype", create_type=False)
    task_status_t = postgresql.ENUM(
        "new", "estimated", "in_queue", "in_progress", "review", "done", "cancelled",
        name="taskstatus", create_type=False,
    )
    task_priority_t = postgresql.ENUM("low", "medium", "high", "critical", name="taskpriority", create_type=False)
    wallet_type_t = postgresql.ENUM("main", "karma", name="wallettype", create_type=False)

    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("league", league_t, nullable=False),
        sa.Column("role", user_role_t, nullable=False),
        sa.Column("mpw", sa.Integer(), nullable=False),
        sa.Column("wip_limit", sa.Integer(), nullable=False),
        sa.Column("wallet_main", sa.Numeric(10, 1), nullable=False),
        sa.Column("wallet_karma", sa.Numeric(10, 1), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # catalog_items
    op.create_table(
        "catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", catalog_category_t, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("complexity", complexity_t, nullable=False),
        sa.Column("base_cost_q", sa.Numeric(5, 1), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("min_league", league_t, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # tasks
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", task_type_t, nullable=False),
        sa.Column("complexity", complexity_t, nullable=False),
        sa.Column("estimated_q", sa.Numeric(5, 1), nullable=False),
        sa.Column("priority", task_priority_t, nullable=False),
        sa.Column("status", task_status_t, nullable=False),
        sa.Column("min_league", league_t, nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("estimator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("estimation_details", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"],),
        sa.ForeignKeyConstraint(["estimator_id"], ["users.id"],),
        sa.ForeignKeyConstraint(["validator_id"], ["users.id"],),
    )

    # q_transactions
    op.create_table(
        "q_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(5, 1), nullable=False),
        sa.Column("wallet_type", wallet_type_t, nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"],),
    )


def downgrade() -> None:
    op.drop_table("q_transactions")
    op.drop_table("tasks")
    op.drop_table("catalog_items")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    postgresql.ENUM(name="wallettype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="taskpriority").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="taskstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="tasktype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="complexity").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="catalogcategory").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="userrole").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="league").drop(op.get_bind(), checkfirst=True)
