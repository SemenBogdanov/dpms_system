"""Allow immutable data-only skill archives without enabling trusted execution."""

from alembic import op
import sqlalchemy as sa


revision = "084_audit_declarative_skills"
down_revision = "083_audit_legacy_transfer"
branch_labels = None
depends_on = None

TABLE = "audit_atomization_skill_versions"
FORMAT_CHECK = "ck_audit_atomization_skill_versions_package_format"
BLOB_CHECK = "ck_audit_atomization_skill_versions_package_blob"


def upgrade() -> None:
    op.drop_constraint(FORMAT_CHECK, TABLE, type_="check")
    op.drop_constraint(BLOB_CHECK, TABLE, type_="check")
    op.create_check_constraint(
        FORMAT_CHECK, TABLE,
        "package_format IN ('declarative_json', 'declarative_archive', 'trusted_skill_archive')",
    )
    op.create_check_constraint(
        BLOB_CHECK, TABLE,
        "(package_format = 'declarative_json' AND package_blob IS NULL) OR "
        "(package_format IN ('declarative_archive', 'trusted_skill_archive') AND package_blob IS NOT NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(
        f"SELECT EXISTS (SELECT 1 FROM {TABLE} WHERE package_format = 'declarative_archive')"
    )).scalar_one():
        raise RuntimeError(
            "Cannot downgrade while declarative archives exist. Preserve immutable skill blobs and provenance."
        )
    op.drop_constraint(BLOB_CHECK, TABLE, type_="check")
    op.drop_constraint(FORMAT_CHECK, TABLE, type_="check")
    op.create_check_constraint(
        FORMAT_CHECK, TABLE,
        "package_format IN ('declarative_json', 'trusted_skill_archive')",
    )
    op.create_check_constraint(
        BLOB_CHECK, TABLE,
        "(package_format = 'declarative_json' AND package_blob IS NULL) OR "
        "(package_format = 'trusted_skill_archive' AND package_blob IS NOT NULL)",
    )
