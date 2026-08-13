"""Add durable email outbox and delivery documentation.

Revision ID: 057_email_outbox
Revises: 056_messages_attention
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "057_email_outbox"
down_revision = "056_messages_attention"
branch_labels = None
depends_on = None


ARTICLE_ID = "4a34cd14-8740-4e5e-aed3-e579326aa0be"
ARTICLE_SLUG = "email-uvedomleniya-o-soobshcheniyah"
ARTICLE_BODY = """# Email-уведомления о сообщениях

## Когда приходит письмо

Если принятый контакт написал вам в разделе **Сообщения**, система ставит
email-уведомление в надежную очередь. Отправка письма не задерживает сохранение
самого сообщения: даже при временной недоступности почтового сервера переписка
остается в DPMS, а доставка будет повторена автоматически.

Несколько быстрых сообщений одной переписки могут быть объединены в одно
письмо, чтобы не создавать лишний почтовый шум.

## Что находится в письме

Письмо содержит имя сотрудника, факт нового сообщения и ссылку на нужную
переписку в **Простосделал.рф**. Текст сообщения, заметка и вложения в email не
копируются. Это уменьшает риск раскрытия рабочей информации за пределами
системы.

## Что делать пользователю

1. Откройте ссылку из письма.
2. Войдите в систему, если сессия завершилась.
3. Прочитайте сообщение в соответствующей переписке.

Индикатор непрочитанных обращений внутри системы остается основным источником
актуального состояния. Email является дополнительным каналом и не заменяет
статус прочтения в DPMS.

## Если письмо не пришло

Сообщение уже сохранено в системе и доступно в разделе **Сообщения**. Почтовая
доставка выполняется отдельно и может быть временно задержана настройками
почтового сервера или фильтрами организации.
"""


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_post_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("deep_link_path", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.String(length=120), nullable=True),
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
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed')",
            name="ck_email_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_outbox_attempts",
        ),
        sa.CheckConstraint(
            "char_length(btrim(recipient_email)) BETWEEN 3 AND 255",
            name="ck_email_outbox_recipient_email",
        ),
        sa.CheckConstraint(
            "left(deep_link_path, 1) = '/' AND deep_link_path NOT LIKE '//%'",
            name="ck_email_outbox_deep_link",
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'processing' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_email_outbox_lease_state",
        ),
        sa.CheckConstraint(
            "status <> 'sent' OR (sent_at IS NOT NULL "
            "AND provider_message_id IS NOT NULL)",
            name="ck_email_outbox_sent_state",
        ),
        sa.ForeignKeyConstraint(
            ["message_post_id"],
            ["message_posts.id"],
            name="fk_email_outbox_message_post",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_email_outbox_recipient_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_email_outbox_idempotency_key",
        ),
    )
    op.create_index(
        "ix_email_outbox_delivery",
        "email_outbox",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_email_outbox_recipient_created",
        "email_outbox",
        ["recipient_user_id", "created_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                CAST(:article_id AS uuid), :slug, :title, :summary, :section,
                :body, 'published', 43, now(), now(), now()
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
            title="Email-уведомления о сообщениях",
            summary="Когда приходит письмо, какие данные оно содержит и как работает надежная доставка.",
            section="tasks",
            body=ARTICLE_BODY,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM knowledge_articles WHERE id = CAST(:article_id AS uuid)"
        ).bindparams(article_id=ARTICLE_ID)
    )
    op.drop_index("ix_email_outbox_recipient_created", table_name="email_outbox")
    op.drop_index("ix_email_outbox_delivery", table_name="email_outbox")
    op.drop_table("email_outbox")
