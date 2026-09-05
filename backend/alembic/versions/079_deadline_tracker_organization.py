"""Personal tracker organization, occurrence history, and durable reminders.

Revision ID: 079_tracker_organization
Revises: 078_start_menu_knowledge_layout
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "079_tracker_organization"
down_revision = "078_start_menu_knowledge_layout"
branch_labels = None
depends_on = None

ARTICLE_ID = "9fc2195f-1fc7-4e76-8973-11d4c45f3b57"
ARTICLE_SLUG = "trekery-gruppy-povtoreniya-napominaniya"
ARTICLE_BODY = """Обновлено: 2026-09-05

## Группы и категории
Группа задает личное расположение трекера, порядок, цвет и свернутое состояние.
Удаление группы оставляет трекеры без группы. Архив группы не завершает ее трекеры.
Категория служит только классификацией: Абонемент, Система, Пароль, Задача,
Документ, Оплата и Другое сохранены как стартовые личные категории.
Категорию можно переименовать или архивировать, старые записи сохраняют ее.
Группы, категории, история и напоминания доступны только владельцу.

## Источник
Источник вычисляется из связи: самостоятельный трекер, личная задача или Q-задача.
Название, сроки и исполнитель связанного источника показываются без возможности
редактирования. Доступ проверяется по правам источника. Связанный трекер всегда
разовый; его срок обновляется при изменении задачи, фоновая сверка идет раз в минуту.
У самостоятельного трекера поле Ответственный больше не используется.

## Повторения
Серия задает день, неделю, месяц или год, интервал и IANA timezone.
Первый срок входит в число повторений. Окончание бывает без ограничения,
до указанного момента включительно или после N повторений.
Каждое наступление хранится отдельно. Выполнить наступление не означает завершить
серию; для этого есть отдельное действие Завершить серию.
Расчет идет от исходного срока: 31 января -> 28/29 февраля -> 31 марта.
29 февраля при ежегодном повторении становится 28 февраля в обычном году
и снова 29 февраля в високосном. Несуществующее местное время при переходе DST
переносится вперед на величину скачка; двойное время выбирает первое вхождение.
Пауза серии не сдвигает календарь, наступления сохраняются, алерты в паузе подавляются.
Изменение правила создает новую версию расписания и сохраняет прошлую историю.
Разовый самостоятельный трекер сохраняет прежний сдвиг срока на округленные дни паузы.

## Напоминания и Сообщения
Можно задать до 10 уникальных смещений: минуты, часы, дни или недели до срока,
включая 0 для самого срока, не ранее чем за 366 дней. 1 час и 60 минут считаются
одной точкой. Для дней и недель смещение означает 24 и 168 часов соответственно.
Уже прошедшие точки при создании напоминания не рассылаются задним числом.
Перенос срока пересчитывает только будущие неотправленные точки; история доставки
не меняется. Выполнение, архив и пауза подавляют новые алерты.
Фоновый worker хранит очередь и дедупликацию в БД: перезапуск не теряет доставку.
Владелец получает алерт во Важном с зеленым индикатором и ссылкой на конкретный
трекер. Следующая синхронизация Сообщений показывает доставку.
Открытие конкретного трекера отмечает прочитанными только связанные с ним алерты.
"""


def _id():
    return sa.Column("id", pg.UUID(as_uuid=True), primary_key=True)


def _fk(name, target, *, nullable=False, ondelete="CASCADE"):
    return sa.Column(name, pg.UUID(as_uuid=True), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def upgrade():
    for table in ("deadline_tracker_groups", "deadline_tracker_categories"):
        extra = [sa.Column("is_collapsed", sa.Boolean, nullable=False, server_default=sa.false())] if table.endswith("groups") else [
            sa.Column("legacy_type", sa.String(30)),
            sa.UniqueConstraint("owner_id", "legacy_type", name="uq_tracker_category_legacy"),
        ]
        op.create_table(table, _id(), _fk("owner_id", "users.id"),
            sa.Column("name", sa.String(100), nullable=False), sa.Column("color", sa.String(7)),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("is_archived", sa.Boolean, nullable=False, server_default=sa.false()), *extra)
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
    op.add_column("deadline_trackers", sa.Column("group_id", pg.UUID(as_uuid=True)))
    op.add_column("deadline_trackers", sa.Column("category_id", pg.UUID(as_uuid=True)))
    op.add_column("deadline_trackers", sa.Column("url", sa.String(2000)))
    op.add_column("deadline_trackers", sa.Column("recurrence", pg.JSONB))
    op.add_column("deadline_trackers", sa.Column("schedule_version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("deadline_trackers", sa.Column("next_sequence", sa.Integer, nullable=False, server_default="1"))
    for field in ("next_occurrence_at", "schedule_check_at", "source_check_at", "alerts_suppressed_until"):
        op.add_column("deadline_trackers", sa.Column(field, sa.DateTime(timezone=True)))
    for field, target in (("group_id", "deadline_tracker_groups"), ("category_id", "deadline_tracker_categories")):
        op.create_foreign_key(f"fk_tracker_{field}", "deadline_trackers", target, [field], ["id"], ondelete="SET NULL")
        op.create_index(f"ix_deadline_trackers_{field}", "deadline_trackers", [field])
    op.create_index("ix_tracker_expansion", "deadline_trackers", ["schedule_check_at"], postgresql_where=sa.text("schedule_check_at IS NOT NULL"))
    op.create_index("ix_tracker_source_check", "deadline_trackers", ["source_check_at"], postgresql_where=sa.text("source_check_at IS NOT NULL"))
    op.create_table("deadline_tracker_occurrences", _id(), _fk("tracker_id", "deadline_trackers.id"),
        sa.Column("schedule_version", sa.Integer, nullable=False), sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tracker_id", "schedule_version", "sequence", name="uq_tracker_occurrence_sequence"))
    op.create_index("ix_tracker_occurrence_current", "deadline_tracker_occurrences", ["tracker_id", "status", "due_at"])
    op.create_table("deadline_tracker_reminders", _id(), _fk("tracker_id", "deadline_trackers.id"),
        sa.Column("value", sa.Integer, nullable=False), sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("offset_seconds", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tracker_id", "offset_seconds", name="uq_tracker_reminder_offset"))
    op.create_table("deadline_tracker_deliveries", _id(), _fk("tracker_id", "deadline_trackers.id"),
        _fk("occurrence_id", "deadline_tracker_occurrences.id"), _fk("reminder_id", "deadline_tracker_reminders.id"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        _fk("notification_id", "notifications.id", nullable=True, ondelete="SET NULL"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tracker_id", "occurrence_id", "reminder_id", name="uq_tracker_delivery"))
    op.create_index("ix_tracker_delivery_due", "deadline_tracker_deliveries", ["status", "scheduled_for"])
    op.create_index("ix_tracker_delivery_history", "deadline_tracker_deliveries", ["tracker_id", "scheduled_for"])
    op.create_table("deadline_tracker_events", _id(), _fk("tracker_id", "deadline_trackers.id"),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("details", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_tracker_event_history", "deadline_tracker_events", ["tracker_id", "created_at"])
    backfill_legacy(op.get_bind())
    op.create_unique_constraint("uq_tracker_owner_personal_task", "deadline_trackers", ["owner_id", "personal_task_id"])
    op.create_unique_constraint("uq_tracker_owner_task", "deadline_trackers", ["owner_id", "linked_task_id"])
    op.create_check_constraint("ck_tracker_single_source", "deadline_trackers", "personal_task_id IS NULL OR linked_task_id IS NULL")
    op.create_check_constraint("ck_tracker_linked_one_time", "deadline_trackers", "recurrence IS NULL OR (personal_task_id IS NULL AND linked_task_id IS NULL)")
    op.get_bind().execute(sa.text("""
        INSERT INTO knowledge_articles (id, slug, title, summary, section, body, status, sort_order, created_at, updated_at, published_at)
        VALUES (CAST(:id AS uuid), :slug, :title, :summary, 'start', :body, 'published', 16, now(), now(), now())
        ON CONFLICT (slug) DO NOTHING
    """), {"id": ARTICLE_ID, "slug": ARTICLE_SLUG, "title": "Трекеры: группы, повторения и напоминания", "summary": "Личная организация сроков и напоминания во Важном.", "body": ARTICLE_BODY})


def backfill_legacy(bind):
    bind.execute(sa.text("""
        INSERT INTO deadline_tracker_categories (id, owner_id, name, legacy_type, sort_order)
        SELECT md5(u.id::text || ':' || 'tracker-category:' || c.kind)::uuid, u.id, c.name, c.kind, c.position
        FROM users u CROSS JOIN (VALUES
          ('subscription','Абонемент',0), ('system','Система',1), ('password','Пароль',2),
          ('task','Задача',3), ('document','Документ',4), ('payment','Оплата',5), ('other','Другое',6)
        ) c(kind, name, position)
        ON CONFLICT (owner_id, legacy_type) DO NOTHING
    """))
    bind.execute(sa.text("""
        UPDATE deadline_trackers t SET category_id = c.id FROM deadline_tracker_categories c
        WHERE t.owner_id = c.owner_id AND t.tracker_type = c.legacy_type
    """))
    # Preserve every tracker UUID/backlink and exact original link tuple before repair.
    bind.execute(sa.text("""
        INSERT INTO deadline_tracker_events (id, tracker_id, event_type, details)
        SELECT md5('legacy-links:' || id::text)::uuid, id, 'legacy_links_snapshot',
          jsonb_build_object('personal_task_id', personal_task_id, 'linked_task_id', linked_task_id)
        FROM deadline_trackers WHERE personal_task_id IS NOT NULL OR linked_task_id IS NOT NULL
    """))
    bind.execute(sa.text("UPDATE deadline_trackers SET linked_task_id = NULL WHERE personal_task_id IS NOT NULL AND linked_task_id IS NOT NULL"))
    for field in ("personal_task_id", "linked_task_id"):
        bind.execute(sa.text(f"""
            WITH duplicates AS (
              SELECT id, row_number() OVER (PARTITION BY owner_id, {field} ORDER BY created_at, id) AS n
              FROM deadline_trackers WHERE {field} IS NOT NULL
            ) UPDATE deadline_trackers t SET {field} = NULL FROM duplicates d WHERE t.id = d.id AND d.n > 1
        """))
    bind.execute(sa.text("""
        INSERT INTO deadline_tracker_occurrences (id, tracker_id, schedule_version, sequence, due_at, status, completed_at, created_at)
        SELECT md5('legacy-occurrence:' || id::text)::uuid, id, 1, 1,
          due_at + CASE WHEN personal_task_id IS NULL AND linked_task_id IS NULL
            THEN ceil(GREATEST(paused_seconds, 0) / 86400.0) * interval '1 day' ELSE interval '0' END,
          CASE WHEN status = 'done' THEN 'completed' WHEN status = 'archived' THEN 'cancelled' ELSE 'pending' END,
          completed_at, created_at FROM deadline_trackers
    """))
    bind.execute(sa.text("""
        UPDATE deadline_trackers SET next_sequence = 2,
          source_check_at = CASE WHEN personal_task_id IS NOT NULL OR linked_task_id IS NOT NULL THEN now() END
    """))


def downgrade():
    for constraint in ("ck_tracker_linked_one_time", "ck_tracker_single_source", "uq_tracker_owner_task", "uq_tracker_owner_personal_task"):
        op.drop_constraint(constraint, "deadline_trackers")
    op.get_bind().execute(sa.text("""
        UPDATE deadline_trackers t SET
          personal_task_id = CASE WHEN EXISTS (SELECT 1 FROM personal_tasks p WHERE p.id = (e.details->>'personal_task_id')::uuid)
            THEN (e.details->>'personal_task_id')::uuid END,
          linked_task_id = CASE WHEN EXISTS (SELECT 1 FROM tasks q WHERE q.id = (e.details->>'linked_task_id')::uuid)
            THEN (e.details->>'linked_task_id')::uuid END
        FROM deadline_tracker_events e WHERE e.tracker_id = t.id AND e.event_type = 'legacy_links_snapshot'
    """))
    op.get_bind().execute(sa.text("DELETE FROM knowledge_articles WHERE id = CAST(:id AS uuid) AND slug = :slug"), {"id": ARTICLE_ID, "slug": ARTICLE_SLUG})
    for table in ("deadline_tracker_events", "deadline_tracker_deliveries", "deadline_tracker_reminders", "deadline_tracker_occurrences"):
        op.drop_table(table)
    for field in ("alerts_suppressed_until", "source_check_at", "schedule_check_at", "next_occurrence_at", "next_sequence", "schedule_version", "recurrence", "url", "category_id", "group_id"):
        op.drop_column("deadline_trackers", field)
    op.drop_table("deadline_tracker_categories")
    op.drop_table("deadline_tracker_groups")
