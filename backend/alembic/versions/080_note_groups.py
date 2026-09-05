"""Private note groups, context and audited share previews.

Revision ID: 080_note_groups
Revises: 079_tracker_organization
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "080_note_groups"
down_revision = "079_tracker_organization"
branch_labels = None
depends_on = None

ARTICLE = {
    "id": "f3559350-b613-4f0a-89ae-0cc992a52365",
    "slug": "lichnye-gruppy-zametok-i-kontekst",
    "title": "Группы заметок, связи и явный доступ",
    "summary": "Личная структура заметок, динамические связи и проверка массового открытия доступа.",
    "section": "start",
    "body": """## Личные группы

В «Заметках» создавайте одноуровневые группы, меняйте название и порядок, сворачивайте и архивируйте. Системные представления «Все», «Без группы» и «Доступные мне» не удаляются. Прежние заметки остаются без группы. Входящие общие заметки не меняют структуру владельца.

Выберите свои заметки флажками и перенесите их в группу или в «Без группы». Архив группы не архивирует заметки. Перед удалением группу нужно архивировать; удаление группы сохраняет все заметки в «Без группы».

## Контекстные связи

Группа и отдельная заметка могут быть связаны с несколькими доступными проектами, целями и собственными личными задачами. Связь группы вычисляется динамически: новые заметки и перенесённые в неё заметки получают этот контекст. Перенос из группы снимает только наследуемую связь, сохраняя индивидуальные связи и доступ.

В заметке видны индивидуальные, наследуемые и ранее созданные связи с проектами. Связь «Источник задачи» сохраняет происхождение личной задачи и не удаляется как обычный контекст.

Связи не открывают доступ. Участник проекта не получает названия, количества или содержимого закрытых заметок и личных групп. Обратные ссылки показывают только заметки, доступ к которым уже предоставлен.

## Открыть доступ

Выберите свои заметки или группу и нажмите «Открыть доступ». Получатели должны быть принятыми контактами. Фильтр проекта ограничивает список его участниками, но не заменяет принятие контакта.

В предпросмотре проверьте точный список заметок, получателей, файлов и количества комментариев. Открывается текущая заметка целиком, включая существующие и будущие файлы и обсуждение. Подтвердите «Открыть доступ»; операция сохраняется в истории. Новые заметки, добавленные в группу после подтверждения, автоматически не открываются.

Предпросмотр действует десять минут. При изменении состава группы, заметок, файлов, обсуждения или доступа система потребует новую проверку. Повтор подтверждённого запроса не создаёт повторные уведомления. Отозвать доступ можно в обычном окне доступа отдельной заметки.
""",
}


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table("note_groups",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("owner_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collapsed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("position >= 0", name="ck_note_groups_position"),
        sa.CheckConstraint("revision >= 1", name="ck_note_groups_revision"),
    )
    op.create_index("ix_note_groups_owner_id", "note_groups", ["owner_id"])
    op.add_column("quick_notes", sa.Column("group_id", uuid, nullable=True))
    op.create_foreign_key("fk_quick_notes_group_id", "quick_notes", "note_groups", ["group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_quick_notes_group_id", "quick_notes", ["group_id"])
    op.create_table("note_context_links",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("group_id", uuid, sa.ForeignKey("note_groups.id", ondelete="CASCADE")),
        sa.Column("note_id", uuid, sa.ForeignKey("quick_notes.id", ondelete="CASCADE")),
        sa.Column("entity_id", uuid, sa.ForeignKey("work_entities.id", ondelete="CASCADE")),
        sa.Column("personal_task_id", uuid, sa.ForeignKey("personal_tasks.id", ondelete="CASCADE")),
        sa.CheckConstraint("(group_id IS NULL) <> (note_id IS NULL)", name="ck_note_context_source"),
        sa.CheckConstraint("(entity_id IS NULL) <> (personal_task_id IS NULL)", name="ck_note_context_target"),
        sa.UniqueConstraint("group_id", "entity_id", name="uq_note_context_group_entity"),
        sa.UniqueConstraint("group_id", "personal_task_id", name="uq_note_context_group_task"),
        sa.UniqueConstraint("note_id", "entity_id", name="uq_note_context_note_entity"),
        sa.UniqueConstraint("note_id", "personal_task_id", name="uq_note_context_note_task"),
    )
    for column in ("group_id", "note_id", "entity_id", "personal_task_id"):
        op.create_index(f"ix_note_context_links_{column}", "note_context_links", [column])
    op.create_table("note_share_batches",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("owner_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_note_share_batches_owner_id", "note_share_batches", ["owner_id"])
    op.get_bind().execute(sa.text("""
        INSERT INTO knowledge_articles (id, slug, title, summary, section, body, status, sort_order, created_at, updated_at, published_at)
        VALUES (CAST(:id AS uuid), :slug, :title, :summary, :section, :body, 'published', 17, now(), now(), now())
        ON CONFLICT (slug) DO UPDATE SET title=EXCLUDED.title, summary=EXCLUDED.summary,
            body=EXCLUDED.body, updated_at=now()
        WHERE knowledge_articles.id = EXCLUDED.id
    """), ARTICLE)


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM knowledge_articles WHERE id=CAST(:id AS uuid) AND slug=:slug"),
                          {"id": ARTICLE["id"], "slug": ARTICLE["slug"]})
    op.drop_table("note_share_batches")
    op.drop_table("note_context_links")
    op.drop_index("ix_quick_notes_group_id", "quick_notes")
    op.drop_constraint("fk_quick_notes_group_id", "quick_notes", type_="foreignkey")
    op.drop_column("quick_notes", "group_id")
    op.drop_table("note_groups")
