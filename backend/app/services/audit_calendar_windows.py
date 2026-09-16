"""Bounded meeting-window search using the same domain rules as plan.save."""
import asyncio
from collections import defaultdict
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.models.audit_calendar import (
    AuditCalendarGroup as Group, AuditCalendarGroupVersion as GroupVersion,
    AuditCalendarPlan as Plan, AuditCalendarPlanParticipant as PlanParticipant,
    AuditCalendarFact as Fact, AuditCalendarFactParticipant as FactParticipant,
    AuditCalendarAvailability as Availability, AuditCalendarAbsence as Absence,
)
from app.services import audit_calendar_math as math
from app.services.audit_calendar_domain import (
    availability_issues, availability_projections, composition_issues,
    conflict_issues, meeting_instant,
)


MAX_VARIANTS = 2000
MAX_PERSON_INTERVALS = 50000
MAX_VARIANT_INTERVALS = 250000
MAX_CONTEXT_ROWS = 20000


def too_broad():
    raise HTTPException(422, "Подбор слишком широкий; сократите период или выберите группу и докладчика")


def validate_period(first, last, duration):
    if not math.MIN_DATE <= first <= last <= math.MAX_DATE or (last - first).days >= 31:
        raise HTTPException(422, "Для подбора доступных окон выберите период от 1 до 31 дня")
    if not 30 <= duration <= 480 or duration % 30:
        raise HTTPException(422, "Длительность подбора: от 30 до 480 минут, с шагом 30 минут")


class WindowContext:
    def __init__(self, service, groups, versions, speakers, plans, plan_people, facts, fact_people, windows, absences):
        self.service, self.groups, self.speakers = service, groups, speakers
        self.versions = defaultdict(list)
        for version in sorted(versions, key=lambda row: (row.effective_from, str(row.id))):
            self.versions[version.group_id].append(version)
        self.windows, self.absences = defaultdict(list), defaultdict(list)
        projected_windows, projected_absences = availability_projections(windows, absences)
        for window in projected_windows:
            self.windows[(window.person_id, window.day)].append(window)
        for absence in projected_absences:
            self.absences[absence.person_id].append(absence)
        self.plan_people, self.fact_people = plan_people, fact_people
        self.plans, self.facts = defaultdict(list), defaultdict(list)
        for records, members, target in ((plans, plan_people, self.plans), (facts, fact_people, self.facts)):
            for record in records:
                for uid in members.get(record.id, ()):
                    target[(uid, record.date)].append(record)

    def variants(self, day):
        result = []
        if self.service.scope.archived:
            return result
        for group in self.groups:
            versions = [v for v in self.versions.get(group.id, ()) if v.effective_from <= day]
            version = versions[-1] if versions else None
            for speaker in self.speakers:
                errors, people = composition_issues(group, version, self.service.members,
                    self.service.users, "Подбор встречи", speaker)
                if not errors:
                    result.append((group, version, speaker, tuple(uid for uid, _ in people)))
        return result

    def person(self, day, start, duration, uid):
        errors, warnings = availability_issues(day, start, duration, [uid],
            self.windows.get((str(uid), day), ()), self.absences.get(str(uid), ()))
        candidate = SimpleNamespace(id=None, date=day, start=start, duration=duration)
        errors += conflict_issues(candidate, [uid], self.plans.get((uid, day), ()), self.plan_people)
        errors += conflict_issues(candidate, [uid], self.facts.get((uid, day), ()), self.fact_people, facts=True)
        return errors, warnings


class MeetingWindowSearch:
    async def bounded_window_rows(self, model, *conditions):
        rows = list((await self.db.scalars(select(model).where(model.scope_id == self.scope.id, *conditions)
            .limit(MAX_CONTEXT_ROWS + 1).execution_options(populate_existing=True))).all())
        if len(rows) > MAX_CONTEXT_ROWS:
            too_broad()
        return rows

    async def window_context(self, first, last, group_id, speaker_id, *, starts_per_day=1):
        await self.lock()
        groups = [await self.one(Group, group_id)] if group_id else await self.bounded_window_rows(Group)
        if speaker_id:
            self.require_member(speaker_id, "speaker")
        speakers = [speaker_id] if speaker_id else [uid for uid, member in self.members.items()
            if member.active and member.role == "speaker" and self.users[uid].is_active
            and self.users[uid].audit_calendar_enabled]
        groups = sorted((g for g in groups if not g.archived and not g.legacy), key=lambda g: (g.code, str(g.id)))
        speakers.sort(key=lambda uid: (self.members[uid].code, str(uid)))
        if len(groups) * len(speakers) > MAX_VARIANTS:
            raise HTTPException(422, "Слишком много вариантов подбора; выберите конкретную группу или докладчика")
        if len(groups) > MAX_VARIANTS:
            too_broad()
        versions = await self.bounded_window_rows(GroupVersion, GroupVersion.group_id.in_([g.id for g in groups]), GroupVersion.effective_from <= last)
        # Bound CPU before loading the period. Include only revisions effective in it.
        versions_by_group = defaultdict(list)
        for version in versions:
            versions_by_group[version.group_id].append(version)
        people = set(speakers)
        for group_versions in versions_by_group.values():
            prior = max((v for v in group_versions if v.effective_from <= first), key=lambda v: v.effective_from, default=None)
            for version in ([prior] if prior else []) + [v for v in group_versions if first < v.effective_from <= last]:
                people.update(uid for uid in (version.auditor_id, version.tech_id) if uid)
        intervals = ((last - first).days + 1) * starts_per_day
        if len(people) * intervals > MAX_PERSON_INTERVALS or len(groups) * len(speakers) * intervals > MAX_VARIANT_INTERVALS:
            too_broad()
        plan_conditions = (Plan.date >= first, Plan.date <= last, Plan.status != "cancelled")
        fact_conditions = (Fact.date >= first, Fact.date <= last, Fact.outcome == "completed")
        plans = await self.bounded_window_rows(Plan, *plan_conditions)
        facts = await self.bounded_window_rows(Fact, *fact_conditions)
        plan_people, fact_people = defaultdict(set), defaultdict(set)
        # Read every booking in the scope, not just the groups visible in the graph.
        plan_ids = select(Plan.id).where(Plan.scope_id == self.scope.id, *plan_conditions)
        fact_ids = select(Fact.id).where(Fact.scope_id == self.scope.id, *fact_conditions)
        for row in await self.bounded_window_rows(PlanParticipant, PlanParticipant.plan_id.in_(plan_ids)):
            plan_people[row.plan_id].add(row.user_id)
        for row in await self.bounded_window_rows(FactParticipant, FactParticipant.fact_id.in_(fact_ids)):
            fact_people[row.fact_id].add(row.user_id)
        for records, members in ((plans, plan_people), (facts, fact_people)):
            for record in records:
                if record.speaker_id:
                    members[record.id].add(record.speaker_id)
        windows = await self.bounded_window_rows(Availability, Availability.date >= first, Availability.date <= last)
        absences = await self.bounded_window_rows(Absence, Absence.start_date <= last, Absence.end_date >= first, Absence.status == "active")
        return WindowContext(self, groups, versions, speakers, plans, plan_people, facts, fact_people, windows, absences)

    async def meeting_windows(self, first, last, duration=30, *, group_id=None, speaker_id=None, full_day=False):
        validate_period(first, last, duration)
        context = await self.window_context(first, last, group_id, speaker_id, starts_per_day=48 if full_day else 16)
        cells = []
        begin, end = (0, 1440) if full_day else (600, 1080)
        day = first
        while day <= last:
            variants = context.variants(day)
            people = {uid for _, _, _, participants in variants for uid in participants}
            for start in range(begin, end, 30):
                confirmed, uncertain = 0, 0
                past = meeting_instant(day, start) < self.now
                if start + duration <= end:
                    # Evaluate each person once per interval; shared groups reuse the verdict.
                    statuses = {uid: context.person(day, start, duration, uid) for uid in people}
                    for _, _, _, participants in variants:
                        if any(statuses[uid][0] for uid in participants):
                            continue
                        if any(statuses[uid][1] for uid in participants):
                            uncertain += 1
                        else:
                            confirmed += 1
                if past:
                    status = "expired" if confirmed else "unavailable"
                    if not confirmed:
                        uncertain = 0
                else:
                    status = "available" if confirmed else "warning" if uncertain else "unavailable"
                cells.append({"date": day, "start": start,
                    "status": status,
                    "confirmed": confirmed, "uncertain": uncertain})
                if (start - begin) % 240 == 210:
                    await asyncio.sleep(0)
            day += timedelta(days=1)
            await asyncio.sleep(0)
        return jsonable_encoder({"version": self.scope.version, "now": self.now,
            "period": {"from": first, "to": last, "duration": duration, "group_id": group_id,
                       "speaker_id": speaker_id, "full_day": full_day}, "cells": cells})

    async def meeting_window_options(self, day, start, duration=30, *, group_id=None, speaker_id=None):
        validate_period(day, day, duration)
        if not 0 <= start <= 1410 or start % 30 or start + duration > 1440:
            raise HTTPException(422, "Окно встречи должно целиком находиться в пределах одного дня")
        context = await self.window_context(day, day, group_id, speaker_id)
        options, statuses = [], {}
        if meeting_instant(day, start) >= self.now:
            for group, version, speaker, participants in context.variants(day):
                for uid in participants:
                    if uid not in statuses:
                        statuses[uid] = context.person(day, start, duration, uid)
                if any(statuses[uid][0] for uid in participants):
                    continue
                warnings = [warning for uid in participants for warning in statuses[uid][1]]
                options.append({"group_id": group.id, "group_version_id": version.id,
                    "auditor_id": version.auditor_id, "tech_id": version.tech_id, "speaker_id": speaker,
                    "status": "warning" if warnings else "available", "warnings": self.label_issues(warnings)})
        options.sort(key=lambda option: option["status"] != "available")
        return jsonable_encoder({"version": self.scope.version, "now": self.now,
            "query": {"date": day, "start": start, "duration": duration, "group_id": group_id, "speaker_id": speaker_id},
            "options": options})
