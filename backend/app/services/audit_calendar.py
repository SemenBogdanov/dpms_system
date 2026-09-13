"""Calendar transaction boundary. Every mutation locks the same durable scope."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select, text

from app.models.user import User
from app.models.audit_calendar import (
    AuditCalendarScope as Scope, AuditCalendarMember as Member,
    AuditCalendarGroup as Group, AuditCalendarGroupVersion as GroupVersion,
    AuditCalendarPlan as Plan, AuditCalendarPlanParticipant as PlanParticipant,
    AuditCalendarFact as Fact, AuditCalendarFactParticipant as FactParticipant,
    AuditCalendarAvailability as Availability, AuditCalendarAbsence as Absence,
    AuditCalendarNormRevision as Norm, AuditCalendarNotice as Notice,
    AuditCalendarEvent as Event, AuditCalendarIdempotency as Replay,
    AuditCalendarImportBatch as ImportBatch, AuditCalendarImportRow as ImportRow,
    AuditCalendarImportApplication as ImportApplication,
    AuditCalendarImportMapping as ImportMapping,
)
from app.services import audit_calendar_math as math
from app.services.audit_calendar_domain import (
    MOSCOW, attendance_state, availability_issues, availability_projections,
    composition_issues, conflict_issues, issue, meeting_instant, historical_source_issues,
)


def fail(status, message):
    raise HTTPException(status, detail=message)


def encoded(value):
    return jsonable_encoder(value)


def body_hash(operation, body):
    return hashlib.sha256(json.dumps({"operation": operation, "body": encoded(body)},
                                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def columns(row, names):
    return {name: getattr(row, name) for name in names.split()}


def plan_value(row):
    return columns(row, "id date start duration group_id group_version_id activity speaker_id status version origin source_id")


def fact_value(row):
    return columns(row, "id plan_id date start duration group_id activity speaker_id outcome reason evidence recorded_by_id recorded_at participant_snapshot planned_snapshot composition_unknown origin")


class CalendarService:
    def __init__(self, db, actor, *, now=None):
        self.db, self.actor_id = db, actor.id
        self.session_version = getattr(actor, "auth_version", None)
        self.now = (now or datetime.now(timezone.utc)).astimezone(MOSCOW)
        self.today = self.now.date()
        self.scope = None
        self.users, self.members = {}, {}

    async def rows(self, model, *conditions):
        return list((await self.db.scalars(select(model).where(model.scope_id == self.scope.id, *conditions)
                                          .execution_options(populate_existing=True))).all())

    async def one(self, model, identity):
        row = await self.db.scalar(select(model).where(model.scope_id == self.scope.id, model.id == identity)
                                   .execution_options(populate_existing=True))
        if row is None:
            fail(404, "Запись календаря не найдена")
        return row

    async def load_users(self, ids=None, *, lock=False):
        # Project only identity/grant fields, never credential columns.
        query = select(User.id, User.full_name, User.email, User.is_active,
                       User.audit_calendar_enabled, User.role, User.auth_version).order_by(User.id)
        if ids is not None:
            query = query.where(User.id.in_(sorted(set(ids), key=str)))
        if lock:
            query = query.with_for_update(read=True)
        return {row.id: SimpleNamespace(**row._mapping) for row in (await self.db.execute(query)).all()}

    async def lock(self, *, admin=False, helper=False, write=False, extra_users=()):
        self.scope = await self.db.scalar(select(Scope).where(Scope.singleton == 1)
                                         .with_for_update(read=not write).execution_options(populate_existing=True))
        if self.scope is None:
            fail(404, "Контур календаря ещё не настроен")
        self.members = {m.user_id: m for m in await self.rows(Member)}
        self.users = await self.load_users([self.actor_id, *self.members, *extra_users], lock=True)
        self.actor = self.users.get(self.actor_id)
        self.authorize(admin=admin, helper=helper)

    def authorize(self, *, admin=False, helper=False):
        actor = self.actor
        if actor is None or not actor.is_active or (self.session_version is not None and actor.auth_version != self.session_version):
            fail(403, "Текущая сессия или допуск пользователя отозваны")
        if admin:
            if getattr(actor.role, "value", actor.role) != "admin":
                fail(403, "Требуются права администратора системы")
            return
        member = self.members.get(actor.id)
        if not actor.audit_calendar_enabled or not member or not member.active:
            fail(403, "Нужны активное участие в контуре календаря и допуск к разделу")
        if helper and not member.can_manage:
            fail(403, "Требуются полномочия помощника по управлению календарём")

    def require_member(self, user_id, role=None):
        member, user = self.members.get(user_id), self.users.get(user_id)
        if not member or not member.active or not user or not user.is_active or not user.audit_calendar_enabled:
            fail(422, "Выбранный пользователь должен быть активным участником контура с допуском к календарю")
        if role and member.role != role:
            fail(422, "Роль выбранного участника не соответствует назначению")
        return member

    def ownership(self, user_id):
        if user_id != self.actor_id and not self.members[self.actor_id].can_manage:
            fail(403, "Сотрудник может изменять только свою доступность и свои отсутствия")
        self.require_member(user_id)

    async def replay(self, operation, body):
        digest = body_hash(operation, body.model_dump(mode="json"))
        previous = await self.db.scalar(select(Replay).where(Replay.scope_id == self.scope.id,
            Replay.actor_id == self.actor_id, Replay.request_id == body.request_id))
        if previous:
            if previous.body_hash != digest:
                fail(409, "Этот идентификатор запроса уже использован с другими данными")
            return previous.response, digest
        if hasattr(body, "expected_version") and body.expected_version != self.scope.version:
            fail(409, {"code": "STALE_VERSION", "version": self.scope.version})
        return None, digest

    async def finish(self, operation, body, digest, result, detail=None, *, raw=False):
        self.scope.version += 1
        response = encoded({**result, "version": self.scope.version} if raw else {"version": self.scope.version, "result": result})
        self.db.add(Event(scope_id=self.scope.id, action=operation, actor_id=self.actor_id,
                          actor_name=self.actor.full_name, detail=encoded(detail or body.model_dump(mode="json"))))
        self.db.add(Replay(scope_id=self.scope.id, actor_id=self.actor_id, request_id=body.request_id,
                          body_hash=digest, response=response))
        await self.db.flush()
        return response

    def editable(self, operation):
        if self.scope.archived and operation != "scope.archive":
            fail(409, "Контур календаря находится в архиве и недоступен для изменений")

    def scope_value(self):
        return {**columns(self.scope, "id name timezone baseline version archived history_complete"),
                "today": self.today, "now": self.now}

    def member_values(self):
        return [{**columns(m, "user_id code role can_manage active"),
                 "full_name": self.users[m.user_id].full_name} for m in self.members.values()]

    async def admin_state(self):
        self.users = await self.load_users([self.actor_id], lock=True)
        self.actor = self.users.get(self.actor_id)
        self.authorize(admin=True)
        self.scope = await self.db.scalar(select(Scope).where(Scope.singleton == 1))
        self.users = await self.load_users()
        self.members = {m.user_id: m for m in await self.rows(Member)} if self.scope else {}
        return encoded({"scope": self.scope_value() if self.scope else None, "members": self.member_values(),
                        "users": [columns(u, "id full_name email audit_calendar_enabled is_active") for u in self.users.values()]})

    async def setup(self, body):
        # Bootstrap has no row to lock yet. This transaction advisory lock only
        # serializes singleton creation; every subsequent write uses the row.
        if self.db.bind.dialect.name == "postgresql":
            await self.db.execute(text("SELECT pg_advisory_xact_lock(8700911)"))
        self.scope = await self.db.scalar(select(Scope).where(Scope.singleton == 1).with_for_update())
        self.users = await self.load_users([self.actor_id], lock=True)
        self.actor = self.users.get(self.actor_id)
        self.authorize(admin=True)
        if self.scope:
            prior, _ = await self.replay("admin.setup", body)
            if prior:
                return prior
            fail(409, "Единственный контур календаря уже создан")
        baseline = body.baseline or self.today
        if baseline > self.today:
            fail(422, "Дата начала учёта не может быть в будущем")
        self.scope = Scope(id=uuid4(), singleton=1, name=body.name, baseline=baseline,
                           timezone="Europe/Moscow", version=0, archived=False, history_complete=False)
        self.db.add(self.scope)
        await self.db.flush()
        self.db.add(Norm(scope_id=self.scope.id, group_id=None, effective_from=baseline, value=6,
                         revision=1, reason="Первоначальная настройка контура", recorded_by_id=self.actor_id))
        return await self.finish("admin.setup", body, body_hash("admin.setup", body.model_dump(mode="json")), {"id": self.scope.id})

    async def save_member(self, body):
        await self.lock(admin=True, write=True, extra_users=[body.user_id])
        prior, digest = await self.replay("admin.members", body)
        if prior:
            return prior
        user = self.users.get(body.user_id)
        if user is None or body.active and (not user.is_active or not user.audit_calendar_enabled):
            fail(422, "Перед активацией участия выдайте пользователю допуск к разделу календаря")
        if any(m.code == body.code and m.user_id != body.user_id for m in self.members.values()):
            fail(409, "Этот код уже назначен другому участнику")
        member = self.members.get(body.user_id)
        before = columns(member, "user_id code role can_manage active version") if member else None
        if member is None:
            member = Member(id=uuid4(), scope_id=self.scope.id, user_id=body.user_id, version=0)
            self.db.add(member)
        for key in ("code", "role", "can_manage", "active"):
            setattr(member, key, getattr(body, key))
        member.version += 1
        after = columns(member, "user_id code role can_manage active version")
        return await self.finish("admin.members", body, digest, after, {"before": before, "after": after})

    async def command(self, body):
        personal = body.operation in ("availability.paint", "absence.add", "absence.end")
        await self.lock(helper=not personal, write=True)
        if personal:
            target = (await self.one(Absence, body.payload.id)).user_id if body.operation == "absence.end" else body.payload.user_id
            self.ownership(target)
        prior, digest = await self.replay(body.operation, body)
        if prior:
            return prior
        self.editable(body.operation)
        handlers = {"group.save": self.save_group, "plan.save": self.save_plan, "plan.revise": self.revise_plan, "fact.record": self.record_fact,
                    "fact.restore": self.restore_fact, "notice.record": self.record_notice,
                    "availability.paint": self.paint, "absence.add": self.add_absence,
                    "absence.end": self.end_absence, "norm.set": self.set_norm, "scope.archive": self.archive}
        result = await handlers[body.operation](body.payload)
        return await self.finish(body.operation, body, digest, result)

    async def group_version(self, group_id, day):
        return await self.db.scalar(select(GroupVersion).where(GroupVersion.scope_id == self.scope.id,
            GroupVersion.group_id == group_id, GroupVersion.effective_from <= day)
            .order_by(GroupVersion.effective_from.desc()).limit(1))

    async def save_group(self, p):
        if p.effective_from < self.today or p.effective_from < self.scope.baseline:
            fail(422, "Состав группы нельзя изменять задним числом")
        self.require_member(p.auditor_id, "auditor")
        self.require_member(p.tech_id, "tech")
        if p.auditor_id == p.tech_id:
            fail(422, "Аудитор и техспециалист должны быть разными участниками")
        group = await self.one(Group, p.id) if p.id else None
        if any(g.code == p.code and g.id != p.id for g in await self.rows(Group)):
            fail(409, "Этот код уже назначен другой группе")
        if group and group.legacy:
            fail(409, "Историческую группу нельзя преобразовать в современную")
        if group is None:
            group = Group(id=uuid4(), scope_id=self.scope.id, code=p.code, label=p.label, legacy=False, archived=p.archived)
            self.db.add(group)
            await self.db.flush()
            await self.append_norm(group.id, p.effective_from, 3, p.reason)
        group.code, group.label, group.archived = p.code, p.label, p.archived
        versions = await self.rows(GroupVersion, GroupVersion.group_id == group.id)
        exact = next((v for v in versions if v.effective_from == p.effective_from), None)
        if exact and (exact.auditor_id, exact.tech_id) != (p.auditor_id, p.tech_id):
            fail(409, "Версии состава неизменяемы; выберите новую дату начала действия")
        if not exact:
            self.db.add(GroupVersion(scope_id=self.scope.id, group_id=group.id, effective_from=p.effective_from,
                                     auditor_id=p.auditor_id, tech_id=p.tech_id, reason=p.reason))
        return {"id": group.id}

    async def diagnostics(self, candidate, group, version, *, facts=False, check_availability=True):
        errors, people = composition_issues(group, version, self.members, self.users, candidate.activity, candidate.speaker_id)
        warnings = []
        participant_model, record_model = (FactParticipant, Fact) if facts else (PlanParticipant, Plan)
        records = await self.rows(record_model, record_model.date == candidate.date)
        links = await self.rows(participant_model)
        by_record = {}
        for link in links:
            rid = link.fact_id if facts else link.plan_id
            by_record.setdefault(rid, set()).add(link.user_id)
        if facts:
            for record in records:
                if record.speaker_id:
                    by_record.setdefault(record.id, set()).add(record.speaker_id)
        errors += conflict_issues(candidate, [uid for uid, _ in people], records, by_record, facts=facts)
        if check_availability:
            windows, absences = availability_projections(
                await self.rows(Availability, Availability.date == candidate.date),
                await self.rows(Absence, Absence.start_date <= candidate.date, Absence.end_date >= candidate.date))
            extra, warnings = availability_issues(candidate.date, candidate.start, candidate.duration,
                                                   [uid for uid, _ in people], windows, absences)
            errors += extra
        return errors, warnings, people

    async def revise_plan(self, p):
        plan = await self.one(Plan, p.id)
        if not plan.source_id:
            fail(422, "Для рабочей редакции нужен план из подтверждённого источника")
        source = await self.one(ImportRow, plan.source_id)
        if not await self.rows(ImportApplication, ImportApplication.batch_id == source.batch_id):
            fail(422, "Пакет источника ещё не подтверждён")
        return await self.save_plan(p, source_revision=True)

    async def save_plan(self, p, *, source_revision=False):
        plan = await self.one(Plan, p.id) if p.id else None
        if plan and await self.rows(Fact, Fact.plan_id == plan.id):
            fail(409, "План с зафиксированным фактом нельзя изменять")
        if p.date < self.today or plan and plan.date < self.today and not source_revision:
            fail(422, "Прошедший план нельзя изменять здесь; используйте отдельную рабочую редакцию подтверждённого источника")
        group = await self.one(Group, p.group_id)
        version = await self.group_version(group.id, p.date)
        errors, warnings, people = await self.diagnostics(p, group, version)
        if p.status == "planned" and errors:
            fail(422, {"issues": errors, "warnings": warnings})
        if plan is None:
            plan = Plan(id=uuid4(), scope_id=self.scope.id, version=0, origin="native")
            self.db.add(plan)
        for key in ("date", "start", "duration", "group_id", "activity", "speaker_id", "status"):
            setattr(plan, key, getattr(p, key))
        plan.group_version_id = version.id if version else None
        plan.version += 1
        if plan.source_id:
            plan.origin = "working-revision"
        await self.db.flush()
        await self.db.execute(delete(PlanParticipant).where(PlanParticipant.scope_id == self.scope.id, PlanParticipant.plan_id == plan.id))
        for uid, role in people:
            self.require_member(uid)
            self.db.add(PlanParticipant(scope_id=self.scope.id, plan_id=plan.id, user_id=uid, role=role))
        return {**plan_value(plan), "issues": errors, "warnings": warnings}

    async def canonical_source(self, source):
        applications = {a.batch_id: a for a in await self.rows(ImportApplication)}
        if source.batch_id not in applications:
            fail(422, "Пакет источника должен быть явно подтверждён")
        aliases = [r for r in await self.rows(ImportRow, ImportRow.source_id == source.source_id,
                    ImportRow.kind == source.kind) if r.batch_id in applications]
        if any(r.original != source.original for r in aliases):
            fail(409, "Содержимое исходной записи расходится с ранее подтверждённой версией")
        canonical = min(aliases, key=lambda r: (applications[r.batch_id].applied_at, str(r.id)))
        return canonical, [r.id for r in aliases]

    async def make_fact(self, p, plan, group_id, people, *, origin, source_row_id=None, unknown=False):
        if plan and await self.rows(Fact, Fact.plan_id == plan.id):
            fail(409, "Для плана уже зафиксирован неизменяемый факт")
        if source_row_id:
            source, aliases = await self.canonical_source(await self.one(ImportRow, source_row_id))
            if await self.rows(Fact, Fact.source_row_id.in_(aliases)):
                fail(409, "Для этой исходной записи уже зафиксирован факт, в том числе в другом пакете импорта")
            source_row_id = source.id
        snapshots = [{"user_id": uid, "role": role, "full_name": self.users[uid].full_name,
                      "code": self.members[uid].code} for uid, role in people]
        fact = Fact(id=uuid4(), scope_id=self.scope.id, plan_id=plan.id if plan else None,
            source_row_id=source_row_id, date=p.date, start=p.start, duration=p.duration, group_id=group_id,
            activity=p.activity, speaker_id=p.speaker_id, outcome=p.outcome, reason=p.reason, evidence=p.evidence,
            recorded_by_id=self.actor_id, recorded_at=self.now, participant_snapshot=encoded(snapshots),
            planned_snapshot=encoded(plan_value(plan)) if plan else None, composition_unknown=unknown,
            origin=origin, auditor_absent_minutes=getattr(p, "auditor_absent_minutes", 0))
        self.db.add(fact)
        await self.db.flush()
        for uid, role in people:
            self.db.add(FactParticipant(scope_id=self.scope.id, fact_id=fact.id, user_id=uid, role=role))
        await self.db.flush()
        return fact_value(fact)

    async def record_fact(self, p):
        plan = await self.one(Plan, p.plan_id)
        if plan.status != "planned":
            fail(422, "Факт можно зафиксировать только для запланированной встречи")
        if meeting_instant(p.date, p.start + (p.duration if p.outcome == "completed" else 0)) > self.now:
            fail(422, "Время факта ещё не наступило или проведённая встреча ещё не закончилась")
        group = await self.one(Group, p.group_id)
        version = await self.group_version(group.id, p.date)
        errors, _, people = await self.diagnostics(p, group, version, facts=True, check_availability=False)
        if p.outcome == "completed" and p.auditor_absent_minutes > 5:
            errors.append(issue("AUDITOR_ABSENT", "При отсутствии аудитора более пяти минут встречу нельзя отметить проведённой; укажите срыв"))
        if p.outcome == "completed" and errors:
            fail(422, {"issues": errors})
        for uid, _ in people:
            self.require_member(uid)
        return await self.make_fact(p, plan, group.id, people, origin="native")

    async def historical_context(self, p, *, actual_group_code=None):
        source, aliases = await self.canonical_source(await self.one(ImportRow, p.source_row_id))
        if await self.rows(Fact, Fact.source_row_id.in_(aliases)):
            fail(409, "Для этой исходной записи уже зафиксирован факт, в том числе в другом пакете импорта")
        batch = await self.one(ImportBatch, source.batch_id)
        applications = await self.rows(ImportApplication, ImportApplication.batch_id == batch.id)
        if not applications or source.kind not in ("plan", "fact"):
            fail(422, "Нужна строка встречи из подтверждённого источника")
        if not batch.horizon_from <= p.date <= min(batch.horizon_to, date(2026, 9, 11)) or p.date >= self.today:
            fail(422, "Исторический факт должен быть раньше сегодня и в пределах подтверждённого периода источника")
        plans = await self.rows(Plan, Plan.source_id == source.id)
        plan = plans[0] if source.kind == "plan" and plans else None
        if source.kind == "plan" and plan is None:
            fail(422, "Исходный план ещё не перенесён в календарь")
        if plan and plan.origin != "source":
            fail(409, "Рабочая редакция не даёт права на историческое исключение; оригинал сохраняется только как подтверждающий источник")
        errors = historical_source_issues(source.original, p.date, self.today, actual_group_code=actual_group_code)
        if errors:
            fail(422, {"issues": errors})
        mapping = await self.one(ImportMapping, applications[0].mapping_id)
        bound_group = mapping.summary.get("groups", {}).get(source.original.get("groupId"))
        group = await self.one(Group, UUID(bound_group)) if bound_group else None
        people = [(entry.user_id, entry.role) for entry in p.participants]
        if p.composition_unknown and people:
            fail(422, "При неизвестном составе список участников комиссии должен быть пустым")
        if len({uid for uid, _ in people}) != len(people):
            fail(422, "В историческом составе повторяется участник")
        if not p.reason.strip() or not p.evidence.strip():
            fail(422, "Для восстановления истории нужны основание и подтверждающий документ")
        if not p.activity.strip() or len(p.activity) > 80:
            fail(422, "Укажите историческую активность длиной от 1 до 80 символов")
        if not p.speaker_id:
            fail(422, "Для восстановления исторического факта нужно указать докладчика")
        if not p.composition_unknown and not any(role in ("auditor", "tech") for _, role in people):
            fail(422, "Известный исторический состав должен включать хотя бы одного участника комиссии")
        for uid, _ in people:
            self.require_member(uid)
        if p.speaker_id:
            self.require_member(p.speaker_id)
            if not p.composition_unknown and (p.speaker_id, "speaker") not in people:
                fail(422, "Исторический докладчик должен быть указан в снимке фактического состава")
        if p.outcome == "completed":
            links = await self.rows(FactParticipant)
            by_fact = {}
            for link in links:
                by_fact.setdefault(link.fact_id, set()).add(link.user_id)
            records = await self.rows(Fact, Fact.date == p.date)
            for fact in records:
                if fact.speaker_id:
                    by_fact.setdefault(fact.id, set()).add(fact.speaker_id)
            errors = conflict_issues(p, {uid for uid, _ in people} | ({p.speaker_id} if p.speaker_id else set()),
                records, by_fact, facts=True)
            if errors:
                fail(422, {"issues": errors})
        return source, plan, group, people

    async def restore_fact(self, p):
        source, plan, group, people = await self.historical_context(p)
        return await self.make_fact(p, plan, group.id if group else None, people,
                                    origin="historical-entry", source_row_id=source.id, unknown=p.composition_unknown)

    async def record_notice(self, p):
        plan = await self.one(Plan, p.plan_id)
        self.require_member(p.user_id)
        if not await self.rows(PlanParticipant, PlanParticipant.plan_id == plan.id, PlanParticipant.user_id == p.user_id):
            fail(422, "Сообщение об отсутствии можно записать только для участника этой встречи")
        if p.reported_at > self.now:
            fail(422, "Время сообщения об отсутствии не может быть в будущем")
        notice = Notice(id=uuid4(), scope_id=self.scope.id, **p.model_dump())
        self.db.add(notice)
        return {"id": notice.id, "attendance": attendance_state(plan, [*await self.rows(Notice), notice], self.now)}

    async def paint(self, p):
        if any(patch.date < self.today for patch in p.patches):
            fail(422, "Доступность за прошедшие даты нельзя изменять")
        days = {patch.date for patch in p.patches}
        old = await self.rows(Availability, Availability.user_id == p.user_id, Availability.date.in_(days))
        windows, _ = availability_projections(old, [])
        for patch in p.patches:
            windows = math.paint_availability(windows, person_id=str(p.user_id), day=patch.date,
                start_minute=patch.start, end_minute=patch.end, value=patch.value)
        await self.db.execute(delete(Availability).where(Availability.scope_id == self.scope.id,
            Availability.user_id == p.user_id, Availability.date.in_(days)))
        for w in windows:
            self.db.add(Availability(scope_id=self.scope.id, user_id=p.user_id, date=w.day,
                                     start=w.start_minute, end=w.end_minute, available=w.available))
        return {"user_id": p.user_id, "days": sorted(days)}

    async def add_absence(self, p):
        if p.start_date < self.today:
            fail(422, "Прошедшее отсутствие можно добавить только через подтверждённый импорт источника")
        overlaps = await self.rows(Absence, Absence.user_id == p.user_id, Absence.status == "active",
                                  Absence.start_date <= p.end_date, Absence.end_date >= p.start_date)
        if overlaps:
            fail(409, "Отсутствие пересекается с уже указанным действующим периодом")
        absence = Absence(id=uuid4(), scope_id=self.scope.id, **p.model_dump(), status="active", version=1)
        self.db.add(absence)
        return columns(absence, "id user_id start_date end_date reason version status")

    async def end_absence(self, p):
        absence = await self.one(Absence, p.id)
        if absence.status != "active" or absence.end_date < self.today:
            fail(409, "Этот период отсутствия уже завершён или отменён")
        before = columns(absence, "id user_id start_date end_date reason version status")
        if absence.start_date >= self.today:
            absence.status = "cancelled"
        else:
            absence.end_date = self.today - timedelta(days=1)
        absence.version += 1
        return {"before": before, "after": columns(absence, "id user_id start_date end_date reason version status")}

    async def append_norm(self, group_id, day, value, reason):
        revision = (await self.db.scalar(select(func.max(Norm.revision)).where(Norm.scope_id == self.scope.id)) or 0) + 1
        norm = Norm(id=uuid4(), scope_id=self.scope.id, group_id=group_id, effective_from=day,
                    value=value, reason=reason, revision=revision, recorded_by_id=self.actor_id, recorded_at=self.now)
        self.db.add(norm)
        await self.db.flush()
        return norm

    async def set_norm(self, p):
        if p.effective_from < max(self.today, self.scope.baseline):
            fail(422, "Изменение нормы не может пересчитывать прошлые даты")
        if p.group_id:
            group = await self.one(Group, p.group_id)
            if group.legacy or group.archived:
                fail(422, "Новую норму можно задать только для действующей современной группы")
        norm = await self.append_norm(p.group_id, p.effective_from, p.value, p.reason)
        return columns(norm, "id group_id effective_from value reason recorded_at recorded_by_id")

    async def archive(self, p):
        self.scope.archived = p.archived
        return {"archived": p.archived}

    async def state(self, start, end, *, group_id=None, person_id=None, query=""):
        try:
            math.day_range(start, end)
        except ValueError as exc:
            fail(422, "Укажите включительный период от 1 до 366 дней с датами в диапазоне с 2000 по 2100 год")
        await self.lock()
        groups = await self.rows(Group)
        group_map = {g.id: g for g in groups}
        if group_id and group_id not in group_map:
            fail(404, "Группа не найдена в этом контуре календаря")
        if person_id and person_id not in self.members:
            fail(404, "Участник не найден в этом контуре календаря")
        versions = await self.rows(GroupVersion)
        version_map = {v.id: v for v in versions}
        plans = await self.rows(Plan, Plan.date >= start, Plan.date <= end)
        visible_facts = await self.rows(Fact, Fact.date >= start, Fact.date <= end)
        fact_links = await self.rows(FactParticipant)
        plan_links = await self.rows(PlanParticipant)
        by_plan, by_fact = {}, {}
        for link in plan_links:
            by_plan.setdefault(link.plan_id, set()).add(link.user_id)
        for link in fact_links:
            by_fact.setdefault(link.fact_id, set()).add(link.user_id)
        windows = await self.rows(Availability, Availability.date >= start, Availability.date <= end)
        absences = await self.rows(Absence, Absence.start_date <= end, Absence.end_date >= start)
        projected_windows, projected_absences = availability_projections(windows, absences)
        notices = await self.rows(Notice, Notice.plan_id.in_([p.id for p in plans]))

        def matches(row, participants):
            group = group_map.get(row.group_id)
            haystack = " ".join([row.activity, group.code if group else "", group.label if group else "",
                *[self.users[uid].full_name + " " + self.members[uid].code for uid in participants if uid in self.users and uid in self.members]])
            return ((not group_id or row.group_id == group_id) and (not person_id or person_id in participants)
                    and (not query or query.casefold() in haystack.casefold()))

        plan_values = []
        frozen_ids = {f.plan_id for f in await self.rows(Fact, Fact.plan_id.in_([p.id for p in plans]))}
        for plan in plans:
            people = by_plan.get(plan.id, set())
            if not matches(plan, people):
                continue
            errors, warnings = [], []
            if plan.id not in frozen_ids and plan.status != "cancelled":
                historical = plan.origin == "source" and plan.date < self.today
                if historical:
                    if not plan.activity:
                        errors.append(issue("ACTIVITY_MISSING", "В историческом плане не указана активность"))
                    if not plan.speaker_id:
                        errors.append(issue("SPEAKER_MISSING", "В историческом плане не указан докладчик"))
                else:
                    errors, _ = composition_issues(group_map[plan.group_id], version_map.get(plan.group_version_id),
                        self.members, self.users, plan.activity, plan.speaker_id)
                    errors += conflict_issues(plan, people, plans, by_plan)
                    availability_errors, warnings = availability_issues(plan.date, plan.start, plan.duration,
                        people, projected_windows, projected_absences)
                    errors += availability_errors
                    active_versions = [v for v in versions if v.group_id == plan.group_id and v.effective_from <= plan.date]
                    current = max(active_versions, key=lambda v: v.effective_from, default=None)
                    if current and current.id != plan.group_version_id:
                        errors.append(issue("COMPOSITION_CHANGED", "Состав группы изменился; пересогласуйте план встречи"))
                if attendance_state(plan, notices, self.now) in ("absence", "late-absence"):
                    errors.append(issue("ABSENCE_NOTICE", "Участник сообщил об отсутствии"))
            plan_values.append({**plan_value(plan), "issues": errors, "warnings": warnings})
        fact_values = [fact_value(f) for f in visible_facts if matches(f, by_fact.get(f.id, set()) | ({f.speaker_id} if f.speaker_id else set()))]
        norms = sorted(await self.rows(Norm), key=lambda n: n.revision)
        latest = {}
        for norm in norms:
            latest[(norm.group_id, norm.effective_from)] = norm
        schedule = math.TargetSchedule(self.scope.baseline, tuple(math.TargetChange(n.effective_from, n.value,
            str(n.group_id) if n.group_id else None) for n in latest.values()))
        all_facts = await self.rows(Fact, Fact.date >= self.scope.baseline, Fact.date <= end)
        records = [math.MeetingRecord(str(f.id), f.date, str(f.group_id) if f.group_id else None,
                    outcome=f.outcome, duration_minutes=f.duration) for f in all_facts]
        group_key = str(group_id) if group_id else None
        accumulated = math.cumulative(schedule, records, end, today=self.today, group_id=group_key)

        def totals(first, last, gid):
            target = math.target_between(schedule, first, last, group_id=gid)
            completed = math.count_completed(records, first, last, group_id=gid)
            balance = target - completed
            return {"target": float(target), "completed": completed, "balance": float(balance), "backlog": float(max(0, balance))}

        fortnights = []
        cursor = self.scope.baseline
        # At most 2635 buckets over the supported 101-year date range.
        while cursor <= end:
            last = date.fromordinal(min(cursor.toordinal() + 13, end.toordinal()))
            closed_last = min(last.toordinal(), self.today.toordinal() - 1)
            closed = date.fromordinal(closed_last) if closed_last >= cursor.toordinal() else None
            value = totals(cursor, closed, group_key) if closed else {"target": 0, "completed": 0, "balance": 0, "backlog": 0}
            cumulative = math.cumulative(schedule, records, last, today=self.today, group_id=group_key)
            fortnights.append({"from": cursor, "to": last, **value, "cumulative_backlog": float(cumulative.backlog)})
            if last == end:
                break
            cursor = date.fromordinal(last.toordinal() + 1)
        group_totals = []
        for g in groups:
            value = math.cumulative(schedule, records, end, today=self.today, group_id=str(g.id))
            group_totals.append({"group_id": g.id, "code": g.code, "target": float(value.target),
                                 "completed": value.completed, "balance": float(value.balance), "backlog": float(value.backlog)})
        stats = {"plan": sum(p["status"] == "planned" for p in plan_values),
                 "fact": sum(f["outcome"] == "completed" for f in fact_values),
                 "attention": sum(bool(p["issues"] or p["warnings"]) for p in plan_values if p["status"] != "cancelled"),
                 "target": float(math.target_between(schedule, start, end, group_id=group_key)),
                 "daily_targets": {day.isoformat(): float(math.daily_target(schedule, day, group_id=group_key))
                                   for day in math.day_range(start, end)},
                 "backlog": float(accumulated.backlog), "through": accumulated.through,
                 "target_scope": "group" if group_id else "team", "groups": group_totals, "fortnights": fortnights}
        return encoded({"scope": self.scope_value(), "actor": {"user_id": self.actor_id, "can_manage": self.members[self.actor_id].can_manage},
            "members": self.member_values(), "groups": [{**columns(g, "id code label legacy archived"),
                "versions": [columns(v, "id effective_from auditor_id tech_id") for v in versions if v.group_id == g.id]} for g in groups],
            "plans": plan_values, "facts": fact_values,
            "availability": [columns(w, "user_id date start end available") for w in windows],
            "absences": [columns(a, "id user_id start_date end_date reason version status") for a in absences],
            "norms": [columns(n, "id group_id effective_from value reason recorded_at recorded_by_id") for n in latest.values()],
            "notices": [columns(n, "id plan_id user_id reported_at reason") for n in notices], "stats": stats})

    async def history(self, limit=100):
        await self.lock(helper=True)
        count = await self.db.scalar(select(func.count()).select_from(Event).where(Event.scope_id == self.scope.id))
        rows = (await self.db.scalars(select(Event).where(Event.scope_id == self.scope.id)
                .order_by(Event.occurred_at.desc(), Event.id).limit(limit))).all()
        return encoded({"items": [columns(e, "id action actor_name occurred_at detail") for e in rows], "total": count})
