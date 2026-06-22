"""Add updated timestamp to competency answers

Revision ID: 027_competency_answer_updated_at
Revises: 026_competency_mgmt
"""

from alembic import op
import sqlalchemy as sa


revision = "027_competency_answer_updated_at"
down_revision = "026_competency_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "competency_answers",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_competency_answers_updated_at"), "competency_answers", ["updated_at"])
    op.alter_column("competency_answers", "updated_at", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_competency_answers_updated_at"), table_name="competency_answers")
    op.drop_column("competency_answers", "updated_at")
