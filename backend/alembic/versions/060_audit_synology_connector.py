"""Add the admin-only Synology connector for Audit.

Revision ID: 060_audit_synology_connector
Revises: 059_audit_workspace
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "060_audit_synology_connector"
down_revision = "059_audit_workspace"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "98d3e0cb-4268-4af2-9a03-06022f444113",
    "slug": "audit-synology-batch-import",
    "title": "Аудит: импорт документов из Synology",
    "summary": "Как администратору подключить File Station, выбрать несколько ТЗ и безопасно создать черновики аудита.",
    "section": "audit",
    "body": """Обновлено: 2026-08-22

## Для чего нужен коннектор
Synology можно использовать как источник исходных технических заданий. Администратор открывает разрешенную папку File Station, выбирает несколько PDF, DOCX или XLSX и создает по одному черновику аудита на каждый документ.

## Кто может работать с подключением
Настройка, просмотр удаленных папок и импорт доступны только пользователям с системной ролью `admin`. Руководитель аудита, ответственный и обычный участник команды не получают доступ к Synology и его учетным данным.

## Порядок работы
1. Откройте в разделе «Аудит» пункт `Synology`.
2. Укажите разрешенный HTTPS-адрес NAS, отдельную учетную запись только для чтения и корневую папку с материалами аудита.
3. Введите пароль и одноразовый 2FA-код, затем нажмите «Подключиться».
4. Откройте папку, отметьте нужные документы и нажмите «Проверить выбор».
5. Проверьте имена, размеры и общий объем пакета.
6. Подтвердите импорт. Каждый файл появится как неизменяемый материал отдельного черновика в реестре договоров.

## Ограничения
- не более 20 файлов за один импорт;
- не более 25 МБ на файл;
- не более 100 МБ на пакет;
- поддерживаются только PDF, DOCX и XLSX;
- папки нельзя выбирать как договоры;
- повторный импорт неизмененной версии удаленного файла блокируется.

## Безопасность
DSM-пароль и 2FA-код не сохраняются в БД. После входа SID остается только в памяти backend, привязан к текущему администратору и автоматически завершается после 30 минут бездействия, при отключении или остановке сервера. DPMS работает только с HTTPS-origin из серверного allowlist, не следует redirects и не позволяет выйти выше выбранной корневой папки. В журнале не сохраняются пароль, 2FA-код, SID или полный путь на NAS.

Для Synology рекомендуется создать отдельного пользователя только для чтения и выдать ему доступ только к папке материалов аудита.
""",
}


def upgrade() -> None:
    op.create_table(
        "audit_synology_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="synology"),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("root_path", sa.String(length=1000), nullable=False),
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
        sa.UniqueConstraint("provider", name="uq_audit_synology_connections_provider"),
        sa.CheckConstraint("provider = 'synology'", name="ck_audit_synology_connections_provider"),
        sa.CheckConstraint("config_version >= 1", name="ck_audit_synology_connections_version"),
        sa.CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('ok', 'error')",
            name="ck_audit_synology_connections_test_status",
        ),
    )
    op.create_index("ix_audit_synology_connections_created_by_id", "audit_synology_connections", ["created_by_id"])
    op.create_index("ix_audit_synology_connections_updated_by_id", "audit_synology_connections", ["updated_by_id"])

    op.create_table(
        "audit_synology_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_key_hash", sa.String(length=64), nullable=False),
        sa.Column("selection_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="committed"),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("imported_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["connection_id"], ["audit_synology_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_key_hash", name="uq_audit_synology_import_batches_request_key"),
        sa.CheckConstraint("status = 'committed'", name="ck_audit_synology_import_batches_status"),
    )
    op.create_index("ix_audit_synology_import_batches_connection_id", "audit_synology_import_batches", ["connection_id"])
    op.create_index("ix_audit_synology_import_batches_imported_by_id", "audit_synology_import_batches", ["imported_by_id"])
    op.create_index("ix_audit_synology_import_batches_created_at", "audit_synology_import_batches", ["created_at"])

    op.create_table(
        "audit_synology_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("remote_path_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("remote_size", sa.BigInteger(), nullable=False),
        sa.Column("remote_mtime", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["connection_id"], ["audit_synology_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["audit_synology_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_audit_synology_imports_document_id"),
        sa.UniqueConstraint(
            "connection_id",
            "remote_path_fingerprint",
            "remote_size",
            "remote_mtime",
            name="uq_audit_synology_imports_remote_version",
        ),
        sa.CheckConstraint("remote_size >= 0", name="ck_audit_synology_imports_remote_size"),
        sa.CheckConstraint("remote_mtime >= 0", name="ck_audit_synology_imports_remote_mtime"),
    )
    op.create_index("ix_audit_synology_imports_connection_id", "audit_synology_imports", ["connection_id"])
    op.create_index("ix_audit_synology_imports_batch_id", "audit_synology_imports", ["batch_id"])
    op.create_index("ix_audit_synology_imports_case_id", "audit_synology_imports", ["case_id"])
    op.create_index("ix_audit_synology_imports_document_id", "audit_synology_imports", ["document_id"])
    op.create_index("ix_audit_synology_imports_remote_path_fingerprint", "audit_synology_imports", ["remote_path_fingerprint"])
    op.create_index("ix_audit_synology_imports_content_sha256", "audit_synology_imports", ["content_sha256"])
    op.create_index("ix_audit_synology_imports_imported_by_id", "audit_synology_imports", ["imported_by_id"])
    op.create_index("ix_audit_synology_imports_created_at", "audit_synology_imports", ["created_at"])

    op.create_table(
        "audit_synology_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["connection_id"], ["audit_synology_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("outcome IN ('success', 'error')", name="ck_audit_synology_events_outcome"),
    )
    op.create_index("ix_audit_synology_events_connection_id", "audit_synology_events", ["connection_id"])
    op.create_index("ix_audit_synology_events_actor_id", "audit_synology_events", ["actor_id"])
    op.create_index("ix_audit_synology_events_event_type", "audit_synology_events", ["event_type"])
    op.create_index("ix_audit_synology_events_created_at", "audit_synology_events", ["created_at"])

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            ) VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 212,
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

    op.drop_index("ix_audit_synology_events_created_at", table_name="audit_synology_events")
    op.drop_index("ix_audit_synology_events_event_type", table_name="audit_synology_events")
    op.drop_index("ix_audit_synology_events_actor_id", table_name="audit_synology_events")
    op.drop_index("ix_audit_synology_events_connection_id", table_name="audit_synology_events")
    op.drop_table("audit_synology_events")

    op.drop_index("ix_audit_synology_imports_created_at", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_imported_by_id", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_content_sha256", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_remote_path_fingerprint", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_document_id", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_case_id", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_batch_id", table_name="audit_synology_imports")
    op.drop_index("ix_audit_synology_imports_connection_id", table_name="audit_synology_imports")
    op.drop_table("audit_synology_imports")

    op.drop_index("ix_audit_synology_import_batches_created_at", table_name="audit_synology_import_batches")
    op.drop_index("ix_audit_synology_import_batches_imported_by_id", table_name="audit_synology_import_batches")
    op.drop_index("ix_audit_synology_import_batches_connection_id", table_name="audit_synology_import_batches")
    op.drop_table("audit_synology_import_batches")

    op.drop_index("ix_audit_synology_connections_updated_by_id", table_name="audit_synology_connections")
    op.drop_index("ix_audit_synology_connections_created_by_id", table_name="audit_synology_connections")
    op.drop_table("audit_synology_connections")
