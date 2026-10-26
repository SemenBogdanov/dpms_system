"""Add active methodology flag

Revision ID: 044_active_work_methodology
Revises: 043_work_track_methodologies
"""
from alembic import op
import sqlalchemy as sa

revision = "044_active_work_methodology"
down_revision = "043_work_track_methodologies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_work_tracks_status", "work_tracks", type_="check")
    op.create_check_constraint(
        "ck_work_tracks_status",
        "work_tracks",
        "status IN ('draft', 'active', 'paused', 'done', 'archived')",
    )
    op.alter_column("work_tracks", "status", server_default="draft")

    op.add_column("work_methodologies", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("work_methodologies", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_work_methodologies_is_active", "work_methodologies", ["is_active"])
    op.create_index(
        "uq_work_methodologies_one_active",
        "work_methodologies",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.execute("UPDATE work_tracks SET status = 'active' WHERE status = 'draft'")
    op.alter_column("work_tracks", "status", server_default="active")
    op.drop_constraint("ck_work_tracks_status", "work_tracks", type_="check")
    op.create_check_constraint(
        "ck_work_tracks_status",
        "work_tracks",
        "status IN ('active', 'paused', 'done', 'archived')",
    )

    op.drop_index("uq_work_methodologies_one_active", table_name="work_methodologies")
    op.drop_index("ix_work_methodologies_is_active", table_name="work_methodologies")
    op.drop_column("work_methodologies", "activated_at")
    op.drop_column("work_methodologies", "is_active")
