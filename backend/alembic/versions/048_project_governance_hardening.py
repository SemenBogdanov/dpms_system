"""Harden project governance, evidence, and charter history.

Revision ID: 048_project_governance_hardening
Revises: 047_project_scope_revisions
"""
from alembic import op
import sqlalchemy as sa


revision = "048_project_governance_hardening"
down_revision = "047_project_scope_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_entities",
        sa.Column("baseline_outcome_statement", sa.Text(), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("baseline_success_criteria", sa.Text(), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("baseline_constraints", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE work_entities
        SET baseline_outcome_statement = outcome_statement,
            baseline_success_criteria = success_criteria,
            baseline_constraints = constraints
        WHERE baseline_locked_at IS NOT NULL
        """
    )
    op.drop_constraint(
        "ck_work_entity_artifacts_type",
        "work_entity_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_entity_artifacts_type",
        "work_entity_artifacts",
        (
            "artifact_type IN "
            "('note', 'decision', 'evidence', 'document', 'reference', 'other')"
        ),
    )
    op.create_check_constraint(
        "ck_work_entity_artifacts_evidence_parent",
        "work_entity_artifacts",
        (
            "(artifact_type != 'evidence' "
            "OR (milestone_id IS NOT NULL AND task_id IS NULL))"
        ),
    )
    op.execute(
        """
        UPDATE knowledge_articles
        SET body = replace(
                replace(
                    body,
                    '## Изменение scope после запуска',
                    '## Подтверждение результата

Критерий успеха в черновике является планом проверки. Фактическое
подтверждение оформляется артефактом типа «Подтверждение» и привязывается к
контрольной точке. Проект нельзя завершить, пока работы не приняты, точки не
пройдены и для пройденных точек не приложены подтверждения.

## Изменение паспорта после запуска

При запуске система фиксирует исходные результат, критерии успеха и ограничения.
После этого обычное редактирование их не меняет. Новая формулировка проводится
через управляемую поправку к паспорту: сначала показывается сравнение, затем
руководитель указывает причину, а система создает новую ревизию и запись в
журнале. Исходный baseline сохраняется.

## Изменение scope после запуска'
                ),
                '## AI-помощник

Если администратор подключил совместимый AI-провайдер, помощник может
предложить черновик результата, контрольных точек и работ. Предложение всегда
остается редактируемым черновиком. Модель не активирует проект и не применяет
изменения самостоятельно. При недоступности провайдера ручное планирование
продолжает работать.',
                '## AI-помощник

AI-помощник не входит в текущую версию пульта. Его подключение проектируется
отдельным безопасным модулем: модель сможет подготовить только проверяемый
черновик, а ручное планирование останется основным и независимым процессом.'
            ),
            updated_at = now()
        WHERE slug = 'rabochee-prostranstvo-proekta'
        """
    )


def downgrade() -> None:
    evidence_count = op.get_bind().execute(
        sa.text(
            """
            SELECT count(*)
            FROM work_entity_artifacts
            WHERE artifact_type = 'evidence'
            """
        )
    ).scalar_one()
    if evidence_count:
        raise RuntimeError(
            "Нельзя откатить 048: сначала перенесите артефакты "
            "типа evidence в поддерживаемую модель данных."
        )
    op.execute(
        """
        ALTER TABLE work_entity_artifacts
        DROP CONSTRAINT IF EXISTS ck_work_entity_artifacts_evidence_parent
        """
    )
    op.drop_constraint(
        "ck_work_entity_artifacts_type",
        "work_entity_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_entity_artifacts_type",
        "work_entity_artifacts",
        (
            "artifact_type IN "
            "('note', 'decision', 'document', 'reference', 'other')"
        ),
    )
    op.drop_column("work_entities", "baseline_constraints")
    op.drop_column("work_entities", "baseline_success_criteria")
    op.drop_column("work_entities", "baseline_outcome_statement")
