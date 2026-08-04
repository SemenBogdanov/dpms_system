"""Index administrative user audit events by target employee.

Revision ID: 052_admin_user_audit
Revises: 051_acceptance_revisions
"""
from alembic import op


revision = "052_admin_user_audit"
down_revision = "051_acceptance_revisions"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_activity_events_admin_target_occurred"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {INDEX_NAME}
            ON activity_events ((metadata->>'target_user_id'), occurred_at DESC)
            WHERE event_type IN (
                'authn_user_created',
                'admin_user_updated',
                'authn_temporary_password_issued'
            )
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
