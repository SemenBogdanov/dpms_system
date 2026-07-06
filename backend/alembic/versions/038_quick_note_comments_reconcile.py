"""Reconcile quick note contacts and comments

Revision ID: 038_quick_note_comments
Revises: 037_quick_note_sharing
"""

from alembic import op

revision = "038_quick_note_comments"
down_revision = "037_quick_note_sharing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id uuid PRIMARY KEY,
            requester_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status varchar(20) NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_contacts_no_self CHECK (requester_id <> recipient_id),
            CONSTRAINT ck_contacts_status CHECK (status IN ('pending', 'accepted', 'rejected')),
            CONSTRAINT uq_contacts_pair UNIQUE (requester_id, recipient_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_requester_id ON contacts (requester_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_recipient_id ON contacts (recipient_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_status ON contacts (status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quick_note_comments (
            id uuid PRIMARY KEY,
            note_id uuid NOT NULL REFERENCES quick_notes(id) ON DELETE CASCADE,
            author_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_id uuid NULL REFERENCES quick_note_comments(id) ON DELETE CASCADE,
            body text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_quick_note_comments_note_id ON quick_note_comments (note_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quick_note_comments_author_id ON quick_note_comments (author_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_quick_note_comments_parent_id ON quick_note_comments (parent_id)")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.quick_note_feedback') IS NOT NULL THEN
                EXECUTE $sql$
                    INSERT INTO quick_note_comments (id, note_id, author_id, parent_id, body, created_at)
                    SELECT feedback.id, shares.note_id, feedback.author_id, NULL, feedback.body, feedback.created_at
                    FROM quick_note_feedback feedback
                    JOIN quick_note_shares shares ON shares.id = feedback.share_id
                    ON CONFLICT (id) DO NOTHING
                $sql$;
                EXECUTE 'DROP TABLE quick_note_feedback';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS quick_note_comments")
    op.execute("DROP TABLE IF EXISTS contacts")
