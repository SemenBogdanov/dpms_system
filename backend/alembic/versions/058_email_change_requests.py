"""Add verified email-login change requests.

Revision ID: 058_email_change_requests
Revises: 057_email_outbox
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "058_email_change_requests"
down_revision = "057_email_outbox"
branch_labels = None
depends_on = None


ARTICLE_ID = "7c8dc04d-6bd0-48ee-94dd-61af4d37df58"
ARTICLE_SLUG = "bezopasnaya-smena-email-logina"
ARTICLE_BODY = """# Безопасная смена email-логина

Email в DPMS одновременно является адресом связи и логином. Поэтому его нельзя
заменить обычным редактированием профиля: система должна убедиться, что новый
адрес принадлежит сотруднику, и завершить старые сеансы.

## Самостоятельная смена

1. Откройте **Настройки** и нажмите **Изменить email**.
2. Укажите новый адрес и текущий пароль.
3. Откройте письмо на новом адресе и явно подтвердите изменение.
4. После подтверждения войдите заново, используя новый email и прежний пароль.

На старый адрес приходит отдельное предупреждение. Если запрос создавали не вы,
его можно отменить по ссылке из этого письма. Ссылка действует ограниченное время
и используется только один раз.

## Смена с помощью администратора

Администратор может инициировать процедуру для сотрудника, например при замене
корпоративного адреса личным. Администратор указывает новый email и обязательную
причину, но не может подтвердить адрес вместо сотрудника. Изменение вступает в
силу только после подтверждения из нового почтового ящика.

## Что происходит с доступом

После успешной смены все ранее открытые сессии завершаются. Пароль не меняется,
но следующий вход выполняется уже с новым email. Незавершенный запрос можно
отменить в настройках; новый запрос заменяет предыдущий.

## Аудит и безопасность

Создание, подтверждение, отмена и замена заявки записываются в историю
администрирования сотрудника. Секретные ссылки и пароли в журнал не попадают.
Если срок ссылки истек или учетная запись изменилась после создания заявки,
нужно начать процедуру заново.
"""


def upgrade() -> None:
    op.create_table(
        "email_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_kind", sa.String(length=20), nullable=False),
        sa.Column("old_email", sa.String(length=255), nullable=False),
        sa.Column("new_email", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("auth_version_at_request", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "request_kind IN ('self', 'admin_assisted')",
            name="ck_email_change_request_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled', 'expired', 'superseded')",
            name="ck_email_change_request_status",
        ),
        sa.CheckConstraint(
            "char_length(btrim(old_email)) BETWEEN 3 AND 255",
            name="ck_email_change_old_email",
        ),
        sa.CheckConstraint(
            "char_length(btrim(new_email)) BETWEEN 3 AND 255",
            name="ck_email_change_new_email",
        ),
        sa.CheckConstraint(
            "lower(btrim(old_email)) <> lower(btrim(new_email))",
            name="ck_email_change_distinct_emails",
        ),
        sa.CheckConstraint(
            "auth_version_at_request >= 0",
            name="ck_email_change_auth_version",
        ),
        sa.CheckConstraint(
            "request_kind <> 'admin_assisted' OR "
            "(reason IS NOT NULL AND char_length(btrim(reason)) BETWEEN 3 AND 500)",
            name="ck_email_change_admin_reason",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_email_change_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name="fk_email_change_requested_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_email_change_pending_user",
        "email_change_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_email_change_pending_email",
        "email_change_requests",
        ["new_email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_email_change_user_created",
        "email_change_requests",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_email_change_status_expires",
        "email_change_requests",
        ["status", "expires_at"],
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
                :body, 'published', 44, now(), now(), now()
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
            title="Безопасная смена email-логина",
            summary="Как сотрудник или администратор запускает подтверждаемую смену email и что происходит с сессиями.",
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
    op.drop_index("ix_email_change_status_expires", table_name="email_change_requests")
    op.drop_index("ix_email_change_user_created", table_name="email_change_requests")
    op.drop_index("uq_email_change_pending_email", table_name="email_change_requests")
    op.drop_index("uq_email_change_pending_user", table_name="email_change_requests")
    op.drop_table("email_change_requests")
