"""Strict calendar commands. No client-supplied actor, grant or fact snapshot."""
from datetime import date as Date, datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import AfterValidator, BeforeValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints, TypeAdapter, model_validator


def calendar_date(value: Date) -> Date:
    if not Date(2000, 1, 1) <= value <= Date(2100, 12, 31):
        raise ValueError("Дата должна быть в диапазоне с 2000 по 2100 год")
    return value


def date_input(value):
    if type(value) is Date:
        return value
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Укажите календарную дату в формате ГГГГ-ММ-ДД")
    return value


Day = Annotated[Date, BeforeValidator(date_input), AfterValidator(calendar_date)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Role = Literal["auditor", "tech", "speaker", "observer"]
Minute = Annotated[StrictInt, Field(ge=0, le=1440, multiple_of=30)]
Count = Annotated[StrictInt, Field(ge=0, le=1000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def literal_types(cls, value):
        if isinstance(value, dict):
            for key in ("confirm", "legacy"):
                if key in value and type(value[key]) is not bool:
                    raise ValueError(f"Поле {key} должно иметь логическое значение")
            if "version" in value and type(value["version"]) is not int:
                raise ValueError("Версия должна быть целым числом")
        return value


class Versioned(StrictModel):
    request_id: UUID
    expected_version: Annotated[StrictInt, Field(ge=0)]


class Setup(StrictModel):
    request_id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    baseline: Day | None = None


class MemberSave(Versioned):
    user_id: UUID
    code: Code
    role: Role
    can_manage: StrictBool
    active: StrictBool


class GroupSave(StrictModel):
    id: UUID | None = None
    code: Code
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    legacy: Literal[False] = False
    archived: StrictBool = False
    effective_from: Day
    auditor_id: UUID | None = None
    tech_id: UUID | None = None
    reason: Reason


class Meeting(StrictModel):
    date: Day
    start: Minute
    duration: Annotated[StrictInt, Field(ge=30, le=1440, multiple_of=30)]
    activity: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
    speaker_id: UUID | None

    @model_validator(mode="after")
    def interval(self):
        if self.start + self.duration > 1440:
            raise ValueError("Встреча не может переходить через полночь")
        return self


class PlanSave(Meeting):
    id: UUID | None = None
    group_id: UUID
    status: Literal["draft", "planned", "cancelled"]
    reason: Text = ""


class FactRecord(Meeting):
    plan_id: UUID
    group_id: UUID
    outcome: Literal["completed", "cancelled"]
    reason: Reason
    evidence: Reason
    auditor_absent_minutes: Annotated[StrictInt, Field(ge=0, le=1440)]


class PlanRevise(PlanSave):
    id: UUID
    reason: Reason


class Participant(StrictModel):
    user_id: UUID
    role: Role


class FactRestore(Meeting):
    source_row_id: UUID
    outcome: Literal["completed", "cancelled"]
    reason: Reason
    evidence: Reason
    composition_unknown: StrictBool
    participants: Annotated[list[Participant], Field(max_length=30)]
    confirm: Literal[True]

    @model_validator(mode="after")
    def composition(self):
        ids = [p.user_id for p in self.participants]
        if len(ids) != len(set(ids)):
            raise ValueError("Участник повторяется в историческом составе")
        if self.composition_unknown == bool(self.participants):
            raise ValueError("Укажите фактических участников или явно отметьте состав как неизвестный")
        return self


class NoticeRecord(StrictModel):
    plan_id: UUID
    user_id: UUID
    reported_at: datetime
    reason: Reason

    @model_validator(mode="after")
    def aware(self):
        if self.reported_at.utcoffset() is None:
            raise ValueError("Время сообщения должно содержать часовой пояс")
        return self


class AvailabilityPatch(StrictModel):
    date: Day
    start: Minute
    end: Minute
    value: StrictBool | None

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("Конец интервала должен быть позже его начала")
        return self


class AvailabilityPaint(StrictModel):
    user_id: UUID
    patches: Annotated[list[AvailabilityPatch], Field(min_length=1, max_length=672)]

    @model_validator(mode="after")
    def period(self):
        dates = [p.date for p in self.patches]
        if (max(dates) - min(dates)).days > 13:
            raise ValueError("За одну операцию можно изменить доступность не более чем за 14 дней")
        return self


class AbsenceAdd(StrictModel):
    user_id: UUID
    start_date: Day
    end_date: Day
    reason: Reason

    @model_validator(mode="after")
    def period(self):
        if not 0 <= (self.end_date - self.start_date).days < 366:
            raise ValueError("Отсутствие должно длиться от 1 до 366 дней")
        return self


class AbsenceEnd(StrictModel):
    id: UUID
    reason: Reason


class NormSet(StrictModel):
    group_id: UUID | None
    effective_from: Day
    value: Count
    reason: Reason


class ScopeArchive(StrictModel):
    archived: StrictBool
    reason: Reason


class GroupCommand(Versioned):
    operation: Literal["group.save"]
    payload: GroupSave


class PlanCommand(Versioned):
    operation: Literal["plan.save"]
    payload: PlanSave


class FactCommand(Versioned):
    operation: Literal["fact.record"]
    payload: FactRecord


class ReviseCommand(Versioned):
    operation: Literal["plan.revise"]
    payload: PlanRevise


class RestoreCommand(Versioned):
    operation: Literal["fact.restore"]
    payload: FactRestore


class NoticeCommand(Versioned):
    operation: Literal["notice.record"]
    payload: NoticeRecord


class AvailabilityCommand(Versioned):
    operation: Literal["availability.paint"]
    payload: AvailabilityPaint


class AbsenceCommand(Versioned):
    operation: Literal["absence.add"]
    payload: AbsenceAdd


class EndCommand(Versioned):
    operation: Literal["absence.end"]
    payload: AbsenceEnd


class NormCommand(Versioned):
    operation: Literal["norm.set"]
    payload: NormSet


class ArchiveCommand(Versioned):
    operation: Literal["scope.archive"]
    payload: ScopeArchive


Command = Annotated[Union[GroupCommand, PlanCommand, ReviseCommand, FactCommand, RestoreCommand, NoticeCommand, AvailabilityCommand, AbsenceCommand, EndCommand, NormCommand, ArchiveCommand], Field(discriminator="operation")]
command_adapter = TypeAdapter(Command)


class ImportGroupMapping(StrictModel):
    auditor_id: UUID
    tech_id: UUID

    @model_validator(mode="after")
    def distinct(self):
        if self.auditor_id == self.tech_id:
            raise ValueError("Аудитор и техспециалист должны быть разными участниками")
        return self


class ImportPreview(Versioned):
    source: dict
    mapping: Annotated[dict[str, UUID], Field(max_length=1000)]
    bootstrap_history: StrictBool = False
    group_mapping: Annotated[dict[str, ImportGroupMapping], Field(max_length=1000)] = Field(default_factory=dict)


class ImportApply(Versioned):
    confirm: Literal[True]
    reason: Reason
