"""Add feedback numbers and artifacts

Revision ID: 023_feedback_request_artifacts
Revises: 022_feedback_requests
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023_feedback_request_artifacts"
down_revision = "022_feedback_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for value in ("triage", "needs_info", "planned", "withdrawn"):
        op.execute(f"ALTER TYPE feedbackstatus ADD VALUE IF NOT EXISTS '{value}'")

    object_type_enum = postgresql.ENUM("task", "shop", "report", "rule", "kb", "other", name="feedbackobjecttype")
    object_type_enum.create(bind, checkfirst=True)
    object_type_column_enum = postgresql.ENUM(
        "task", "shop", "report", "rule", "kb", "other", name="feedbackobjecttype", create_type=False
    )

    op.execute("CREATE SEQUENCE IF NOT EXISTS feedback_request_number_seq")
    op.add_column("feedback_requests", sa.Column("feedback_number", sa.Integer(), nullable=True))
    op.execute("UPDATE feedback_requests SET feedback_number = nextval('feedback_request_number_seq') WHERE feedback_number IS NULL")
    op.alter_column(
        "feedback_requests",
        "feedback_number",
        nullable=False,
        server_default=sa.text("nextval('feedback_request_number_seq'::regclass)"),
    )
    op.create_index("ix_feedback_requests_feedback_number", "feedback_requests", ["feedback_number"], unique=True)

    op.add_column(
        "feedback_requests",
        sa.Column("object_type", object_type_column_enum, nullable=False, server_default="other"),
    )
    op.add_column("feedback_requests", sa.Column("object_ref", sa.String(length=255), nullable=True))
    op.add_column("feedback_requests", sa.Column("expected_result", sa.Text(), nullable=True))
    op.add_column("feedback_requests", sa.Column("impact", sa.Text(), nullable=True))
    op.add_column(
        "feedback_requests",
        sa.Column("evidence_links", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("feedback_requests", sa.Column("decision_summary", sa.Text(), nullable=True))
    op.add_column("feedback_requests", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.add_column("feedback_requests", sa.Column("next_action", sa.Text(), nullable=True))
    op.add_column("feedback_requests", sa.Column("target_release", sa.String(length=64), nullable=True))
    op.add_column("feedback_requests", sa.Column("decided_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("feedback_requests", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_feedback_requests_decided_by_id_users", "feedback_requests", "users", ["decided_by_id"], ["id"])
    op.create_index("ix_feedback_requests_object_type", "feedback_requests", ["object_type"])
    op.create_index("ix_feedback_requests_decided_by_id", "feedback_requests", ["decided_by_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_requests_decided_by_id", table_name="feedback_requests")
    op.drop_index("ix_feedback_requests_object_type", table_name="feedback_requests")
    op.drop_constraint("fk_feedback_requests_decided_by_id_users", "feedback_requests", type_="foreignkey")
    op.drop_column("feedback_requests", "decided_at")
    op.drop_column("feedback_requests", "decided_by_id")
    op.drop_column("feedback_requests", "target_release")
    op.drop_column("feedback_requests", "next_action")
    op.drop_column("feedback_requests", "decision_reason")
    op.drop_column("feedback_requests", "decision_summary")
    op.drop_column("feedback_requests", "evidence_links")
    op.drop_column("feedback_requests", "impact")
    op.drop_column("feedback_requests", "expected_result")
    op.drop_column("feedback_requests", "object_ref")
    op.drop_column("feedback_requests", "object_type")
    op.drop_index("ix_feedback_requests_feedback_number", table_name="feedback_requests")
    op.drop_column("feedback_requests", "feedback_number")
    op.execute("DROP SEQUENCE IF EXISTS feedback_request_number_seq")
    postgresql.ENUM(name="feedbackobjecttype").drop(op.get_bind(), checkfirst=True)
