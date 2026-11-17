"""Private direct-PostgreSQL Inbox bridge in the existing application schema.

No roles, schemas or login grants are created here. A DBA must grant only schema
USAGE and EXECUTE on connect/enqueue/status/protocol to a dedicated, otherwise
unprivileged login, then provision its explicit owner/grants mapping. Legacy
pair is NOT a bridge-login grant. Never grant table access or owner membership.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "101_mail_import_db_queue"
down_revision = "100_mail_import"
branch_labels = None
depends_on = None

SIGNATURES = {
    "mail_import_db_pair": "text, text",
    "mail_import_db_enqueue": "text, uuid, text",
    "mail_import_db_status": "text, uuid",
    "mail_import_db_protocol": "",
    "mail_import_db_connect": "text, text",
}


def qualified(schema, name):
    quote = postgresql.dialect().identifier_preparer.quote_identifier
    return f"{quote(schema)}.{quote(name)}"


def function_statements(schema):
    """Render literal, qualified SQL without importing any application settings."""
    devices = qualified(schema, "mail_import_devices")
    users = qualified(schema, "users")
    queue = qualified(schema, "mail_import_queue")
    logins = qualified(schema, "mail_import_db_logins")
    bindings = qualified(schema, "mail_import_db_devices")
    # The legacy branch is retained for owner-controlled SQL pair callers only;
    # the role-bound branch cannot fall back even if its binding is removed.
    authorized_device = f"""
        SELECT x.* INTO d FROM {devices} AS x JOIN {users} AS u ON u.id = x.owner_id
        LEFT JOIN {bindings} AS b ON b.device_id = x.id
        LEFT JOIN {logins} AS l ON l.role_oid = b.role_oid AND l.role_name = b.role_name
        LEFT JOIN pg_catalog.pg_roles AS r ON r.oid = l.role_oid AND r.rolname = l.role_name
        WHERE x.paired_at IS NOT NULL AND x.revoked_at IS NULL
        AND x.expires_at > pg_catalog.clock_timestamp() AND u.is_active AND x.owner_auth_version = u.auth_version
        AND ((x.device_secret_hash = hashed AND b.device_id IS NOT NULL
              AND l.enabled AND l.owner_id = x.owner_id AND r.rolname = SESSION_USER AND r.rolcanlogin
              AND (r.rolvaliduntil IS NULL OR r.rolvaliduntil > pg_catalog.clock_timestamp())
              AND (NOT x.include_body OR l.include_body) AND (NOT x.include_attachments OR l.include_attachments))
          OR (x.device_secret_hash = legacy_hash AND b.device_id IS NULL
              AND SESSION_USER = CURRENT_USER
              AND NOT EXISTS (SELECT 1 FROM {logins} AS caller WHERE caller.role_name = SESSION_USER)));
    """
    connect = f"""
DECLARE
    login {logins}%ROWTYPE;
    d {devices}%ROWTYPE;
    u record;
    hashed text;
    normalized_name text;
    stamp timestamptz;
    new_id uuid;
    live_devices bigint;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'unsupported_transaction', 'error_status', 400);
    END IF;
    SELECT l.* INTO login FROM {logins} AS l JOIN pg_catalog.pg_roles AS r
        ON r.oid = l.role_oid AND r.rolname = l.role_name
        WHERE r.rolname = SESSION_USER AND r.rolcanlogin AND l.enabled
        AND (r.rolvaliduntil IS NULL OR r.rolvaliduntil > pg_catalog.clock_timestamp());
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'db_login_not_provisioned', 'error_status', 403);
    END IF;
    IF $1 IS NULL OR pg_catalog.length($1) > 120 OR $1 !~ '[^[:space:]]'
       OR $2 IS NULL OR pg_catalog.length($2) <> 43 OR $2 !~ '^[A-Za-z0-9_-]{{43}}$' THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_connect_request', 'error_status', 422);
    END IF;
    normalized_name := pg_catalog.regexp_replace($1, '^[[:space:]]+|[[:space:]]+$', '', 'g');
    SELECT x.id, x.full_name, x.is_active, x.auth_version INTO u FROM {users} AS x WHERE x.id = login.owner_id FOR SHARE;
    IF NOT FOUND OR NOT u.is_active THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'db_login_not_provisioned', 'error_status', 403);
    END IF;
    SELECT l.* INTO login FROM {logins} AS l JOIN pg_catalog.pg_roles AS r
        ON r.oid = l.role_oid AND r.rolname = l.role_name
        WHERE r.rolname = SESSION_USER AND r.rolcanlogin AND l.enabled AND l.owner_id = u.id
        AND (r.rolvaliduntil IS NULL OR r.rolvaliduntil > pg_catalog.clock_timestamp()) FOR SHARE OF l;
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'db_login_not_provisioned', 'error_status', 403);
    END IF;
    -- Same owner quota lock as the HTTPS create-device service (signed SHA256 prefix).
    PERFORM pg_catalog.pg_advisory_xact_lock(('x' || pg_catalog.substr(pg_catalog.encode(
        pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:' || u.id::text || ':quota', 'UTF8')), 'hex'), 1, 16))::bit(64)::bigint);
    stamp := pg_catalog.clock_timestamp();
    hashed := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:db-device:' || $2, 'UTF8')), 'hex');
    SELECT x.* INTO d FROM {devices} AS x WHERE x.device_secret_hash = hashed;
    IF FOUND THEN
        IF d.owner_id <> u.id OR d.name <> normalized_name OR d.owner_auth_version <> u.auth_version
           OR d.revoked_at IS NOT NULL OR d.paired_at IS NULL OR d.expires_at IS NULL OR d.expires_at <= stamp
           OR d.include_body <> login.include_body OR d.include_attachments <> login.include_attachments
           OR NOT EXISTS (SELECT 1 FROM {bindings} AS b WHERE b.device_id = d.id
                          AND b.role_oid = login.role_oid AND b.role_name = login.role_name) THEN
            RETURN pg_catalog.jsonb_build_object('error_code', 'connect_conflict', 'error_status', 409);
        END IF;
        RETURN pg_catalog.jsonb_build_object('protocol_version', 1, 'device_id', d.id, 'device_secret', $2,
            'owner_name', u.full_name, 'include_body', d.include_body, 'include_attachments', d.include_attachments);
    END IF;
    SELECT pg_catalog.count(*) INTO live_devices FROM {devices} AS x WHERE x.owner_id = u.id
        AND x.revoked_at IS NULL AND x.owner_auth_version = u.auth_version
        AND COALESCE(x.expires_at, x.pairing_expires_at) > stamp;
    IF live_devices >= 100 THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'device_count_limit', 'error_status', 409);
    END IF;
    -- PG12 needs no UUID extension: independent SHA256 domain over 256-bit client entropy.
    new_id := pg_catalog.substr(pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
        'dpms-mail-import:db-device-id:' || $2, 'UTF8')), 'hex'), 1, 32)::uuid;
    BEGIN
        INSERT INTO {devices} (id, owner_id, name, include_body, include_attachments, owner_auth_version,
            pairing_expires_at, device_secret_hash, paired_at, expires_at, created_at)
            VALUES (new_id, u.id, normalized_name, login.include_body, login.include_attachments, u.auth_version,
                stamp, hashed, stamp, stamp + interval '365 days', stamp);
        INSERT INTO {bindings} (device_id, role_oid, role_name) VALUES (new_id, login.role_oid, login.role_name);
    EXCEPTION WHEN unique_violation THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'connect_conflict', 'error_status', 409);
    END;
    RETURN pg_catalog.jsonb_build_object('protocol_version', 1, 'device_id', new_id, 'device_secret', $2,
        'owner_name', u.full_name, 'include_body', login.include_body, 'include_attachments', login.include_attachments);
END
"""
    pair = f"""
DECLARE
    d {devices}%ROWTYPE;
    u record;
    code_digest text;
    new_digest text;
    paired_time timestamptz;
BEGIN
    IF $1 IS NULL OR pg_catalog.length($1) <> 43 OR $1 !~ '^[A-Za-z0-9_-]{{43}}$' THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    IF $2 IS NULL OR pg_catalog.length($2) <> 43 OR $2 !~ '^[A-Za-z0-9_-]{{43}}$' OR $1 = $2 THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_pairing_request', 'error_status', 422);
    END IF;
    code_digest := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:pair:' || $1, 'UTF8')), 'hex');
    SELECT x.* INTO d FROM {devices} AS x WHERE x.pairing_code_hash = code_digest;
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    SELECT x.id, x.full_name, x.is_active, x.auth_version INTO u FROM {users} AS x WHERE x.id = d.owner_id FOR SHARE;
    IF NOT FOUND OR NOT u.is_active THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    SELECT x.* INTO d FROM {devices} AS x WHERE x.id = d.id FOR UPDATE;
    paired_time := pg_catalog.clock_timestamp();
    IF NOT FOUND OR d.owner_id <> u.id OR d.owner_auth_version <> u.auth_version
       OR d.revoked_at IS NOT NULL OR d.paired_at IS NOT NULL
       OR d.pairing_code_hash IS DISTINCT FROM code_digest OR d.pairing_expires_at <= paired_time THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    new_digest := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:device:' || $2, 'UTF8')), 'hex');
    BEGIN
        UPDATE {devices} AS x SET pairing_code_hash = NULL, device_secret_hash = new_digest,
            paired_at = paired_time, expires_at = paired_time + interval '365 days' WHERE x.id = d.id;
    EXCEPTION WHEN unique_violation THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_pairing_request', 'error_status', 409);
    END;
    RETURN pg_catalog.jsonb_build_object('protocol_version', 1, 'device_id', d.id, 'device_secret', $2,
        'owner_name', u.full_name, 'include_body', d.include_body, 'include_attachments', d.include_attachments);
END
"""
    # No parent row locks, including implicit FK locks, on admission. The global
    # two-int advisory key occupies a different keyspace from import bigint locks.
    enqueue = f"""
DECLARE
    d {devices}%ROWTYPE;
    q {queue}%ROWTYPE;
    hashed text;
    legacy_hash text;
    body_hash text;
    body_bytes bigint;
    owner_count bigint;
    owner_bytes bigint;
    global_bytes bigint;
    stamp timestamptz;
    caller_role_oid oid;
    caller_role_name text;
BEGIN
    IF pg_catalog.current_setting('transaction_isolation') <> 'read committed' THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'unsupported_transaction', 'error_status', 400);
    END IF;
    IF $1 IS NULL OR pg_catalog.length($1) <> 43 OR $1 !~ '^[A-Za-z0-9_-]{{43}}$' THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    hashed := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:db-device:' || $1, 'UTF8')), 'hex');
    legacy_hash := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:device:' || $1, 'UTF8')), 'hex');
    {authorized_device}
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    IF $2 IS NULL OR $3 IS NULL OR pg_catalog.octet_length($3) = 0 THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_request', 'error_status', 422);
    END IF;
    body_bytes := pg_catalog.octet_length(pg_catalog.convert_to($3, 'UTF8'));
    IF body_bytes > 33554432 THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'batch_too_large', 'error_status', 413);
    END IF;
    body_hash := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to($3, 'UTF8')), 'hex');
    PERFORM pg_catalog.pg_advisory_xact_lock(1146113363, 1296646481);
    -- Recheck after waiting; execution revalidates again under owner/device locks.
    {authorized_device}
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
    END IF;
    SELECT x.* INTO q FROM {queue} AS x WHERE x.device_id = d.id AND x.request_id = $2;
    IF FOUND THEN
        IF q.payload_hash <> body_hash OR q.payload_bytes <> body_bytes THEN
            RETURN pg_catalog.jsonb_build_object('error_code', 'request_conflict', 'error_status', 409);
        END IF;
        RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', q.state);
    END IF;
    SELECT pg_catalog.count(*), COALESCE(pg_catalog.sum(x.payload_bytes), 0)
        INTO owner_count, owner_bytes FROM {queue} AS x WHERE x.owner_id = d.owner_id AND x.state = 'pending';
    SELECT COALESCE(pg_catalog.sum(x.payload_bytes), 0) INTO global_bytes FROM {queue} AS x WHERE x.state = 'pending';
    IF EXISTS (SELECT 1 FROM {queue} AS x WHERE x.device_id = d.id AND x.state = 'pending')
       OR owner_count >= 4 OR owner_bytes + body_bytes > 134217728 OR global_bytes + body_bytes > 1073741824 THEN
        RETURN pg_catalog.jsonb_build_object('error_code', 'queue_full', 'error_status', 429);
    END IF;
    stamp := pg_catalog.clock_timestamp();
    IF d.device_secret_hash = hashed THEN
        SELECT b.role_oid, b.role_name INTO caller_role_oid, caller_role_name FROM {bindings} AS b WHERE b.device_id = d.id;
        IF NOT FOUND THEN
            RETURN pg_catalog.jsonb_build_object('error_code', 'invalid_device', 'error_status', 401);
        END IF;
    END IF;
    INSERT INTO {queue} (device_id, request_id, owner_id, device_digest, payload, payload_hash,
        payload_bytes, state, created_at, expires_at, login_role_oid, login_role_name)
        VALUES (d.id, $2, d.owner_id, d.device_secret_hash, $3, body_hash, body_bytes, 'pending', stamp, stamp + interval '24 hours',
            caller_role_oid, caller_role_name);
    RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', 'pending');
END
"""
    status = f"""
DECLARE
    d {devices}%ROWTYPE;
    q {queue}%ROWTYPE;
    hashed text;
    legacy_hash text;
BEGIN
    IF $1 IS NULL OR pg_catalog.length($1) <> 43 OR $1 !~ '^[A-Za-z0-9_-]{{43}}$' THEN
        RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', 'error', 'result', NULL,
            'error_code', 'invalid_device', 'error_status', 401);
    END IF;
    hashed := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:db-device:' || $1, 'UTF8')), 'hex');
    legacy_hash := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('dpms-mail-import:device:' || $1, 'UTF8')), 'hex');
    {authorized_device}
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', 'error', 'result', NULL,
            'error_code', 'invalid_device', 'error_status', 401);
    END IF;
    SELECT x.* INTO q FROM {queue} AS x
        WHERE x.device_id = d.id AND x.owner_id = d.owner_id AND x.device_digest = d.device_secret_hash AND x.request_id = $2;
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', 'error', 'result', NULL,
            'error_code', 'request_not_found', 'error_status', 404);
    END IF;
    IF q.state = 'pending' AND q.expires_at <= pg_catalog.clock_timestamp() THEN
        RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', 'error', 'result', NULL,
            'error_code', 'request_expired', 'error_status', 408);
    END IF;
    RETURN pg_catalog.jsonb_build_object('request_id', $2, 'state', q.state, 'result', q.result,
        'error_code', q.error_code, 'error_status', q.error_status);
END
"""
    definitions = (
        ("mail_import_db_pair", "code text, new_secret text", pair),
        ("mail_import_db_enqueue", "secret text, request_id uuid, payload text", enqueue),
        ("mail_import_db_status", "secret text, request_id uuid", status),
        ("mail_import_db_protocol", "", "BEGIN RETURN pg_catalog.jsonb_build_object('protocol_version', 1, 'maximum_batch_bytes', 33554432, 'login_mode', 'role_bound'); END"),
        ("mail_import_db_connect", "device_name text, new_secret text", connect),
    )
    statements = []
    for name, args, body in definitions:
        function = qualified(schema, name)
        # A SQL string literal avoids delimiter injection even in unusual schema names.
        literal = "'" + body.replace("'", "''") + "'"
        statements.append(f"CREATE FUNCTION {function}({args}) RETURNS jsonb LANGUAGE plpgsql "
                          f"SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS {literal}")
        statements.append(f"REVOKE ALL ON FUNCTION {function}({SIGNATURES[name]}) FROM PUBLIC")
    return statements


def application_schema():
    bind = op.get_bind()
    schema = bind.execute(sa.text("SELECT pg_catalog.current_schema()")).scalar_one()
    if not schema or schema.startswith("pg_") or schema == "information_schema":
        raise RuntimeError("Queue migration requires the existing application schema")
    inspector = sa.inspect(bind)
    if not all(inspector.has_table(name, schema=schema) for name in ("users", "mail_import_devices")):
        raise RuntimeError("Queue migration requires schema100 in the current application schema")
    return schema


def upgrade():
    schema = application_schema()
    op.create_table(
        "mail_import_db_logins",
        sa.Column("role_oid", postgresql.OID(), primary_key=True),
        sa.Column("role_name", sa.String(63), nullable=False, unique=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{schema}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("include_body", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("include_attachments", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema=schema,
    )
    op.create_table(
        "mail_import_db_devices",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{schema}.mail_import_devices.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_oid", postgresql.OID(), nullable=False),
        sa.Column("role_name", sa.String(63), nullable=False),
        schema=schema,
    )
    op.create_table(
        "mail_import_queue",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_digest", sa.String(64), nullable=False),
        sa.Column("login_role_oid", postgresql.OID()),
        sa.Column("login_role_name", sa.String(63)),
        sa.Column("payload", sa.Text()),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(8), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(none_as_null=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_status", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("payload_bytes BETWEEN 1 AND 33554432", name="ck_mail_import_queue_bytes"),
        sa.CheckConstraint("(login_role_oid IS NULL) = (login_role_name IS NULL)", name="ck_mail_import_queue_login"),
        sa.CheckConstraint(
            "(state = 'pending' AND payload IS NOT NULL AND result IS NULL AND error_code IS NULL "
            "AND error_status IS NULL AND finished_at IS NULL) OR "
            "(state = 'done' AND payload IS NULL AND result IS NOT NULL AND error_code IS NULL "
            "AND error_status IS NULL AND finished_at IS NOT NULL) OR "
            "(state = 'error' AND payload IS NULL AND result IS NULL AND error_code IS NOT NULL "
            "AND error_status IS NOT NULL AND error_status BETWEEN 400 AND 599 AND finished_at IS NOT NULL)",
            name="ck_mail_import_queue_state",
        ),
        schema=schema,
    )
    op.create_index("uq_mail_import_queue_pending_device", "mail_import_queue", ["device_id"],
                    unique=True, postgresql_where=sa.text("state = 'pending'"), schema=schema)
    op.create_index("ix_mail_import_queue_owner_state", "mail_import_queue", ["owner_id", "state"], schema=schema)
    op.create_index("ix_mail_import_queue_pending", "mail_import_queue", ["created_at"],
                    postgresql_where=sa.text("state = 'pending'"), schema=schema)
    op.create_index("ix_mail_import_queue_finished", "mail_import_queue", ["finished_at"], schema=schema)
    for table in ("mail_import_queue", "mail_import_db_logins", "mail_import_db_devices"):
        op.execute(f"REVOKE ALL ON TABLE {qualified(schema, table)} FROM PUBLIC")
    for statement in function_statements(schema):
        # Function bodies contain literal colons, not SQLAlchemy bind parameters.
        op.get_bind().exec_driver_sql(statement)


def downgrade():
    schema = application_schema()
    tables = [qualified(schema, name) for name in ("mail_import_queue", "mail_import_db_devices", "mail_import_db_logins")]
    op.execute(f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT " + " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in tables))).scalar_one():
        raise RuntimeError("Queue downgrade blocked: stored requests, receipts or login bindings exist")
    for name, args in SIGNATURES.items():
        op.execute(f"DROP FUNCTION {qualified(schema, name)}({args})")
    op.drop_table("mail_import_queue", schema=schema)
    op.drop_table("mail_import_db_devices", schema=schema)
    op.drop_table("mail_import_db_logins", schema=schema)
