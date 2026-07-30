"""Add project-native tasks, artifacts, and dependencies

Revision ID: 044_work_entity_workspace
Revises: 043_work_entities
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "044_work_entity_workspace"
down_revision = "043_work_entities"
branch_labels = None
depends_on = None


WORKSPACE_KB_BODY = """# Рабочее пространство проекта

Обновлено: 2026-07-28

Раздел «Проекты и цели» позволяет сначала создать проект или цель, пригласить участников, а затем сформировать работу непосредственно внутри этой сущности.

## Проектные задачи

Проектная задача создается внутри проекта и автоматически доступна его участникам. Это отдельная сущность, а не личная задача сотрудника.

Для задачи можно задать:

- исполнителя из состава проекта;
- даты начала и окончания;
- приоритет и статус;
- критерии приемки;
- следующий шаг и ожидание;
- зависимости от других проектных задач.

Наблюдатель не назначается исполнителем. Участник может менять состояние назначенной ему задачи и вести журнал. Редактор управляет задачами и зависимостями. Владелец дополнительно управляет доступом.

## Контрольные точки

Контрольная точка использует тот же жизненный цикл, но отображается на карте как milestone. Она подходит для согласования, выпуска результата или другого проверяемого рубежа.

## Артефакты

Внутри проекта можно создать общую заметку, решение, документ-ссылку или справочный материал. Артефакт можно прикрепить к конкретной проектной задаче.

Проектные артефакты доступны всем участникам проекта. Ранее созданные личные заметки и личные задачи не раскрываются автоматически: они остаются внешними связанными объектами со своими правилами доступа.

## Зависимости и карта

Связь зависимости означает, что одна задача ожидает завершения другой. Система не разрешает циклические зависимости и не дает начать или завершить задачу с незавершенными предшественниками.

Карта проекта строится из задач, контрольных точек, артефактов и разрешенных внешних связей. Она показывает сроки, параллельное выполнение и направленные зависимости.

## Журнал

Журнал сохраняет автора и время ключевых действий:

- создание и изменение задачи;
- назначение исполнителя;
- изменение статуса;
- добавление записи о ходе работы;
- создание артефакта;
- добавление или удаление зависимости;
- изменение состава участников.

История проекта сохраняется после завершения задач и используется для разбора последовательности выполнения.
"""


def upgrade() -> None:
    op.drop_constraint(
        "ck_work_entity_members_role",
        "work_entity_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_entity_members_role",
        "work_entity_members",
        "role IN ('viewer', 'participant', 'editor')",
    )

    op.execute("CREATE SEQUENCE work_entity_tasks_task_number_seq START WITH 1001")
    op.create_table(
        "work_entity_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(
                "nextval('work_entity_tasks_task_number_seq'::regclass)"
            ),
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False, server_default="task"),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=True),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("waiting_for", sa.String(length=240), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "item_type IN ('task', 'milestone')",
            name="ck_work_entity_tasks_item_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'waiting', 'blocked', "
            "'review', 'done', 'cancelled')",
            name="ck_work_entity_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_work_entity_tasks_priority",
        ),
        sa.CheckConstraint(
            "(starts_at IS NULL OR due_at IS NULL OR due_at > starts_at)",
            name="ck_work_entity_tasks_dates",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_number",
            name="uq_work_entity_tasks_task_number",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_tasks_entity_id_id",
        ),
    )
    op.create_index(
        "ix_work_entity_tasks_entity_id",
        "work_entity_tasks",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_tasks_item_type",
        "work_entity_tasks",
        ["item_type"],
    )
    op.create_index(
        "ix_work_entity_tasks_status",
        "work_entity_tasks",
        ["status"],
    )
    op.create_index(
        "ix_work_entity_tasks_priority",
        "work_entity_tasks",
        ["priority"],
    )
    op.create_index(
        "ix_work_entity_tasks_assignee_id",
        "work_entity_tasks",
        ["assignee_id"],
    )
    op.create_index(
        "ix_work_entity_tasks_created_by_id",
        "work_entity_tasks",
        ["created_by_id"],
    )
    op.create_index(
        "ix_work_entity_tasks_starts_at",
        "work_entity_tasks",
        ["starts_at"],
    )
    op.create_index(
        "ix_work_entity_tasks_due_at",
        "work_entity_tasks",
        ["due_at"],
    )
    op.create_index(
        "ix_work_entity_tasks_entity_status_due",
        "work_entity_tasks",
        ["entity_id", "status", "due_at"],
    )
    op.create_index(
        "ix_work_entity_tasks_entity_assignee_status",
        "work_entity_tasks",
        ["entity_id", "assignee_id", "status"],
    )

    op.create_table(
        "work_entity_task_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "depends_on_task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "task_id <> depends_on_task_id",
            name="ck_work_entity_task_dependencies_no_self",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_dependencies_task_entity",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "depends_on_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_dependencies_prerequisite_entity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "depends_on_task_id",
            name="uq_work_entity_task_dependencies_pair",
        ),
    )
    op.create_index(
        "ix_work_entity_task_dependencies_entity_id",
        "work_entity_task_dependencies",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_task_dependencies_task_id",
        "work_entity_task_dependencies",
        ["task_id"],
    )
    op.create_index(
        "ix_work_entity_task_dependencies_depends_on_task_id",
        "work_entity_task_dependencies",
        ["depends_on_task_id"],
    )

    op.create_table(
        "work_entity_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "artifact_type",
            sa.String(length=30),
            nullable=False,
            server_default="note",
        ),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "artifact_type IN ('note', 'decision', 'document', 'reference', 'other')",
            name="ck_work_entity_artifacts_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_work_entity_artifacts_status",
        ),
        sa.CheckConstraint(
            "(body IS NOT NULL OR url IS NOT NULL)",
            name="ck_work_entity_artifacts_content",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["work_entity_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            name="fk_work_entity_artifacts_task_entity",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_entity_artifacts_entity_id",
        "work_entity_artifacts",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_artifacts_task_id",
        "work_entity_artifacts",
        ["task_id"],
    )
    op.create_index(
        "ix_work_entity_artifacts_artifact_type",
        "work_entity_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        "ix_work_entity_artifacts_status",
        "work_entity_artifacts",
        ["status"],
    )
    op.create_index(
        "ix_work_entity_artifacts_created_by_id",
        "work_entity_artifacts",
        ["created_by_id"],
    )
    op.create_index(
        "ix_work_entity_artifacts_entity_status_updated",
        "work_entity_artifacts",
        ["entity_id", "status", "updated_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '126876f6-a052-4483-93b3-fd2cbc0f8de0',
                'rabochee-prostranstvo-proekta',
                'Рабочее пространство проекта',
                'Проектные задачи, участники, артефакты, зависимости, карта и журнал.',
                'tasks',
                :body,
                'published',
                37,
                now(),
                now(),
                now()
            )
            ON CONFLICT DO NOTHING
            """
        ).bindparams(body=WORKSPACE_KB_BODY)
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM knowledge_articles
        WHERE id = '126876f6-a052-4483-93b3-fd2cbc0f8de0'
          AND slug = 'rabochee-prostranstvo-proekta'
        """
    )

    op.drop_index(
        "ix_work_entity_artifacts_entity_status_updated",
        table_name="work_entity_artifacts",
    )
    op.drop_index(
        "ix_work_entity_artifacts_created_by_id",
        table_name="work_entity_artifacts",
    )
    op.drop_index(
        "ix_work_entity_artifacts_status",
        table_name="work_entity_artifacts",
    )
    op.drop_index(
        "ix_work_entity_artifacts_artifact_type",
        table_name="work_entity_artifacts",
    )
    op.drop_index(
        "ix_work_entity_artifacts_task_id",
        table_name="work_entity_artifacts",
    )
    op.drop_index(
        "ix_work_entity_artifacts_entity_id",
        table_name="work_entity_artifacts",
    )
    op.drop_table("work_entity_artifacts")

    op.drop_index(
        "ix_work_entity_task_dependencies_depends_on_task_id",
        table_name="work_entity_task_dependencies",
    )
    op.drop_index(
        "ix_work_entity_task_dependencies_task_id",
        table_name="work_entity_task_dependencies",
    )
    op.drop_index(
        "ix_work_entity_task_dependencies_entity_id",
        table_name="work_entity_task_dependencies",
    )
    op.drop_table("work_entity_task_dependencies")

    op.drop_index(
        "ix_work_entity_tasks_entity_assignee_status",
        table_name="work_entity_tasks",
    )
    op.drop_index(
        "ix_work_entity_tasks_entity_status_due",
        table_name="work_entity_tasks",
    )
    op.drop_index("ix_work_entity_tasks_due_at", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_starts_at", table_name="work_entity_tasks")
    op.drop_index(
        "ix_work_entity_tasks_created_by_id",
        table_name="work_entity_tasks",
    )
    op.drop_index(
        "ix_work_entity_tasks_assignee_id",
        table_name="work_entity_tasks",
    )
    op.drop_index("ix_work_entity_tasks_priority", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_status", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_item_type", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_entity_id", table_name="work_entity_tasks")
    op.drop_table("work_entity_tasks")
    op.execute("DROP SEQUENCE work_entity_tasks_task_number_seq")

    op.execute(
        "UPDATE work_entity_members SET role = 'viewer' WHERE role = 'participant'"
    )
    op.drop_constraint(
        "ck_work_entity_members_role",
        "work_entity_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_entity_members_role",
        "work_entity_members",
        "role IN ('viewer', 'editor')",
    )
