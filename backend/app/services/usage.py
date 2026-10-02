"""Privacy-minimal section capture and SQL-aggregated usage analytics."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import Date, String, cast, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.user import User, UserRole
from app.schemas.usage import SectionViewCreate, USAGE_SECTION_IDS, UsageReportRead
from app.services.sidebar_menu import accessible_sidebar_item_ids


TIMEZONE = "Europe/Moscow"
MOSCOW = ZoneInfo(TIMEZONE)
LOGIN_EVENT = "login_success"
SECTION_VIEW_EVENT = "usage_section_view"
MAX_PERIOD_DAYS = 366
MAX_OFFSET = 100_000
SECTION_VIEW_NAMESPACE = UUID("b46e4c33-6d91-5dba-934b-8d8b5bb16a85")
UNKNOWN = "Не определено"
SECTION_LABELS = {
    "personal-tasks": "Личные задачи",
    "deadline-trackers": "Контроль сроков",
    "quick-notes": "Заметки",
    "contacts": "Контакты",
    "messages": "Сообщения",
    "graphs": "Графы",
    "my-tasks": "Мои задачи",
    "queue": "Очередь",
    "catalog": "Каталог",
    "knowledge": "База знаний",
    "shop": "Магазин",
    "work-entities": "Проекты",
    "calculator": "Калькулятор",
    "dashboard": "Дашборд",
    "reports": "Отчёты",
    "absences": "Отсутствия",
    "calibration": "Калибровка",
    "audit": "Аудит",
    "audit-calendar": "Календарь аудита",
    "competencies": "Компетенции",
    "feedback": "Обратная связь",
    "settings": "Настройки",
    "profile": "Профиль",
    "admin-users": "Пользователи",
    "admin-integrations": "Интеграции",
}


def period_bounds(
    start_date: date, end_date: date, *, today: date | None = None,
) -> tuple[datetime, datetime]:
    """Convert inclusive Moscow dates to a bounded, half-open UTC interval."""
    today = today or datetime.now(MOSCOW).date()
    if end_date < start_date:
        raise ValueError("Дата окончания не может быть раньше даты начала")
    if end_date > today:
        raise ValueError("Период не может включать будущие даты")
    if (end_date - start_date).days >= MAX_PERIOD_DAYS:
        raise ValueError("Период не может превышать 366 дней")
    try:
        start = datetime.combine(start_date, time.min, MOSCOW).astimezone(timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), time.min, MOSCOW).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("Дата выходит за допустимые границы") from None
    return start, end


def section_view_id(actor_id: UUID, event_id: UUID) -> UUID:
    return uuid5(SECTION_VIEW_NAMESPACE, f"{actor_id}:{event_id}")


async def record_section_view(db: AsyncSession, user: User, payload: SectionViewCreate) -> None:
    allowed = accessible_sidebar_item_ids(user) | {"settings"}
    if user.role == UserRole.admin or user.task_workspace_enabled:
        allowed |= {"profile"}
    if user.role == UserRole.admin:
        allowed |= {"admin-users", "admin-integrations"}
    if payload.section not in allowed:
        raise HTTPException(status_code=403, detail="Раздел недоступен")
    # Neither a replay nor a changed replay can overwrite the first stored event.
    await db.execute(insert(ActivityEvent).values(
        id=section_view_id(user.id, payload.event_id),
        actor_id=user.id,
        event_type=SECTION_VIEW_EVENT,
        event_data={"section": payload.section},
        occurred_at=datetime.now(timezone.utc),
    ).on_conflict_do_nothing(index_elements=[ActivityEvent.id]))


def classify_user_agent(value: object) -> dict[str, str]:
    """Return only coarse known labels; never echo untrusted client text."""
    ua = value[:2048].lower() if isinstance(value, str) else ""
    device = os_name = browser = UNKNOWN
    if "ipad" in ua:
        device, os_name = "Планшет", "iPadOS"
    elif "iphone" in ua or "ipod" in ua:
        device, os_name = "Телефон", "iOS"
    elif "android" in ua:
        device, os_name = ("Телефон" if "mobile" in ua else "Планшет"), "Android"
    elif "windows phone" in ua:
        device, os_name = "Телефон", "Windows Phone"
    elif "windows" in ua:
        device, os_name = "Компьютер", "Windows"
    elif "macintosh" in ua or "mac os x" in ua:
        device, os_name = "Компьютер", "macOS"
    elif "linux" in ua:
        device, os_name = "Компьютер", "Linux"

    for markers, label in (
        (("edg/", "edge/", "edgios/", "edga/"), "Edge"),
        (("opr/", "opera/", "opios/"), "Opera"),
        (("firefox/", "fxios/"), "Firefox"),
        (("chrome/", "crios/"), "Chrome"),
        (("version/",), "Safari"),
    ):
        if any(marker in ua for marker in markers):
            if label == "Safari" and "safari/" not in ua:
                continue
            browser = label
            break
    return {"device": device, "browser": browser, "os": os_name}


def _json_rows(rows, *ordering):
    """Aggregate only an already-grouped or paginated SQL relation."""
    # PostgreSQL cannot infer untyped key binds in this polymorphic function.
    fields = [part for column in rows.c for part in (cast(column.name, String), column)]
    value = func.jsonb_build_object(*fields)
    return select(func.jsonb_agg(aggregate_order_by(value, *ordering))).scalar_subquery()


def report_statement(start: datetime, end: datetime, user_id: UUID | None, limit: int, offset: int):
    event = ActivityEvent
    # Raw login metadata is deliberately absent from the shared period relation.
    period = select(
        event.id, event.actor_id, event.event_type, event.occurred_at,
        event.event_data["section"].astext.label("section"),
    ).where(
        event.occurred_at >= start, event.occurred_at < end,
        event.event_type.in_([LOGIN_EVENT, SECTION_VIEW_EVENT]),
    ).cte("usage_period")
    is_login = period.c.event_type == LOGIN_EVENT
    is_view = period.c.event_type == SECTION_VIEW_EVENT
    summary = select(
        func.count().filter(is_login).label("login_count"),
        func.count(func.distinct(period.c.actor_id)).filter(is_login).label("login_users"),
        func.count().filter(is_view).label("section_view_count"),
        func.count(func.distinct(period.c.actor_id)).filter(is_view).label("section_users"),
    ).cte("usage_summary")
    sections = select(
        period.c.section,
        func.count().label("views"),
        func.count(func.distinct(period.c.actor_id)).label("users"),
    ).where(is_view, period.c.section.in_(sorted(USAGE_SECTION_IDS))).group_by(period.c.section).cte("usage_sections")
    users = select(
        User.id, User.full_name.label("name"), User.email, func.count().label("logins"),
    ).join(period, period.c.actor_id == User.id).where(is_login).group_by(
        User.id, User.full_name, User.email,
    ).cte("usage_users")
    local_day = cast(func.timezone(TIMEZONE, period.c.occurred_at), Date)
    daily = select(
        local_day.label("date"),
        func.count().filter(is_login).label("logins"),
        func.count().filter(is_view).label("section_views"),
    ).group_by(local_day).cte("usage_daily")
    login_filter = [
        event.event_type == LOGIN_EVENT, event.occurred_at >= start, event.occurred_at < end,
    ]
    if user_id is not None:
        login_filter.append(event.actor_id == user_id)
    page = select(
        event.id, event.actor_id.label("user_id"), User.full_name.label("name"), User.email,
        event.occurred_at, event.event_data["user_agent"].astext.label("user_agent"),
    ).join(User, User.id == event.actor_id).where(*login_filter).order_by(
        event.occurred_at.desc(), event.id.desc(),
    ).limit(limit).offset(offset).cte("usage_login_page")

    def first(event_type: str):
        return select(func.min(event.occurred_at)).where(event.event_type == event_type).scalar_subquery()

    # One statement supplies one PostgreSQL MVCC snapshot even under READ COMMITTED.
    return select(
        *summary.c,
        first(LOGIN_EVENT).label("first_login_at"),
        first(SECTION_VIEW_EVENT).label("first_section_view_at"),
        _json_rows(sections, sections.c.views.desc(), sections.c.section).label("sections"),
        _json_rows(users, users.c.logins.desc(), users.c.name, users.c.id).label("users"),
        _json_rows(daily, daily.c.date).label("daily"),
        select(func.count()).select_from(event).where(*login_filter).scalar_subquery().label("login_total"),
        _json_rows(page, page.c.occurred_at.desc(), page.c.id.desc()).label("login_items"),
    )


async def get_usage_report(
    db: AsyncSession, *, start_date: date, end_date: date,
    user_id: UUID | None = None, limit: int = 25, offset: int = 0,
) -> UsageReportRead:
    start, end = period_bounds(start_date, end_date)
    if not 1 <= limit <= 100 or not 0 <= offset <= MAX_OFFSET:
        raise ValueError("Недопустимые параметры страницы")
    result = (await db.execute(report_statement(start, end, user_id, limit, offset))).mappings().one()
    days = {row["date"]: row for row in result["daily"] or []}
    daily = []
    for index in range((end_date - start_date).days + 1):
        day = (start_date + timedelta(days=index)).isoformat()
        daily.append(days.get(day, {"date": day, "logins": 0, "section_views": 0}))
    items = []
    for row in result["login_items"] or []:
        row = dict(row)
        row.update(classify_user_agent(row.pop("user_agent", None)))
        items.append(row)
    return UsageReportRead(
        start_date=start_date, end_date=end_date,
        login_count=result["login_count"], login_users=result["login_users"],
        section_view_count=result["section_view_count"], section_users=result["section_users"],
        first_login_at=result["first_login_at"], first_section_view_at=result["first_section_view_at"],
        sections=[{**row, "label": SECTION_LABELS[row["section"]]} for row in result["sections"] or []],
        users=result["users"] or [], daily=daily,
        logins={"total": result["login_total"], "items": items},
    )
