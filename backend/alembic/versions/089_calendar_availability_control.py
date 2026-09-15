"""Day locks and auditable availability change requests."""
from alembic import op

revision = "089_calendar_day_controls"
down_revision = "088_audit_calendar_guide"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("""CREATE TABLE audit_calendar_availability_locks (
        id uuid PRIMARY KEY, scope_id uuid NOT NULL REFERENCES audit_calendar_scopes(id) ON DELETE RESTRICT,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, date date NOT NULL,
        locked boolean NOT NULL, locked_at timestamptz NOT NULL,
        locked_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, snapshot jsonb NOT NULL,
        UNIQUE(scope_id,id), UNIQUE(scope_id,user_id,date),
        CHECK(date BETWEEN '2000-01-01' AND '2100-12-31'), CHECK(jsonb_typeof(snapshot)='array'),
        FOREIGN KEY(scope_id,user_id) REFERENCES audit_calendar_members(scope_id,user_id) ON DELETE RESTRICT)""")
    op.execute("""CREATE TABLE audit_calendar_change_requests (
        id uuid PRIMARY KEY, scope_id uuid NOT NULL REFERENCES audit_calendar_scopes(id) ON DELETE RESTRICT,
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT, date date NOT NULL,
        reason text NOT NULL CHECK(length(trim(reason))>0), status varchar(16) NOT NULL,
        requested_at timestamptz NOT NULL, requested_by_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        opened_at timestamptz, opened_by_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        closed_at timestamptz, closed_by_id uuid REFERENCES users(id) ON DELETE RESTRICT,
        resolution text NOT NULL, "before" jsonb NOT NULL, "after" jsonb,
        UNIQUE(scope_id,id), CHECK(date BETWEEN '2000-01-01' AND '2100-12-31'),
        CHECK(jsonb_typeof("before")='array'),
        CHECK(status IN ('pending','approved','closed','rejected')),
        CHECK((status='pending' AND opened_at IS NULL AND opened_by_id IS NULL AND closed_at IS NULL AND closed_by_id IS NULL AND "after" IS NULL)
           OR (status='approved' AND opened_at>=requested_at AND opened_by_id IS NOT NULL AND closed_at IS NULL AND closed_by_id IS NULL AND "after" IS NULL)
           OR (status='closed' AND opened_at>=requested_at AND opened_by_id IS NOT NULL AND closed_at>=opened_at AND closed_by_id IS NOT NULL AND "after" IS NOT NULL)
           OR (status='rejected' AND opened_at IS NULL AND opened_by_id IS NULL AND closed_at>=requested_at AND closed_by_id IS NOT NULL AND "after" IS NOT NULL)),
        FOREIGN KEY(scope_id,user_id) REFERENCES audit_calendar_members(scope_id,user_id) ON DELETE RESTRICT)""")
    op.execute("CREATE UNIQUE INDEX uq_ac_open_request ON audit_calendar_change_requests(scope_id,user_id,date) WHERE status IN ('pending','approved')")
    for table in ("availability_locks", "change_requests"):
        op.execute(f"CREATE INDEX ix_ac_{table}_scope_date ON audit_calendar_{table}(scope_id,date)")
        op.execute(f"CREATE TRIGGER ac_00_scope_lock BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_{table} FOR EACH ROW EXECUTE FUNCTION ac_scope_lock()")
    op.execute("""CREATE FUNCTION ac_request_history() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Availability request history cannot be deleted' USING ERRCODE='23514'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.status<>'pending' THEN RAISE EXCEPTION 'Request must start pending' USING ERRCODE='23514'; END IF;
        ELSE
          IF (NEW.scope_id,NEW.user_id,NEW.date,NEW.reason,NEW.requested_at,NEW.requested_by_id,NEW."before")
              IS DISTINCT FROM (OLD.scope_id,OLD.user_id,OLD.date,OLD.reason,OLD.requested_at,OLD.requested_by_id,OLD."before")
            OR NOT ((OLD.status='pending' AND NEW.status IN ('approved','rejected')) OR (OLD.status='approved' AND NEW.status='closed'))
            OR (OLD.status='approved' AND (NEW.opened_at,NEW.opened_by_id) IS DISTINCT FROM (OLD.opened_at,OLD.opened_by_id)) THEN
            RAISE EXCEPTION 'Availability request history is immutable' USING ERRCODE='23514';
          END IF;
        END IF;
        IF NOT EXISTS(SELECT 1 FROM audit_calendar_availability_locks l WHERE l.scope_id=NEW.scope_id AND l.user_id=NEW.user_id AND l.date=NEW.date AND l.locked) THEN
          RAISE EXCEPTION 'Request transition requires a locked day' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("CREATE TRIGGER ac_request_history BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_change_requests FOR EACH ROW EXECUTE FUNCTION ac_request_history()")
    op.execute("""CREATE FUNCTION ac_day_lock_history() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Day lock history cannot be deleted' USING ERRCODE='23514'; END IF;
        IF TG_OP='UPDATE' THEN
          IF (NEW.user_id,NEW.date) IS DISTINCT FROM (OLD.user_id,OLD.date) OR NEW.locked=OLD.locked THEN
            RAISE EXCEPTION 'Day lock identity/state is protected' USING ERRCODE='23514';
          END IF;
          IF NOT NEW.locked AND (NEW.locked_at,NEW.locked_by_id,NEW.snapshot) IS DISTINCT FROM (OLD.locked_at,OLD.locked_by_id,OLD.snapshot) THEN
            RAISE EXCEPTION 'Opening a day cannot rewrite its baseline' USING ERRCODE='23514';
          END IF;
        ELSIF NOT NEW.locked THEN
          RAISE EXCEPTION 'A day lock must start closed' USING ERRCODE='23514';
        END IF;
        IF NOT NEW.locked AND NOT EXISTS(SELECT 1 FROM audit_calendar_change_requests r WHERE r.scope_id=NEW.scope_id AND r.user_id=NEW.user_id AND r.date=NEW.date AND r.status='approved') THEN
          RAISE EXCEPTION 'Opening requires an approved day request' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("CREATE TRIGGER ac_day_lock_history BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_availability_locks FOR EACH ROW EXECUTE FUNCTION ac_day_lock_history()")
    op.execute("""CREATE FUNCTION ac_availability_locked() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP<>'INSERT' AND EXISTS(SELECT 1 FROM audit_calendar_availability_locks l WHERE l.scope_id=OLD.scope_id AND l.user_id=OLD.user_id AND l.date=OLD.date AND l.locked) THEN
          RAISE EXCEPTION 'Availability day is locked' USING ERRCODE='23514';
        END IF;
        IF TG_OP<>'DELETE' AND EXISTS(SELECT 1 FROM audit_calendar_availability_locks l WHERE l.scope_id=NEW.scope_id AND l.user_id=NEW.user_id AND l.date=NEW.date AND l.locked) THEN
          RAISE EXCEPTION 'Availability day is locked' USING ERRCODE='23514';
        END IF;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
      END $$""")
    op.execute("CREATE TRIGGER ac_availability_locked BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_availability FOR EACH ROW EXECUTE FUNCTION ac_availability_locked()")
    op.execute("""CREATE FUNCTION ac_absence_locked() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE l record; old_covered boolean; new_covered boolean;
      BEGIN
        FOR l IN SELECT * FROM audit_calendar_availability_locks WHERE locked AND scope_id=CASE WHEN TG_OP='DELETE' THEN OLD.scope_id ELSE NEW.scope_id END LOOP
          old_covered:=false; new_covered:=false;
          IF TG_OP<>'INSERT' THEN old_covered:=OLD.status='active' AND l.user_id=OLD.user_id AND l.date BETWEEN OLD.start_date AND OLD.end_date; END IF;
          IF TG_OP<>'DELETE' THEN new_covered:=NEW.status='active' AND l.user_id=NEW.user_id AND l.date BETWEEN NEW.start_date AND NEW.end_date; END IF;
          IF old_covered IS DISTINCT FROM new_covered THEN
            RAISE EXCEPTION 'Absence changes a locked availability day' USING ERRCODE='23514';
          END IF;
        END LOOP;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
      END $$""")
    op.execute("CREATE TRIGGER ac_absence_locked BEFORE INSERT OR UPDATE OR DELETE ON audit_calendar_absences FOR EACH ROW EXECUTE FUNCTION ac_absence_locked()")


def downgrade():
    raise RuntimeError("Availability requests contain immutable history; use a reviewed forward migration.")
