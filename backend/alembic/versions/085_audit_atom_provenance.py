"""Immutable atom origin snapshots and idempotent model-item publication.

Existing origins are reconstructed on read. No historical model result is
published by this migration, and no atom or human decision is rewritten.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "085_audit_atom_provenance"
down_revision = "084_audit_declarative_skills"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_atoms", sa.Column(
        "provenance_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"),
    ))
    op.add_column("audit_atoms", sa.Column("ai_registry_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_audit_atoms_ai_registry_item", "audit_atoms", "audit_ai_model_registry_items",
        ["ai_registry_item_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "uq_audit_atoms_ai_registry_item_id", "audit_atoms", ["ai_registry_item_id"],
        unique=True, postgresql_where=sa.text("ai_registry_item_id IS NOT NULL"),
    )
    op.execute(sa.text("""
        CREATE FUNCTION audit_atom_origin_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.provenance_json <> '[]'::jsonb AND NEW.provenance_json IS DISTINCT FROM OLD.provenance_json)
                OR (OLD.ai_registry_item_id IS NOT NULL AND NEW.ai_registry_item_id IS DISTINCT FROM OLD.ai_registry_item_id)
            THEN
                RAISE EXCEPTION 'Atom origin snapshots and publication links are immutable';
            END IF;
            RETURN NEW;
        END $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_audit_atom_origin_immutable BEFORE UPDATE ON audit_atoms
        FOR EACH ROW EXECUTE FUNCTION audit_atom_origin_immutable()
    """))
    # A1.9 compares complete row dictionaries, including default-valued columns.
    op.execute(sa.text("""
        UPDATE audit_legacy_transfer_rows SET
            "before" = CASE WHEN "before" IS NOT NULL THEN
                '{"provenance_json": [], "ai_registry_item_id": null}'::jsonb || "before" END,
            "after" = CASE WHEN "after" IS NOT NULL THEN
                '{"provenance_json": [], "ai_registry_item_id": null}'::jsonb || "after" END
        WHERE target_table = 'audit_atoms'
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE audit_atoms, audit_legacy_transfer_rows IN ACCESS EXCLUSIVE MODE"))
    used = bind.execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM audit_atoms
            WHERE ai_registry_item_id IS NOT NULL OR provenance_json <> '[]'::jsonb)
        OR EXISTS (SELECT 1 FROM audit_legacy_transfer_rows WHERE target_table = 'audit_atoms'
            AND (COALESCE("before"->'provenance_json', '[]'::jsonb) <> '[]'::jsonb
                OR COALESCE("after"->'provenance_json', '[]'::jsonb) <> '[]'::jsonb
                OR "before"->>'ai_registry_item_id' IS NOT NULL
                OR "after"->>'ai_registry_item_id' IS NOT NULL))
    """)).scalar_one()
    if used:
        raise RuntimeError("Cannot discard persisted atom provenance or publication links.")
    op.execute(sa.text("""
        UPDATE audit_legacy_transfer_rows SET
            "before" = "before" - 'provenance_json' - 'ai_registry_item_id',
            "after" = "after" - 'provenance_json' - 'ai_registry_item_id'
        WHERE target_table = 'audit_atoms'
    """))
    op.execute("DROP TRIGGER trg_audit_atom_origin_immutable ON audit_atoms")
    op.execute("DROP FUNCTION audit_atom_origin_immutable()")
    op.drop_index("uq_audit_atoms_ai_registry_item_id", table_name="audit_atoms")
    op.drop_constraint("fk_audit_atoms_ai_registry_item", "audit_atoms", type_="foreignkey")
    op.drop_column("audit_atoms", "ai_registry_item_id")
    op.drop_column("audit_atoms", "provenance_json")
