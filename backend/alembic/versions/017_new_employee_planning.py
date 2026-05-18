"""Add new employee and plan start fields

Revision ID: 017_new_employee_planning
Revises: 016_knowledge_articles
"""

from alembic import op
import sqlalchemy as sa


revision = "017_new_employee_planning"
down_revision = "016_knowledge_articles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_new_employee", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("plan_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("onboarding_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("onboarding_until", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("users", "is_new_employee", server_default=None)
    op.alter_column(
        "period_snapshots",
        "mpw",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 1),
        existing_nullable=False,
        postgresql_using="mpw::numeric(10,1)",
    )


def downgrade() -> None:
    op.alter_column(
        "period_snapshots",
        "mpw",
        existing_type=sa.Numeric(10, 1),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(mpw)::integer",
    )
    op.drop_column("users", "onboarding_until")
    op.drop_column("users", "onboarding_started_at")
    op.drop_column("users", "plan_started_at")
    op.drop_column("users", "is_new_employee")
