"""Add methodology bridge for work tracks

Revision ID: 043_work_track_methodologies
Revises: 042_work_tracks
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "043_work_track_methodologies"
down_revision = "042_work_tracks"
branch_labels = None
depends_on = None

WORK_TRACKS_METHOD_KB_APPEND = """

## Кубики и методологии

Трек может быть связан с импортированной методологией. Методология хранится как версионируемый JSON-источник: система запоминает `schemaVersion`, `methodologyVersion`, название, маршруты, стадии, кубики и полный исходный payload.

Почему это важно: методология может меняться. Поэтому DPMS не пришивает текущую структуру кубиков жестко к задачам. При применении маршрута к треку система создает элементы типа `Кубик` и сохраняет snapshot каждого кубика и чек-листа на момент применения.

Кубик в треке можно:

- поставить в нужное место последовательности;
- закрыть как самостоятельный шаг;
- указать предполагаемого исполнителя по email;
- отправить исполнителю на рассмотрение будущей работы;
- использовать как основу для дальнейшего создания DPMS-задачи или личной задачи.

Статусы бронирования будущей работы:

- `draft` — черновик, исполнитель еще не запрошен;
- `sent` — отправлено исполнителю на рассмотрение;
- `reserved` — исполнитель подтвердил готовность, работа забронирована;
- `declined` — исполнитель отказался, требуется переназначение или возврат в пул задач;
- `released` — бронь снята.

Если методология меняется, старые треки не ломаются: они продолжают показывать snapshot кубиков, с которыми были созданы.
"""


def upgrade() -> None:
    op.create_table(
        "work_methodologies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("methodology_version", sa.String(length=80), nullable=True),
        sa.Column("display_version", sa.String(length=80), nullable=True),
        sa.Column("release_kind", sa.String(length=80), nullable=True),
        sa.Column("source_kind", sa.String(length=60), nullable=False, server_default="json"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("stages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cubes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("routes_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_work_methodologies_fingerprint"),
    )
    op.create_index("ix_work_methodologies_created_by_id", "work_methodologies", ["created_by_id"])
    op.create_index("ix_work_methodologies_methodology_version", "work_methodologies", ["methodology_version"])
    op.create_index("ix_work_methodologies_fingerprint", "work_methodologies", ["fingerprint"])

    op.add_column("work_tracks", sa.Column("methodology_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("work_tracks", sa.Column("product_key", sa.String(length=100), nullable=True))
    op.add_column("work_tracks", sa.Column("route_key", sa.String(length=100), nullable=True))
    op.add_column("work_tracks", sa.Column("methodology_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("work_tracks", sa.Column("route_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key(
        "fk_work_tracks_methodology_id_work_methodologies",
        "work_tracks",
        "work_methodologies",
        ["methodology_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_work_tracks_methodology_id", "work_tracks", ["methodology_id"])

    op.add_column("work_track_items", sa.Column("methodology_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("work_track_items", sa.Column("methodology_node_type", sa.String(length=40), nullable=True))
    op.add_column("work_track_items", sa.Column("methodology_node_id", sa.String(length=120), nullable=True))
    op.add_column("work_track_items", sa.Column("methodology_stage_id", sa.String(length=120), nullable=True))
    op.add_column("work_track_items", sa.Column("methodology_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("work_track_items", sa.Column("checklist_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("work_track_items", sa.Column("proposed_executor_email", sa.String(length=320), nullable=True))
    op.add_column("work_track_items", sa.Column("proposed_executor_name", sa.String(length=200), nullable=True))
    op.add_column(
        "work_track_items",
        sa.Column("reservation_status", sa.String(length=40), nullable=False, server_default="draft"),
    )
    op.create_foreign_key(
        "fk_work_track_items_methodology_id_work_methodologies",
        "work_track_items",
        "work_methodologies",
        ["methodology_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ck_work_track_items_type", "work_track_items", type_="check")
    op.create_check_constraint(
        "ck_work_track_items_type",
        "work_track_items",
        "item_type IN ('task', 'personal_task', 'manual', 'cube')",
    )
    op.create_check_constraint(
        "ck_work_track_items_reservation_status",
        "work_track_items",
        "reservation_status IN ('draft', 'sent', 'reserved', 'declined', 'released')",
    )
    op.create_index("ix_work_track_items_methodology_id", "work_track_items", ["methodology_id"])
    op.create_index("ix_work_track_items_methodology_node_type", "work_track_items", ["methodology_node_type"])
    op.create_index("ix_work_track_items_methodology_node_id", "work_track_items", ["methodology_node_id"])
    op.create_index("ix_work_track_items_methodology_stage_id", "work_track_items", ["methodology_stage_id"])
    op.create_index("ix_work_track_items_proposed_executor_email", "work_track_items", ["proposed_executor_email"])
    op.create_index("ix_work_track_items_reservation_status", "work_track_items", ["reservation_status"])

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, 'Последнее обновление: 09.07.2026', 'Последнее обновление: 10.07.2026') || :append,
                summary = 'Как использовать треки для цепочек задач, кубиков методологии и будущего бронирования работ.',
                updated_at = now(),
                published_at = now()
            WHERE slug = 'treki-zadach-posledovatelnosti'
            """
        ),
        {"append": WORK_TRACKS_METHOD_KB_APPEND},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(
                    replace(body, :append, ''),
                    'Последнее обновление: 10.07.2026',
                    'Последнее обновление: 09.07.2026'
                ),
                summary = 'Как использовать треки для цепочек DPMS-задач, личных задач и ручных шагов.',
                updated_at = now(),
                published_at = now()
            WHERE slug = 'treki-zadach-posledovatelnosti'
            """
        ),
        {"append": WORK_TRACKS_METHOD_KB_APPEND},
    )
    op.drop_index("ix_work_track_items_reservation_status", table_name="work_track_items")
    op.drop_index("ix_work_track_items_proposed_executor_email", table_name="work_track_items")
    op.drop_index("ix_work_track_items_methodology_stage_id", table_name="work_track_items")
    op.drop_index("ix_work_track_items_methodology_node_id", table_name="work_track_items")
    op.drop_index("ix_work_track_items_methodology_node_type", table_name="work_track_items")
    op.drop_index("ix_work_track_items_methodology_id", table_name="work_track_items")
    op.drop_constraint("ck_work_track_items_reservation_status", "work_track_items", type_="check")
    op.drop_constraint("ck_work_track_items_type", "work_track_items", type_="check")
    op.create_check_constraint(
        "ck_work_track_items_type",
        "work_track_items",
        "item_type IN ('task', 'personal_task', 'manual')",
    )
    op.drop_constraint("fk_work_track_items_methodology_id_work_methodologies", "work_track_items", type_="foreignkey")
    op.drop_column("work_track_items", "reservation_status")
    op.drop_column("work_track_items", "proposed_executor_name")
    op.drop_column("work_track_items", "proposed_executor_email")
    op.drop_column("work_track_items", "checklist_snapshot")
    op.drop_column("work_track_items", "methodology_snapshot")
    op.drop_column("work_track_items", "methodology_stage_id")
    op.drop_column("work_track_items", "methodology_node_id")
    op.drop_column("work_track_items", "methodology_node_type")
    op.drop_column("work_track_items", "methodology_id")

    op.drop_index("ix_work_tracks_methodology_id", table_name="work_tracks")
    op.drop_constraint("fk_work_tracks_methodology_id_work_methodologies", "work_tracks", type_="foreignkey")
    op.drop_column("work_tracks", "route_snapshot")
    op.drop_column("work_tracks", "methodology_snapshot")
    op.drop_column("work_tracks", "route_key")
    op.drop_column("work_tracks", "product_key")
    op.drop_column("work_tracks", "methodology_id")

    op.drop_index("ix_work_methodologies_fingerprint", table_name="work_methodologies")
    op.drop_index("ix_work_methodologies_methodology_version", table_name="work_methodologies")
    op.drop_index("ix_work_methodologies_created_by_id", table_name="work_methodologies")
    op.drop_table("work_methodologies")
