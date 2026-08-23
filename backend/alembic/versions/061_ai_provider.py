"""Add the admin-managed OpenAI-compatible provider.

Revision ID: 061_ai_provider
Revises: 060_audit_synology_connector
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "061_ai_provider"
down_revision = "060_audit_synology_connector"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "1fb214df-b6b3-41bb-b02b-b4fbe08ef17e",
    "slug": "admin-ai-provider-connection",
    "title": "Администрирование: подключение ИИ-провайдера",
    "summary": "Как подключить OpenAI-compatible API и безопасно использовать его в функциях системы.",
    "section": "admin",
    "body": """Обновлено: 2026-08-22

## Для чего нужен коннектор
DPMS использует единый серверный профиль ИИ-провайдера. Конкретные функции системы обращаются к этому профилю через backend, поэтому API key не передается в браузер и не дублируется в разных разделах.

## Кто управляет подключением
Создавать, изменять, проверять и удалять профиль может только системный администратор.

## Настройка
1. Откройте `Админ -> Интеграции -> ИИ`.
2. Укажите название подключения, HTTPS API URL, точный идентификатор модели и API key.
3. Сохраните профиль.
4. Нажмите `Проверить подключение`. DPMS отправит короткий технический запрос выбранной модели.

При последующем изменении настроек поле API key можно оставить пустым: сохраненный ключ останется прежним.

## Безопасность
API key хранится только в зашифрованном виде и никогда не возвращается frontend. DPMS разрешает соединение только с HTTPS-origin из серверного allowlist, не следует redirects и не записывает prompts, ответы или ключ в журнал интеграции.

Доступ пользователей к каждой ИИ-функции задается самой бизнес-функцией. Наличие настроенного провайдера не открывает пользователям произвольный чат и не дает им доступ к API key.
""",
}


def upgrade() -> None:
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_kind", sa.String(length=40), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_kind", name="uq_ai_provider_configs_kind"),
        sa.CheckConstraint("provider_kind = 'openai_compatible'", name="ck_ai_provider_configs_kind"),
        sa.CheckConstraint("config_version >= 1", name="ck_ai_provider_configs_version"),
        sa.CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('ok', 'error')",
            name="ck_ai_provider_configs_test_status",
        ),
    )
    op.create_index("ix_ai_provider_configs_created_by_id", "ai_provider_configs", ["created_by_id"])
    op.create_index("ix_ai_provider_configs_updated_by_id", "ai_provider_configs", ["updated_by_id"])

    op.create_table(
        "ai_provider_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_provider_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("outcome IN ('success', 'error')", name="ck_ai_provider_events_outcome"),
    )
    op.create_index("ix_ai_provider_events_provider_id", "ai_provider_events", ["provider_id"])
    op.create_index("ix_ai_provider_events_actor_id", "ai_provider_events", ["actor_id"])
    op.create_index("ix_ai_provider_events_event_type", "ai_provider_events", ["event_type"])
    op.create_index("ix_ai_provider_events_created_at", "ai_provider_events", ["created_at"])

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            ) VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 213,
                now(), now(), now()
            )
            ON CONFLICT DO NOTHING
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM knowledge_articles WHERE id = :id"),
        {"id": ARTICLE["id"]},
    )
    op.drop_index("ix_ai_provider_events_created_at", table_name="ai_provider_events")
    op.drop_index("ix_ai_provider_events_event_type", table_name="ai_provider_events")
    op.drop_index("ix_ai_provider_events_actor_id", table_name="ai_provider_events")
    op.drop_index("ix_ai_provider_events_provider_id", table_name="ai_provider_events")
    op.drop_table("ai_provider_events")
    op.drop_index("ix_ai_provider_configs_updated_by_id", table_name="ai_provider_configs")
    op.drop_index("ix_ai_provider_configs_created_by_id", table_name="ai_provider_configs")
    op.drop_table("ai_provider_configs")
