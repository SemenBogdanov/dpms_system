"""Add custom competency management fields

Revision ID: 026_competency_mgmt
Revises: 025_competency_development
"""

from alembic import op
import sqlalchemy as sa

revision = "026_competency_mgmt"
down_revision = "025_competency_development"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "competencies",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="assigned"),
    )
    op.create_index("ix_competencies_visibility", "competencies", ["visibility"])
    op.execute("UPDATE competencies SET visibility = 'all' WHERE source = 'builtin'")


def downgrade() -> None:
    op.drop_index("ix_competencies_visibility", table_name="competencies")
    op.drop_column("competencies", "visibility")
