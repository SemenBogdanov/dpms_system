"""Add independent model registries and human-reviewed comparison.

Revision ID: 072_audit_multi_model
Revises: 071_canonical_atomization
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "072_audit_multi_model"
down_revision = "071_canonical_atomization"
branch_labels = None
depends_on = None


ARTICLE_APPENDIX = """

## Несколько моделей и генеральный реестр
Для одного подготовленного ТЗ можно последовательно запустить несколько проверенных ИИ-профилей. Результат каждой точной конфигурации `провайдер + модель + версия` сохраняется отдельно и не перезаписывается следующим запуском.

После готовности как минимум двух модельных реестров нажмите `Запустить сравнительный анализ`. DPMS сопоставит варианты по основаниям в исходном документе и формулировкам, покажет уровень согласия и сохранит все модельные варианты рядом с предлагаемым генеральным атомом. Сравнение не назначает одну модель безусловно правильной: итоговый список редактирует и подтверждает сотрудник.

Команда `Записать генеральный реестр` создает рабочие строки `ITEM-*`. До этой команды модельные реестры и сравнительный результат остаются черновиками и не участвуют в альфа-проверке или комиссии.

В деталях опубликованного атома отображаются не только пункт или координата источника, но и текстовые выдержки, на которых основано решение.
"""


def upgrade() -> None:
    op.drop_constraint("uq_ai_provider_configs_kind", "ai_provider_configs", type_="unique")
    op.create_index(
        "ix_ai_provider_configs_kind_created_at",
        "ai_provider_configs",
        ["provider_kind", "created_at"],
    )

    op.create_table(
        "audit_ai_model_registries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_config_version", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("skill_sha256", sa.String(length=64), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=False),
        sa.Column("atom_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "coverage_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("atom_count >= 0", name="ck_audit_ai_model_registries_atom_count"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canonical_run_id"], ["audit_tz_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["audit_atomization_skill_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["provider_config_id"], ["ai_provider_configs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_run_id",
            "provider_config_id",
            "provider_config_version",
            "model_name",
            name="uq_audit_ai_model_registry_lane",
        ),
    )
    op.create_index("ix_audit_ai_model_registries_case_id", "audit_ai_model_registries", ["case_id"])
    op.create_index("ix_audit_ai_model_registries_run_id", "audit_ai_model_registries", ["canonical_run_id"])
    op.create_index("ix_audit_ai_model_registries_provider_id", "audit_ai_model_registries", ["provider_config_id"])
    op.create_index(
        "ix_audit_ai_model_registries_case_created_at",
        "audit_ai_model_registries",
        ["case_id", "created_at"],
    )

    op.create_table(
        "audit_ai_model_registry_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("digital_product", sa.String(length=255), nullable=False),
        sa.Column("work_type", sa.String(length=255), nullable=True),
        sa.Column("object_type", sa.String(length=255), nullable=True),
        sa.Column("source_clause", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["registry_id"], ["audit_ai_model_registries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registry_id", "source_fingerprint", name="uq_audit_ai_registry_items_fingerprint"),
    )
    op.create_index("ix_audit_ai_registry_items_registry_id", "audit_ai_model_registry_items", ["registry_id"])
    op.create_index("ix_audit_ai_registry_items_case_id", "audit_ai_model_registry_items", ["case_id"])
    op.create_index(
        "ix_audit_ai_registry_items_registry_order",
        "audit_ai_model_registry_items",
        ["registry_id", "sort_order"],
    )

    op.create_table(
        "audit_ai_model_comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_key_hash", sa.String(length=64), nullable=False),
        sa.Column("commit_key_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "registry_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "registry_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft_ready"),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("committed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft_ready', 'committed')", name="ck_audit_ai_model_comparisons_status"),
        sa.CheckConstraint("config_version >= 1", name="ck_audit_ai_model_comparisons_version"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canonical_run_id"], ["audit_tz_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["audit_atomization_skill_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["committed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_key_hash", name="uq_audit_ai_model_comparisons_key"),
        sa.UniqueConstraint("commit_key_hash", name="uq_audit_ai_model_comparisons_commit_key"),
    )
    op.create_index("ix_audit_ai_model_comparisons_case_id", "audit_ai_model_comparisons", ["case_id"])
    op.create_index("ix_audit_ai_model_comparisons_run_id", "audit_ai_model_comparisons", ["canonical_run_id"])
    op.create_index(
        "ix_audit_ai_model_comparisons_case_created_at",
        "audit_ai_model_comparisons",
        ["case_id", "created_at"],
    )

    op.create_table(
        "audit_ai_comparison_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("digital_product", sa.String(length=255), nullable=False),
        sa.Column("work_type", sa.String(length=255), nullable=True),
        sa.Column("object_type", sa.String(length=255), nullable=True),
        sa.Column("source_clause", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "model_variants_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confidence_percent", sa.Integer(), nullable=True),
        sa.Column("agreement_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("registry_count", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "review_status IN ('pending', 'committed', 'rejected')",
            name="ck_audit_ai_comparison_drafts_review_status",
        ),
        sa.CheckConstraint("agreement_count >= 1", name="ck_audit_ai_comparison_drafts_agreement"),
        sa.CheckConstraint(
            "registry_count >= agreement_count",
            name="ck_audit_ai_comparison_drafts_registry_count",
        ),
        sa.ForeignKeyConstraint(["comparison_id"], ["audit_ai_model_comparisons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_id",
            "source_fingerprint",
            name="uq_audit_ai_comparison_drafts_fingerprint",
        ),
    )
    op.create_index("ix_audit_ai_comparison_drafts_comparison_id", "audit_ai_comparison_drafts", ["comparison_id"])
    op.create_index("ix_audit_ai_comparison_drafts_case_id", "audit_ai_comparison_drafts", ["case_id"])
    op.create_index(
        "ix_audit_ai_comparison_drafts_order",
        "audit_ai_comparison_drafts",
        ["comparison_id", "sort_order"],
    )

    op.add_column("audit_atoms", sa.Column("source_evidence_text", sa.Text(), nullable=True))
    op.add_column(
        "audit_atoms",
        sa.Column(
            "source_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "audit_atoms",
        sa.Column("ai_comparison_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audit_atoms_ai_comparison_draft",
        "audit_atoms",
        "audit_ai_comparison_drafts",
        ["ai_comparison_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_audit_atoms_ai_comparison_draft_id",
        "audit_atoms",
        ["ai_comparison_draft_id"],
        unique=True,
        postgresql_where=sa.text("ai_comparison_draft_id IS NOT NULL"),
    )

    op.execute(
        """
        UPDATE audit_atoms AS atom
        SET source_refs_json = draft.source_refs_json,
            source_evidence_text = evidence.text
        FROM audit_ai_atom_drafts AS draft
        LEFT JOIN LATERAL (
            SELECT string_agg(ref.value->>'excerpt', E'\n\n' ORDER BY ref.ordinality) AS text
            FROM jsonb_array_elements(draft.source_refs_json) WITH ORDINALITY AS ref(value, ordinality)
            WHERE COALESCE(ref.value->>'excerpt', '') <> ''
        ) AS evidence ON true
        WHERE atom.ai_atomization_draft_id = draft.id
        """
    )

    op.execute(
        """
        INSERT INTO audit_ai_model_registries (
            id, case_id, canonical_run_id, document_id, skill_version_id,
            provider_config_id, provider_config_version, provider_name, model_name,
            document_sha256, skill_sha256, response_sha256, atom_count,
            coverage_json, warnings_json, created_by_id, created_at
        )
        SELECT gen_random_uuid(), attempt.case_id, attempt.canonical_run_id,
               attempt.document_id, attempt.skill_version_id, attempt.provider_config_id,
               attempt.provider_config_version, provider.display_name, attempt.model_name,
               attempt.document_sha256, attempt.skill_sha256,
               COALESCE(attempt.response_sha256, repeat('0', 64)),
               (SELECT count(*) FROM audit_ai_atom_drafts draft WHERE draft.attempt_id = attempt.id),
               attempt.coverage_json, attempt.warnings_json, attempt.requested_by_id, attempt.created_at
        FROM audit_ai_atomization_attempts attempt
        JOIN ai_provider_configs provider ON provider.id = attempt.provider_config_id
        WHERE attempt.canonical_run_id IS NOT NULL
          AND attempt.status IN ('draft_ready', 'committed')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO audit_ai_model_registry_items (
            id, registry_id, case_id, title, digital_product, work_type, object_type,
            source_clause, notes, source_refs_json, source_fingerprint,
            confidence_percent, sort_order, created_at
        )
        SELECT gen_random_uuid(), registry.id, draft.case_id, draft.title, draft.digital_product,
               draft.work_type, draft.object_type, draft.source_clause, draft.notes,
               draft.source_refs_json, draft.source_fingerprint, draft.confidence_percent,
               draft.sort_order, draft.created_at
        FROM audit_ai_atom_drafts draft
        JOIN audit_ai_atomization_attempts attempt ON attempt.id = draft.attempt_id
        JOIN audit_ai_model_registries registry
          ON registry.canonical_run_id = attempt.canonical_run_id
         AND registry.provider_config_id = attempt.provider_config_id
         AND registry.provider_config_version = attempt.provider_config_version
         AND registry.model_name = attempt.model_name
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = body || :appendix,
                summary = 'Как получить независимые реестры нескольких моделей, сравнить их и подтвердить генеральный список атомов.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
              AND body NOT LIKE '%Несколько моделей и генеральный реестр%'
            """
        ).bindparams(appendix=ARTICLE_APPENDIX)
    )


def downgrade() -> None:
    op.drop_index("uq_audit_atoms_ai_comparison_draft_id", table_name="audit_atoms")
    op.drop_constraint("fk_audit_atoms_ai_comparison_draft", "audit_atoms", type_="foreignkey")
    op.drop_column("audit_atoms", "ai_comparison_draft_id")
    op.drop_column("audit_atoms", "source_refs_json")
    op.drop_column("audit_atoms", "source_evidence_text")

    op.drop_index("ix_audit_ai_comparison_drafts_order", table_name="audit_ai_comparison_drafts")
    op.drop_index("ix_audit_ai_comparison_drafts_case_id", table_name="audit_ai_comparison_drafts")
    op.drop_index("ix_audit_ai_comparison_drafts_comparison_id", table_name="audit_ai_comparison_drafts")
    op.drop_table("audit_ai_comparison_drafts")
    op.drop_index("ix_audit_ai_model_comparisons_case_created_at", table_name="audit_ai_model_comparisons")
    op.drop_index("ix_audit_ai_model_comparisons_run_id", table_name="audit_ai_model_comparisons")
    op.drop_index("ix_audit_ai_model_comparisons_case_id", table_name="audit_ai_model_comparisons")
    op.drop_table("audit_ai_model_comparisons")
    op.drop_index("ix_audit_ai_registry_items_registry_order", table_name="audit_ai_model_registry_items")
    op.drop_index("ix_audit_ai_registry_items_case_id", table_name="audit_ai_model_registry_items")
    op.drop_index("ix_audit_ai_registry_items_registry_id", table_name="audit_ai_model_registry_items")
    op.drop_table("audit_ai_model_registry_items")
    op.drop_index("ix_audit_ai_model_registries_case_created_at", table_name="audit_ai_model_registries")
    op.drop_index("ix_audit_ai_model_registries_provider_id", table_name="audit_ai_model_registries")
    op.drop_index("ix_audit_ai_model_registries_run_id", table_name="audit_ai_model_registries")
    op.drop_index("ix_audit_ai_model_registries_case_id", table_name="audit_ai_model_registries")
    op.drop_table("audit_ai_model_registries")

    op.drop_index("ix_ai_provider_configs_kind_created_at", table_name="ai_provider_configs")
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM ai_provider_configs WHERE provider_kind = 'openai_compatible') > 1 THEN
                RAISE EXCEPTION 'Cannot downgrade while multiple AI provider profiles exist';
            END IF;
        END $$
        """
    )
    op.create_unique_constraint("uq_ai_provider_configs_kind", "ai_provider_configs", ["provider_kind"])
