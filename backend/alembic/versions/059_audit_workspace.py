"""Add audit workspace, team, assignment and immutable documents.

Revision ID: 059_audit_workspace
Revises: 058_audit_atomization
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "059_audit_workspace"
down_revision = "058_audit_atomization"
branch_labels = None
depends_on = None


AUDIT_WORKSPACE_ARTICLE = {
    "id": "12b55e2d-bf8b-4be3-9795-1718a56113c0",
    "slug": "audit-workspace-registry-team-documents",
    "title": "Аудит: реестр договоров, команда и документы",
    "summary": "Как создать карточку договора, назначить ответственного и загрузить реестр атомов именно в выбранный аудит.",
    "section": "audit",
    "body": """Обновлено: 2026-08-21

## Рабочее пространство
Раздел «Аудит» состоит из дашборда, реестра договоров и команды аудита. В реестре каждый договор занимает одну строку: слева реквизиты и состояние атомизации, по центру прогресс, справа ответственный, материалы и переход в договор.

## Новый документ
Можно загрузить одно или несколько ТЗ в PDF, DOCX или XLSX. Каждый файл сохраняется как неизменяемая версия и создает черновую карточку аудита. После загрузки заполните продукт, дату и другие параметры карточки.

## Ответственный
Ответственного выбирают из команды аудита. Назначение доступно администратору, тимлиду или руководителю аудита и записывается в историю карточки.

## Состояние атомизации
- Красный статус означает, что договор находится в черновике или ТЗ еще не декомпозировано.
- Желтый статус означает, что реестр уже есть, но часть атомов остается черновой.
- Зеленый статус означает, что декомпозиция завершена.

## Путь исполнителя
1. Откройте назначенный вам договор.
2. В панели управления скачайте Excel-шаблон.
3. Заполните один договор и его атомы, не меняя имя листа и заголовки колонок.
4. Нажмите «Загрузить реестр атомов» и выберите файл.
5. Сначала выполните проверку файла. До подтверждения данные не изменяются.
6. Исправьте показанные ошибки или явно подтвердите корректный импорт.
7. Проверьте атомы во вкладке «Атомы», а исходный Excel — во вкладке «Материалы».

## Защита от неверной привязки
Импорт из карточки всегда привязывается только к выбранному договору. Файл с другим номером или датой, несколькими договорами, архивной карточкой либо уже использованный в другом аудите отклоняется. Система не создает скрытую вторую карточку.

## Материалы, атомы и история
Контекстная панель выбранного договора разделяет неизменяемые файлы, рабочий реестр атомов и журнал действий. Загруженный Excel сохраняется как отдельный материал; изменения ответственного, параметров и атомов фиксируются в истории.

## Конфиденциальность
В реестре отображается только замаскированный номер договора. Исходные документы доступны только участникам рабочего пространства аудита. Назначенный исполнитель может атомизировать свой активный договор; управленческие действия остаются у руководителя аудита.
""",
}


def upgrade() -> None:
    op.add_column(
        "audit_cases",
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_cases_responsible_user_id_users",
        "audit_cases",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_audit_cases_responsible_user_id",
        "audit_cases",
        ["responsible_user_id"],
    )

    op.create_table(
        "audit_team_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("added_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_audit_team_members_user_id"),
        sa.CheckConstraint("role IN ('leader', 'member')", name="ck_audit_team_members_role"),
    )
    op.create_index("ix_audit_team_members_user_id", "audit_team_members", ["user_id"])
    op.create_index("ix_audit_team_members_role", "audit_team_members", ["role"])

    op.create_table(
        "audit_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="technical_spec"),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename", name="uq_audit_documents_stored_filename"),
        sa.UniqueConstraint("case_id", "sha256", name="uq_audit_documents_case_sha256"),
        sa.CheckConstraint(
            "kind IN ('technical_spec', 'atom_register', 'audit_result', 'protocol', 'other')",
            name="ck_audit_documents_kind",
        ),
    )
    op.create_index("ix_audit_documents_case_id", "audit_documents", ["case_id"])
    op.create_index("ix_audit_documents_uploaded_by_id", "audit_documents", ["uploaded_by_id"])
    op.create_index("ix_audit_documents_sha256", "audit_documents", ["sha256"])
    op.create_index("ix_audit_documents_case_created_at", "audit_documents", ["case_id", "created_at"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 211,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                updated_at = now(),
                published_at = COALESCE(knowledge_articles.published_at, now())
            """
        ),
        AUDIT_WORKSPACE_ARTICLE,
    )


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_articles WHERE slug = 'audit-workspace-registry-team-documents'")

    op.drop_index("ix_audit_documents_case_created_at", table_name="audit_documents")
    op.drop_index("ix_audit_documents_sha256", table_name="audit_documents")
    op.drop_index("ix_audit_documents_uploaded_by_id", table_name="audit_documents")
    op.drop_index("ix_audit_documents_case_id", table_name="audit_documents")
    op.drop_table("audit_documents")

    op.drop_index("ix_audit_team_members_role", table_name="audit_team_members")
    op.drop_index("ix_audit_team_members_user_id", table_name="audit_team_members")
    op.drop_table("audit_team_members")

    op.drop_index("ix_audit_cases_responsible_user_id", table_name="audit_cases")
    op.drop_constraint("fk_audit_cases_responsible_user_id_users", "audit_cases", type_="foreignkey")
    op.drop_column("audit_cases", "responsible_user_id")
