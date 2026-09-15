"""Explicit non-null lifecycle timestamps for immutable day requests."""
from alembic import op

revision = "091_calendar_request_guards"
down_revision = "090_calendar_controls_guide"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""ALTER TABLE audit_calendar_change_requests
        ADD CONSTRAINT ck_ac_request_lifecycle_times CHECK (
            (status NOT IN ('approved','closed') OR opened_at IS NOT NULL)
            AND (status NOT IN ('closed','rejected') OR closed_at IS NOT NULL)
            AND ("after" IS NULL OR jsonb_typeof("after")='array')
        )""")


def downgrade():
    raise RuntimeError("Lifecycle integrity must not be weakened; use a reviewed forward migration.")
