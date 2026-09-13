"""Bounded V5 export parser, deliberately free of DB, clock and external I/O."""
import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from app.schemas.audit_calendar import Count, Day, Minute, Reason, StrictModel, Text


HISTORY_FROM = date(2026, 8, 28)
HISTORY_TO = date(2026, 9, 11)
SourceID = Annotated[str, StringConstraints(min_length=1, max_length=160)]
SourceText = Annotated[str, StringConstraints(max_length=120)]
SOURCE_ROLES = {"А": "auditor", "Т": "tech", "Л": "speaker", "auditor": "auditor", "tech": "tech", "speaker": "speaker", "observer": "observer"}


class SourcePerson(StrictModel):
    id: SourceID
    name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    role: Literal["А", "Т", "Л", "auditor", "tech", "speaker", "observer"]


class SourceSlot(StrictModel):
    date: Day
    start: Minute
    duration: Annotated[StrictInt, Field(ge=30, le=1440, multiple_of=30)]
    groupId: SourceText
    activity: SourceText
    speakerId: SourceText

    @model_validator(mode="after")
    def interval(self):
        if self.start + self.duration > 1440:
            raise ValueError("Встреча переходит через полночь")
        return self


class SourceOriginal(SourceSlot):
    id: SourceID
    kind: Literal["plan", "fact"]
    sourceRow: Annotated[StrictInt, Field(ge=2, le=38)] | None = None


class PlannedSnapshot(SourceSlot):
    status: Literal["draft", "planned", "cancelled"]


class SourceMeeting(SourceOriginal):
    status: Literal["draft", "planned", "cancelled"] | None = None
    origin: Annotated[str, StringConstraints(max_length=40)] = "native"
    sourceId: SourceID | None = None
    sourceOriginal: SourceOriginal | None = None
    planId: SourceID | None = None
    outcome: Literal["completed", "cancelled"] | None = None
    reason: Text = ""
    admin: Text = ""
    auditorAbsentMinutes: Annotated[StrictInt, Field(ge=0, le=1440)] = 0
    participantIds: Annotated[list[SourceID], Field(max_length=30)] = Field(default_factory=list)
    participantSnapshot: Annotated[list[SourcePerson], Field(max_length=30)] = Field(default_factory=list)
    plannedSnapshot: PlannedSnapshot | None = None
    recordedAt: datetime | None = None
    groupLabel: Text = ""
    legacy: StrictBool = False
    compositionUnknown: StrictBool = False
    sourceEvidence: Text = ""
    sourceReference: Text = ""
    sourceMapping: dict | None = None
    helperId: Text = ""


class SourceAvailability(StrictModel):
    id: SourceID | None = None
    personId: SourceID
    date: Day
    start: Minute
    end: Minute
    available: StrictBool

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("Некорректный интервал доступности: конец должен быть позже начала")
        return self


class SourceNotice(StrictModel):
    id: SourceID | None = None
    meetingId: SourceID
    personId: SourceID
    reportedAt: datetime
    reason: Text = ""

    @model_validator(mode="after")
    def aware(self):
        if self.reportedAt.utcoffset() is None:
            raise ValueError("Время сообщения должно содержать часовой пояс")
        return self


class SourceNorm(StrictModel):
    from_: Day = Field(alias="from")
    value: Count
    groupId: SourceID | None = None


class SourceAbsence(StrictModel):
    id: SourceID
    personId: SourceID
    from_: Day = Field(alias="from")
    to: Day
    reason: Reason

    @model_validator(mode="after")
    def period(self):
        if not 0 <= (self.to - self.from_).days < 366:
            raise ValueError("Отсутствие должно длиться от 1 до 366 дней")
        return self


class SourcePlanning(StrictModel):
    trackingStart: Day
    dailyTargets: Annotated[list[SourceNorm], Field(min_length=1, max_length=1024)]
    groupTargets: Annotated[list[SourceNorm], Field(max_length=10000)]
    absences: Annotated[list[SourceAbsence], Field(max_length=5000)]

    @model_validator(mode="after")
    def identities(self):
        identities = set()
        for n in self.dailyTargets + self.groupTargets:
            key = (n.groupId, n.from_)
            if key in identities or n.from_ < self.trackingStart:
                raise ValueError("Норма повторяется или действует раньше начала учёта")
            identities.add(key)
        if any(n.groupId for n in self.dailyTargets) or any(not n.groupId for n in self.groupTargets):
            raise ValueError("Некорректно указана область действия нормы: команда или группа")
        if (None, self.trackingStart) not in identities:
            raise ValueError("Укажите начальную общую норму с даты начала учёта")
        ids = [a.id for a in self.absences]
        if len(set(ids)) != len(ids):
            raise ValueError("В источнике повторяется идентификатор отсутствия")
        by_person = {}
        for a in self.absences:
            by_person.setdefault(a.personId, []).append(a)
        for periods in by_person.values():
            ordered = sorted(periods, key=lambda a: a.from_)
            if any(a.to >= b.from_ for a, b in zip(ordered, ordered[1:])):
                raise ValueError("В источнике пересекаются периоды отсутствия одного участника")
        return self


class SourceDecision(StrictModel):
    checked: Annotated[list[Annotated[StrictInt, Field(ge=0, le=5)]], Field(max_length=6)]
    participants: Text
    comment: Text
    result: Literal["pilot", "approved", "revise"]
    recorded: datetime | None = None


class SourceLog(StrictModel):
    id: SourceID
    at: datetime
    action: Text
    details: str | dict | list | None = None


class SourceData(StrictModel):
    version: Literal[1]
    plans: Annotated[list[SourceMeeting], Field(max_length=10000)]
    facts: Annotated[list[SourceMeeting], Field(max_length=10000)]
    availability: Annotated[list[SourceAvailability], Field(max_length=100000)]
    notifications: Annotated[list[SourceNotice], Field(max_length=10000)]
    log: Annotated[list[SourceLog], Field(max_length=20000)]
    decision: SourceDecision
    planning: SourcePlanning | None = None

    @model_validator(mode="after")
    def references(self):
        plans = {p.id: p for p in self.plans}
        all_ids = [r.id for r in self.plans + self.facts]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("В источнике повторяется идентификатор встречи")
        if any(p.kind != "plan" or p.status is None or p.outcome is not None or not p.groupId for p in self.plans):
            raise ValueError("Некорректная запись плана в источнике")
        seen_links = set()
        for fact in self.facts:
            if fact.kind != "fact" or fact.outcome is None:
                raise ValueError("Некорректная запись факта в источнике")
            if fact.planId:
                if fact.planId not in plans or fact.planId in seen_links:
                    raise ValueError("Связанный план отсутствует или для него указано несколько фактов")
                seen_links.add(fact.planId)
                if fact.plannedSnapshot is None:
                    raise ValueError("Факт, связанный с планом, должен содержать снимок этого плана")
                plan = plans[fact.planId]
                for key in SourceSlot.model_fields:
                    if getattr(fact.plannedSnapshot, key) != getattr(plan, key):
                        raise ValueError("Снимок плана в источнике не соответствует связанному плану")
                if fact.plannedSnapshot.status != plan.status:
                    raise ValueError("Статус в снимке плана не соответствует статусу связанного плана")
            participants = [p.id for p in fact.participantSnapshot]
            if len(set(participants)) != len(participants):
                raise ValueError("В составе из источника повторяется участник")
            if fact.compositionUnknown and participants:
                raise ValueError("При неизвестном составе снимок участников должен быть пустым")
        if any(n.meetingId not in plans for n in self.notifications):
            raise ValueError("Сообщение об отсутствии ссылается на неизвестный план")
        for plan in self.plans:
            if plan.origin == "working-revision":
                if not plan.sourceOriginal or plan.sourceId != plan.sourceOriginal.id or plan.id != plan.sourceId:
                    raise ValueError("Рабочая редакция должна содержать собственную неизменяемую исходную запись")
        return self


class V5JSON(StrictModel):
    application: Literal["audit-meeting-constructor"]
    version: Literal[1]
    exportedAt: datetime
    source: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    data: SourceData


def parse_source(original):
    try:
        wire = json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Источник должен быть корректным JSON без нечисловых и бесконечных значений") from exc
    if len(wire) > 8 * 1024 * 1024:
        raise ValueError("Размер источника превышает 8 МиБ")
    parsed = V5JSON.model_validate(original)
    return parsed, hashlib.sha256(wire).hexdigest()


def required_people(source):
    ids = set()
    for row in source.data.plans + source.data.facts:
        ids.update(p.id for p in row.participantSnapshot)
        ids.update(row.participantIds)
        if row.speakerId:
            ids.add(row.speakerId)
    ids.update(w.personId for w in source.data.availability)
    ids.update(n.personId for n in source.data.notifications)
    if source.data.planning:
        ids.update(a.personId for a in source.data.planning.absences)
    return ids
