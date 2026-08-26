"""Store audit contract references encrypted for controlled reveal.

Revision ID: 076_audit_contract_reference
Revises: 075_audit_runtime_queue_control
"""

from alembic import op
import sqlalchemy as sa


revision = "076_audit_contract_reference"
down_revision = "075_audit_runtime_queue_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_cases",
        sa.Column("contract_reference_ciphertext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_cases", "contract_reference_ciphertext")
