"""Add audit atomization slice

Revision ID: 058_audit_atomization
Revises: 057_email_outbox
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "058_audit_atomization"
down_revision = "057_email_outbox"
branch_labels = None
depends_on = None


AUDIT_ARTICLE = {
    "id": "8f3a8032-2f63-4c0e-b14d-5f6d3ec8f301",
    "slug": "audit-atomization-import",
    "title": "Аудит: атомизация и XLSX-импорт",
    "summary": "Как подготовить реестр audit_example.xlsx, проверить preview и безопасно импортировать атомы договора.",
    "section": "audit",
    "body": """Обновлено: 2026-08-21

## Что импортируется
Первый локальный срез читает только именованный лист `5.1 Реестр технических объектов` шаблона `audit_example.xlsx` с точными заголовками. Сводные листы, графики, pivot и формулы не создают бизнес-факты.

## Безопасность
- Реальный номер договора не возвращается в preview.
- Вместо него используется маска и keyed fingerprint.
- Гиперссылки из Excel не открываются и не следуются сервером во время импорта.
- Preview показывает только маску ссылки на объект.

## Правила импорта
1. Сначала запускайте preview.
2. Commit требует тот же `expected_sha256`, который вернул preview.
3. Если в любой строке есть ошибка, commit отклоняется целиком.
4. Повторный commit того же файла идемпотентен.

## Что создается
- `AuditCase` по точному договору;
- `AuditAtom` по строкам первого листа;
- `AuditImportBatch` и `AuditEvent` для provenance и истории.""",
}


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("audit_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_case_sequence_seq START WITH 1 INCREMENT BY 1")

    op.create_table(
        "audit_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "case_sequence",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("nextval('audit_case_sequence_seq'::regclass)"),
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("digital_product", sa.String(length=255), nullable=False),
        sa.Column("contract_reference_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("contract_reference_mask", sa.String(length=255), nullable=True),
        sa.Column("contract_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_sequence", name="uq_audit_cases_case_sequence"),
        sa.CheckConstraint(
            "status IN ('draft', 'atomization', 'ready', 'archived')",
            name="ck_audit_cases_status",
        ),
    )
    op.create_index(
        "uq_audit_cases_contract_reference_fingerprint",
        "audit_cases",
        ["contract_reference_fingerprint"],
        unique=True,
        postgresql_where=sa.text("contract_reference_fingerprint IS NOT NULL"),
    )
    op.create_index("ix_audit_cases_status", "audit_cases", ["status"])

    op.create_table(
        "audit_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_sheet", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="committed"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", name="uq_audit_import_batches_sha256"),
        sa.CheckConstraint("status IN ('committed')", name="ck_audit_import_batches_status"),
    )
    op.create_index("ix_audit_import_batches_sha256", "audit_import_batches", ["sha256"])

    op.create_table(
        "audit_atoms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_code", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("digital_product", sa.String(length=255), nullable=False),
        sa.Column("work_type", sa.String(length=255), nullable=True),
        sa.Column("object_type", sa.String(length=255), nullable=True),
        sa.Column("source_clause", sa.String(length=500), nullable=True),
        sa.Column("system_url", sa.String(length=1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("source_sheet", sa.String(length=255), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alpha_result", sa.String(length=40), nullable=True),
        sa.Column("alpha_result_raw", sa.String(length=500), nullable=True),
        sa.Column("alpha_date", sa.Date(), nullable=True),
        sa.Column("commission_result", sa.String(length=40), nullable=True),
        sa.Column("commission_result_raw", sa.String(length=500), nullable=True),
        sa.Column("commission_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_batch_id"], ["audit_import_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("state IN ('draft', 'ready', 'excluded')", name="ck_audit_atoms_state"),
        sa.CheckConstraint(
            "alpha_result IS NULL OR alpha_result IN ('present', 'not_present', 'partial', 'not_applicable', 'needs_clarification')",
            name="ck_audit_atoms_alpha_result",
        ),
        sa.CheckConstraint(
            "commission_result IS NULL OR commission_result IN ('confirmed', 'not_confirmed', 'deferred', 'not_applicable')",
            name="ck_audit_atoms_commission_result",
        ),
    )
    op.create_index("ix_audit_atoms_case_sort_order", "audit_atoms", ["case_id", "sort_order"])
    op.create_index("uq_audit_atoms_case_item_code", "audit_atoms", ["case_id", "item_code"], unique=True)
    op.create_index(
        "uq_audit_atoms_case_source_fingerprint",
        "audit_atoms",
        ["case_id", "source_fingerprint"],
        unique=True,
        postgresql_where=sa.text("source_fingerprint IS NOT NULL"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("atom_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["atom_id"], ["audit_atoms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["import_batch_id"], ["audit_import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_case_created_at", "audit_events", ["case_id", "created_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 210,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        AUDIT_ARTICLE,
    )


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_articles WHERE slug = 'audit-atomization-import'")

    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_case_created_at", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("uq_audit_atoms_case_source_fingerprint", table_name="audit_atoms")
    op.drop_index("uq_audit_atoms_case_item_code", table_name="audit_atoms")
    op.drop_index("ix_audit_atoms_case_sort_order", table_name="audit_atoms")
    op.drop_table("audit_atoms")

    op.drop_index("ix_audit_import_batches_sha256", table_name="audit_import_batches")
    op.drop_table("audit_import_batches")

    op.drop_index("ix_audit_cases_status", table_name="audit_cases")
    op.drop_index("uq_audit_cases_contract_reference_fingerprint", table_name="audit_cases")
    op.drop_table("audit_cases")
    op.execute("DROP SEQUENCE IF EXISTS audit_case_sequence_seq")

    op.drop_column("users", "audit_enabled")
