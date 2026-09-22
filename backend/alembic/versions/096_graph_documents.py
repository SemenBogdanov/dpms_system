"""Add owner-only server graph documents.

Revision ID: 096_graph_documents
Revises: 095_web_push
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "096_graph_documents"
down_revision = "095_web_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "client_id", name="uq_graph_documents_owner_client"),
        sa.CheckConstraint("revision >= 1", name="ck_graph_documents_revision_positive"),
        sa.CheckConstraint("payload_bytes > 0", name="ck_graph_documents_payload_bytes_positive"),
        sa.CheckConstraint("node_count >= 0", name="ck_graph_documents_node_count_nonnegative"),
        sa.CheckConstraint("edge_count >= 0", name="ck_graph_documents_edge_count_nonnegative"),
    )
    op.create_index("ix_graph_documents_owner_id", "graph_documents", ["owner_id"])
    op.create_index("ix_graph_documents_owner_updated", "graph_documents", ["owner_id", "updated_at"])


def downgrade() -> None:
    op.drop_table("graph_documents")
