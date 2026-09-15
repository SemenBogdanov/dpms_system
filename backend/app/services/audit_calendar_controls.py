"""Scoped day locks, change requests and explicit coordination notifications."""
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.models.audit_calendar import (
    AuditCalendarAvailability as Availability, AuditCalendarAbsence as Absence,
    AuditCalendarAvailabilityLock as DayLock, AuditCalendarChangeRequest as ChangeRequest,
    AuditCalendarGroup as Group, AuditCalendarGroupVersion as GroupVersion,
    AuditCalendarPlan as Plan, AuditCalendarPlanParticipant as PlanParticipant,
    AuditCalendarFact as Fact, AuditCalendarFactParticipant as FactParticipant,
    AuditCalendarEvent as Event,
)
from app.services.audit_calendar_domain import availability_projections
from app.services.audit_calendar_math import availability_value, MIN_DATE, MAX_DATE

LOCK_FIELDS = "id user_id date locked locked_at locked_by_id snapshot"
REQUEST_FIELDS = "id user_id date reason status requested_at requested_by_id opened_at opened_by_id closed_at closed_by_id resolution before after"
WORK_START, WORK_END = 600, 1080


def value(row, fields):
    return {name: getattr(row, name) for name in fields.split()}


def fail(message, status=409):
    raise HTTPException(status, detail=message)


def intervals(minutes):
    result = []
    for start in sorted(minutes):
        if result and result[-1]["end"] == start:
            result[-1]["end"] = start + 30
        else:
            result.append({"start": start, "end": start + 30})
    return result


class AvailabilityControl:
    async def day_snapshot(self, user_id, day):
        windows = await self.rows(Availability, Availability.user_id == user_id, Availability.date == day)
        absences = await self.rows(Absence, Absence.user_id == user_id, Absence.status == "active",
                                   Absence.start_date <= day, Absence.end_date >= day)
        return jsonable_encoder([
            *[{"kind": "availability", **value(w, "date start end available")} for w in sorted(windows, key=lambda w: w.start)],
            *[{"kind": "absence", **value(a, "id start_date end_date reason status")} for a in sorted(absences, key=lambda a: str(a.id))],
        ])

    async def assert_days_open(self, user_id, days):
        locked = await self.rows(DayLock, DayLock.user_id == user_id, DayLock.date.in_(days), DayLock.locked.is_(True))
        if locked:
            fail("Доступность закрыта помощником на " + ", ".join(str(x.date) for x in sorted(locked, key=lambda x: x.date)) + ". Подайте заявку на изменение дня.")

    async def lock_day(self, p):
        self.require_member(p.user_id)
        if p.date < self.today:
            fail("Прошедшую дату нельзя закрыть задним числом", 422)
        existing = await self.rows(DayLock, DayLock.user_id == p.user_id, DayLock.date == p.date)
        if existing:
            fail("День уже закрыт или открыт по заявке. Для повторной блокировки закройте эту заявку.")
        lock = DayLock(id=uuid4(), scope_id=self.scope.id, user_id=p.user_id, date=p.date,
                       locked=True, locked_at=self.now, locked_by_id=self.actor_id,
                       snapshot=await self.day_snapshot(p.user_id, p.date))
        self.db.add(lock)
        return value(lock, LOCK_FIELDS)

    async def request_day(self, p):
        if p.date < self.today:
            fail("Нельзя запросить изменение прошедшей даты", 422)
        existing = await self.rows(DayLock, DayLock.user_id == p.user_id, DayLock.date == p.date)
        if not existing or not existing[0].locked:
            fail("Заявка нужна только для закрытого дня")
        active = await self.rows(ChangeRequest, ChangeRequest.user_id == p.user_id, ChangeRequest.date == p.date,
                                  ChangeRequest.status.in_(("pending", "approved")))
        if active:
            fail("Для этого дня уже есть незакрытая заявка")
        request = ChangeRequest(id=uuid4(), scope_id=self.scope.id, user_id=p.user_id, date=p.date,
            reason=p.reason, status="pending", requested_at=self.now, requested_by_id=self.actor_id,
            opened_at=None, opened_by_id=None, closed_at=None, closed_by_id=None, resolution="",
            before=await self.day_snapshot(p.user_id, p.date), after=None)
        self.db.add(request)
        helpers = [m.user_id for m in self.members.values() if m.can_manage]
        await self.notify_users(helpers, "calendar_availability_requested", "Заявка на изменение доступности",
            f"{self.users[p.user_id].full_name}: {p.date}. {p.reason}", p.date, request.id)
        return value(request, REQUEST_FIELDS)

    async def resolve_day(self, p):
        request = await self.one(ChangeRequest, p.id)
        locks = await self.rows(DayLock, DayLock.user_id == request.user_id, DayLock.date == request.date)
        if not locks:
            fail("Закрытый день заявки не найден")
        lock = locks[0]
        if p.action == "approve":
            self.require_member(request.user_id)
            if request.status != "pending" or not lock.locked:
                fail("Открыть день можно только по ожидающей заявке")
            if request.date < self.today:
                fail("Дата заявки уже прошла: отклоните заявку с пояснением", 422)
            request.status, request.opened_at, request.opened_by_id = "approved", self.now, self.actor_id
            request.resolution = p.reason
            await self.db.flush()
            lock.locked = False
        else:
            required = "approved" if p.action == "close" else "pending"
            if request.status != required:
                fail("Эта заявка уже закрыта или её состояние не допускает выбранное действие")
            snapshot = await self.day_snapshot(request.user_id, request.date)
            if p.action == "close":
                lock.locked, lock.locked_at, lock.locked_by_id, lock.snapshot = True, self.now, self.actor_id, snapshot
                await self.db.flush()
            request.status = "closed" if p.action == "close" else "rejected"
            request.closed_at, request.closed_by_id = self.now, self.actor_id
            request.resolution, request.after = p.reason, snapshot
        labels = {"approve": "День открыт для изменения", "close": "Заявка закрыта, день заблокирован", "reject": "Заявка отклонена"}
        await self.notify_users([request.user_id], "calendar_availability_resolved", labels[p.action],
                                f"{request.date}: {p.reason}", request.date, request.id)
        return value(request, REQUEST_FIELDS)

    async def notify_users(self, recipients, kind, title, message, day, source_id, *, duration=None):
        from app.services.notifications import create_notification
        tab = "groups" if kind == "calendar_group_reconcile_requested" else "requests"
        link = f"/audit-calendar?view=readiness&summary_tab={tab}&from={day}&to={day}"
        if duration is not None:
            link += f"&duration={duration}"
        notified = []
        for uid in sorted(set(recipients), key=str):
            m, u = self.members.get(uid), self.users.get(uid)
            if uid == self.actor_id or not m or not m.active or not u or not u.is_active or not u.audit_calendar_enabled:
                continue
            await create_notification(self.db, uid, kind, title, message,
                link=link, actor_id=self.actor_id,
                dedupe_key=f"calendar:{self.scope.id}:{source_id}:{kind}:{self.command_request_id}")
            notified.append(uid)
        return notified

    async def notify_group(self, p):
        if p.date < self.today:
            fail("Согласование общих окон нужно для текущих или будущих дат", 422)
        group = await self.one(Group, p.group_id)
        summary = await self.readiness(p.date, p.date, p.duration, locked=True)
        row = next((g["days"][0] for g in summary["groups"] if g["group_id"] == str(group.id) and g["days"]), None)
        if not row or row["status"] != "no_overlap":
            fail("Уведомление требуется, когда все участники заполнили день, но общего свободного окна нет")
        recent = await self.rows(Event, Event.action == "availability.notify", Event.occurred_at >= self.now - timedelta(minutes=15))
        if any(e.detail.get("result", {}).get("group_id") == str(group.id) and e.detail.get("result", {}).get("date") == str(p.date) for e in recent):
            fail("Участникам уже отправлена просьба. Повторная отправка доступна через 15 минут.")
        ids = [self.members[uid].user_id for uid in self.members if str(uid) in row["member_ids"]]
        notified = await self.notify_users(ids, "calendar_group_reconcile_requested", "Согласуйте общие окна группы",
            f"{group.label} ({group.code}), {p.date}: общего свободного окна на {p.duration} мин нет. {p.reason}", p.date, group.id, duration=p.duration)
        return {"group_id": group.id, "date": p.date, "duration": p.duration, "notified_user_ids": notified, "sent_at": self.now}

    async def control_state(self, start, end):
        locks = await self.rows(DayLock, DayLock.date >= start, DayLock.date <= end)
        requests = await self.rows(ChangeRequest, ChangeRequest.date >= start, ChangeRequest.date <= end)
        if not self.members[self.actor_id].can_manage:
            requests = [r for r in requests if r.user_id == self.actor_id]
        return {"availability_locks": [value(row, LOCK_FIELDS) for row in locks],
                "change_requests": [value(row, REQUEST_FIELDS) for row in sorted(requests, key=lambda r: (r.requested_at, str(r.id)), reverse=True)]}

    async def readiness(self, start, end, duration=30, *, locked=False):
        if not MIN_DATE <= start <= MAX_DATE or not MIN_DATE <= end <= MAX_DATE:
            fail("Даты сводки должны быть в диапазоне с 2000 по 2100 год", 422)
        if not 0 <= (end - start).days <= 30 or not 30 <= duration <= 480 or duration % 30:
            fail("Выберите период до 31 дня и длительность от 30 до 480 минут с шагом 30 минут", 422)
        if not locked:
            await self.lock()
        days = [start + timedelta(days=i) for i in range((end-start).days+1) if (start+timedelta(days=i)).weekday() < 5]
        windows = await self.rows(Availability, Availability.date >= start, Availability.date <= end)
        absences = await self.rows(Absence, Absence.start_date <= end, Absence.end_date >= start, Absence.status == "active")
        locks = {(row.user_id, row.date): row for row in await self.rows(DayLock, DayLock.date >= start, DayLock.date <= end)}
        projected, projected_absences = availability_projections(windows, absences)
        active = [m for m in self.members.values() if m.active and self.users[m.user_id].is_active and self.users[m.user_id].audit_calendar_enabled]
        known, free = {}, {}
        employees = []
        for member in sorted(active, key=lambda m: self.users[m.user_id].full_name):
            values = []
            for day in days:
                uid = member.user_id
                is_absent = any(a.user_id == uid and a.start_date <= day <= a.end_date for a in absences)
                slots = {t: availability_value(projected, person_id=str(uid), day=day, start_minute=t,
                           end_minute=t+30, absences=projected_absences) for t in range(WORK_START, WORK_END, 30)}
                count = sum(v is not None for v in slots.values())
                state = "absent" if is_absent else "filled" if count == 16 else "partial" if count else "missing"
                free[(uid, day)] = {t for t, v in slots.items() if v is True}
                known[(uid, day)] = state
                row = {"date": day, "status": state, "free_minutes": len(free[(uid, day)]) * 30,
                       "locked": bool(locks.get((uid, day)) and locks[(uid, day)].locked)}
                values.append(row)
            employees.append({"user_id": member.user_id, "full_name": self.users[member.user_id].full_name,
                "code": member.code, "role": member.role, "days": values,
                "filled_days": sum(r["status"] in ("filled", "absent") for r in values), "total_days": len(days)})
        groups = await self.rows(Group, Group.archived.is_(False), Group.legacy.is_(False))
        versions = await self.rows(GroupVersion)
        plans = await self.rows(Plan, Plan.date >= start, Plan.date <= end, Plan.status != "cancelled")
        facts = await self.rows(Fact, Fact.date >= start, Fact.date <= end, Fact.outcome == "completed")
        plan_links, fact_links = await self.rows(PlanParticipant), await self.rows(FactParticipant)
        by_plan, by_fact = {}, {}
        for link in plan_links:
            by_plan.setdefault(link.plan_id, set()).add(link.user_id)
        for link in fact_links:
            by_fact.setdefault(link.fact_id, set()).add(link.user_id)
        for fact in facts:
            if fact.speaker_id:
                by_fact.setdefault(fact.id, set()).add(fact.speaker_id)
        notifications = await self.rows(Event, Event.action == "availability.notify")
        group_rows = []
        for group in groups:
            rows = []
            for day in days:
                versions_today = [v for v in versions if v.group_id == group.id and v.effective_from <= day]
                version = max(versions_today, key=lambda v: v.effective_from, default=None)
                ids = [uid for uid in (getattr(version, "auditor_id", None), getattr(version, "tech_id", None)) if uid]
                valid = len(set(ids)) == 2 and all((uid, day) in known for uid in ids)
                if valid:
                    valid = self.members[ids[0]].role == "auditor" and self.members[ids[1]].role == "tech"
                missing = [uid for uid in ids if known.get((uid, day)) not in ("filled", "absent")]
                common = set.intersection(*(free[(uid, day)] for uid in ids)) if valid else set()
                taken = set()
                for record, people in [*((p, by_plan.get(p.id, set())) for p in plans), *((f, by_fact.get(f.id, set())) for f in facts)]:
                    if record.date == day and set(ids).intersection(people):
                        taken.update(t for t in common if t < record.start+record.duration and t+30 > record.start)
                remaining = common-taken
                def starts(minutes):
                    return [{"start": t, "end": t+duration} for t in sorted(minutes)
                            if all(x in minutes for x in range(t, t+duration, 30))]
                slots = starts(remaining)
                status = ("no_composition" if not valid else "absent" if any(known[(uid, day)] == "absent" for uid in ids)
                          else "available" if slots else "booked" if starts(common)
                          else "missing" if missing else "no_overlap")
                sent = [e.occurred_at for e in notifications if e.detail.get("result", {}).get("group_id") == str(group.id)
                        and e.detail.get("result", {}).get("date") == str(day)]
                rows.append({"date": day, "member_ids": ids, "missing_user_ids": missing, "status": status,
                    "common_windows": intervals(common), "free_windows": intervals(remaining), "slots": slots,
                    "plans": [value(p, "id start duration activity status") for p in plans if p.date == day and p.group_id == group.id],
                    "last_notified_at": max(sent, default=None)})
            group_rows.append({"group_id": group.id, "code": group.code, "label": group.label, "days": rows})
        return jsonable_encoder({"scope_version": self.scope.version, "from": start, "to": end, "duration": duration,
            "working_start": WORK_START, "working_end": WORK_END, "employees": employees, "groups": group_rows})
