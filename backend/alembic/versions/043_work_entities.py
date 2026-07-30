"""Add projects, goals, and typed entity links

Revision ID: 043_work_entities
Revises: 042_auth_session_hardening
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "043_work_entities"
down_revision = "042_auth_session_hardening"
branch_labels = None
depends_on = None


WORK_ENTITIES_KB_BODY = """# Проекты и цели

Обновлено: 2026-07-28

Раздел «Проекты и цели» объединяет связанные задачи, заметки, сроки и другие сущности в одном рабочем контексте.

## Какие сущности можно создать

- проект;
- инициатива;
- цель;
- система;
- KPI-контекст;
- другая сущность.

KPI в первой версии является контекстом для связей. Значения, формулы и отчетные периоды KPI в этом разделе пока не рассчитываются.

## Как работают связи

К сущности можно привязать:

- DPMS-задачу;
- личную задачу;
- заметку;
- элемент трекера сроков;
- другую сущность.

Один объект можно одновременно связать с несколькими сущностями. Например, одна задача может относиться к проекту, стратегической цели и KPI-контексту.

Тип связи поясняет смысл:

- `В составе` — объект является частью сущности;
- `Вносит вклад` — объект помогает достичь цели;
- `Зависит от` — выполнение зависит от связанного объекта;
- `Измеряет` — объект используется как показатель;
- `Связано` — информационная связь без иерархии.

## Доступ

Новая сущность приватна по умолчанию. Владелец может открыть ее выбранным контактам:

- наблюдатель просматривает сущность;
- редактор меняет описание и связи;
- только владелец управляет доступом и архивированием.

Важно: связь не предоставляет доступ к исходному объекту. Если участнику доступен проект, но недоступна связанная личная задача или заметка, содержимое этого объекта не раскрывается.

## Сводка

Сводка показывает факты по прямым доступным связям:

- количество связанных объектов;
- число завершенных рабочих элементов;
- просрочки;
- ближайший срок;
- распределение по типам и статусам.

Система не строит скрытый взвешенный рейтинг и не меняет статус проекта автоматически.

## Рекомендуемый порядок

1. Создайте проект, цель или другую сущность.
2. Заполните описание и сроки.
3. Добавьте существующие задачи, заметки и контрольные сроки.
4. Свяжите проект с более крупной целью или KPI-контекстом.
5. При необходимости откройте доступ наблюдателям или редакторам.
6. Используйте сводку для контроля состояния и ближайших сроков.
"""


def upgrade() -> None:
    op.create_table(
        "work_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::character varying[]"),
        ),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "entity_type IN ('project', 'initiative', 'goal', 'system', 'kpi', 'other')",
            name="ck_work_entities_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'done', 'archived')",
            name="ck_work_entities_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'shared')",
            name="ck_work_entities_visibility",
        ),
        sa.CheckConstraint(
            "(starts_at IS NULL OR due_at IS NULL OR due_at > starts_at)",
            name="ck_work_entities_dates",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_entities_owner_id", "work_entities", ["owner_id"])
    op.create_index("ix_work_entities_entity_type", "work_entities", ["entity_type"])
    op.create_index("ix_work_entities_status", "work_entities", ["status"])
    op.create_index("ix_work_entities_visibility", "work_entities", ["visibility"])
    op.create_index("ix_work_entities_due_at", "work_entities", ["due_at"])
    op.create_index(
        "ix_work_entities_owner_status_updated",
        "work_entities",
        ["owner_id", "status", "updated_at"],
    )

    op.create_table(
        "work_entity_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('viewer', 'editor')", name="ck_work_entity_members_role"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["work_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "user_id", name="uq_work_entity_members_entity_user"),
    )
    op.create_index("ix_work_entity_members_entity_id", "work_entity_members", ["entity_id"])
    op.create_index("ix_work_entity_members_user_id", "work_entity_members", ["user_id"])
    op.create_index("ix_work_entity_members_role", "work_entity_members", ["role"])

    op.create_table(
        "work_entity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("personal_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quick_note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deadline_tracker_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relation_type", sa.String(length=30), nullable=False, server_default="contains"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "num_nonnulls(target_entity_id, task_id, personal_task_id, quick_note_id, "
            "deadline_tracker_id) = 1",
            name="ck_work_entity_links_exactly_one_target",
        ),
        sa.CheckConstraint(
            "(target_entity_id IS NULL OR target_entity_id <> entity_id)",
            name="ck_work_entity_links_no_self_link",
        ),
        sa.CheckConstraint(
            "relation_type IN ('contains', 'contributes_to', 'depends_on', 'measures', 'related')",
            name="ck_work_entity_links_relation_type",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deadline_tracker_id"], ["deadline_trackers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["work_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["personal_task_id"], ["personal_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quick_note_id"], ["quick_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["work_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id",
            "target_entity_id",
            name="uq_work_entity_links_entity_target_entity",
        ),
        sa.UniqueConstraint("entity_id", "task_id", name="uq_work_entity_links_entity_task"),
        sa.UniqueConstraint(
            "entity_id",
            "personal_task_id",
            name="uq_work_entity_links_entity_personal_task",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "quick_note_id",
            name="uq_work_entity_links_entity_quick_note",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "deadline_tracker_id",
            name="uq_work_entity_links_entity_deadline_tracker",
        ),
    )
    op.create_index("ix_work_entity_links_entity_id", "work_entity_links", ["entity_id"])
    op.create_index("ix_work_entity_links_target_entity_id", "work_entity_links", ["target_entity_id"])
    op.create_index("ix_work_entity_links_task_id", "work_entity_links", ["task_id"])
    op.create_index("ix_work_entity_links_personal_task_id", "work_entity_links", ["personal_task_id"])
    op.create_index("ix_work_entity_links_quick_note_id", "work_entity_links", ["quick_note_id"])
    op.create_index("ix_work_entity_links_deadline_tracker_id", "work_entity_links", ["deadline_tracker_id"])
    op.create_index("ix_work_entity_links_relation_type", "work_entity_links", ["relation_type"])
    op.create_index(
        "ix_work_entity_links_entity_position",
        "work_entity_links",
        ["entity_id", "position", "created_at"],
    )

    op.create_table(
        "work_entity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["work_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_entity_events_entity_id", "work_entity_events", ["entity_id"])
    op.create_index("ix_work_entity_events_actor_id", "work_entity_events", ["actor_id"])
    op.create_index("ix_work_entity_events_event_type", "work_entity_events", ["event_type"])
    op.create_index("ix_work_entity_events_created_at", "work_entity_events", ["created_at"])
    op.create_index(
        "ix_work_entity_events_entity_created",
        "work_entity_events",
        ["entity_id", "created_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '36e051b2-963a-4e15-a0d7-cf691dc3b631',
                'proekty-i-celi-svyazi',
                'Проекты и цели: сущности и связи',
                'Как объединять задачи, заметки, сроки, проекты, цели и KPI-контексты.',
                'tasks',
                :body,
                'published',
                36,
                now(),
                now(),
                now()
            )
            ON CONFLICT DO NOTHING
            """
        ).bindparams(body=WORK_ENTITIES_KB_BODY)
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM knowledge_articles
        WHERE id = '36e051b2-963a-4e15-a0d7-cf691dc3b631'
          AND slug = 'proekty-i-celi-svyazi'
        """
    )

    op.drop_index("ix_work_entity_events_entity_created", table_name="work_entity_events")
    op.drop_index("ix_work_entity_events_created_at", table_name="work_entity_events")
    op.drop_index("ix_work_entity_events_event_type", table_name="work_entity_events")
    op.drop_index("ix_work_entity_events_actor_id", table_name="work_entity_events")
    op.drop_index("ix_work_entity_events_entity_id", table_name="work_entity_events")
    op.drop_table("work_entity_events")

    op.drop_index("ix_work_entity_links_entity_position", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_relation_type", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_deadline_tracker_id", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_quick_note_id", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_personal_task_id", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_task_id", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_target_entity_id", table_name="work_entity_links")
    op.drop_index("ix_work_entity_links_entity_id", table_name="work_entity_links")
    op.drop_table("work_entity_links")

    op.drop_index("ix_work_entity_members_role", table_name="work_entity_members")
    op.drop_index("ix_work_entity_members_user_id", table_name="work_entity_members")
    op.drop_index("ix_work_entity_members_entity_id", table_name="work_entity_members")
    op.drop_table("work_entity_members")

    op.drop_index("ix_work_entities_owner_status_updated", table_name="work_entities")
    op.drop_index("ix_work_entities_due_at", table_name="work_entities")
    op.drop_index("ix_work_entities_visibility", table_name="work_entities")
    op.drop_index("ix_work_entities_status", table_name="work_entities")
    op.drop_index("ix_work_entities_entity_type", table_name="work_entities")
    op.drop_index("ix_work_entities_owner_id", table_name="work_entities")
    op.drop_table("work_entities")
