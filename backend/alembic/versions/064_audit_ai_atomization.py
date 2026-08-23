"""Add versioned audit skills and human-reviewed AI atom drafts.

Revision ID: 064_audit_ai_drafts
Revises: 063_ai_verify_save
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "064_audit_ai_drafts"
down_revision = "063_ai_verify_save"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "e717d272-f51c-4ebf-a4bf-5bb6db4587b9",
    "slug": "audit-ai-atomization-skills",
    "title": "Аудит: атомизация ТЗ с помощью ИИ и skill",
    "summary": "Как установить методику, сформировать проверяемый ИИ-черновик и безопасно записать атомы.",
    "section": "audit",
    "body": """Обновлено: 2026-08-23

## Что делает функция
DPMS может взять неизменяемое техническое задание из карточки аудита, применить установленную методику и подготовить черновик атомарных требований с указанием исходных фрагментов. ИИ не изменяет документ и не записывает атомы автоматически.

## Кто и что делает
1. Администратор настраивает и проверяет ИИ-провайдера в `Админ -> Интеграции -> ИИ`.
2. Администратор импортирует декларативный JSON skill. Новая версия сохраняется неизменяемо и становится активной.
3. Назначенный ответственный или руководитель аудита открывает договор без атомов, выбирает ТЗ и skill.
4. Перед запуском пользователь явно подтверждает передачу текста документа внешнему провайдеру.
5. DPMS проверяет полноту ссылок на исходные фрагменты и показывает редактируемый черновик.
6. Пользователь исключает лишние предложения, исправляет формулировки и отдельно нажимает `Подтвердить атомы`.

До шестого шага основной реестр атомов остается пустым. После фиксации все созданные записи имеют статус `Черновик` и проходят обычную ручную работу аудита.

## Формат skill
Skill является только данными и никогда не исполняет код. Поддерживается UTF-8 JSON до 256 КБ:

```json
{
  "schema_version": "1.0",
  "slug": "audit-tz",
  "name": "Атомизация технического задания",
  "version": "1.0.0",
  "description": "Правила выделения проверяемых требований",
  "instructions": "Подробная методика длиной не менее 50 символов",
  "rules": ["Один атом содержит одно независимо проверяемое требование"]
}
```

Одинаковый `slug + version` нельзя заменить другим содержимым: для изменения методики импортируется новая версия.

## Контроль и безопасность
- API key не передается frontend и хранится зашифрованно.
- Внешнему провайдеру отправляются только извлеченные текстовые фрагменты выбранного документа и активная версия skill.
- Текст документа считается недоверенными данными и не может менять протокол или JSON-схему.
- Полный prompt, полный ответ модели и текст договора не записываются в технические события. Сохраняются SHA-256, версия модели, версия skill, ограниченные цитаты и решения человека.
- Изменение документа, появление ручных атомов или изменение ИИ-профиля во время генерации блокирует результат.

## Ограничения первого slice
Поддерживаются текстовые DOCX и PDF. Зашифрованные, содержащие внешние объекты или сканированные без текстового слоя документы блокируются. Извлеченный текст ограничен 35 000 символов; большой документ нужно разделить на самостоятельные части. OCR и автоматическое объединение ИИ-черновика с уже существующим реестром выполняются отдельными будущими слайсами.
""",
}


def upgrade() -> None:
    op.create_table(
        "audit_atomization_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_audit_atomization_skills_slug"),
    )
    op.create_index("ix_audit_atomization_skills_created_by_id", "audit_atomization_skills", ["created_by_id"])
    op.create_index("ix_audit_atomization_skills_updated_by_id", "audit_atomization_skills", ["updated_by_id"])

    op.create_table(
        "audit_atomization_skill_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_label", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False, server_default="1.0"),
        sa.Column("instructions_text", sa.Text(), nullable=False),
        sa.Column("rules_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["skill_id"], ["audit_atomization_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256", name="uq_audit_atomization_skill_versions_sha"),
        sa.UniqueConstraint("skill_id", "version_label", name="uq_audit_atomization_skill_versions_label"),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_audit_atomization_skill_versions_schema"),
    )
    op.create_index("ix_audit_atomization_skill_versions_skill_id", "audit_atomization_skill_versions", ["skill_id"])
    op.create_index("ix_audit_atomization_skill_versions_created_by_id", "audit_atomization_skill_versions", ["created_by_id"])
    op.create_index(
        "uq_audit_atomization_skill_versions_active",
        "audit_atomization_skill_versions",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "audit_ai_atomization_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_config_version", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("skill_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("commit_key_hash", sa.String(length=64), nullable=True),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("committed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["audit_atomization_skill_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_config_id"], ["ai_provider_configs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["committed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_key_hash", name="uq_audit_ai_attempts_request_key"),
        sa.UniqueConstraint("commit_key_hash", name="uq_audit_ai_attempts_commit_key"),
        sa.CheckConstraint(
            "status IN ('running', 'draft_ready', 'failed', 'committed')",
            name="ck_audit_ai_attempts_status",
        ),
        sa.CheckConstraint("config_version >= 1", name="ck_audit_ai_attempts_version"),
    )
    op.create_index("ix_audit_ai_attempts_case_id", "audit_ai_atomization_attempts", ["case_id"])
    op.create_index("ix_audit_ai_attempts_document_id", "audit_ai_atomization_attempts", ["document_id"])
    op.create_index("ix_audit_ai_attempts_skill_version_id", "audit_ai_atomization_attempts", ["skill_version_id"])
    op.create_index("ix_audit_ai_attempts_provider_config_id", "audit_ai_atomization_attempts", ["provider_config_id"])
    op.create_index("ix_audit_ai_attempts_requested_by_id", "audit_ai_atomization_attempts", ["requested_by_id"])
    op.create_index("ix_audit_ai_attempts_case_created_at", "audit_ai_atomization_attempts", ["case_id", "created_at"])

    op.create_table(
        "audit_ai_atom_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("digital_product", sa.String(length=255), nullable=False),
        sa.Column("work_type", sa.String(length=255), nullable=True),
        sa.Column("object_type", sa.String(length=255), nullable=True),
        sa.Column("source_clause", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["attempt_id"], ["audit_ai_atomization_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "source_fingerprint", name="uq_audit_ai_drafts_fingerprint"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected', 'committed')",
            name="ck_audit_ai_drafts_review_status",
        ),
        sa.CheckConstraint(
            "confidence_percent IS NULL OR (confidence_percent >= 0 AND confidence_percent <= 100)",
            name="ck_audit_ai_drafts_confidence",
        ),
    )
    op.create_index("ix_audit_ai_drafts_attempt_id", "audit_ai_atom_drafts", ["attempt_id"])
    op.create_index("ix_audit_ai_drafts_case_id", "audit_ai_atom_drafts", ["case_id"])
    op.create_index("ix_audit_ai_drafts_attempt_order", "audit_ai_atom_drafts", ["attempt_id", "sort_order"])

    op.add_column(
        "audit_atoms",
        sa.Column("ai_atomization_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_atoms_ai_atomization_draft_id",
        "audit_atoms",
        "audit_ai_atom_drafts",
        ["ai_atomization_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_audit_atoms_ai_atomization_draft_id",
        "audit_atoms",
        ["ai_atomization_draft_id"],
        unique=True,
        postgresql_where=sa.text("ai_atomization_draft_id IS NOT NULL"),
    )

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            ) VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 214,
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
    op.get_bind().execute(
        sa.text("DELETE FROM knowledge_articles WHERE id = :id"),
        {"id": ARTICLE["id"]},
    )
    op.drop_index("uq_audit_atoms_ai_atomization_draft_id", table_name="audit_atoms")
    op.drop_constraint("fk_audit_atoms_ai_atomization_draft_id", "audit_atoms", type_="foreignkey")
    op.drop_column("audit_atoms", "ai_atomization_draft_id")
    op.drop_index("ix_audit_ai_drafts_attempt_order", table_name="audit_ai_atom_drafts")
    op.drop_index("ix_audit_ai_drafts_case_id", table_name="audit_ai_atom_drafts")
    op.drop_index("ix_audit_ai_drafts_attempt_id", table_name="audit_ai_atom_drafts")
    op.drop_table("audit_ai_atom_drafts")
    op.drop_index("ix_audit_ai_attempts_case_created_at", table_name="audit_ai_atomization_attempts")
    op.drop_index("ix_audit_ai_attempts_requested_by_id", table_name="audit_ai_atomization_attempts")
    op.drop_index("ix_audit_ai_attempts_provider_config_id", table_name="audit_ai_atomization_attempts")
    op.drop_index("ix_audit_ai_attempts_skill_version_id", table_name="audit_ai_atomization_attempts")
    op.drop_index("ix_audit_ai_attempts_document_id", table_name="audit_ai_atomization_attempts")
    op.drop_index("ix_audit_ai_attempts_case_id", table_name="audit_ai_atomization_attempts")
    op.drop_table("audit_ai_atomization_attempts")
    op.drop_index("uq_audit_atomization_skill_versions_active", table_name="audit_atomization_skill_versions")
    op.drop_index("ix_audit_atomization_skill_versions_created_by_id", table_name="audit_atomization_skill_versions")
    op.drop_index("ix_audit_atomization_skill_versions_skill_id", table_name="audit_atomization_skill_versions")
    op.drop_table("audit_atomization_skill_versions")
    op.drop_index("ix_audit_atomization_skills_updated_by_id", table_name="audit_atomization_skills")
    op.drop_index("ix_audit_atomization_skills_created_by_id", table_name="audit_atomization_skills")
    op.drop_table("audit_atomization_skills")
