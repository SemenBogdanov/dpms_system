"""Add external-model drafts to canonical audit-tz runs.

Revision ID: 071_canonical_atomization
Revises: 070_audit_document_binding
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "071_canonical_atomization"
down_revision = "070_audit_document_binding"
branch_labels = None
depends_on = None


ARTICLE_BODY = """Обновлено: 2026-08-24

## Что делает атомизация ТЗ
DPMS разделяет процесс на три понятных результата:

1. **Исходные фрагменты** — абзацы и строки таблиц, извлеченные из неизменяемого DOCX. Это техническая единица контроля полноты, а не готовый атом.
2. **ИИ-черновик атомов** — самостоятельные элементы цифрового продукта: экраны, вкладки, формы, реестры, таблицы, фильтры, показатели, отчеты, действия, уведомления, интеграции и наблюдаемое поведение.
3. **Реестр атомов** — только те черновики, которые ответственный сотрудник проверил и явно подтвердил.

Поэтому число исходных фрагментов обычно заметно больше числа итоговых атомов. Система не пытается сделать атом из каждого абзаца.

## Как запустить
1. Откройте нужный аудит и вкладку `Атомы`.
2. Нажмите `Сформировать с ИИ`.
3. Выберите неизменяемое ТЗ DOCX и активную проверенную методику.
4. Нажмите `Подготовить документ`. Отдельный runtime проверит SHA-256, структуру DOCX и полноту извлечения. Внешний ИИ на этом шаге не вызывается.
5. После подготовки проверьте название ИИ-провайдера и состав передаваемых данных. Подтвердите передачу обезличенных фрагментов и нажмите `Запустить атомизацию`.
6. Дождитесь завершения пакетной обработки. Окно можно закрыть: прогресс сохраняется и продолжится в worker.
7. Проверьте найденные атомы, их типы и основания в ТЗ. Исправьте формулировки или исключите неподходящие строки.
8. Нажмите `Записать в реестр`. Только после этого строки `ITEM-…` появятся во вкладке `Атомы` выбранного аудита.

## Как контролируется качество
Большое ТЗ обрабатывается последовательными ограниченными пакетами, чтобы модель не потеряла середину документа. Каждый исходный фрагмент обязан получить одно решение: атомизирован, служебный текст, повтор, вне области проверки, требует уточнения или заблокирован. Неполный ответ модели не сохраняется. До показа пользователю повторяющиеся кандидаты из разных пакетов объединяются, поэтому количество атомов не равно количеству фрагментов и не складывается механически из пакетных ответов.

Каждый черновик содержит внутреннюю ссылку на конкретные фрагменты и выдержки из исходного DOCX. Внешней модели передаются только обезличенный текст и псевдонимные ID фрагментов. Название файла, локаторы, внутренние пути, SHA-256 и служебный идентификатор запуска не передаются. Реквизиты, похожие на номер договора, автоматически заменяются служебной меткой; вводить или подтверждать номер договора не нужно.

При сетевой ошибке уже завершенные пакеты сохраняются, поэтому повторная попытка не обязана начинать весь документ заново. Все старты, ошибки, готовность черновика и ручное подтверждение записываются в историю аудита.

## Граница текущей версии
Текущая версия формирует проверяемый primary-черновик и требует ручного подтверждения. Независимые challenger, adjudicator, critic, workbook QA и architect gates методики `audit-tz` остаются последующими этапами и не подменяются текущим черновиком.
"""


def upgrade() -> None:
    op.drop_constraint("ck_audit_tz_runs_status", "audit_tz_runs", type_="check")
    op.add_column(
        "audit_tz_runs",
        sa.Column("atom_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_tz_runs",
        sa.Column("completed_batch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_tz_runs",
        sa.Column("total_batch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "audit_tz_runs",
        sa.Column("external_ai_called", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_audit_tz_runs_status",
        "audit_tz_runs",
        "status IN ('queued', 'running', 'preflight_pass', 'atomization_queued', "
        "'atomizing', 'draft_ready', 'committed', 'blocked', 'failed')",
    )
    op.create_check_constraint("ck_audit_tz_runs_atoms", "audit_tz_runs", "atom_count >= 0")
    op.create_check_constraint(
        "ck_audit_tz_runs_completed_batches",
        "audit_tz_runs",
        "completed_batch_count >= 0",
    )
    op.create_check_constraint(
        "ck_audit_tz_runs_total_batches",
        "audit_tz_runs",
        "total_batch_count >= 0",
    )
    op.create_check_constraint(
        "ck_audit_tz_runs_batch_progress",
        "audit_tz_runs",
        "completed_batch_count <= total_batch_count",
    )

    op.drop_constraint("ck_audit_tz_runtime_jobs_kind", "audit_tz_runtime_jobs", type_="check")
    op.drop_constraint("ck_audit_tz_runtime_jobs_target", "audit_tz_runtime_jobs", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_kind",
        "audit_tz_runtime_jobs",
        "kind IN ('skill_selftest', 'preflight', 'atomization')",
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        "(kind = 'skill_selftest' AND run_id IS NULL) OR "
        "(kind IN ('preflight', 'atomization') AND run_id IS NOT NULL)",
    )
    op.create_index(
        "uq_audit_tz_runtime_jobs_atomization",
        "audit_tz_runtime_jobs",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'atomization'"),
    )

    op.drop_constraint("ck_audit_tz_artifacts_kind", "audit_tz_artifacts", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_artifacts_kind",
        "audit_tz_artifacts",
        "kind IN ('identity_report', 'gated_evidence_bundle', 'source_units', "
        "'primary_prompt', 'primary_atom_package')",
    )

    op.add_column(
        "audit_ai_atomization_attempts",
        sa.Column("canonical_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "audit_ai_atomization_attempts",
        sa.Column(
            "batch_results_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_audit_ai_attempts_canonical_run",
        "audit_ai_atomization_attempts",
        "audit_tz_runs",
        ["canonical_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_audit_ai_attempts_canonical_run",
        "audit_ai_atomization_attempts",
        ["canonical_run_id"],
        unique=True,
        postgresql_where=sa.text("canonical_run_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = :body,
                summary = 'Как превратить фрагменты DOCX в проверяемый ИИ-черновик и записать подтвержденные атомы в реестр.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        ).bindparams(body=ARTICLE_BODY)
    )


def downgrade() -> None:
    op.drop_index("uq_audit_ai_attempts_canonical_run", table_name="audit_ai_atomization_attempts")
    op.drop_constraint(
        "fk_audit_ai_attempts_canonical_run",
        "audit_ai_atomization_attempts",
        type_="foreignkey",
    )
    op.drop_column("audit_ai_atomization_attempts", "batch_results_json")
    op.drop_column("audit_ai_atomization_attempts", "canonical_run_id")

    op.execute("DELETE FROM audit_tz_artifacts WHERE kind IN ('primary_prompt', 'primary_atom_package')")
    op.drop_constraint("ck_audit_tz_artifacts_kind", "audit_tz_artifacts", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_artifacts_kind",
        "audit_tz_artifacts",
        "kind IN ('identity_report', 'gated_evidence_bundle', 'source_units')",
    )

    op.execute("DELETE FROM audit_tz_runtime_jobs WHERE kind = 'atomization'")
    op.drop_index("uq_audit_tz_runtime_jobs_atomization", table_name="audit_tz_runtime_jobs")
    op.drop_constraint("ck_audit_tz_runtime_jobs_target", "audit_tz_runtime_jobs", type_="check")
    op.drop_constraint("ck_audit_tz_runtime_jobs_kind", "audit_tz_runtime_jobs", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_kind",
        "audit_tz_runtime_jobs",
        "kind IN ('skill_selftest', 'preflight')",
    )
    op.create_check_constraint(
        "ck_audit_tz_runtime_jobs_target",
        "audit_tz_runtime_jobs",
        "(kind = 'skill_selftest' AND run_id IS NULL) OR "
        "(kind = 'preflight' AND run_id IS NOT NULL)",
    )

    op.execute(
        "UPDATE audit_tz_runs SET status = 'preflight_pass', current_phase = 'preflight_complete' "
        "WHERE status IN ('atomization_queued', 'atomizing', 'draft_ready', 'committed')"
    )
    op.drop_constraint("ck_audit_tz_runs_batch_progress", "audit_tz_runs", type_="check")
    op.drop_constraint("ck_audit_tz_runs_total_batches", "audit_tz_runs", type_="check")
    op.drop_constraint("ck_audit_tz_runs_completed_batches", "audit_tz_runs", type_="check")
    op.drop_constraint("ck_audit_tz_runs_atoms", "audit_tz_runs", type_="check")
    op.drop_constraint("ck_audit_tz_runs_status", "audit_tz_runs", type_="check")
    op.create_check_constraint(
        "ck_audit_tz_runs_status",
        "audit_tz_runs",
        "status IN ('queued', 'running', 'preflight_pass', 'blocked', 'failed')",
    )
    op.drop_column("audit_tz_runs", "external_ai_called")
    op.drop_column("audit_tz_runs", "total_batch_count")
    op.drop_column("audit_tz_runs", "completed_batch_count")
    op.drop_column("audit_tz_runs", "atom_count")
