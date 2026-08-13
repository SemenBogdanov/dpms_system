"""Add focused messages, attention inbox and correspondence.

Revision ID: 056_messages_attention
Revises: 055_quick_note_collaboration
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "056_messages_attention"
down_revision = "055_quick_note_collaboration"
branch_labels = None
depends_on = None


ARTICLE_ID = "59f2a5d6-42bf-48f8-b7bf-cd17be7e8b64"
ARTICLE_SLUG = "soobshcheniya-obrashcheniya-i-vazhnoe"
ARTICLE_BODY = """# Сообщения: обращения и важное

## Для чего нужен раздел

Раздел **Сообщения** собирает только адресные события, которые требуют
внимания пользователя. Он заменяет общий колокольчик и разделяет события на
две понятные категории.

## Красный индикатор — обращения

Красная точка рядом с разделом означает, что к пользователю обратился другой
человек:

- отправил запрос на добавление в контакты;
- написал письмо или ответил в переписке;
- поделился заметкой;
- оставил новый комментарий в обсуждении общей заметки.

Несколько комментариев к одной заметке объединяются в одно обращение. Оно
снова становится непрочитанным, если после просмотра появился новый
комментарий.

## Зеленый индикатор — важное

Зеленая точка означает существенное изменение в рабочем процессе: назначение,
возврат или приемку задачи, решение по заявке, покупке или периоду. Обычные
технические события и повторяющиеся напоминания сюда не попадают.

## Вдумчивая переписка

Переписка строится по темам, а не как бесконечный чат. При создании письма
нужно выбрать принятый контакт, указать тему и написать сообщение. При
необходимости к письму можно приложить собственную заметку — доступ к ней
будет открыт получателю одновременно с отправкой.

Личные задачи к письмам не прикладываются и остаются полностью приватными.

## Как событие становится прочитанным

Открытие всего раздела не снимает все индикаторы. Обращение считается
просмотренным после открытия конкретной переписки, заметки или списка заявок
контактов. Важное событие отмечается прочитанным после открытия именно этого
события. Массовой команды «прочитать все» в разделе нет.

## Доставка и восстановление соединения

Новые адресные обращения появляются без ручного обновления страницы. Если
живое соединение временно недоступно, система периодически сверяет состояние с
сервером, поэтому непрочитанные события не теряются.
"""


def upgrade() -> None:
    op.create_table(
        "communication_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_key", sa.String(length=180), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_communication_events_actor",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_communication_events_idempotency_key",
        ),
    )
    op.create_index(
        "ix_communication_events_source_created",
        "communication_events",
        ["source_type", "source_key", "created_at"],
    )

    op.create_table(
        "user_attention_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('direct', 'important')",
            name="ck_user_attention_items_kind",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_attention_items_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["communication_events.id"],
            name="fk_user_attention_items_event",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "dedupe_key",
            name="uq_user_attention_items_user_dedupe",
        ),
    )
    op.create_index(
        "ix_user_attention_items_inbox",
        "user_attention_items",
        ["user_id", "kind", "is_read", "updated_at"],
    )

    op.create_table(
        "message_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(length=180), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(subject)) BETWEEN 1 AND 180",
            name="ck_message_threads_subject",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_message_threads_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by_id",
            "request_id",
            name="uq_message_threads_creator_request",
        ),
    )
    op.create_index(
        "ix_message_threads_updated_at",
        "message_threads",
        ["updated_at"],
    )

    op.create_table(
        "message_thread_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "unread_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "unread_count >= 0",
            name="ck_message_thread_participants_unread",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["message_threads.id"],
            name="fk_message_thread_participants_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_message_thread_participants_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "user_id",
            name="uq_message_thread_participants_thread_user",
        ),
    )
    op.create_index(
        "ix_message_thread_participants_user_unread",
        "message_thread_participants",
        ["user_id", "unread_count"],
    )

    op.create_table(
        "message_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("quick_note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(body)) BETWEEN 1 AND 20000",
            name="ck_message_posts_body",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["message_threads.id"],
            name="fk_message_posts_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name="fk_message_posts_author",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quick_note_id"],
            ["quick_notes.id"],
            name="fk_message_posts_quick_note",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "author_id",
            "request_id",
            name="uq_message_posts_author_request",
        ),
    )
    op.create_index(
        "ix_message_posts_thread_created",
        "message_posts",
        ["thread_id", "created_at"],
    )

    # Contacts are a symmetric relation. Never discard legacy rows silently:
    # stop the transactional migration if opposite-direction duplicates need
    # an explicit data decision before the unique index can be installed.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM contacts
                GROUP BY
                    LEAST(requester_id::text, recipient_id::text),
                    GREATEST(requester_id::text, recipient_id::text)
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Duplicate symmetric contact pairs require explicit reconciliation before migration 056';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_contacts_unordered_pair
        ON contacts (
            (LEAST(requester_id::text, recipient_id::text)),
            (GREATEST(requester_id::text, recipient_id::text))
        )
        """
    )

    # Preserve high-value unread items when the header bell is replaced. Noisy
    # legacy types stay in the legacy journal and do not drive the new badge.
    op.execute(
        """
        INSERT INTO communication_events (
            id, event_type, actor_id, source_type, source_key, title, body,
            link, idempotency_key, created_at
        )
        SELECT
            n.id,
            n.type,
            NULL,
            'notification',
            n.id::text,
            n.title,
            COALESCE(n.message, ''),
            n.link,
            'notification:' || n.id::text,
            n.created_at
        FROM notifications n
        WHERE n.is_read = false
          AND n.type IN (
              'task_assigned',
              'task_cancelled',
              'task_rejected',
              'task_validated',
              'task_acceptance_criteria_submitted',
              'task_acceptance_criteria_reviewed',
              'task_acceptance_decision_revised',
              'bugfix_assigned',
              'bugfix_orphan',
              'quality_alert',
              'feedback_created',
              'feedback_updated',
              'purchase_pending',
              'purchase_approved',
              'purchase_rejected',
              'rollover'
          )
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT DISTINCT ON (
                n.user_id,
                'important:' || n.type || ':' || md5(COALESCE(n.link, n.id::text))
            )
                n.id,
                n.user_id,
                'important:' || n.type || ':' || md5(COALESCE(n.link, n.id::text))
                    AS dedupe_key,
                n.created_at
            FROM notifications n
            WHERE n.is_read = false
              AND n.type IN (
                  'task_assigned',
                  'task_cancelled',
                  'task_rejected',
                  'task_validated',
                  'task_acceptance_criteria_submitted',
                  'task_acceptance_criteria_reviewed',
                  'task_acceptance_decision_revised',
                  'bugfix_assigned',
                  'bugfix_orphan',
                  'quality_alert',
                  'feedback_created',
                  'feedback_updated',
                  'purchase_pending',
                  'purchase_approved',
                  'purchase_rejected',
                  'rollover'
              )
            ORDER BY
                n.user_id,
                'important:' || n.type || ':' || md5(COALESCE(n.link, n.id::text)),
                n.created_at DESC,
                n.id DESC
        )
        INSERT INTO user_attention_items (
            id, user_id, event_id, kind, dedupe_key, is_read, read_at,
            created_at, updated_at
        )
        SELECT
            ranked.id,
            ranked.user_id,
            ranked.id,
            'important',
            ranked.dedupe_key,
            false,
            NULL,
            ranked.created_at,
            ranked.created_at
        FROM ranked
        ON CONFLICT (user_id, dedupe_key) DO UPDATE
        SET event_id = EXCLUDED.event_id,
            kind = 'important',
            is_read = false,
            read_at = NULL,
            updated_at = EXCLUDED.updated_at
        """
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                CAST(:article_id AS uuid),
                :slug,
                :title,
                :summary,
                'tasks',
                :body,
                'published',
                43,
                now(),
                now(),
                now()
            )
            ON CONFLICT (slug) DO UPDATE
            SET title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                body = EXCLUDED.body,
                status = 'published',
                updated_at = now(),
                published_at = now()
            WHERE knowledge_articles.id = CAST(:article_id AS uuid)
            """
        ).bindparams(
            article_id=ARTICLE_ID,
            slug=ARTICLE_SLUG,
            title="Сообщения: обращения и важное",
            summary="Адресная переписка, красные обращения и отфильтрованные важные события.",
            body=ARTICLE_BODY,
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_user_data = bool(
        bind.execute(
            sa.text(
                """
                SELECT
                    EXISTS (SELECT 1 FROM message_threads)
                    OR EXISTS (
                        SELECT 1
                        FROM communication_events
                        WHERE source_type <> 'notification'
                    )
                """
            )
        ).scalar()
    )
    if has_user_data:
        raise RuntimeError(
            "Downgrade 056 would delete correspondence or direct attention "
            "history. Use an application rollback without a DB downgrade, "
            "or restore a verified pre-migration backup."
        )

    op.execute(
        sa.text(
            "DELETE FROM knowledge_articles WHERE id = CAST(:article_id AS uuid)"
        ).bindparams(article_id=ARTICLE_ID)
    )
    op.execute("DROP INDEX IF EXISTS uq_contacts_unordered_pair")
    op.drop_index("ix_message_posts_thread_created", table_name="message_posts")
    op.drop_table("message_posts")
    op.drop_index(
        "ix_message_thread_participants_user_unread",
        table_name="message_thread_participants",
    )
    op.drop_table("message_thread_participants")
    op.drop_index("ix_message_threads_updated_at", table_name="message_threads")
    op.drop_table("message_threads")
    op.drop_index("ix_user_attention_items_inbox", table_name="user_attention_items")
    op.drop_table("user_attention_items")
    op.drop_index(
        "ix_communication_events_source_created",
        table_name="communication_events",
    )
    op.drop_table("communication_events")
