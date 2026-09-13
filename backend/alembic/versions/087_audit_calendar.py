"""Native scoped calendar and immutable history. Downgrade is intentionally refused."""
from alembic import op
import sqlalchemy as sa

revision = "087_audit_calendar"
down_revision = "086_audit_skills_registry_guide"
branch_labels = None
depends_on = None


# Frozen DDL: migrations do not import evolving application model metadata.
TABLES = {
    "members": """user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        code varchar(40) NOT NULL, role varchar(16) NOT NULL CHECK(role IN ('auditor','tech','speaker','observer')),
        can_manage boolean NOT NULL, active boolean NOT NULL, version integer NOT NULL,
        UNIQUE(scope_id,user_id), UNIQUE(scope_id,code)""",
    "groups": """code varchar(40) NOT NULL, label varchar(160) NOT NULL,
        legacy boolean NOT NULL, archived boolean NOT NULL, UNIQUE(scope_id,code)""",
    "group_versions": """group_id uuid NOT NULL, effective_from date NOT NULL CHECK(effective_from BETWEEN '2000-01-01' AND '2100-12-31'),
        auditor_id uuid REFERENCES users(id) ON DELETE RESTRICT, tech_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        reason text NOT NULL, CHECK(auditor_id IS NULL OR tech_id IS NULL OR auditor_id <> tech_id),
        UNIQUE(scope_id,group_id,effective_from),
        FOREIGN KEY(scope_id,group_id) REFERENCES audit_calendar_groups(scope_id,id) ON DELETE RESTRICT""",
    "import_batches": """source_sha256 varchar(64) NOT NULL, original jsonb NOT NULL,
        horizon_from date NOT NULL, horizon_to date NOT NULL,
        CHECK(horizon_from = '2026-08-28' AND horizon_to = '2026-09-11'),
        created_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL, UNIQUE(scope_id,source_sha256)""",
    "import_rows": """batch_id uuid NOT NULL, source_id varchar(160) NOT NULL, kind varchar(32) NOT NULL,
        original jsonb NOT NULL, UNIQUE(batch_id,source_id),
        FOREIGN KEY(scope_id,batch_id) REFERENCES audit_calendar_import_batches(scope_id,id) ON DELETE RESTRICT""",
    "import_mappings": """batch_id uuid NOT NULL, revision integer NOT NULL,
        mapping jsonb NOT NULL, summary jsonb NOT NULL,
        created_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, UNIQUE(batch_id,revision),
        FOREIGN KEY(scope_id,batch_id) REFERENCES audit_calendar_import_batches(scope_id,id) ON DELETE RESTRICT""",
    "import_applications": """batch_id uuid NOT NULL UNIQUE, mapping_id uuid NOT NULL,
        reason text NOT NULL, applied_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        applied_at timestamptz NOT NULL,
        FOREIGN KEY(scope_id,batch_id) REFERENCES audit_calendar_import_batches(scope_id,id) ON DELETE RESTRICT,
        FOREIGN KEY(scope_id,mapping_id) REFERENCES audit_calendar_import_mappings(scope_id,id) ON DELETE RESTRICT""",
    "plans": """date date NOT NULL CHECK(date BETWEEN '2000-01-01' AND '2100-12-31'),
        start integer NOT NULL, duration integer NOT NULL,
        CHECK(start >= 0 AND start % 30 = 0 AND duration >= 30 AND duration % 30 = 0 AND start + duration <= 1440),
        group_id uuid NOT NULL, group_version_id uuid, activity varchar(120) NOT NULL,
        speaker_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        status varchar(16) NOT NULL CHECK(status IN ('draft','planned','cancelled')),
        version integer NOT NULL, origin varchar(32) NOT NULL, source_id uuid,
        UNIQUE(scope_id,source_id),
        FOREIGN KEY(scope_id,group_id) REFERENCES audit_calendar_groups(scope_id,id) ON DELETE RESTRICT,
        FOREIGN KEY(scope_id,group_version_id) REFERENCES audit_calendar_group_versions(scope_id,id) ON DELETE RESTRICT,
        FOREIGN KEY(scope_id,source_id) REFERENCES audit_calendar_import_rows(scope_id,id) ON DELETE RESTRICT""",
    "plan_participants": """plan_id uuid NOT NULL, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        role varchar(16) NOT NULL CHECK(role IN ('auditor','tech','speaker','observer')),
        UNIQUE(plan_id,user_id,role),
        FOREIGN KEY(scope_id,plan_id) REFERENCES audit_calendar_plans(scope_id,id) ON DELETE RESTRICT""",
    "facts": """plan_id uuid, source_row_id uuid,
        date date NOT NULL CHECK(date BETWEEN '2000-01-01' AND '2100-12-31'),
        start integer NOT NULL, duration integer NOT NULL,
        CHECK(start >= 0 AND start % 30 = 0 AND duration >= 30 AND duration % 30 = 0 AND start + duration <= 1440),
        group_id uuid, activity varchar(120) NOT NULL,
        speaker_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        outcome varchar(16) NOT NULL CHECK(outcome IN ('completed','cancelled')),
        reason text NOT NULL, evidence text NOT NULL,
        recorded_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        recorded_at timestamptz NOT NULL, participant_snapshot jsonb NOT NULL,
        planned_snapshot jsonb, composition_unknown boolean NOT NULL, origin varchar(32) NOT NULL,
        auditor_absent_minutes integer NOT NULL CHECK(auditor_absent_minutes BETWEEN 0 AND 1440),
        CHECK(jsonb_typeof(participant_snapshot) = 'array'),
        CHECK(NOT composition_unknown OR jsonb_array_length(participant_snapshot) = 0),
        UNIQUE(scope_id,plan_id), UNIQUE(scope_id,source_row_id),
        FOREIGN KEY(scope_id,plan_id) REFERENCES audit_calendar_plans(scope_id,id) ON DELETE RESTRICT,
        FOREIGN KEY(scope_id,group_id) REFERENCES audit_calendar_groups(scope_id,id) ON DELETE RESTRICT,
        FOREIGN KEY(scope_id,source_row_id) REFERENCES audit_calendar_import_rows(scope_id,id) ON DELETE RESTRICT""",
    "fact_participants": """fact_id uuid NOT NULL, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        role varchar(16) NOT NULL CHECK(role IN ('auditor','tech','speaker','observer')),
        UNIQUE(fact_id,user_id,role),
        FOREIGN KEY(scope_id,fact_id) REFERENCES audit_calendar_facts(scope_id,id) ON DELETE RESTRICT""",
    "availability": """user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        date date NOT NULL CHECK(date BETWEEN '2000-01-01' AND '2100-12-31'),
        start integer NOT NULL, "end" integer NOT NULL, available boolean NOT NULL,
        CHECK(start >= 0 AND "end" <= 1440 AND start < "end" AND start % 30 = 0 AND "end" % 30 = 0)""",
    "absences": """user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        start_date date NOT NULL CHECK(start_date BETWEEN '2000-01-01' AND '2100-12-31'),
        end_date date NOT NULL CHECK(end_date BETWEEN '2000-01-01' AND '2100-12-31'),
        CHECK(end_date >= start_date AND end_date - start_date < 366), reason text NOT NULL,
        version integer NOT NULL, status varchar(16) NOT NULL CHECK(status IN ('active','cancelled'))""",
    "norm_revisions": """group_id uuid,
        effective_from date NOT NULL CHECK(effective_from BETWEEN '2000-01-01' AND '2100-12-31'),
        value integer NOT NULL CHECK(value BETWEEN 0 AND 1000), revision integer NOT NULL,
        reason text NOT NULL, recorded_at timestamptz NOT NULL,
        recorded_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        UNIQUE(scope_id,revision),
        FOREIGN KEY(scope_id,group_id) REFERENCES audit_calendar_groups(scope_id,id) ON DELETE RESTRICT""",
    "notices": """plan_id uuid NOT NULL, user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        reported_at timestamptz NOT NULL, reason text NOT NULL,
        FOREIGN KEY(scope_id,plan_id) REFERENCES audit_calendar_plans(scope_id,id) ON DELETE RESTRICT""",
    "events": """action varchar(64) NOT NULL, actor_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        actor_name varchar(255) NOT NULL, occurred_at timestamptz NOT NULL, detail jsonb NOT NULL""",
    "idempotency": """actor_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        request_id uuid NOT NULL, body_hash varchar(64) NOT NULL, response jsonb NOT NULL,
        UNIQUE(scope_id,actor_id,request_id)""",
}

IMMUTABLE = ("facts", "fact_participants", "group_versions", "norm_revisions", "notices", "events",
             "import_batches", "import_rows", "import_mappings", "import_applications", "idempotency")


def install_guards():
    op.execute("""CREATE FUNCTION ac_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Calendar immutable history: %', TG_TABLE_NAME USING ERRCODE='23514'; END $$""")
    op.execute("""CREATE FUNCTION ac_scope_lock() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM id FROM audit_calendar_scopes WHERE id = CASE WHEN TG_OP='DELETE' THEN OLD.scope_id ELSE NEW.scope_id END FOR UPDATE;
          IF TG_OP='UPDATE' AND (NEW.scope_id,NEW.id) IS DISTINCT FROM (OLD.scope_id,OLD.id) THEN
            RAISE EXCEPTION 'Calendar identity is immutable' USING ERRCODE='23514';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$""")
    for name in TABLES:
        op.execute(f"CREATE TRIGGER ac_00_scope_lock BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_{name} FOR EACH ROW EXECUTE FUNCTION ac_scope_lock()")
    for name in IMMUTABLE:
        op.execute(f"CREATE TRIGGER ac_immutable BEFORE UPDATE OR DELETE ON audit_calendar_{name} FOR EACH ROW EXECUTE FUNCTION ac_immutable()")
    op.execute("""CREATE FUNCTION ac_plan_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE pid uuid; sid uuid;
        BEGIN
          IF TG_TABLE_NAME='audit_calendar_plans' THEN pid := OLD.id; sid := OLD.scope_id;
          ELSE
            IF TG_OP <> 'INSERT' AND EXISTS(SELECT 1 FROM audit_calendar_facts WHERE plan_id=OLD.plan_id AND scope_id=OLD.scope_id) THEN
              RAISE EXCEPTION 'Fact freezes old plan participant' USING ERRCODE='23514';
            END IF;
            IF TG_OP='DELETE' THEN pid := OLD.plan_id; sid := OLD.scope_id;
            ELSE pid := NEW.plan_id; sid := NEW.scope_id; END IF;
          END IF;
          IF EXISTS(SELECT 1 FROM audit_calendar_facts WHERE plan_id=pid AND scope_id=sid) THEN
            RAISE EXCEPTION 'Fact freezes its plan and children' USING ERRCODE='23514';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_plan_frozen BEFORE UPDATE OR DELETE ON audit_calendar_plans FOR EACH ROW EXECUTE FUNCTION ac_plan_frozen()")
    op.execute("CREATE TRIGGER ac_plan_frozen BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_plan_participants FOR EACH ROW EXECUTE FUNCTION ac_plan_frozen()")
    op.execute("""CREATE FUNCTION ac_fact_child_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot jsonb; created_here boolean;
        BEGIN
          SELECT participant_snapshot, xmin::text = (txid_current() % 4294967296)::text
            INTO snapshot,created_here FROM audit_calendar_facts WHERE scope_id=NEW.scope_id AND id=NEW.fact_id;
          IF NOT coalesce(created_here,false) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(snapshot) p
            WHERE p->>'user_id'=NEW.user_id::text AND p->>'role'=NEW.role) THEN
            RAISE EXCEPTION 'Fact child must be inserted with its immutable snapshot' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_fact_child_insert BEFORE INSERT ON audit_calendar_fact_participants FOR EACH ROW EXECUTE FUNCTION ac_fact_child_insert()")
    op.execute("""CREATE FUNCTION ac_fact_canonical_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.source_row_id IS NOT NULL THEN
            IF NOT EXISTS(SELECT 1 FROM audit_calendar_import_rows r
              JOIN audit_calendar_import_applications a ON a.scope_id=r.scope_id AND a.batch_id=r.batch_id
              WHERE r.id=NEW.source_row_id AND r.scope_id=NEW.scope_id) THEN
              RAISE EXCEPTION 'Fact source has not been explicitly accepted' USING ERRCODE='23514';
            END IF;
            IF EXISTS(SELECT 1 FROM audit_calendar_import_rows incoming
              JOIN audit_calendar_import_rows prior ON prior.scope_id=incoming.scope_id
                AND prior.source_id=incoming.source_id AND prior.kind=incoming.kind
              JOIN audit_calendar_facts f ON f.scope_id=prior.scope_id AND f.source_row_id=prior.id
              WHERE incoming.id=NEW.source_row_id AND incoming.scope_id=NEW.scope_id) THEN
              RAISE EXCEPTION 'Canonical source identity already has a fact' USING ERRCODE='23505';
            END IF;
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_fact_canonical_source BEFORE INSERT ON audit_calendar_facts FOR EACH ROW EXECUTE FUNCTION ac_fact_canonical_source()")
    op.execute("""CREATE FUNCTION ac_fact_children_complete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (SELECT count(*) FROM audit_calendar_fact_participants WHERE scope_id=NEW.scope_id AND fact_id=NEW.id)
             <> jsonb_array_length(NEW.participant_snapshot) THEN
            RAISE EXCEPTION 'Fact children must exactly match snapshot' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER ac_fact_children_complete AFTER INSERT ON audit_calendar_facts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ac_fact_children_complete()")
    op.execute("""CREATE FUNCTION ac_norm_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE baseline_day date; accepted_bootstrap boolean;
        BEGIN
          SELECT baseline INTO baseline_day FROM audit_calendar_scopes WHERE id=NEW.scope_id;
          SELECT EXISTS(
            SELECT 1 FROM audit_calendar_import_applications a
              JOIN audit_calendar_import_mappings m ON m.id=a.mapping_id AND m.batch_id=a.batch_id AND m.scope_id=a.scope_id
              JOIN audit_calendar_import_batches b ON b.id=a.batch_id AND b.scope_id=a.scope_id
            WHERE a.scope_id=NEW.scope_id AND a.xmin::text=(txid_current() % 4294967296)::text
              AND m.summary->>'bootstrap_history'='true'
              AND b.original->'data'->'planning'->>'trackingStart'=baseline_day::text
              AND NOT EXISTS(SELECT 1 FROM audit_calendar_plans p WHERE p.scope_id=NEW.scope_id AND p.xmin::text<>(txid_current() % 4294967296)::text)
              AND NOT EXISTS(SELECT 1 FROM audit_calendar_facts f WHERE f.scope_id=NEW.scope_id AND f.xmin::text<>(txid_current() % 4294967296)::text)
              AND NOT EXISTS(SELECT 1 FROM audit_calendar_norm_revisions n WHERE n.scope_id=NEW.scope_id AND n.group_id IS NOT NULL AND n.xmin::text<>(txid_current() % 4294967296)::text)
              AND EXISTS(SELECT 1 FROM jsonb_array_elements(
                CASE WHEN NEW.group_id IS NULL THEN b.original->'data'->'planning'->'dailyTargets'
                     ELSE b.original->'data'->'planning'->'groupTargets' END) n
                WHERE n->>'from'=NEW.effective_from::text AND (n->>'value')::integer=NEW.value
                  AND (NEW.group_id IS NULL OR m.summary->'groups'->>(n->>'groupId')=NEW.group_id::text))
              AND NOT EXISTS(SELECT 1 FROM audit_calendar_norm_revisions n WHERE n.scope_id=NEW.scope_id
                AND n.group_id IS NOT DISTINCT FROM NEW.group_id AND n.effective_from=NEW.effective_from)
          ) INTO accepted_bootstrap;
          IF NEW.effective_from < baseline_day OR (NEW.effective_from < (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Moscow')::date
            AND NOT (NEW.group_id IS NULL AND NEW.effective_from=baseline_day AND
              NOT EXISTS(SELECT 1 FROM audit_calendar_norm_revisions WHERE scope_id=NEW.scope_id))
            AND NOT accepted_bootstrap) THEN
            RAISE EXCEPTION 'Norm history cannot be rewritten' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_norm_insert BEFORE INSERT ON audit_calendar_norm_revisions FOR EACH ROW EXECUTE FUNCTION ac_norm_insert()")
    op.execute("""CREATE FUNCTION ac_absence_history() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE today date := (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Moscow')::date;
        BEGIN
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Absence deletion is forbidden' USING ERRCODE='23514'; END IF;
          IF (NEW.user_id,NEW.start_date,NEW.reason) IS DISTINCT FROM (OLD.user_id,OLD.start_date,OLD.reason)
            OR NEW.version <> OLD.version+1 OR OLD.status <> 'active' OR OLD.end_date < today
            OR NOT ((OLD.start_date >= today AND NEW.status='cancelled' AND NEW.end_date=OLD.end_date)
              OR (OLD.start_date < today AND NEW.status='active' AND NEW.end_date=today-1)) THEN
            RAISE EXCEPTION 'Absence history must be preserved' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_absence_history BEFORE UPDATE OR DELETE ON audit_calendar_absences FOR EACH ROW EXECUTE FUNCTION ac_absence_history()")
    op.execute("""CREATE FUNCTION ac_source_append() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS(SELECT 1 FROM audit_calendar_import_applications WHERE batch_id=NEW.batch_id AND scope_id=NEW.scope_id) THEN
            RAISE EXCEPTION 'Applied source rows and mapping cannot be extended' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    for name in ("import_rows", "import_mappings"):
        op.execute(f"CREATE TRIGGER ac_source_append BEFORE INSERT ON audit_calendar_{name} FOR EACH ROW EXECUTE FUNCTION ac_source_append()")
    op.execute("""CREATE FUNCTION ac_application_mapping() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS(SELECT 1 FROM audit_calendar_import_mappings WHERE id=NEW.mapping_id AND scope_id=NEW.scope_id AND batch_id=NEW.batch_id) THEN
            RAISE EXCEPTION 'Mapping belongs to another batch' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_application_mapping BEFORE INSERT ON audit_calendar_import_applications FOR EACH ROW EXECUTE FUNCTION ac_application_mapping()")
    op.execute("""CREATE FUNCTION ac_scope_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Calendar scope cannot be deleted' USING ERRCODE='23514'; END IF;
          IF (NEW.id,NEW.singleton,NEW.baseline,NEW.timezone) IS DISTINCT FROM (OLD.id,OLD.singleton,OLD.baseline,OLD.timezone)
             OR NEW.version <> OLD.version+1 THEN
            RAISE EXCEPTION 'Calendar scope identity, baseline and version are protected' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER ac_scope_history BEFORE UPDATE OR DELETE ON audit_calendar_scopes FOR EACH ROW EXECUTE FUNCTION ac_scope_history()")


def upgrade():
    op.add_column("users", sa.Column("audit_calendar_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""CREATE TABLE audit_calendar_scopes (
        id uuid PRIMARY KEY, singleton integer NOT NULL UNIQUE CHECK(singleton=1), name varchar(160) NOT NULL,
        timezone varchar(40) NOT NULL CHECK(timezone='Europe/Moscow'),
        baseline date NOT NULL CHECK(baseline BETWEEN '2000-01-01' AND '2100-12-31'),
        version integer NOT NULL CHECK(version>=0), archived boolean NOT NULL, history_complete boolean NOT NULL)""")
    for name, ddl in TABLES.items():
        op.execute(f"CREATE TABLE audit_calendar_{name} (id uuid PRIMARY KEY, scope_id uuid NOT NULL REFERENCES audit_calendar_scopes(id) ON DELETE RESTRICT, UNIQUE(scope_id,id), {ddl})")
        op.execute(f"CREATE INDEX ix_audit_calendar_{name}_scope_id ON audit_calendar_{name}(scope_id)")
    for name in ("plans", "facts", "availability"):
        op.execute(f"CREATE INDEX ix_audit_calendar_{name}_date ON audit_calendar_{name}(date)")
    for table, column in (("plan_participants", "user_id"), ("fact_participants", "user_id"),
                          ("availability", "user_id"), ("absences", "user_id"), ("notices", "user_id"),
                          ("group_versions", "auditor_id"), ("group_versions", "tech_id"),
                          ("plans", "speaker_id"), ("facts", "speaker_id")):
        op.execute(f"ALTER TABLE audit_calendar_{table} ADD CONSTRAINT fk_ac_{table}_{column}_member FOREIGN KEY(scope_id,{column}) REFERENCES audit_calendar_members(scope_id,user_id) ON DELETE RESTRICT")
    install_guards()


def downgrade():
    raise RuntimeError("087_audit_calendar contains immutable history. Downgrade refuses data loss; use a reviewed forward migration.")
