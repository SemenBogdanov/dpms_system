"""Scoped planning coverage, not a measure of employee work performance."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.services import audit_calendar_math as math


WORK_START, WORK_END, SLOT_MINUTES = 600, 1080, 30


def workload_report(*, start, end, baseline, version, members, groups, versions,
                    norms, plans, participants, facts, windows, absences, group_id=None):
    """Pure projection of already scoped rows; no current-status history filters."""
    days = math.day_range(start, end)
    workdays = [day for day in days if day.weekday() < 5]
    selected_groups = {g.id for g in groups if group_id is None or g.id == group_id}
    members_by_id = {m["user_id"]: m for m in members}
    targets = defaultdict(Decimal)
    selected_members = set(members_by_id) if group_id is None else set()

    latest_norms = {}
    for norm in sorted(norms, key=lambda n: n.revision):
        latest_norms[(norm.group_id, norm.effective_from)] = norm
    schedule = math.TargetSchedule(baseline, tuple(
        math.TargetChange(n.effective_from, n.value, str(n.group_id) if n.group_id else None)
        for n in latest_norms.values()
    ))
    versions_by_group = defaultdict(list)
    for entry in versions:
        if entry.group_id in selected_groups and entry.effective_from <= end:
            versions_by_group[entry.group_id].append(entry)
    for gid, history in versions_by_group.items():
        history.sort(key=lambda entry: entry.effective_from)
        for index, current in enumerate(history):
            first = max(start, current.effective_from)
            last = min(end, history[index + 1].effective_from - timedelta(days=1)) if index + 1 < len(history) else end
            if first > last:
                continue
            people = {current.auditor_id, current.tech_id} - {None}
            selected_members.update(people)
            # Segment sums are equivalent to daily norms, without rescanning
            # the full revision history once per group per day under the lock.
            target = math.target_between(schedule, first, last, group_id=str(gid))
            for uid in people:
                targets[uid] += target

    by_plan = defaultdict(set)
    for participant in participants:
        by_plan[participant.plan_id].add(participant.user_id)
    cancelled = {fact.plan_id for fact in facts if fact.outcome == "cancelled"}
    member_plans = defaultdict(dict)
    for plan in plans:
        if plan.group_id not in selected_groups or not start <= plan.date <= end:
            continue
        people = by_plan[plan.id] | ({plan.speaker_id} if plan.speaker_id else set())
        selected_members.update(people)
        if plan.status != "planned" or plan.id in cancelled:
            continue
        # Membership in several groups/roles never duplicates a planned identity.
        for uid in people:
            member_plans[uid][plan.id] = plan

    by_day = defaultdict(list)
    for window in windows:
        if window.user_id in selected_members and start <= window.date <= end:
            by_day[(window.user_id, window.date)].append(math.AvailabilityWindow(
                str(window.user_id), window.date, window.start, window.end, window.available))
    absences_by_user = defaultdict(list)
    for absence in absences:
        if absence.status == "active" and absence.user_id in selected_members:
            absences_by_user[absence.user_id].append(absence)

    result = []
    for uid in sorted(selected_members & members_by_id.keys(),
                      key=lambda uid: (members_by_id[uid]["full_name"].casefold(),
                                       members_by_id[uid]["code"], str(uid))):
        row = {**members_by_id[uid], "filled_days": 0, "partial_days": 0,
               "unfilled_days": 0, "absence_days": 0, "free_slots": 0}
        for day in workdays:
            if any(a.start_date <= day <= a.end_date for a in absences_by_user[uid]):
                row["absence_days"] += 1
                continue
            # Do not pass absences to availability_value: False there would turn
            # an absence with no raw data into a fully filled day.
            slots = [math.availability_value(by_day[(uid, day)], person_id=str(uid),
                     day=day, start_minute=t, end_minute=t + SLOT_MINUTES)
                     for t in range(WORK_START, WORK_END, SLOT_MINUTES)]
            known = sum(value is not None for value in slots)
            row["filled_days" if known == len(slots) else
                "partial_days" if known else "unfilled_days"] += 1
            row["free_slots"] += sum(value is True for value in slots)
        count = len(member_plans[uid])
        minutes = sum(plan.duration for plan in member_plans[uid].values())
        work_minutes = sum(
            max(0, min(WORK_END, plan.start + plan.duration) - max(WORK_START, plan.start))
            for plan in member_plans[uid].values() if plan.date.weekday() < 5)
        free = row["free_slots"] * SLOT_MINUTES
        target = targets[uid]
        row.update(free_minutes=free, planned_meetings=count, planned_minutes=minutes,
                   planned_work_minutes=work_minutes, outside_work_minutes=minutes - work_minutes,
                   target=float(target), power_percent=work_minutes * 100 / free if free else None,
                   norm_percent=float(Decimal(count) * 100 / target) if target else None)
        result.append(row)
    return {"version": version, "period": {"from": start, "to": end, "group_id": group_id},
            "working_days": len(workdays),
            "working_window": {"start": WORK_START, "end": WORK_END, "slot_minutes": SLOT_MINUTES},
            "members": result}


class CalendarReporting:
    async def workload(self, start, end, group_id=None):
        from fastapi import HTTPException
        from fastapi.encoders import jsonable_encoder
        from app.models.audit_calendar import (
            AuditCalendarGroup as Group, AuditCalendarGroupVersion as GroupVersion,
            AuditCalendarNormRevision as Norm, AuditCalendarPlan as Plan,
            AuditCalendarPlanParticipant as Participant, AuditCalendarFact as Fact,
            AuditCalendarAvailability as Availability, AuditCalendarAbsence as Absence,
        )

        try:
            math.day_range(start, end)
        except ValueError:
            raise HTTPException(422, "Укажите включительный период от 1 до 366 дней с датами в диапазоне с 2000 по 2100 год") from None
        await self.lock()
        groups = await self.rows(Group)
        if group_id is not None and group_id not in {g.id for g in groups}:
            raise HTTPException(404, "Группа не найдена в этом контуре календаря")
        versions = await self.rows(GroupVersion, GroupVersion.effective_from <= end)
        norms = await self.rows(Norm)
        plans = await self.rows(Plan, Plan.date >= start, Plan.date <= end)
        plan_ids = [p.id for p in plans]
        participants = await self.rows(Participant, Participant.plan_id.in_(plan_ids))
        # A cancellation may be recorded outside the selected period.
        facts = await self.rows(Fact, Fact.plan_id.in_(plan_ids))
        windows = await self.rows(Availability, Availability.date >= start, Availability.date <= end)
        absences = await self.rows(Absence, Absence.start_date <= end, Absence.end_date >= start,
                                   Absence.status == "active")
        return jsonable_encoder(workload_report(
            start=start, end=end, baseline=self.scope.baseline, version=self.scope.version,
            group_id=group_id, members=self.member_values(), groups=groups, versions=versions,
            norms=norms, plans=plans, participants=participants, facts=facts,
            windows=windows, absences=absences))
