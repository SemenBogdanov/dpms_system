"""Add feedback requests

Revision ID: 022_feedback_requests
Revises: 021_global_holidays
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "022_feedback_requests"
down_revision = "021_global_holidays"
branch_labels = None
depends_on = None


def upgrade() -> None:
    category_enum = postgresql.ENUM("improvement", "disagreement", "bug", "process", "other", name="feedbackcategory")
    status_enum = postgresql.ENUM("new", "in_review", "accepted", "rejected", "done", name="feedbackstatus")
    priority_enum = postgresql.ENUM("low", "medium", "high", name="feedbackpriority")
    category_enum.create(op.get_bind(), checkfirst=True)
    status_enum.create(op.get_bind(), checkfirst=True)
    priority_enum.create(op.get_bind(), checkfirst=True)

    category_column_enum = postgresql.ENUM(
        "improvement", "disagreement", "bug", "process", "other", name="feedbackcategory", create_type=False
    )
    status_column_enum = postgresql.ENUM(
        "new", "in_review", "accepted", "rejected", "done", name="feedbackstatus", create_type=False
    )
    priority_column_enum = postgresql.ENUM("low", "medium", "high", name="feedbackpriority", create_type=False)

    op.create_table(
        "feedback_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", category_column_enum, nullable=False),
        sa.Column("status", status_column_enum, nullable=False),
        sa.Column("priority", priority_column_enum, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_requests_author_id", "feedback_requests", ["author_id"])
    op.create_index("ix_feedback_requests_reviewer_id", "feedback_requests", ["reviewer_id"])
    op.create_index("ix_feedback_requests_category", "feedback_requests", ["category"])
    op.create_index("ix_feedback_requests_status", "feedback_requests", ["status"])
    op.create_index("ix_feedback_requests_priority", "feedback_requests", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_feedback_requests_priority", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_status", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_category", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_reviewer_id", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_author_id", table_name="feedback_requests")
    op.drop_table("feedback_requests")
    sa.Enum(name="feedbackpriority").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="feedbackstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="feedbackcategory").drop(op.get_bind(), checkfirst=True)
