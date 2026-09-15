"""One-day availability and saved meeting participants, without live composition."""
from collections import defaultdict

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.models.audit_calendar import (
    AuditCalendarAvailability as Availability, AuditCalendarAbsence as Absence,
    AuditCalendarAvailabilityLock as DayLock, AuditCalendarGroup as Group,
    AuditCalendarPlan as Plan, AuditCalendarPlanParticipant as PlanParticipant,
    AuditCalendarFact as Fact, AuditCalendarFactParticipant as FactParticipant,
)
from app.services.audit_calendar_controls import LOCK_FIELDS, value
from app.services.audit_calendar_math import MIN_DATE, MAX_DATE


MAX_TIMELINE_ROWS = 20000
MAX_TIMELINE_MEMBERS = 2000


def too_large():
    raise HTTPException(422, detail={
        "code": "TIMELINE_TOO_LARGE", "message": "Слишком много данных для дневной сводки календаря",
    })


class AvailabilityTimeline:
    async def timeline_rows(self, model, *conditions):
        rows = list((await self.db.scalars(select(model)
            .where(model.scope_id == self.scope.id, *conditions)
            .limit(MAX_TIMELINE_ROWS + 1).execution_options(populate_existing=True))).all())
        if len(rows) > MAX_TIMELINE_ROWS:
            too_large()
        return rows

    async def availability_timeline(self, day):
        if not MIN_DATE <= day <= MAX_DATE:
            raise HTTPException(422, "Дата сводки должна быть в диапазоне с 2000 по 2100 год")
        await self.lock()
        if len(self.members) > MAX_TIMELINE_MEMBERS:
            too_large()

        # Booking rules retain the original plan independently of its recorded fact.
        plans = await self.timeline_rows(Plan, Plan.date == day, Plan.status != "cancelled")
        facts = await self.timeline_rows(Fact, Fact.date == day, Fact.outcome == "completed")
        if len(plans) + len(facts) > MAX_TIMELINE_ROWS:
            too_large()
        plan_people, fact_people = defaultdict(set), defaultdict(set)
        for link in await self.timeline_rows(PlanParticipant, PlanParticipant.plan_id.in_([p.id for p in plans])):
            plan_people[link.plan_id].add((link.user_id, link.role))
        for link in await self.timeline_rows(FactParticipant, FactParticipant.fact_id.in_([f.id for f in facts])):
            fact_people[link.fact_id].add((link.user_id, link.role))
        groups = {g.id: g.code for g in await self.timeline_rows(Group,
            Group.id.in_({r.group_id for r in [*plans, *facts] if r.group_id}))}
        meetings = []
        for kind, records, people in (("plan", plans, plan_people), ("fact", facts, fact_people)):
            for record in records:
                participants = people[record.id]
                if kind == "fact" and record.composition_unknown:
                    participants = set()
                elif record.speaker_id:
                    participants.add((record.speaker_id, "speaker"))
                meetings.append({
                    **value(record, "id start duration activity"), "kind": kind,
                    "status": record.status if kind == "plan" else record.outcome,
                    "group_code": groups.get(record.group_id, ""),
                    "participants": [{"user_id": uid, "role": role}
                        for uid, role in sorted(participants, key=lambda p: (str(p[0]), p[1]))],
                })
        windows = await self.timeline_rows(Availability, Availability.date == day)
        absences = await self.timeline_rows(Absence, Absence.status == "active",
            Absence.start_date <= day, Absence.end_date >= day)
        locks = await self.timeline_rows(DayLock, DayLock.date == day)
        return jsonable_encoder({
            "version": self.scope.version, "date": day,
            "members": sorted(self.member_values(), key=lambda m: (m["full_name"], m["code"], str(m["user_id"]))),
            "availability": [value(w, "user_id date start end available")
                for w in sorted(windows, key=lambda w: (str(w.user_id), w.start, w.end))],
            "absences": [value(a, "id user_id start_date end_date reason status version")
                for a in sorted(absences, key=lambda a: (str(a.user_id), a.start_date, str(a.id)))],
            "locks": [value(lock, LOCK_FIELDS) for lock in sorted(locks, key=lambda lock: str(lock.user_id))],
            "meetings": sorted(meetings, key=lambda m: (m["start"], m["kind"], str(m["id"]))),
        })
