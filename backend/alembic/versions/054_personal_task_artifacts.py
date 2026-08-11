"""Add versioned documents and artifacts to personal tasks.

Revision ID: 054_personal_task_artifacts
Revises: 053_execution_contracts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "054_personal_task_artifacts"
down_revision = "053_execution_contracts"
branch_labels = None
depends_on = None

ARTICLE_ID = "c34b7f3f-1bf7-4baf-986e-96f1bb50f85a"
ARTICLE_SLUG = "dokumenty-i-artefakty-lichnoj-zadachi"
ARTICLE_BODY = """# Документы и артефакты личной задачи

## Для чего нужен раздел «Материалы»

Материалы связывают работу по личной задаче с конкретными документами и
результатами. Они не меняют дедлайн или статус задачи и не публикуются в
глобальную очередь автоматически.

## Типы материалов

- **Документ** — файл, который нужен для выполнения задачи: паспорт, таблица,
  презентация, PDF или рабочий текст.
- **Ссылка** — HTTP(S)-адрес внешнего ресурса. DPMS хранит адрес, но не
  загружает содержимое внешнего сайта.
- **Результат** — итоговый файл или ссылка на подготовленный результат.

## Как добавить материал

1. Откройте личную задачу.
2. В блоке **Материалы** нажмите **Добавить**.
3. Выберите тип, задайте понятное название и при необходимости описание.
4. Добавьте один файл или одну ссылку и сохраните.

Файлы проверяются по размеру и фактической сигнатуре. Исполняемые файлы, HTML,
SVG и файл с расширением, не соответствующим содержимому, не принимаются.

## Версии

Если материал обновился, используйте действие **Новая версия**. Предыдущая
версия остается доступной в истории, поэтому итоговый документ не затирает
исходник. В комментарии к версии кратко укажите, что изменилось.

## Архив и доступ

Доступ к материалам наследуется от личной задачи. Сейчас личная задача является
приватной и доступна только владельцу. Архивирование задачи не удаляет файлы:
их можно открыть и скачать, но добавление и изменение блокируются до
восстановления задачи. Материал также можно отдельно архивировать и вернуть.

Создание материала, добавление версии, изменение и архивирование записываются
в журнал задачи.
"""


def upgrade() -> None:
    op.drop_constraint(
        "ck_personal_task_events_type",
        "personal_task_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_personal_task_events_type",
        "personal_task_events",
        "event_type IN ("
        "'task_created', 'task_updated', 'status_changed', 'meeting', "
        "'follow_up', 'note', 'checkpoint_created', 'checkpoint_updated', "
        "'checkpoint_done', 'promoted', 'artifact_created', "
        "'artifact_version_added', 'artifact_updated', 'artifact_archived', "
        "'artifact_restored', 'artifact_deleted'"
        ")",
    )

    op.create_table(
        "personal_task_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "artifact_type IN ('document', 'link', 'result')",
            name="ck_personal_task_artifacts_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_personal_task_artifacts_status",
        ),
        sa.CheckConstraint(
            "current_version >= 1",
            name="ck_personal_task_artifacts_current_version",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND archived_at IS NULL) "
            "OR (status = 'archived' AND archived_at IS NOT NULL)",
            name="ck_personal_task_artifacts_archive_state",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["personal_tasks.id"],
            name="fk_personal_task_artifacts_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_personal_task_artifacts_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_personal_task_artifacts_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_task_artifacts_task_id",
        "personal_task_artifacts",
        ["task_id"],
    )
    op.create_index(
        "ix_personal_task_artifacts_task_status_updated",
        "personal_task_artifacts",
        ["task_id", "status", "updated_at"],
    )

    op.create_table(
        "personal_task_artifact_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("stored_filename", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('file', 'link')",
            name="ck_personal_task_artifact_versions_source_kind",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_personal_task_artifact_versions_number",
        ),
        sa.CheckConstraint(
            "(source_kind = 'file' AND url IS NULL "
            "AND original_filename IS NOT NULL AND stored_filename IS NOT NULL "
            "AND content_type IS NOT NULL AND size_bytes IS NOT NULL "
            "AND sha256 IS NOT NULL) "
            "OR (source_kind = 'link' AND url IS NOT NULL "
            "AND original_filename IS NULL AND stored_filename IS NULL "
            "AND content_type IS NULL AND size_bytes IS NULL AND sha256 IS NULL)",
            name="ck_personal_task_artifact_versions_payload",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["personal_task_artifacts.id"],
            name="fk_personal_task_artifact_versions_artifact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_personal_task_artifact_versions_created_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "version_number",
            name="uq_personal_task_artifact_versions_number",
        ),
    )
    op.create_index(
        "ix_personal_task_artifact_versions_artifact_id",
        "personal_task_artifact_versions",
        ["artifact_id"],
    )
    op.create_index(
        "ix_personal_task_artifact_versions_artifact_created",
        "personal_task_artifact_versions",
        ["artifact_id", "created_at"],
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
                'Документы и артефакты личной задачи',
                'Как хранить рабочие документы, ссылки, результаты и их версии внутри личной задачи.',
                'tasks',
                :body,
                'published',
                41,
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
            WHERE knowledge_articles.id = EXCLUDED.id
            """
        ).bindparams(
            article_id=ARTICLE_ID,
            slug=ARTICLE_SLUG,
            body=ARTICLE_BODY,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM personal_task_artifacts LIMIT 1) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade 054 while personal task artifacts exist';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM knowledge_articles
            WHERE id = CAST(:article_id AS uuid) AND slug = :slug
            """
        ).bindparams(article_id=ARTICLE_ID, slug=ARTICLE_SLUG)
    )
    op.drop_index(
        "ix_personal_task_artifact_versions_artifact_created",
        table_name="personal_task_artifact_versions",
    )
    op.drop_index(
        "ix_personal_task_artifact_versions_artifact_id",
        table_name="personal_task_artifact_versions",
    )
    op.drop_table("personal_task_artifact_versions")
    op.drop_index(
        "ix_personal_task_artifacts_task_status_updated",
        table_name="personal_task_artifacts",
    )
    op.drop_index(
        "ix_personal_task_artifacts_task_id",
        table_name="personal_task_artifacts",
    )
    op.drop_table("personal_task_artifacts")
    op.execute(
        sa.text(
            """
            DELETE FROM personal_task_events
            WHERE event_type IN (
                'artifact_created',
                'artifact_version_added',
                'artifact_updated',
                'artifact_archived',
                'artifact_restored',
                'artifact_deleted'
            )
            """
        )
    )
    op.drop_constraint(
        "ck_personal_task_events_type",
        "personal_task_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_personal_task_events_type",
        "personal_task_events",
        "event_type IN ("
        "'task_created', 'task_updated', 'status_changed', 'meeting', "
        "'follow_up', 'note', 'checkpoint_created', 'checkpoint_updated', "
        "'checkpoint_done', 'promoted'"
        ")",
    )
