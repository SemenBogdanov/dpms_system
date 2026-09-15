"""Independent calendar scope and append-only evidence; no audit/Q side effects."""
from datetime import date as DateType, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now():
    return datetime.now(timezone.utc)


JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")


class Scoped:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_id: Mapped[UUID] = mapped_column(ForeignKey("audit_calendar_scopes.id", ondelete="RESTRICT"), index=True)


def constraints(name, *extra):
    return (UniqueConstraint("scope_id", "id", name=f"uq_ac_{name}_scope_id"), *extra)


def scoped_fk(column, target):
    return ForeignKeyConstraint(["scope_id", column], [f"audit_calendar_{target}.scope_id", f"audit_calendar_{target}.id"], ondelete="RESTRICT")


def member_fk(column):
    return ForeignKeyConstraint(["scope_id", column], ["audit_calendar_members.scope_id", "audit_calendar_members.user_id"], ondelete="RESTRICT")


def interval_constraint(name):
    return CheckConstraint("start >= 0 AND start % 30 = 0 AND duration >= 30 AND duration % 30 = 0 AND start + duration <= 1440", name=f"ck_ac_{name}_interval")


def date_constraint(column, name):
    return CheckConstraint(f"{column} BETWEEN '2000-01-01' AND '2100-12-31'", name=f"ck_ac_{name}_date")


class AuditCalendarScope(Base):
    __tablename__ = "audit_calendar_scopes"
    __table_args__ = (CheckConstraint("singleton = 1", name="ck_ac_singleton"),
                      CheckConstraint("timezone = 'Europe/Moscow'", name="ck_ac_timezone"),
                      date_constraint("baseline", "scope"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    singleton: Mapped[int] = mapped_column(Integer, unique=True, default=1)
    name: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(40), default="Europe/Moscow")
    baseline: Mapped[DateType] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    history_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditCalendarMember(Scoped, Base):
    __tablename__ = "audit_calendar_members"
    __table_args__ = constraints("member", UniqueConstraint("scope_id", "user_id"), UniqueConstraint("scope_id", "code"), CheckConstraint("role IN ('auditor','tech','speaker','observer')", name="ck_ac_member_role"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(16))
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class AuditCalendarGroup(Scoped, Base):
    __tablename__ = "audit_calendar_groups"
    __table_args__ = constraints("group", UniqueConstraint("scope_id", "code"))
    code: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(160))
    legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditCalendarGroupVersion(Scoped, Base):
    __tablename__ = "audit_calendar_group_versions"
    __table_args__ = constraints("group_version", scoped_fk("group_id", "groups"), member_fk("auditor_id"), member_fk("tech_id"), UniqueConstraint("scope_id", "group_id", "effective_from"), date_constraint("effective_from", "group_version"), CheckConstraint("auditor_id IS NULL OR tech_id IS NULL OR auditor_id <> tech_id", name="ck_ac_group_distinct"))
    group_id: Mapped[UUID] = mapped_column()
    effective_from: Mapped[DateType] = mapped_column(Date)
    auditor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    tech_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)


class AuditCalendarPlan(Scoped, Base):
    __tablename__ = "audit_calendar_plans"
    __table_args__ = constraints("plan", scoped_fk("group_id", "groups"), scoped_fk("group_version_id", "group_versions"), scoped_fk("source_id", "import_rows"), member_fk("speaker_id"), UniqueConstraint("scope_id", "source_id"), interval_constraint("plan"), date_constraint("date", "plan"), CheckConstraint("status IN ('draft','planned','cancelled')", name="ck_ac_plan_status"))
    date: Mapped[DateType] = mapped_column(Date, index=True)
    start: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[UUID] = mapped_column()
    group_version_id: Mapped[UUID | None] = mapped_column()
    activity: Mapped[str] = mapped_column(String(120))
    speaker_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    origin: Mapped[str] = mapped_column(String(32), default="native")
    source_id: Mapped[UUID | None] = mapped_column()


class AuditCalendarPlanParticipant(Scoped, Base):
    __tablename__ = "audit_calendar_plan_participants"
    __table_args__ = constraints("plan_participant", scoped_fk("plan_id", "plans"), member_fk("user_id"), UniqueConstraint("plan_id", "user_id", "role"), CheckConstraint("role IN ('auditor','tech','speaker','observer')", name="ck_ac_pp_role"))
    plan_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(String(16))


class AuditCalendarFact(Scoped, Base):
    __tablename__ = "audit_calendar_facts"
    __table_args__ = constraints("fact", scoped_fk("plan_id", "plans"), scoped_fk("group_id", "groups"), scoped_fk("source_row_id", "import_rows"), member_fk("speaker_id"), UniqueConstraint("scope_id", "plan_id"), UniqueConstraint("scope_id", "source_row_id"), interval_constraint("fact"), date_constraint("date", "fact"), CheckConstraint("outcome IN ('completed','cancelled')", name="ck_ac_fact_outcome"), CheckConstraint("auditor_absent_minutes >= 0 AND auditor_absent_minutes <= 1440", name="ck_ac_fact_attendance"))
    plan_id: Mapped[UUID | None] = mapped_column()
    source_row_id: Mapped[UUID | None] = mapped_column()
    date: Mapped[DateType] = mapped_column(Date, index=True)
    start: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    group_id: Mapped[UUID | None] = mapped_column()
    activity: Mapped[str] = mapped_column(String(120))
    speaker_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    recorded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    participant_snapshot: Mapped[list] = mapped_column(JSON_VALUE)
    planned_snapshot: Mapped[dict | None] = mapped_column(JSON_VALUE, nullable=True)
    composition_unknown: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(32))
    auditor_absent_minutes: Mapped[int] = mapped_column(Integer, default=0)


class AuditCalendarFactParticipant(Scoped, Base):
    __tablename__ = "audit_calendar_fact_participants"
    __table_args__ = constraints("fact_participant", scoped_fk("fact_id", "facts"), member_fk("user_id"), UniqueConstraint("fact_id", "user_id", "role"), CheckConstraint("role IN ('auditor','tech','speaker','observer')", name="ck_ac_fp_role"))
    fact_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(String(16))


class AuditCalendarAvailability(Scoped, Base):
    __tablename__ = "audit_calendar_availability"
    __table_args__ = constraints("availability", member_fk("user_id"), date_constraint("date", "availability"), CheckConstraint('start >= 0 AND "end" <= 1440 AND start < "end" AND start % 30 = 0 AND "end" % 30 = 0', name="ck_ac_availability_interval"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    date: Mapped[DateType] = mapped_column(Date, index=True)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean)


class AuditCalendarAbsence(Scoped, Base):
    __tablename__ = "audit_calendar_absences"
    __table_args__ = constraints("absence", member_fk("user_id"), date_constraint("start_date", "absence_start"), date_constraint("end_date", "absence_end"), CheckConstraint("end_date >= start_date", name="ck_ac_absence_interval"), CheckConstraint("status IN ('active','cancelled')", name="ck_ac_absence_status"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    start_date: Mapped[DateType] = mapped_column(Date)
    end_date: Mapped[DateType] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")


class AuditCalendarAvailabilityLock(Scoped, Base):
    __tablename__ = "audit_calendar_availability_locks"
    __table_args__ = constraints("availability_lock", member_fk("user_id"), UniqueConstraint("scope_id", "user_id", "date"), date_constraint("date", "lock"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    date: Mapped[DateType] = mapped_column(Date)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    snapshot: Mapped[list] = mapped_column(JSON_VALUE)


class AuditCalendarChangeRequest(Scoped, Base):
    __tablename__ = "audit_calendar_change_requests"
    __table_args__ = constraints("change_request", member_fk("user_id"), date_constraint("date", "request"), CheckConstraint("status IN ('pending','approved','closed','rejected')", name="ck_ac_request_status"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    date: Mapped[DateType] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    resolution: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[list] = mapped_column(JSON_VALUE)
    after: Mapped[list | None] = mapped_column(JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True)


class AuditCalendarNormRevision(Scoped, Base):
    __tablename__ = "audit_calendar_norm_revisions"
    __table_args__ = constraints("norm", scoped_fk("group_id", "groups"), date_constraint("effective_from", "norm"), CheckConstraint("value BETWEEN 0 AND 1000", name="ck_ac_norm_value"), UniqueConstraint("scope_id", "revision"))
    group_id: Mapped[UUID | None] = mapped_column()
    effective_from: Mapped[DateType] = mapped_column(Date)
    value: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    recorded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AuditCalendarNotice(Scoped, Base):
    __tablename__ = "audit_calendar_notices"
    __table_args__ = constraints("notice", scoped_fk("plan_id", "plans"), member_fk("user_id"))
    plan_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)


class AuditCalendarEvent(Scoped, Base):
    __tablename__ = "audit_calendar_events"
    __table_args__ = constraints("event")
    action: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_name: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    detail: Mapped[dict] = mapped_column(JSON_VALUE)


class AuditCalendarImportBatch(Scoped, Base):
    __tablename__ = "audit_calendar_import_batches"
    __table_args__ = constraints("batch", UniqueConstraint("scope_id", "source_sha256"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    original: Mapped[dict] = mapped_column(JSON_VALUE)
    horizon_from: Mapped[DateType] = mapped_column(Date)
    horizon_to: Mapped[DateType] = mapped_column(Date)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditCalendarImportRow(Scoped, Base):
    __tablename__ = "audit_calendar_import_rows"
    __table_args__ = constraints("import_row", scoped_fk("batch_id", "import_batches"), UniqueConstraint("batch_id", "source_id"))
    batch_id: Mapped[UUID] = mapped_column()
    source_id: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32))
    original: Mapped[dict] = mapped_column(JSON_VALUE)


class AuditCalendarImportMapping(Scoped, Base):
    __tablename__ = "audit_calendar_import_mappings"
    __table_args__ = constraints("mapping", scoped_fk("batch_id", "import_batches"), UniqueConstraint("batch_id", "revision"))
    batch_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    mapping: Mapped[dict] = mapped_column(JSON_VALUE)
    summary: Mapped[dict] = mapped_column(JSON_VALUE)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AuditCalendarImportApplication(Scoped, Base):
    __tablename__ = "audit_calendar_import_applications"
    __table_args__ = constraints("application", scoped_fk("batch_id", "import_batches"), scoped_fk("mapping_id", "import_mappings"), UniqueConstraint("batch_id"))
    batch_id: Mapped[UUID] = mapped_column()
    mapping_id: Mapped[UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(Text)
    applied_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditCalendarIdempotency(Scoped, Base):
    __tablename__ = "audit_calendar_idempotency"
    __table_args__ = constraints("idempotency", UniqueConstraint("scope_id", "actor_id", "request_id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column()
    body_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON_VALUE)
