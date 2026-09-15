"""Preview, explicit mapping revisions and append-only V5 application."""
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.audit_calendar import AuditCalendarImportMapping as Mapping
from app.services.audit_calendar import (
    CalendarService, Scope, Member, Group, Plan, PlanParticipant, Fact, FactParticipant,
    Availability, Absence, Norm, Notice, ImportBatch, ImportRow, ImportApplication, DayLock,
    encoded, fail, columns,
)
from app.services.audit_calendar_domain import composition_issues, conflict_issues, issue, meeting_instant, availability_issues, availability_projections, historical_source_issues
from app.services.audit_calendar_math import AvailabilityWindow as Window, Absence as MathAbsence
from app.models.audit_calendar import AuditCalendarGroupVersion as GroupVersion
from app.services.audit_calendar_source import HISTORY_FROM, HISTORY_TO, SOURCE_ROLES, parse_source, required_people


def original_row(row):
    return row.model_dump(mode="json", by_alias=True, exclude_none=True)


class CalendarImportService(CalendarService):
    async def latest_mapping(self, batch_id):
        return await self.db.scalar(select(Mapping).where(Mapping.scope_id == self.scope.id, Mapping.batch_id == batch_id)
                                    .order_by(Mapping.revision.desc()).limit(1))

    async def inspect(self, source, mapping, *, groups=None, bootstrap_history=False, group_mapping=None):
        issues = []
        group_mapping = group_mapping or {}
        existing_norms = await self.rows(Norm)
        empty = (not await self.rows(Plan) and not await self.rows(Fact) and not await self.rows(Group)
                 and not await self.rows(Absence) and not await self.rows(Availability)
                 and len(existing_norms) == 1 and existing_norms[0].group_id is None
                 and existing_norms[0].effective_from == self.scope.baseline and existing_norms[0].value == 6)
        if bootstrap_history and not empty:
            issues.append(issue("BOOTSTRAP_NOT_EMPTY", "Первоначальный перенос истории разрешён только в пустой календарь с единственной начальной общей нормой"))
        if bootstrap_history and (not source.data.planning or source.data.planning.trackingStart != self.scope.baseline):
            issues.append(issue("BOOTSTRAP_BASELINE", "Для первоначального переноса нужны настройки планирования с той же датой начала учёта, что и в контуре"))
        required = required_people(source)
        missing = sorted(required - mapping.keys())
        if set(mapping) - required:
            issues.append(issue("MAPPING_EXTRA", "Сопоставление содержит участников, которых нет в источнике"))
        if len(set(mapping.values())) != len(mapping):
            issues.append(issue("MAPPING_COLLISION", "Разных участников источника нужно сопоставить с разными пользователями"))
        for uid in mapping.values():
            try:
                self.require_member(uid)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 422:
                    raise
                issues.append(issue("MAPPING_MEMBER", "Один из сопоставленных пользователей не имеет активного участия или допуска к календарю"))
        catalog = await self.rows(Group)
        by_code = {g.code: g for g in catalog}
        group_codes = {r.groupId for r in source.data.plans + source.data.facts if r.groupId}
        if source.data.planning:
            group_codes.update(n.groupId for n in source.data.planning.groupTargets)
        if set(group_mapping) - group_codes:
            issues.append(issue("GROUP_MAPPING_EXTRA", "Сопоставление содержит группу, которой нет в исходных встречах или нормах"))
        if group_mapping and not bootstrap_history:
            issues.append(issue("GROUP_BOOTSTRAP_REQUIRED", "Для создания сопоставленных групп явно подтвердите первоначальный перенос в пустой календарь"))
        for code, pair in group_mapping.items():
            if code == "G21":
                issues.append(issue("G21_UNKNOWN", "Состав исторической группы G21 неизвестен; назначать его по предположению нельзя"))
            for role, uid in (("auditor", pair["auditor_id"]), ("tech", pair["tech_id"])):
                member, user = self.members.get(UUID(str(uid))), self.users.get(UUID(str(uid)))
                if not member or not member.active or member.role != role or not user or not user.is_active or not user.audit_calendar_enabled:
                    issues.append(issue("GROUP_MEMBER_ROLE", f"Группа {code}: проверьте роли, активное участие и допуск к календарю у сопоставленных аудитора и техспециалиста"))
        bound = dict(groups or {})
        # Bind repeat exports to earlier accepted row attribution, not a mutable
        # group display code which may since have been renamed or reused.
        applied = {a.batch_id: a for a in await self.rows(ImportApplication)}
        incoming = {r.id: r for r in source.data.plans + source.data.facts}
        accepted_mappings = {m.id: m for m in await self.rows(Mapping)}
        by_group_id = {g.id: g for g in catalog}
        for old in await self.rows(ImportRow, ImportRow.source_id.in_(incoming)):
            if old.batch_id not in applied:
                continue
            row = incoming[old.source_id]
            if old.original != original_row(row):
                issues.append(issue("SOURCE_ID_CONFLICT", "Содержимое исходной записи отличается от ранее подтверждённой версии"))
                continue
            accepted = accepted_mappings[applied[old.batch_id].mapping_id]
            gid = accepted.summary["groups"].get(row.groupId)
            if gid:
                if row.groupId in bound and bound[row.groupId] != gid:
                    issues.append(issue("SOURCE_GROUP_CONFLICT", "Предлагаемое сопоставление изменяет группу ранее подтверждённой исходной записи"))
                bound[row.groupId] = gid
                by_code[row.groupId] = by_group_id[UUID(gid)]
        for code in sorted(group_codes):
            bound.setdefault(code, str(by_code[code].id if code in by_code else uuid4()))
        for code, uid in bound.items():
            if code in by_code and str(by_code[code].id) != uid:
                issues.append(issue("GROUP_MAPPING_CHANGED", f"Группа {code} была назначена после предварительного просмотра; обновите сопоставление"))
        for row in source.data.plans:
            original = row.sourceOriginal if row.origin == "working-revision" else row
            historic = (row.origin == "source" and row.sourceRow is not None and HISTORY_FROM <= row.date <= HISTORY_TO and row.date < self.today)
            if row.date < self.today and not historic:
                issues.append(issue("PAST_PLAN", "Прошедший новый план или рабочая редакция не дают права на историческое исключение"))
            if row.origin == "working-revision" and not (original.sourceRow is not None and HISTORY_FROM <= original.date <= HISTORY_TO):
                issues.append(issue("SOURCE_HORIZON", "Оригинал рабочей редакции находится за пределами установленного периода источника"))
            if not historic and row.speakerId and not missing:
                member = self.members.get(mapping[row.speakerId])
                if not member or member.role != "speaker":
                    issues.append(issue("MEMBER_ROLE", "Докладчик нового плана из источника должен иметь календарную роль «Докладчик», включая черновики"))
            if not historic and row.status == "planned" and not missing:
                group = by_code.get(row.groupId)
                pair = group_mapping.get(row.groupId)
                if not group and pair:
                    group = SimpleNamespace(id=UUID(bound[row.groupId]), legacy=False, archived=False)
                if not group:
                    issues.append(issue("GROUP_REQUIRED", "Перед импортом будущих планов создайте соответствующую современную группу"))
                else:
                    version = SimpleNamespace(auditor_id=UUID(pair["auditor_id"]), tech_id=UUID(pair["tech_id"])) if pair else await self.group_version(group.id, row.date)
                    errors, _ = composition_issues(group, version, self.members, self.users, row.activity, mapping.get(row.speakerId))
                    issues.extend(issue(e["code"], f"План из источника: {e['message']}") for e in errors)
        for row in source.data.facts:
            if meeting_instant(row.date, row.start + (row.duration if row.outcome == "completed" else 0)) > self.now:
                issues.append(issue("FACT_FUTURE", "Время исходного факта ещё не наступило или проведённая встреча ещё не закончилась"))
            historical = row.origin in ("source", "historical-entry")
            if historical and row.planId:
                source_plan = next(p for p in source.data.plans if p.id == row.planId)
                issues.extend(historical_source_issues(original_row(source_plan), row.date, self.today,
                                                       actual_group_code=row.groupId))
            if historical and not (HISTORY_FROM <= row.date <= HISTORY_TO and row.date < self.today):
                issues.append(issue("SOURCE_HORIZON", "Историческое исключение ограничено периодом с 28.08.2026 по 11.09.2026 и датами раньше сегодня"))
            if not row.planId and not (row.origin == "source" and row.sourceRow is not None and historical):
                issues.append(issue("STANDALONE_SOURCE", "Для факта без связанного плана нужна оригинальная строка в установленном историческом периоде"))
            if row.origin == "historical-entry" and (not row.sourceEvidence.strip() or not row.reason.strip() or not row.planId):
                issues.append(issue("HISTORICAL_EVIDENCE", "Для восстановления истории нужны основание, подтверждающий документ и связанный исходный план"))
            if not historical and not missing:
                group = by_code.get(row.groupId)
                pair = group_mapping.get(row.groupId)
                if not group and pair:
                    group = SimpleNamespace(id=UUID(bound[row.groupId]), legacy=False, archived=False)
                if not group:
                    issues.append(issue("GROUP_REQUIRED", "Не найдена современная группа для исходного факта"))
                else:
                    version = SimpleNamespace(auditor_id=UUID(pair["auditor_id"]), tech_id=UUID(pair["tech_id"])) if pair else await self.group_version(group.id, row.date)
                    errors, people = composition_issues(group, version, self.members, self.users, row.activity, mapping.get(row.speakerId))
                    supplied = {(mapping.get(p.id), SOURCE_ROLES[p.role]) for p in row.participantSnapshot}
                    if row.outcome == "completed" and (errors or supplied != set(people) or row.auditorAbsentMinutes > 5):
                        issues.append(issue("FACT_COMPOSITION", "Современный факт не прошёл проверку состава А+Т, докладчика или присутствия аудитора"))
        if source.data.planning:
            planning = source.data.planning
            if planning.trackingStart != self.scope.baseline:
                issues.append(issue("BASELINE_CONFLICT", "Дата начала учёта в источнике отличается от настроенной даты контура"))
            latest = {}
            for n in sorted(await self.rows(Norm), key=lambda n: n.revision):
                latest[(str(n.group_id) if n.group_id else None, n.effective_from)] = n.value
            for n in planning.dailyTargets + planning.groupTargets:
                gid = bound.get(n.groupId) if n.groupId else None
                existing = latest.get((gid, n.from_))
                if existing is not None and existing != n.value:
                    issues.append(issue("NORM_CONFLICT", "Норма из источника отличается от уже сохранённой нормы на ту же дату"))
                elif existing is None and n.from_ < self.today and not (bootstrap_history and empty):
                    issues.append(issue("NORM_HISTORY", "Импорт не может добавить отсутствующую историческую норму в уже действующее расписание"))
                if n.groupId and (n.groupId == "G21" or (n.groupId not in group_mapping and
                    (n.groupId not in by_code or by_code[n.groupId].legacy or by_code[n.groupId].archived))):
                    issues.append(issue("NORM_GROUP", f"Группа {n.groupId}: новую норму можно задать только для действующей современной группы"))
        # Validate future plans against the complete proposed availability and
        # absence set, before insertion. The same path is used again at apply.
        if not missing:
            windows, absences = availability_projections(await self.rows(Availability), await self.rows(Absence))
            locked_days = await self.rows(DayLock, DayLock.locked.is_(True))
            for w in source.data.availability:
                uid = str(mapping[w.personId])
                if any(str(l.user_id) == uid and l.date == w.date for l in locked_days):
                    issues.append(issue("AVAILABILITY_LOCKED", "Импорт затрагивает закрытую доступность; сначала согласуйте заявку на этот день"))
                overlapping = [old for old in windows if old.person_id == uid and old.day == w.date
                               and old.start_minute < w.end and old.end_minute > w.start]
                new = Window(uid, w.date, w.start, w.end, w.available)
                if overlapping and overlapping != [new]:
                    issues.append(issue("AVAILABILITY_CONFLICT", "Доступность из источника пересекается с сохранёнными или другими входящими интервалами"))
                if new not in windows:
                    windows.append(new)
            if source.data.planning:
                for a in source.data.planning.absences:
                    if any(l.user_id == mapping[a.personId] and a.from_ <= l.date <= a.to for l in locked_days):
                        issues.append(issue("AVAILABILITY_LOCKED", "Отсутствие из импорта затрагивает закрытый день"))
                    new = MathAbsence(str(mapping[a.personId]), a.from_, a.to)
                    if any(old.person_id == new.person_id and old.start <= new.end and old.end >= new.start and old != new for old in absences):
                        issues.append(issue("ABSENCE_CONFLICT", "Отсутствие из источника пересекается с сохранённым или другим входящим периодом"))
                    if new not in absences:
                        absences.append(new)
            candidate_plans = []
            participant_map = {}
            for row in source.data.plans:
                if row.date < self.today or row.status != "planned":
                    continue
                group = by_code.get(row.groupId)
                pair = group_mapping.get(row.groupId)
                version = await self.group_version(group.id, row.date) if group else None
                participants = {UUID(str(pair[key])) for key in ("auditor_id", "tech_id")} if pair else {
                    uid for uid in (getattr(version, "auditor_id", None), getattr(version, "tech_id", None)) if uid}
                if row.speakerId:
                    participants.add(mapping[row.speakerId])
                errors, _ = availability_issues(row.date, row.start, row.duration, participants, windows, absences)
                issues.extend(issue(e["code"], f"План из источника: {e['message']}") for e in errors)
                participant_map[row.id] = participants
                candidate_plans.append(row)
            for row in candidate_plans:
                issues.extend(conflict_issues(row, participant_map[row.id], candidate_plans, participant_map))
        return {"plans": len(source.data.plans), "facts": len(source.data.facts), "availability": len(source.data.availability),
                "absences": len(source.data.planning.absences) if source.data.planning else 0,
                "planning_present": source.data.planning is not None, "groups": bound,
                "bootstrap_history": bootstrap_history, "group_compositions": group_mapping,
                "new_legacy_groups": sorted(code for code in group_codes if code not in by_code and code not in group_mapping),
                "horizon_from": HISTORY_FROM.isoformat(), "horizon_to": HISTORY_TO.isoformat(),
                "issues": issues, "mapping_required": missing}

    async def preview(self, body):
        # All JSON/Pydantic parsing is completed before taking any scope lock.
        try:
            source, digest = parse_source(body.source)
        except ValueError as exc:
            fail(422, "Не удалось проверить JSON конструктора V5: проверьте формат файла, обязательные поля, ссылки, даты и размер до 8 МиБ")
        await self.lock(helper=True, write=True)
        prior, replay_digest = await self.replay("imports.preview", body)
        if prior:
            return prior
        self.editable("imports.preview")
        batches = await self.rows(ImportBatch, ImportBatch.source_sha256 == digest)
        batch = batches[0] if batches else None
        previous = await self.latest_mapping(batch.id) if batch else None
        if batch and await self.rows(ImportApplication, ImportApplication.batch_id == batch.id):
            result = await self.batch_value(batch)
            return await self.finish("imports.preview", body, replay_digest, result,
                                     {"batch_id": batch.id, "source_sha256": digest}, raw=True)
        summary = await self.inspect(source, body.mapping, groups=previous.summary["groups"] if previous else None,
            bootstrap_history=body.bootstrap_history,
            group_mapping={code: pair.model_dump(mode="json") for code, pair in body.group_mapping.items()})
        if batch is None:
            batch = ImportBatch(id=uuid4(), scope_id=self.scope.id, source_sha256=digest, original=body.source,
                horizon_from=HISTORY_FROM, horizon_to=HISTORY_TO, created_by_id=self.actor_id)
            self.db.add(batch)
            await self.db.flush()
            for row in source.data.plans + source.data.facts:
                self.db.add(ImportRow(scope_id=self.scope.id, batch_id=batch.id,
                                       source_id=row.id, kind=row.kind, original=original_row(row)))
            await self.db.flush()
        revision = Mapping(id=uuid4(), scope_id=self.scope.id, batch_id=batch.id,
            revision=previous.revision + 1 if previous else 1, mapping={k: str(v) for k, v in body.mapping.items()},
            summary=summary, created_by_id=self.actor_id)
        self.db.add(revision)
        await self.db.flush()
        return await self.finish("imports.preview", body, replay_digest, await self.batch_value(batch),
            {"batch_id": batch.id, "mapping_revision": revision.revision, "source_sha256": digest}, raw=True)

    async def batch_value(self, batch):
        mapping = await self.latest_mapping(batch.id)
        applied = bool(await self.rows(ImportApplication, ImportApplication.batch_id == batch.id))
        summary = mapping.summary if mapping else {}
        return {"id": batch.id, "version": self.scope.version,
                "status": "applied" if applied else "blocked" if summary.get("issues") or summary.get("mapping_required") else "ready",
                "summary": summary, "issues": summary.get("issues", []), "mapping_required": summary.get("mapping_required", []),
                "rows": [{"id": r.id, "source_id": r.source_id, "kind": r.kind,
                          "date": r.original.get("date"), "group": r.original.get("groupId")} for r in await self.rows(ImportRow, ImportRow.batch_id == batch.id)],
                "source_sha256": batch.source_sha256}

    async def imports(self):
        await self.lock(helper=True)
        return encoded([await self.batch_value(b) for b in await self.rows(ImportBatch)])

    async def apply(self, batch_id, body):
        # Authorized preflight read obtains immutable input without holding the
        # serialization lock during parsing. Permission is checked again below.
        self.scope = await self.db.scalar(select(Scope).where(Scope.singleton == 1))
        if not self.scope:
            fail(404, "Контур календаря ещё не настроен")
        self.members = {m.user_id: m for m in await self.rows(Member)}
        self.users = await self.load_users([self.actor_id, *self.members])
        self.actor = self.users.get(self.actor_id)
        self.authorize(helper=True)
        batch = await self.one(ImportBatch, batch_id)
        source, source_digest = parse_source(batch.original)
        await self.lock(helper=True, write=True)
        prior, digest = await self.replay(f"imports.apply:{batch_id}", body)
        if prior:
            return prior
        self.editable("imports.apply")
        batch = await self.one(ImportBatch, batch_id)
        if batch.source_sha256 != source_digest:
            fail(409, "Контрольная сумма источника не совпадает с сохранённой; применение остановлено")
        existing_application = await self.rows(ImportApplication, ImportApplication.batch_id == batch.id)
        if existing_application:
            return await self.finish(f"imports.apply:{batch_id}", body, digest, {"id": batch.id, "status": "applied", "already_applied": True})
        revision = await self.latest_mapping(batch.id)
        if not revision:
            fail(409, "Сначала выполните предварительный просмотр и сопоставление участников")
        mapping = {k: UUID(v) for k, v in revision.mapping.items()}
        summary = await self.inspect(source, mapping, groups=revision.summary["groups"],
            bootstrap_history=revision.summary.get("bootstrap_history", False),
            group_mapping=revision.summary.get("group_compositions", {}))
        if summary["issues"] or summary["mapping_required"]:
            fail(409, {"code": "IMPORT_CONFLICT", "issues": summary["issues"], "mapping_required": summary["mapping_required"]})
        groups = {code: UUID(value) for code, value in summary["groups"].items()}
        existing_groups = {g.id for g in await self.rows(Group)}
        for code, gid in groups.items():
            if gid not in existing_groups:
                pair = summary["group_compositions"].get(code)
                self.db.add(Group(id=gid, scope_id=self.scope.id, code=code, label=code,
                                  legacy=not bool(pair), archived=False))
        await self.db.flush()
        for code, pair in summary["group_compositions"].items():
            self.db.add(GroupVersion(scope_id=self.scope.id, group_id=groups[code], effective_from=self.scope.baseline,
                auditor_id=UUID(pair["auditor_id"]), tech_id=UUID(pair["tech_id"]), reason=body.reason))
        await self.db.flush()
        # Acceptance is in the same transaction as every append. The DB norm
        # guard requires this immutable, source-bound bootstrap attestation.
        self.db.add(ImportApplication(scope_id=self.scope.id, batch_id=batch.id, mapping_id=revision.id,
                                     reason=body.reason, applied_by_id=self.actor_id))
        await self.db.flush()
        source_rows = {r.source_id: r for r in await self.rows(ImportRow, ImportRow.batch_id == batch.id)}
        # Across different export hashes the original identity is never fuzzy
        # matched or overwritten. Exact originals reuse their applied records.
        applied_batches = {a.batch_id for a in await self.rows(ImportApplication) if a.batch_id != batch.id}
        prior_rows = {}
        for r in await self.rows(ImportRow):
            if r.batch_id in applied_batches:
                prior_rows.setdefault(r.source_id, []).append(r)
        reused = {}
        for sid, row in source_rows.items():
            previous = prior_rows.get(sid, [])
            if previous:
                if any(r.kind != row.kind or r.original != row.original for r in previous):
                    fail(409, {"code": "SOURCE_ID_CONFLICT", "source_id": sid})
                reused[sid] = previous[0]
        plans = {}
        for row in source.data.plans:
            if row.id in reused:
                matches = await self.rows(Plan, Plan.source_id == reused[row.id].id)
                if not matches:
                    fail(409, "Ранее перенесённый исходный план недоступен")
                plans[row.id] = matches[0]
                continue
            group = await self.one(Group, groups[row.groupId])
            historical = row.origin == "source" and row.date < self.today
            version = None if historical else await self.group_version(group.id, row.date)
            people = [] if historical else [(uid, role) for uid, role in (
                (getattr(version, "auditor_id", None), "auditor"), (getattr(version, "tech_id", None), "tech")) if uid]
            if row.speakerId:
                people.append((mapping[row.speakerId], "speaker"))
            plan = Plan(id=uuid4(), scope_id=self.scope.id, date=row.date, start=row.start, duration=row.duration,
                group_id=group.id, group_version_id=version.id if version else None, activity=row.activity,
                speaker_id=mapping.get(row.speakerId), status=row.status, version=1,
                origin="source" if historical else "working-revision", source_id=source_rows[row.id].id)
            if not historical and row.status == "planned":
                errors, _, _ = await self.diagnostics(plan, group, version)
                if errors:
                    fail(409, {"code": "IMPORT_PLAN_CONFLICT", "source_id": row.id, "issues": errors})
            self.db.add(plan)
            await self.db.flush()
            for uid, role in people:
                self.db.add(PlanParticipant(scope_id=self.scope.id, plan_id=plan.id, user_id=uid, role=role))
            await self.db.flush()
            plans[row.id] = plan
        for row in source.data.facts:
            if row.id in reused:
                continue
            if row.planId and row.planId in reused:
                plan = plans[row.planId]
                original = next(p for p in source.data.plans if p.id == row.planId)
                if (plan.date, plan.start, plan.duration, plan.group_id, plan.activity, plan.speaker_id, plan.status) != (
                    original.date, original.start, original.duration, groups[original.groupId], original.activity,
                    mapping.get(original.speakerId), original.status):
                    fail(409, "Факт из источника нельзя связать с планом, чья рабочая редакция была отдельно изменена")
            people = [(mapping[p.id], SOURCE_ROLES[p.role]) for p in row.participantSnapshot]
            # Source G21 snapshots may contain only a speaker. Do not invent A+T.
            unknown = row.compositionUnknown or not any(role in ("auditor", "tech") for _, role in people)
            if unknown:
                people = []
            speaker = mapping.get(row.speakerId)
            participants = {uid for uid, _ in people} | ({speaker} if speaker else set())
            links = await self.rows(FactParticipant)
            by_fact = {}
            for link in links:
                by_fact.setdefault(link.fact_id, set()).add(link.user_id)
            records = await self.rows(Fact, Fact.date == row.date)
            for fact in records:
                if fact.speaker_id:
                    by_fact.setdefault(fact.id, set()).add(fact.speaker_id)
            if row.outcome == "completed":
                errors = conflict_issues(row, participants, records, by_fact, facts=True)
                if errors:
                    fail(409, {"code": "IMPORT_FACT_CONFLICT", "issues": errors})
            p = SimpleNamespace(date=row.date, start=row.start, duration=row.duration, activity=row.activity,
                speaker_id=speaker, outcome=row.outcome, reason=row.reason or body.reason,
                evidence=row.sourceEvidence or f"Подтверждённый импорт; исходная запись сохранена. SHA-256 источника: {source_digest}",
                auditor_absent_minutes=row.auditorAbsentMinutes)
            if row.origin == "historical-entry":
                p.source_row_id = source_rows[row.planId].id
                p.composition_unknown = row.compositionUnknown
                p.participants = [SimpleNamespace(user_id=mapping[entry.id], role=SOURCE_ROLES[entry.role])
                                  for entry in row.participantSnapshot]
                p.reason, p.evidence = row.reason, row.sourceEvidence
                _, historical_plan, historical_group, actual_people = await self.historical_context(p, actual_group_code=row.groupId)
                await self.make_fact(p, historical_plan, historical_group.id if historical_group else None, actual_people,
                    origin="historical-entry", source_row_id=source_rows[row.id].id, unknown=p.composition_unknown)
                continue
            await self.make_fact(p, plans.get(row.planId), groups.get(row.groupId), people,
                origin="source" if row.origin == "source" else "historical-entry" if row.origin == "historical-entry" else "import",
                source_row_id=source_rows[row.id].id, unknown=unknown)
        for row in source.data.availability:
            uid = mapping[row.personId]
            overlaps = await self.rows(Availability, Availability.user_id == uid, Availability.date == row.date,
                                      Availability.start < row.end, Availability.end > row.start)
            if overlaps:
                if len(overlaps) == 1 and (overlaps[0].start, overlaps[0].end, overlaps[0].available) == (row.start, row.end, row.available):
                    continue
                fail(409, "Доступность из источника пересекается с сохранёнными интервалами; замена не разрешена")
            self.db.add(Availability(scope_id=self.scope.id, user_id=uid, date=row.date,
                                     start=row.start, end=row.end, available=row.available))
            await self.db.flush()
        if source.data.planning:
            planning = source.data.planning
            norms = await self.rows(Norm)
            for row in planning.dailyTargets + planning.groupTargets:
                gid = groups.get(row.groupId) if row.groupId else None
                if not any(n.group_id == gid and n.effective_from == row.from_ for n in norms):
                    await self.append_norm(gid, row.from_, row.value, body.reason)
            for row in planning.absences:
                uid = mapping[row.personId]
                overlaps = await self.rows(Absence, Absence.user_id == uid, Absence.status == "active",
                                          Absence.start_date <= row.to, Absence.end_date >= row.from_)
                if overlaps:
                    if len(overlaps) == 1 and (overlaps[0].start_date, overlaps[0].end_date, overlaps[0].reason) == (row.from_, row.to, row.reason):
                        continue
                    fail(409, "Отсутствие из источника пересекается с сохранённой историей")
                self.db.add(Absence(scope_id=self.scope.id, user_id=uid, start_date=row.from_, end_date=row.to,
                                    reason=row.reason, status="active", version=1))
                await self.db.flush()
        for row in source.data.notifications:
            if row.reportedAt > self.now:
                fail(422, "Время сообщения об отсутствии в источнике находится в будущем")
            plan, uid = plans[row.meetingId], mapping[row.personId]
            if not await self.rows(PlanParticipant, PlanParticipant.plan_id == plan.id, PlanParticipant.user_id == uid):
                fail(422, "Автор сообщения об отсутствии из источника не участвует в связанном плане")
            if not await self.rows(Notice, Notice.plan_id == plan.id, Notice.user_id == uid, Notice.reported_at == row.reportedAt):
                self.db.add(Notice(scope_id=self.scope.id, plan_id=plan.id, user_id=uid,
                                   reported_at=row.reportedAt, reason=row.reason or body.reason))
        return await self.finish(f"imports.apply:{batch_id}", body, digest,
            {"id": batch.id, "status": "applied", "summary": summary},
            {"batch_id": batch.id, "mapping_revision": revision.revision, "source_sha256": source_digest, "reason": body.reason})
