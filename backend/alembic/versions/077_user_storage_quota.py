"""Add personal file storage quota and increase request workflow.

Revision ID: 077_user_storage_quota
Revises: 076_audit_contract_reference
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "077_user_storage_quota"
down_revision = "076_audit_contract_reference"
branch_labels = None
depends_on = None


DEFAULT_QUOTA_BYTES = 50 * 1024 * 1024
ARTICLE = {
    "id": "e454e4b5-982a-49da-9dd6-d079fe25d80c",
    "slug": "lichnoe-fajlovoe-hranilishche-i-kvota",
    "title": "Личное файловое хранилище и квота",
    "summary": "Как учитываются файлы, предупреждения о заполнении и запрос увеличения лимита.",
    "section": "settings",
    "body": """Обновлено: 2026-09-02

## Что учитывается

По умолчанию каждому пользователю доступно 50 МиБ личного файлового хранилища. В квоту входят файлы заметок и все сохраненные версии материалов личных задач. Ссылки не занимают место. Если заметкой поделились с коллегами, ее файл учитывается один раз у владельца.

Файлы глобальной очереди, проектов и раздела «Аудит» не списываются из личной квоты: это рабочие данные, для которых будет применяться отдельная организационная политика.

## Предупреждения

- при использовании 80% система заранее предупреждает о заполнении;
- при 90% показывает критическое предупреждение;
- при 100% существующие файлы остаются доступными, но новые загрузки блокируются.

Архивирование материала не освобождает место, потому что файл продолжает храниться. Место освобождается после окончательного удаления файла или всех его версий.

## Как запросить увеличение

Откройте «Настройки» и найдите блок «Хранилище». Укажите желаемый общий лимит и кратко объясните причину. Пока заявка рассматривается, повторную заявку создать нельзя. Администратор фиксирует одобрение или отказ с комментарием; решение и изменение лимита записываются в журнал системы.

## Защита от одновременных загрузок

Перед записью файла DPMS резервирует необходимый объем. Поэтому две параллельные загрузки не могут вместе незаметно превысить лимит. Незавершенные резервации очищаются автоматически, а уже сохраненные данные при превышении не удаляются.
""",
}


def upgrade() -> None:
    op.create_table(
        "user_storage_quotas",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "limit_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(DEFAULT_QUOTA_BYTES),
        ),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False, server_default="0"),
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
            "limit_bytes > 0",
            name="ck_user_storage_quotas_limit_positive",
        ),
        sa.CheckConstraint(
            "used_bytes >= 0",
            name="ck_user_storage_quotas_used_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_bytes >= 0",
            name="ck_user_storage_quotas_reserved_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_storage_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stored_filename", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="reserved",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
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
            "size_bytes > 0",
            name="ck_user_storage_files_size_positive",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'active', 'pending_delete', 'released')",
            name="ck_user_storage_files_status",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stored_filename",
            name="uq_user_storage_files_stored_filename",
        ),
    )
    op.create_index(
        "ix_user_storage_files_owner_id",
        "user_storage_files",
        ["owner_id"],
    )
    op.create_index(
        "ix_user_storage_files_owner_status_expiry",
        "user_storage_files",
        ["owner_id", "status", "expires_at"],
    )
    op.create_table(
        "storage_quota_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("requested_limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("approved_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "requested_limit_bytes > current_limit_bytes",
            name="ck_storage_quota_requests_increase",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_storage_quota_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_quota_requests_user_id",
        "storage_quota_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_storage_quota_requests_status_created",
        "storage_quota_requests",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_storage_quota_requests_pending_user",
        "storage_quota_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO user_storage_quotas (
                user_id, limit_bytes, used_bytes, reserved_bytes, created_at, updated_at
            )
            SELECT id, :default_limit, 0, 0, now(), now()
            FROM users
            ON CONFLICT (user_id) DO NOTHING
            """
        ),
        {"default_limit": DEFAULT_QUOTA_BYTES},
    )
    bind.execute(
        sa.text(
            """
            WITH source_files AS (
                SELECT
                    qn.owner_id,
                    qna.stored_filename,
                    qna.size_bytes::bigint AS size_bytes,
                    'quick_note'::varchar AS category,
                    qna.created_at
                FROM quick_note_attachments qna
                JOIN quick_notes qn ON qn.id = qna.note_id
                WHERE qna.size_bytes > 0
                UNION ALL
                SELECT
                    pt.owner_id,
                    ptav.stored_filename,
                    ptav.size_bytes::bigint AS size_bytes,
                    'personal_task_artifact'::varchar AS category,
                    ptav.created_at
                FROM personal_task_artifact_versions ptav
                JOIN personal_task_artifacts pta ON pta.id = ptav.artifact_id
                JOIN personal_tasks pt ON pt.id = pta.task_id
                WHERE ptav.source_kind = 'file'
                  AND ptav.stored_filename IS NOT NULL
                  AND ptav.size_bytes > 0
            ), deduplicated AS (
                SELECT DISTINCT ON (stored_filename)
                    owner_id, stored_filename, size_bytes, category, created_at
                FROM source_files
                ORDER BY stored_filename, created_at, owner_id
            )
            INSERT INTO user_storage_files (
                id, owner_id, stored_filename, size_bytes, category, status,
                expires_at, activated_at, delete_requested_at, released_at,
                created_at, updated_at
            )
            SELECT
                md5(owner_id::text || ':' || stored_filename)::uuid,
                owner_id, stored_filename, size_bytes, category,
                'active', NULL, created_at, NULL, NULL, created_at, now()
            FROM deduplicated
            ON CONFLICT (stored_filename) DO NOTHING
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE user_storage_quotas quota
            SET used_bytes = usage.used_bytes,
                updated_at = now()
            FROM (
                SELECT owner_id, COALESCE(SUM(size_bytes), 0)::bigint AS used_bytes
                FROM user_storage_files
                WHERE status IN ('active', 'pending_delete')
                GROUP BY owner_id
            ) usage
            WHERE quota.user_id = usage.owner_id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 220,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = 'published',
                updated_at = now(),
                published_at = COALESCE(knowledge_articles.published_at, now())
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM knowledge_articles WHERE id = :id AND slug = :slug"
        ),
        {"id": ARTICLE["id"], "slug": ARTICLE["slug"]},
    )
    op.drop_index(
        "uq_storage_quota_requests_pending_user",
        table_name="storage_quota_requests",
    )
    op.drop_index(
        "ix_storage_quota_requests_status_created",
        table_name="storage_quota_requests",
    )
    op.drop_index(
        "ix_storage_quota_requests_user_id",
        table_name="storage_quota_requests",
    )
    op.drop_table("storage_quota_requests")
    op.drop_index(
        "ix_user_storage_files_owner_status_expiry",
        table_name="user_storage_files",
    )
    op.drop_index(
        "ix_user_storage_files_owner_id",
        table_name="user_storage_files",
    )
    op.drop_table("user_storage_files")
    op.drop_table("user_storage_quotas")
