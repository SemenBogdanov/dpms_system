"""Наполнение БД тестовыми данными. Запуск: python -m app.seed."""
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User, League, UserRole
from app.services.wallet import credit_q
from app.models.catalog import CatalogItem, CatalogCategory, Complexity
from app.models.task import Task, TaskStatus, TaskType, TaskPriority


# --- Пользователи (5 штук) ---
USERS = [
    {"full_name": "Семёнова Анна", "email": "semenova@example.com", "league": League.A, "role": UserRole.teamlead, "mpw": 120},
    {"full_name": "Орловская Мария", "email": "orlovskaya@example.com", "league": League.B, "role": UserRole.executor, "mpw": 80},
    {"full_name": "Завьялова Екатерина", "email": "zavyalova@example.com", "league": League.B, "role": UserRole.executor, "mpw": 80},
    {"full_name": "Петров Иван", "email": "petrov@example.com", "league": League.C, "role": UserRole.executor, "mpw": 40},
    {"full_name": "Админ Системы", "email": "admin@example.com", "league": League.A, "role": UserRole.admin, "mpw": 0},
]

# --- Каталог операций ---
CATALOG = [
    # Виджеты
    ("widget", "Текст / Индикатор", "S", Decimal("1.0"), "Текст или индикатор", League.C),
    ("widget", "Простая таблица", "S", Decimal("2.0"), "Простая таблица", League.C),
    ("widget", "KPI-карточка", "S", Decimal("1.5"), "KPI-карточка", League.C),
    ("widget", "Line Chart", "M", Decimal("3.0"), "Линейный график", League.B),
    ("widget", "Bar Chart", "M", Decimal("3.0"), "Столбчатая диаграмма", League.B),
    ("widget", "Pie Chart", "M", Decimal("2.5"), "Круговая диаграмма", League.B),
    ("widget", "Filter / Date Picker", "S", Decimal("1.0"), "Фильтр или выбор даты", League.C),
    ("widget", "Geo Map", "L", Decimal("6.0"), "Геокарта", League.A),
    ("widget", "Pivot Table", "L", Decimal("5.0"), "Сводная таблица", League.B),
    ("widget", "Custom JS Widget", "XL", Decimal("10.0"), "Кастомный JS-виджет", League.A),
    # ETL
    ("etl", "Простой поток (Source → Target)", "S", Decimal("3.0"), "Простой ETL-поток", League.C),
    ("etl", "DDL + Нейминг", "S", Decimal("1.5"), "DDL и нейминг", League.C),
    ("etl", "Настройка NiFi / Airflow DAG", "M", Decimal("4.0"), "Настройка оркестрации", League.B),
    ("etl", "Сложный SQL (JOIN 3+, оконные функции)", "L", Decimal("6.0"), "Сложный SQL", League.A),
    ("etl", "ФЛК (Форматно-логический контроль)", "M", Decimal("3.0"), "ФЛК", League.B),
    ("etl", "Wiki-документация", "S", Decimal("2.0"), "Документация в Wiki", League.C),
]


async def ensure_users(session: AsyncSession) -> dict[str, User]:
    """Создать пользователей, если ещё нет. Возвращает email -> User."""
    result = await session.execute(select(User).where(User.email == "admin@example.com"))
    if result.scalar_one_or_none():
        result = await session.execute(select(User))
        users = {u.email: u for u in result.scalars().all()}
        return users

    users_by_email = {}
    for u in USERS:
        user = User(**u)
        session.add(user)
        await session.flush()
        users_by_email[user.email] = user
    return users_by_email


async def ensure_catalog(session: AsyncSession) -> list[CatalogItem]:
    """Создать позиции каталога, если ещё нет."""
    result = await session.execute(select(CatalogItem).limit(1))
    if result.scalar_one_or_none():
        result = await session.execute(select(CatalogItem))
        return list(result.scalars().all())

    items = []
    for cat, name, compl, cost, desc, min_league in CATALOG:
        item = CatalogItem(
            category=CatalogCategory(cat),
            name=name,
            complexity=Complexity(compl),
            base_cost_q=cost,
            description=desc,
            min_league=min_league,
        )
        session.add(item)
        await session.flush()
        items.append(item)
    return items


async def ensure_tasks(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Создать 10 задач в разных статусах. Орловская — 3 завершённые на 25Q, Петров — 1 на 5Q."""
    result = await session.execute(select(Task).limit(1))
    if result.scalar_one_or_none():
        return

    anna = users_by_email["semenova@example.com"]
    maria = users_by_email["orlovskaya@example.com"]
    ekaterina = users_by_email["zavyalova@example.com"]
    ivan = users_by_email["petrov@example.com"]
    admin = users_by_email["admin@example.com"]
    now = datetime.now(timezone.utc)

    tasks_data = [
        # Орловская: 3 завершённые (done) на 25Q суммарно — например 10+8+7
        {"title": "Дашборд продаж Q1", "status": TaskStatus.done, "estimated_q": Decimal("10"), "assignee": maria, "estimator": admin, "validator": anna},
        {"title": "ETL загрузка логов", "status": TaskStatus.done, "estimated_q": Decimal("8"), "assignee": maria, "estimator": admin, "validator": anna},
        {"title": "Виджеты KPI для отчёта", "status": TaskStatus.done, "estimated_q": Decimal("7"), "assignee": maria, "estimator": admin, "validator": anna},
        # Петров: 1 завершённая на 5Q
        {"title": "Простая таблица выгрузки", "status": TaskStatus.done, "estimated_q": Decimal("5"), "assignee": ivan, "estimator": admin, "validator": anna},
        # В очереди
        {"title": "Line Chart по регионам", "status": TaskStatus.in_queue, "estimated_q": Decimal("3"), "assignee": None, "estimator": admin, "validator": None},
        {"title": "ФЛК справочников", "status": TaskStatus.in_queue, "estimated_q": Decimal("3"), "assignee": None, "estimator": admin, "validator": None},
        # В работе
        {"title": "Pivot по клиентам", "status": TaskStatus.in_progress, "estimated_q": Decimal("5"), "assignee": ekaterina, "estimator": admin, "validator": None},
        {"title": "Документация API", "status": TaskStatus.in_progress, "estimated_q": Decimal("4"), "assignee": maria, "estimator": admin, "validator": None},
        # На проверке
        {"title": "Bar Chart сравнение", "status": TaskStatus.review, "estimated_q": Decimal("3"), "assignee": ivan, "estimator": admin, "validator": None},
        # Новая
        {"title": "Geo Map офисов", "status": TaskStatus.new, "estimated_q": Decimal("6"), "assignee": None, "estimator": admin, "validator": None},
    ]

    for t in tasks_data:
        task = Task(
            title=t["title"],
            description="Описание задачи.",
            task_type=TaskType.widget if "Chart" in t["title"] or "таблиц" in t["title"] or "KPI" in t["title"] else TaskType.etl if "ETL" in t["title"] or "ФЛК" in t["title"] else TaskType.docs,
            complexity=Complexity.M,
            estimated_q=t["estimated_q"],
            priority=TaskPriority.medium,
            status=t["status"],
            min_league=League.C,
            assignee_id=t["assignee"].id if t["assignee"] else None,
            estimator_id=t["estimator"].id,
            validator_id=t["validator"].id if t["validator"] else None,
            started_at=now if t["status"] in (TaskStatus.in_progress, TaskStatus.review, TaskStatus.done) and t["assignee"] else None,
            completed_at=now if t["status"] in (TaskStatus.review, TaskStatus.done) and t["assignee"] else None,
            validated_at=now if t["status"] == TaskStatus.done and t["validator"] else None,
        )
        session.add(task)
        await session.flush()
        # Начислить Q за завершённые задачи (балансы для дашборда)
        if t["status"] == TaskStatus.done and t["assignee"]:
            await credit_q(
                session,
                t["assignee"].id,
                t["estimated_q"],
                reason=f"Task #{task.id} completion (seed)",
                task_id=task.id,
            )


async def run_seed() -> None:
    """Главная функция seed."""
    async with AsyncSessionLocal() as session:
        try:
            users = await ensure_users(session)
            await ensure_catalog(session)
            await ensure_tasks(session, users)
            await session.commit()
            print("Seed выполнен успешно.")
        except Exception as e:
            await session.rollback()
            raise e


if __name__ == "__main__":
    asyncio.run(run_seed())
