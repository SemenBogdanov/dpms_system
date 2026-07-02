"""Add universal deadline trackers

Revision ID: 033_deadline_trackers
Revises: 032_personal_task_history
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "033_deadline_trackers"
down_revision = "032_personal_task_history"
branch_labels = None
depends_on = None


PERSONAL_TASKS_KB_BODY = """Обновлено: 2026-07-02

## Зачем нужны личные задачи
Личная задача — приватный контур контроля поручений, заметок, следующих шагов и подготовки материала до вывода в глобальную очередь DPMS. Она не участвует в Q, MPW и командной очереди, пока пользователь сам не выведет ее в глобальную задачу.

## Основные поля
- Название — короткая формулировка контролируемого вопроса. Хорошее название позволяет понять суть без открытия карточки.
- Описание — исходный контекст: что произошло, зачем это нужно, какая проблема или поручение фиксируется.
- Рабочие заметки — черновые мысли, follow-up, выводы со встреч, промежуточные наблюдения. Это поле можно вести свободно.
- Статус — текущее состояние: Входящие, План, Следующее, В работе, Ожидание, Блок, Готово, Архив.
- Приоритет — управленческая важность: низкий, средний, высокий, критичный.
- Категория — природа задачи: работа, совещание, follow-up, разбор, решение, админ или другое.
- Следующий шаг — ближайшее конкретное действие, которое двигает вопрос дальше.
- Дата следующего шага — когда нужно вернуться к ближайшему действию.
- Дедлайн — конечный срок, к которому задача или контрольный вопрос должны быть закрыты.

## Контекст и связи
- Проект / поток — направление, инициатива или рабочий контур, к которому относится задача.
- Контекст — источник появления задачи: совещание, поручение, звонок, миграция, инцидент, идея.
- Ответственный / кому поручено — человек или группа, от которых зависит движение вопроса.
- Теги — быстрые метки для поиска и группировки.
- Связанная заметка — ссылка на быструю заметку, из которой была создана задача.
- Связанная DPMS-задача — связь с обычной задачей системы, если личный контроль уже превращен в рабочую задачу.

## Критерии и контроль
- Критерии приемки — наблюдаемые условия, по которым понятно, что вопрос закрыт.
- Ожидание — от кого или чего сейчас зависит следующий шаг.
- Причина блока — что мешает двигаться дальше, если статус установлен как Блок.
- Impact — управленческий эффект от решения вопроса по шкале 1–5.
- Effort — примерная трудоемкость по шкале 1–5.
- Этапы контроля — промежуточные контрольные точки внутри одной личной задачи.
- Журнал — история встреч, follow-up, заметок и изменений статуса.

## Когда выводить в глобальную очередь
Выводите личную задачу в глобальную очередь, когда она перестает быть личным контуром контроля и становится работой для команды: нужен исполнитель, оценка, срок, результат и приемка по общим правилам DPMS.

## Практическое правило
Если задача нужна только для контроля и собственных заметок — ведите ее как личную. Если появляется понятный исполнитель, результат и критерии приемки — выводите ее в глобальную очередь."""


def upgrade() -> None:
    op.create_table(
        "deadline_trackers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tracker_type", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_action", sa.String(length=500), nullable=True),
        sa.Column("responsible", sa.String(length=200), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("personal_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linked_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "tracker_type IN ('subscription', 'system', 'password', 'task', 'document', 'payment', 'other')",
            name="ck_deadline_trackers_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'done', 'archived')",
            name="ck_deadline_trackers_status",
        ),
        sa.CheckConstraint("due_at > starts_at", name="ck_deadline_trackers_dates"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["personal_task_id"], ["personal_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deadline_trackers_owner_id", "deadline_trackers", ["owner_id"])
    op.create_index("ix_deadline_trackers_due_at", "deadline_trackers", ["due_at"])
    op.create_index("ix_deadline_trackers_status", "deadline_trackers", ["status"])
    op.create_index("ix_deadline_trackers_tracker_type", "deadline_trackers", ["tracker_type"])
    op.create_index("ix_deadline_trackers_personal_task_id", "deadline_trackers", ["personal_task_id"])
    op.create_index("ix_deadline_trackers_linked_task_id", "deadline_trackers", ["linked_task_id"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '9b25fef6-4b66-4512-bf3e-9d7f7af18830',
                'lichnye-zadachi-polya-i-pravila',
                'Личные задачи: поля и правила заполнения',
                'Описание полей личной задачи: статус, сроки, контекст, контроль, связи и вывод в глобальную очередь.',
                'tasks',
                :body,
                'published',
                35,
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
        {"body": PERSONAL_TASKS_KB_BODY},
    )


def downgrade() -> None:
    op.execute("DELETE FROM knowledge_articles WHERE slug = 'lichnye-zadachi-polya-i-pravila'")
    op.drop_index("ix_deadline_trackers_linked_task_id", table_name="deadline_trackers")
    op.drop_index("ix_deadline_trackers_personal_task_id", table_name="deadline_trackers")
    op.drop_index("ix_deadline_trackers_tracker_type", table_name="deadline_trackers")
    op.drop_index("ix_deadline_trackers_status", table_name="deadline_trackers")
    op.drop_index("ix_deadline_trackers_due_at", table_name="deadline_trackers")
    op.drop_index("ix_deadline_trackers_owner_id", table_name="deadline_trackers")
    op.drop_table("deadline_trackers")
