"""Protect the causal route from project work to checkpoints.

Revision ID: 049_project_route_integrity
Revises: 048_project_governance_hardening
"""
from alembic import op
import sqlalchemy as sa


revision = "049_project_route_integrity"
down_revision = "048_project_governance_hardening"
branch_labels = None
depends_on = None


ARTICLE_SECTION = """## Связь работы с контрольной точкой

Каждая работа проекта готовит ровно одну активную контрольную точку. Эту связь
нельзя просто удалить: при изменении маршрута руководитель выбирает новую точку
и указывает причину, а система атомарно переносит связь и сохраняет событие в
журнале. Контрольную точку нельзя отменить, пока связанные работы не отменены
или не переназначены.

"""


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM work_entity_schedule_dependencies
                WHERE predecessor_task_id IS NOT NULL
                  AND successor_milestone_id IS NOT NULL
                  AND status = 'active'
                GROUP BY entity_id, predecessor_task_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot enforce project route integrity: a task has multiple active target milestones';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM work_entity_schedule_dependencies dependency
                JOIN work_entities entity
                  ON entity.id = dependency.entity_id
                JOIN work_entity_tasks task
                  ON task.id = dependency.predecessor_task_id
                 AND task.entity_id = dependency.entity_id
                JOIN work_entity_milestones milestone
                  ON milestone.id = dependency.successor_milestone_id
                 AND milestone.entity_id = dependency.entity_id
                WHERE entity.entity_type = 'project'
                  AND dependency.status = 'active'
                  AND task.status != 'cancelled'
                  AND milestone.status = 'cancelled'
            ) THEN
                RAISE EXCEPTION
                    'Cannot enforce project route integrity: active work targets a cancelled milestone';
            END IF;
        END
        $$;
        """
    )
    op.create_index(
        "uq_work_entity_schedule_active_task_target",
        "work_entity_schedule_dependencies",
        ["entity_id", "predecessor_task_id"],
        unique=True,
        postgresql_where=sa.text(
            "predecessor_task_id IS NOT NULL "
            "AND successor_milestone_id IS NOT NULL "
            "AND status = 'active'"
        ),
    )
    op.execute(
        f"""
        UPDATE knowledge_articles
        SET body = replace(
                body,
                '## Изменение scope после запуска',
                '{ARTICLE_SECTION}## Изменение scope после запуска'
            ),
            updated_at = now()
        WHERE slug = 'rabochee-prostranstvo-proekta'
          AND body NOT LIKE '%## Связь работы с контрольной точкой%'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "uq_work_entity_schedule_active_task_target",
        table_name="work_entity_schedule_dependencies",
    )
    op.execute(
        f"""
        UPDATE knowledge_articles
        SET body = replace(body, '{ARTICLE_SECTION}', ''),
            updated_at = now()
        WHERE slug = 'rabochee-prostranstvo-proekta'
        """
    )
