"""Support multiple saved Synology connection profiles.

Revision ID: 062_synology_connection_profiles
Revises: 061_ai_provider
"""

from alembic import op
import sqlalchemy as sa


revision = "062_synology_connection_profiles"
down_revision = "061_ai_provider"
branch_labels = None
depends_on = None


OLD_SECURITY = "DSM-пароль и 2FA-код не сохраняются в БД. После входа SID остается только в памяти backend, привязан к текущему администратору и автоматически завершается после 30 минут бездействия, при отключении или остановке сервера."
NEW_SECURITY = "Пароль профиля хранится в БД только в зашифрованном виде и никогда не возвращается в браузер. 2FA-код не сохраняется. После входа SID остается только в памяти backend, привязан к текущему администратору и автоматически завершается после 30 минут бездействия, при отключении или остановке сервера."
OLD_STEPS = "1. Откройте в разделе «Аудит» пункт `Synology`.\n2. Укажите разрешенный HTTPS-адрес NAS, отдельную учетную запись только для чтения и корневую папку с материалами аудита.\n3. Введите пароль и одноразовый 2FA-код, затем нажмите «Подключиться»."
NEW_STEPS = "1. Откройте `Админ → Интеграции → Synology`.\n2. Создайте профиль: задайте понятное название, разрешенный HTTPS-адрес NAS, отдельную учетную запись только для чтения и корневую папку.\n3. Введите пароль и одноразовый 2FA-код, затем нажмите `Проверить и сохранить`. Успешный профиль получает статус `OK`.\n4. Выберите один проверенный профиль и нажмите `Активировать`. Активным одновременно может быть только один профиль."


def upgrade() -> None:
    op.drop_constraint(
        "uq_audit_synology_connections_provider",
        "audit_synology_connections",
        type_="unique",
    )
    op.add_column(
        "audit_synology_connections",
        sa.Column("display_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "audit_synology_connections",
        sa.Column("password_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_synology_connections",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE audit_synology_connections SET display_name = 'Synology'")
    op.alter_column("audit_synology_connections", "display_name", nullable=False)
    op.create_unique_constraint(
        "uq_audit_synology_connections_provider_name",
        "audit_synology_connections",
        ["provider", "display_name"],
    )
    op.create_check_constraint(
        "ck_audit_synology_connections_active_ready",
        "audit_synology_connections",
        "NOT is_active OR (enabled AND password_ciphertext IS NOT NULL)",
    )
    op.create_index(
        "uq_audit_synology_connections_active_provider",
        "audit_synology_connections",
        ["provider"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_constraint(
        "uq_audit_synology_imports_remote_version",
        "audit_synology_imports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_audit_synology_imports_remote_version",
        "audit_synology_imports",
        ["remote_path_fingerprint", "remote_size", "remote_mtime"],
    )
    op.drop_constraint(
        "audit_synology_import_batches_connection_id_fkey",
        "audit_synology_import_batches",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_synology_import_batches_connection_id_fkey",
        "audit_synology_import_batches",
        "audit_synology_connections",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "audit_synology_imports_connection_id_fkey",
        "audit_synology_imports",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_synology_imports_connection_id_fkey",
        "audit_synology_imports",
        "audit_synology_connections",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(replace(body, :old_steps, :new_steps), :old_security, :new_security),
                updated_at = now()
            WHERE id = '98d3e0cb-4268-4af2-9a03-06022f444113'
            """
        ).bindparams(
            old_steps=OLD_STEPS,
            new_steps=NEW_STEPS,
            old_security=OLD_SECURITY,
            new_security=NEW_SECURITY,
        )
    )


def downgrade() -> None:
    profile_count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM audit_synology_connections")
    ).scalar_one()
    if profile_count > 1:
        raise RuntimeError(
            "Cannot downgrade Synology profiles while multiple profiles exist; archive data explicitly first"
        )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(replace(body, :new_steps, :old_steps), :new_security, :old_security),
                updated_at = now()
            WHERE id = '98d3e0cb-4268-4af2-9a03-06022f444113'
            """
        ).bindparams(
            new_steps=NEW_STEPS,
            old_steps=OLD_STEPS,
            new_security=NEW_SECURITY,
            old_security=OLD_SECURITY,
        )
    )
    op.drop_index(
        "uq_audit_synology_connections_active_provider",
        table_name="audit_synology_connections",
    )
    op.drop_constraint(
        "audit_synology_imports_connection_id_fkey",
        "audit_synology_imports",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_synology_imports_connection_id_fkey",
        "audit_synology_imports",
        "audit_synology_connections",
        ["connection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "audit_synology_import_batches_connection_id_fkey",
        "audit_synology_import_batches",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_synology_import_batches_connection_id_fkey",
        "audit_synology_import_batches",
        "audit_synology_connections",
        ["connection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_audit_synology_imports_remote_version",
        "audit_synology_imports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_audit_synology_imports_remote_version",
        "audit_synology_imports",
        ["connection_id", "remote_path_fingerprint", "remote_size", "remote_mtime"],
    )
    op.drop_constraint(
        "ck_audit_synology_connections_active_ready",
        "audit_synology_connections",
        type_="check",
    )
    op.drop_constraint(
        "uq_audit_synology_connections_provider_name",
        "audit_synology_connections",
        type_="unique",
    )
    op.drop_column("audit_synology_connections", "is_active")
    op.drop_column("audit_synology_connections", "password_ciphertext")
    op.drop_column("audit_synology_connections", "display_name")
    op.create_unique_constraint(
        "uq_audit_synology_connections_provider",
        "audit_synology_connections",
        ["provider"],
    )
