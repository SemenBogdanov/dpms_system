"""Pure validation used on save, read diagnostics and import revalidation."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.audit_calendar_math import AvailabilityWindow, Absence, availability_value


MOSCOW = ZoneInfo("Europe/Moscow")


def issue(code, message, **details):
    return {"code": code, "message": message, **details}


def meeting_instant(day, start):
    return datetime.combine(day, time(), MOSCOW) + timedelta(minutes=start)


def historical_source_issues(original, actual_date, today, *, actual_group_code=None):
    errors = []
    source_row = original.get("sourceRow")
    try:
        original_date = date.fromisoformat(original.get("date", ""))
    except (TypeError, ValueError):
        original_date = date.min
    if (original.get("origin") != "source" or original.get("kind") not in ("plan", "fact")
            or type(source_row) is not int or not 2 <= source_row <= 38
            or not date(2026, 8, 28) <= original_date <= date(2026, 9, 11)):
        errors.append(issue("HISTORICAL_SOURCE", "Нужна исходная строка в установленном историческом периоде; новый план, черновик или рабочая редакция не подтверждают историю"))
    if not date(2026, 8, 28) <= actual_date <= date(2026, 9, 11) or actual_date >= today:
        errors.append(issue("HISTORICAL_HORIZON", "Фактическая дата должна быть раньше сегодня и в периоде с 28.08.2026 по 11.09.2026"))
    if actual_group_code is not None and actual_group_code != original.get("groupId"):
        errors.append(issue("HISTORICAL_ATTRIBUTION", "Группа исторического факта определяется исходной строкой и не может быть подменена"))
    return errors


def availability_issues(day, start, duration, user_ids, windows, absences):
    errors, warnings = [], []
    for user_id in sorted(set(user_ids), key=str):
        pid = str(user_id)
        value = availability_value(windows, person_id=pid, day=day,
                                   start_minute=start, end_minute=start + duration, absences=absences)
        if value is False:
            errors.append(issue("UNAVAILABLE", "Участник отсутствует или занят в это время", user_id=pid))
        elif value is None:
            has_free = any(w.person_id == pid and w.day == day and w.available for w in windows)
            (errors if has_free else warnings).append(issue(
                "OUTSIDE_AVAILABILITY" if has_free else "AVAILABILITY_UNKNOWN",
                "Свободные интервалы участника не покрывают встречу целиком" if has_free else "Свободное время участника на эту дату не указано", user_id=pid,
            ))
    return errors, warnings


def composition_issues(group, version, members, users, activity, speaker_id, *, require_speaker=True):
    errors = []
    if group.legacy or group.archived or version is None:
        errors.append(issue("GROUP_UNAVAILABLE", "Нужна действующая версия состава современной группы"))
    roles = [(getattr(version, "auditor_id", None), "auditor"),
             (getattr(version, "tech_id", None), "tech")]
    if require_speaker or speaker_id:
        roles.append((speaker_id, "speaker"))
    for uid, role in roles:
        member, user = members.get(uid), users.get(uid)
        if not uid or not member or not member.active or member.role != role or not user or not user.is_active or not user.audit_calendar_enabled:
            role_label = {"auditor": "Аудитор", "tech": "Техспециалист", "speaker": "Докладчик"}[role]
            errors.append(issue("MEMBER_ROLE", f"{role_label}: проверьте роль, активное участие и допуск к календарю",
                                role=role, **({"user_id": str(uid)} if uid else {})))
    if len({uid for uid, _ in roles if uid}) != len(roles):
        errors.append(issue("PARTICIPANTS_DISTINCT", "Аудитор, техспециалист и докладчик должны быть разными участниками"))
    if not activity.strip() or len(activity.strip()) > 80:
        errors.append(issue("ACTIVITY_MISSING", "Укажите активность длиной от 1 до 80 символов"))
    return errors, [(uid, role) for uid, role in roles if uid]


def overlaps(first, second):
    return first.date == second.date and first.start < second.start + second.duration and second.start < first.start + first.duration


def conflict_issues(candidate, participants, records, by_record, *, facts=False):
    ids = set(participants)
    result = []
    for other in records:
        if getattr(candidate, "id", None) == other.id:
            continue
        if facts and other.outcome != "completed" or not facts and other.status == "cancelled":
            continue
        if overlaps(candidate, other):
            for uid in sorted(ids.intersection(by_record.get(other.id, ())), key=str):
                result.append(issue("FACT_CONFLICT" if facts else "PARTICIPANT_CONFLICT", "Участник уже участвует в другой встрече в это время",
                                    user_id=str(uid), record_id=str(other.id)))
    return result


def attendance_state(plan, notices, now):
    cutoff = meeting_instant(plan.date, plan.start) - timedelta(minutes=60)
    times = [n.reported_at for n in notices if n.plan_id == plan.id and n.reported_at <= now]
    if any(value <= cutoff for value in times):
        return "absence"
    if times:
        return "late-absence"
    return "confirmed" if now >= cutoff else "waiting"


def availability_projections(windows, absences):
    return ([AvailabilityWindow(str(w.user_id), w.date, w.start, w.end, w.available) for w in windows],
            [Absence(str(a.user_id), a.start_date, a.end_date) for a in absences if a.status == "active"])
