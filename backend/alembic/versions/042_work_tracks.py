"""Add work tracks
Revision ID: 042_work_tracks
Revises: 041_task_review_events
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "042_work_tracks"
down_revision = "041_task_review_events"
branch_labels = None
depends_on = None

WORK_TRACKS_KB_BODY = """# Треки задач

Кратко: трек — это последовательность связанных действий, где можно объединить DPMS-задачи, личные задачи и ручные шаги в один управляемый процесс.

Последнее обновление: 09.07.2026

Трек — это последовательность связанных действий. Он нужен, когда одной задачи недостаточно: есть несколько шагов, часть из них живет в глобальной очереди, часть — в личных задачах, а часть пока существует как ручной пункт контроля.

## Когда использовать трек

Используйте трек для процессов, где важны порядок, контроль и срок:

- миграция сервиса;
- подготовка отчета;
- запуск новой витрины или ETL;
- цепочка задач по подразделению;
- контроль поручений после встречи;
- личный план работ по инициативе.

## Из чего состоит трек

У трека есть:

- название;
- описание;
- статус;
- дата старта;
- дата окончания;
- упорядоченный список элементов.

Элемент трека может быть:

- DPMS-задачей из глобальной очереди;
- личной задачей;
- ручным шагом без отдельной задачи.

## Как считается прогресс

Прогресс считается по элементам трека.

- DPMS-задача считается завершенной, когда она принята в системе и находится в статусе `done`.
- Личная задача считается завершенной, когда ее статус `done`.
- Ручной шаг считается завершенным, когда его статус `done` или `skipped`.

Если у элемента есть собственный срок, он используется как контрольный срок элемента. Если собственного срока нет, система берет срок связанной задачи.

## Рекомендуемый порядок работы

1. Создайте трек и задайте понятное название.
2. Добавьте существующие DPMS-задачи или личные задачи.
3. Добавьте ручные шаги, если отдельной задачи еще нет.
4. Расположите элементы в нужном порядке.
5. Следите за прогрессом и ближайшим сроком.
6. Закройте или архивируйте трек, когда процесс завершен.

## Чем трек отличается от трекера сроков

Трекер сроков отвечает на вопрос: когда истекает срок.

Трек отвечает на вопрос: из каких шагов состоит работа и что уже сделано.

В дальнейшем треки можно будет связывать с сущностями, KPI, проектами и отчетными страницами.
"""


def upgrade() -> None:
    op.create_table(
        "work_tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("color", sa.String(length=30), nullable=False, server_default="slate"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'paused', 'done', 'archived')", name="ck_work_tracks_status"),
        sa.CheckConstraint("(start_at IS NULL OR due_at IS NULL OR due_at > start_at)", name="ck_work_tracks_dates"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_tracks_owner_id", "work_tracks", ["owner_id"])
    op.create_index("ix_work_tracks_status", "work_tracks", ["status"])
    op.create_index("ix_work_tracks_due_at", "work_tracks", ["due_at"])

    op.create_table(
        "work_track_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("personal_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("item_type IN ('task', 'personal_task', 'manual')", name="ck_work_track_items_type"),
        sa.CheckConstraint("status IN ('active', 'waiting', 'blocked', 'done', 'skipped')", name="ck_work_track_items_status"),
        sa.CheckConstraint("(starts_at IS NULL OR due_at IS NULL OR due_at > starts_at)", name="ck_work_track_items_dates"),
        sa.CheckConstraint("(item_type <> 'manual' OR title IS NOT NULL)", name="ck_work_track_items_manual_title"),
        sa.ForeignKeyConstraint(["personal_task_id"], ["personal_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["track_id"], ["work_tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "task_id", name="uq_work_track_items_task"),
        sa.UniqueConstraint("track_id", "personal_task_id", name="uq_work_track_items_personal_task"),
    )
    op.create_index("ix_work_track_items_track_id", "work_track_items", ["track_id"])
    op.create_index("ix_work_track_items_item_type", "work_track_items", ["item_type"])
    op.create_index("ix_work_track_items_status", "work_track_items", ["status"])
    op.create_index("ix_work_track_items_position", "work_track_items", ["track_id", "position"])
    op.create_index("ix_work_track_items_task_id", "work_track_items", ["task_id"])
    op.create_index("ix_work_track_items_personal_task_id", "work_track_items", ["personal_task_id"])
    op.create_index("ix_work_track_items_due_at", "work_track_items", ["due_at"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '7f7dc2e6-5055-4fe2-b8f8-cad1b7699c3f',
                'treki-zadach-posledovatelnosti',
                'Треки задач: последовательности и контроль шагов',
                'Как использовать треки для цепочек DPMS-задач, личных задач и ручных шагов.',
                'tasks',
                :body,
                'published',
                34,
                now(),
                now(),
                now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = EXCLUDED.status,
                sort_order = EXCLUDED.sort_order,
                updated_at = now(),
                published_at = now()
            """
        ),
        {"body": WORK_TRACKS_KB_BODY},
    )


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_articles WHERE slug = 'treki-zadach-posledovatelnosti'")
    op.drop_index("ix_work_track_items_due_at", table_name="work_track_items")
    op.drop_index("ix_work_track_items_personal_task_id", table_name="work_track_items")
    op.drop_index("ix_work_track_items_task_id", table_name="work_track_items")
    op.drop_index("ix_work_track_items_position", table_name="work_track_items")
    op.drop_index("ix_work_track_items_status", table_name="work_track_items")
    op.drop_index("ix_work_track_items_item_type", table_name="work_track_items")
    op.drop_index("ix_work_track_items_track_id", table_name="work_track_items")
    op.drop_table("work_track_items")
    op.drop_index("ix_work_tracks_due_at", table_name="work_tracks")
    op.drop_index("ix_work_tracks_status", table_name="work_tracks")
    op.drop_index("ix_work_tracks_owner_id", table_name="work_tracks")
    op.drop_table("work_tracks")
