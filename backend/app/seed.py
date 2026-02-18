"""Наполнение БД тестовыми данными. Запуск: python -m app.seed."""
import asyncio
import random
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from sqlalchemy import select  # type: ignore[import]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import]

from app.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User, League, UserRole
from app.models.transaction import QTransaction, WalletType
from app.models.notification import Notification
from app.services.wallet import credit_q
from app.services.notifications import create_notification
from app.services.queue import create_bugfix
from app.models.catalog import CatalogItem, CatalogCategory, Complexity
from app.models.task import Task, TaskStatus, TaskType, TaskPriority
from app.models.shop import ShopItem


# --- Пользователи (7 штук) ---
USERS = [
    {"full_name": "Семёнова Ксения", "email": "semenova@ac.gov.ru", "league": League.A, "role": UserRole.teamlead, "mpw": 120, "quality_score": 95.0},
    {"full_name": "Орловская Валентина", "email": "orlovskaya@ac.gov.ru", "league": League.B, "role": UserRole.executor, "mpw": 80, "quality_score": 88.0},
    {"full_name": "Завьялова Екатерина", "email": "zavyalova@ac.gov.ru", "league": League.B, "role": UserRole.executor, "mpw": 80, "quality_score": 92.0},
    {"full_name": "Скачков Егор", "email": "petrov@ac.gov.ru", "league": League.C, "role": UserRole.executor, "mpw": 40, "quality_score": 72.0},
    {"full_name": "Богданов Семён", "email": "bogdanov@ac.gov.ru", "league": League.A, "role": UserRole.admin, "mpw": 0, "quality_score": 100.0},
    {"full_name": "Админ Системы", "email": "admin@ac.gov.ru", "league": League.A, "role": UserRole.admin, "mpw": 0, "quality_score": 100.0},
]

# --- Каталог операций ---
CATALOG = [
    # Виджеты
    ("widget", "Разметка (x10)", "M", Decimal("0.5"), "Разметка", League.C), # Закладываем 10 шт. виджета разметки по 3 мин. = 30 мин.
    ("widget", "Event-контейнер (x2)", "M", Decimal("0.25"), "Ивент контейнер", League.C), # Закладываем 2 шт. виджета разметки по 7.5 мин. = 15 мин.
    ("widget", "Текст / Индикатор (x10)", "S", Decimal("0.75"), "Текст или индикатор", League.C), # Закладываем 10 шт. виджета текста или индикатора по 4.5 мин. = 45 мин.
    ("widget", "KPI-карточка (x1)", "M", Decimal("1.0"), "KPI-карточка", League.C), # Закладываем 1 шт. виджета KPI-карточки по 1 час. = 60 мин.
    ("widget", "Домик (x3)", "S", Decimal("0.15"), "Домик", League.C), # Закладываем 3 шт. виджета домик с общим временем 10 мин. = 10 мин.
    ("widget", "Кнопка (x2)", "S", Decimal("0.15"), "Кнопка", League.C), # Закладываем 2 шт. виджета кнопки с общим временем 5 мин. = 10 мин.
    ("widget", "Календарь (x1)", "M", Decimal("0.3"), "Календарь", League.C),  # Закладываем 1 шт. виджета календаря по 30 мин. = 30 мин.
    ("widget", "Фильтр (x5)", "L", Decimal("2.0"), "Фильтр или выбор даты", League.C), # Закладываем 5 шт. виджета фильтра по 24 минут каждый = 120 минут.
    ("widget", "Кнопочный фильтр (x4)", "M", Decimal("1.0"), "Кнопочный фильтр", League.C), # Закладываем 4 шт. виджета кнопочного фильтра по 10 минут каждый = 40 минут.
    ("widget", "Комбинированная диаграмма (x1)", "XL", Decimal("2.5"), "Комбинированная диаграмма", League.B), # Закладываем 1 шт. виджета комбинированной диаграммы по 150 минут. = 150 минут.
    ("widget", "Line Chart (x1)", "M", Decimal("1.0"), "Линейный график", League.B), # Закладываем одну штуку виджета линейного графика стоимостью 1 час. = 60 минут.
    ("widget", "Bar Chart (x1)", "M", Decimal("1.0"), "Столбчатая диаграмма", League.B), # Закладываем одну штуку виджета столбчатой диаграммы стоимостью 1 час. = 60 минут.
    ("widget", "Pie Chart (x1)", "M", Decimal("1.0"), "Круговая диаграмма", League.B), # Закладываем одну штуку виджета круговой диаграммы стоимостью 1 час. = 60 минут.
    ("widget", "Простая таблица (x1)", "M", Decimal("2.0"), "Простая таблица", League.C), # Закладываем одну штуку виджета простой таблицы стоимостью 2 часа. = 120 минут.
    ("widget", "Geo Map (x1)", "L", Decimal("3.0"), "Геокарта", League.A), # Закладываем одну штуку геокарты стоимостью 3 часа. = 180 минут.
    ("widget", "Pivot Table (x1)", "L", Decimal("2.0"), "Сводная таблица", League.A), # Закладываем одну штуку сводной таблицы, стоимостью в два часа. = 120 минут.
    ("widget", "Custom JS Widget (x1)", "XL", Decimal("8.0"), "Кастомный JS-виджет", League.A), # Закладываем одну штуку виджета стоимостью 8 часов. = 480 минут.
    ("widget", "Отладка ошибок S", "S", Decimal("0.5"), "Отладка ошибок на сформированном экране S-сложности", League.C), # Закладываем 1 шт. теста отладки ошибок на сформированном экране 30 минут. = 30 минут.
    ("widget", "Отладка ошибок M", "M", Decimal("1.0"), "Отладка ошибок на сформированном экране M-сложности", League.C), # Закладываем 1 шт. теста отладки ошибок на сформированном экране 60 минут. = 60 минут.
    ("widget", "Отладка ошибок L", "L", Decimal("2.0"), "Отладка ошибок на сформированном экране L-сложности", League.C), # Закладываем 1 шт. теста отладки ошибок на сформированном экране 120 минут. = 120 минут.
    # ETL
    #("etl", "Простой поток (Source → Target) (x1)", "S", Decimal("3.0"), "Простой ETL-поток", League.C),
    ("etl", "DDL + Нейминг", "S", Decimal("1.5"), "DDL и нейминг", League.C),
    ("etl", "Настройка NiFi / Airflow DAG (x1)", "M", Decimal("4.0"), "Настройка оркестрации", League.B),
    ("etl", "Сложный SQL (JOIN 3+, оконные функции) (x1)", "L", Decimal("6.0"), "Сложный SQL", League.A),
    ("etl", "ФЛК (Форматно-логический контроль) (x1)", "M", Decimal("3.0"), "ФЛК", League.B),
    ("etl", "Wiki-документация", "S", Decimal("2.0"), "Документация в Wiki", League.C),
    # ETL/API/Docs (Phase 5)
    ("etl", "NiFi Flow: Simple (1-3 processors)", "S", Decimal("3.0"), "NiFi Flow 1-3 процессора", League.C),
    ("etl", "NiFi Flow: Medium (4-8 processors)", "M", Decimal("6.0"), "NiFi Flow 4-8 процессоров", League.C),
    ("etl", "NiFi Flow: Complex (9+ processors)", "L", Decimal("12.0"), "NiFi Flow 9+ процессоров", League.B),
    ("etl", "Dremio View: Simple Join", "S", Decimal("2.0"), "Dremio View простой join", League.C),
    ("etl", "Dremio View: Multi-source + Transform", "M", Decimal("5.0"), "Dremio View несколько источников", League.B),
    ("etl", "Dremio View: Complex Analytics", "L", Decimal("10.0"), "Dremio View сложная аналитика", League.A),
    ("etl", "PostgreSQL Migration Script", "M", Decimal("4.0"), "Скрипт миграции PostgreSQL", League.C),
    ("etl", "Data Quality Check", "S", Decimal("2.5"), "Проверка качества данных", League.C),
    ("api", "API Endpoint: REST GET", "S", Decimal("3.0"), "REST GET эндпоинт", League.C),
    ("api", "API Endpoint: REST POST + Validation", "M", Decimal("5.0"), "REST POST с валидацией", League.B),
    ("api", "API Integration: External Service", "L", Decimal("8.0"), "Интеграция с внешним сервисом", League.B),
    ("docs", "Documentation: Technical Spec", "M", Decimal("4.0"), "Техническая спецификация", League.C),
    ("docs", "Documentation: User Guide", "S", Decimal("2.0"), "Руководство пользователя", League.C),
]

# Проактивные операции (Доработка 6)
PROACTIVE_CATALOG = [
    ("proactive", "Рефакторинг: оптимизация существующего потока", "M", Decimal("5.0"), "Оптимизация потока", League.C),
    ("proactive", "Документация: описание процесса", "S", Decimal("3.0"), "Описание процесса", League.C),
    ("proactive", "Менторинг: обучение коллеги", "M", Decimal("4.0"), "Обучение коллеги", League.B),
    ("proactive", "Исследование: оценка нового инструмента", "L", Decimal("8.0"), "Оценка инструмента", League.B),
    ("proactive", "Техдолг: покрытие тестами", "S", Decimal("3.0"), "Покрытие тестами", League.C),
    ("proactive", "Техдолг: улучшение мониторинга", "M", Decimal("5.0"), "Улучшение мониторинга", League.B),
    ("proactive", "Предварительный анализ и декомпозиция", "M", Decimal("4.0"), "Анализ сложной задачи, декомпозиция на типовые операции", League.C),
]


async def ensure_users(session: AsyncSession) -> dict[str, User]:
    """Создать пользователей, если ещё нет. Возвращает email -> User."""
    result = await session.execute(select(User).where(User.email == "admin@ac.gov.ru"))
    if result.scalar_one_or_none():
        result = await session.execute(select(User))
        users_list = result.scalars().all()
        for u in users_list:
            if u.password_hash is None:
                u.password_hash = get_password_hash("demo123")
                session.add(u)
        return {u.email: u for u in users_list}

    users_by_email = {}
    for u in USERS:
        user = User(**u)
        user.password_hash = get_password_hash("demo123")
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


async def ensure_proactive_catalog(session: AsyncSession, catalog_items: list[CatalogItem]) -> list[CatalogItem]:
    """Добавить проактивные операции, если их ещё нет."""
    has_proactive = any(getattr(c.category, "value", c.category) == "proactive" for c in catalog_items)
    if has_proactive:
        return catalog_items
    added = []
    for cat, name, compl, cost, desc, min_league in PROACTIVE_CATALOG:
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
        added.append(item)
    return catalog_items + added


async def ensure_tasks(
    session: AsyncSession,
    users_by_email: dict[str, User],
    catalog_items: list[CatalogItem],
) -> None:
    """Создать 10 задач в разных статусах. Минимум 5 done с реалистичными датами и estimation_details для калибровки."""
    result = await session.execute(select(Task).limit(1))
    if result.scalar_one_or_none():
        return

    anna = users_by_email["semenova@ac.gov.ru"]
    maria = users_by_email["orlovskaya@ac.gov.ru"]
    ekaterina = users_by_email["zavyalova@ac.gov.ru"]
    ivan = users_by_email["petrov@ac.gov.ru"]
    admin = users_by_email["admin@ac.gov.ru"]
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Для done-задач: completed_at в текущем месяце, started_at = completed_at - (4..24)h, validated_at = completed_at + 1h
    def make_done_timestamps():
        day_offset = random.randint(1, min(10, (now - month_start).days or 1))
        completed = month_start + timedelta(days=day_offset, hours=random.randint(10, 18))
        started = completed - timedelta(hours=random.randint(4, 24))
        validated = completed + timedelta(hours=1)
        return started, completed, validated

    # Каталог для breakdown (берём первые несколько позиций)
    cat_ids = [str(c.id) for c in catalog_items[:5]]

    tasks_data = [
        # Орловская: 3 завершённые (done)
        {"title": "Дашборд продаж Q1", "status": TaskStatus.done, "estimated_q": Decimal("10"), "assignee": maria, "estimator": admin, "validator": anna},
        {"title": "ETL загрузка логов", "status": TaskStatus.done, "estimated_q": Decimal("8"), "assignee": maria, "estimator": admin, "validator": anna},
        {"title": "Виджеты KPI для отчёта", "status": TaskStatus.done, "estimated_q": Decimal("7"), "assignee": maria, "estimator": admin, "validator": anna},
        # Петров: 1 завершённая
        {"title": "Простая таблица выгрузки", "status": TaskStatus.done, "estimated_q": Decimal("5"), "assignee": ivan, "estimator": admin, "validator": anna},
        # Завьялова: 1 завершённая (итого 5 done для калибровки)
        {"title": "Pivot отчёт по клиентам", "status": TaskStatus.done, "estimated_q": Decimal("5"), "assignee": ekaterina, "estimator": admin, "validator": anna},
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
        is_done = t["status"] == TaskStatus.done and t["assignee"]
        if is_done:
            started_at, completed_at, validated_at = make_done_timestamps()
            est_q = float(t["estimated_q"])
            breakdown = [{"catalog_id": cat_ids[i % len(cat_ids)], "subtotal_q": round(est_q, 1)} for i in range(1)]
            estimation_details = {"breakdown": breakdown}
        else:
            created_at = started_at = completed_at = validated_at = now
            estimation_details = None

        task = Task(
            title=t["title"],
            description="Описание задачи.",
            task_type=TaskType.widget if "Chart" in t["title"] or "таблиц" in t["title"] or "KPI" in t["title"] or "Pivot" in t["title"] else TaskType.etl if "ETL" in t["title"] or "ФЛК" in t["title"] else TaskType.docs,
            complexity=Complexity.M,
            estimated_q=t["estimated_q"],
            priority=TaskPriority.medium,
            status=t["status"],
            min_league=League.C,
            assignee_id=t["assignee"].id if t["assignee"] else None,
            estimator_id=t["estimator"].id,
            validator_id=t["validator"].id if t["validator"] else None,
            estimation_details=estimation_details,
            started_at=started_at if t["status"] in (TaskStatus.in_progress, TaskStatus.review, TaskStatus.done) and t["assignee"] else None,
            completed_at=completed_at if t["status"] in (TaskStatus.review, TaskStatus.done) and t["assignee"] else None,
            validated_at=validated_at if t["status"] == TaskStatus.done and t["validator"] else None,
            due_date=completed_at + timedelta(hours=4) if t["status"] in (TaskStatus.in_progress, TaskStatus.review) and t["assignee"] else None,
        )
        session.add(task)
        await session.flush()
        if is_done and t["assignee"]:
            await credit_q(
                session,
                t["assignee"].id,
                t["estimated_q"],
                reason=f"Задача #{task.id} принята",
                task_id=task.id,
            )

    proactive_items = [c for c in catalog_items if getattr(c.category, "value", str(c.category)) == "proactive"]
    if proactive_items:
        for idx, proact in enumerate(proactive_items[:3]):
            task = Task(
                title=f"Проактивная: {proact.name}",
                description="Демо проактивная задача.",
                task_type=TaskType.proactive,
                complexity=proact.complexity,
                estimated_q=proact.base_cost_q,
                priority=TaskPriority.medium,
                status=TaskStatus.in_queue,
                min_league=proact.min_league,
                assignee_id=None,
                estimator_id=admin.id,
                validator_id=None,
                is_proactive=True,
            )
            session.add(task)
            await session.flush()

    # Демо гарантийного баг-фикса по первой завершённой задаче
    # Берём первую done-задачу Орловской, если она есть
    first_done = await session.execute(
        select(Task).where(Task.status == TaskStatus.done).order_by(Task.created_at.asc())
    )
    parent = first_done.scalars().first()
    if parent:
        await create_bugfix(
            session,
            reporter_id=admin.id,
            parent_task_id=parent.id,
            title="Баг: некорректная фильтрация в дашборде",
            description="При выборе фильтра по дате данные не обновляются",
        )


async def ensure_burndown_transactions(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Транзакции за текущий месяц по дням для графика burn-down (main, amount > 0)."""
    result = await session.execute(
        select(QTransaction.id).where(QTransaction.reason == "Burn-down seed").limit(1)
    )
    if result.scalar_one_or_none():
        return
    now = datetime.now(timezone.utc)
    user = list(users_by_email.values())[0]
    amounts = [Decimal("5.0"), Decimal("8.0"), Decimal("3.5"), Decimal("12.0"), Decimal("6.0")]
    days = [1, 3, 5, 8, 10]
    for day, amount in zip(days, amounts):
        created = now.replace(day=min(day, 28), hour=10, minute=0, second=0, microsecond=0)
        if created > now:
            continue
        t = QTransaction(
            user_id=user.id,
            amount=amount,
            wallet_type=WalletType.main,
            reason="Burn-down seed",
        )
        t.created_at = created
        session.add(t)


async def ensure_shop_items(session: AsyncSession) -> None:
    """Добавить товары магазина, если ещё нет."""
    result = await session.execute(select(ShopItem).limit(1))
    if result.scalar_one_or_none():
        return
    shop_items = [
        ShopItem(
            name="Стикерпак",
            description="Набор стикеров",
            cost_q=Decimal("5.0"),
            icon="🎨",
            max_per_month=2,
            requires_approval=False,
        ),
        ShopItem(
            name="Кофе-бонус",
            description="Бонус на кофе",
            cost_q=Decimal("3.0"),
            icon="☕",
            max_per_month=5,
            requires_approval=False,
        ),
        ShopItem(
            name="Remote Day",
            description="Работа из дома на 1 день",
            cost_q=Decimal("30.0"),
            icon="🏠",
            max_per_month=2,
            requires_approval=True,
        ),
        ShopItem(
            name="Доп. выходной",
            description="Дополнительный выходной",
            cost_q=Decimal("50.0"),
            icon="🏖️",
            max_per_month=1,
            requires_approval=True,
        ),
        ShopItem(
            name="Veto Card",
            description="Право отклонить одну назначенную задачу",
            cost_q=Decimal("10.0"),
            icon="🛡️",
            max_per_month=3,
            requires_approval=True,
        ),
    ]
    for item in shop_items:
        session.add(item)
        await session.flush()


async def ensure_demo_notifications(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Несколько демо-уведомлений для первого пользователя."""
    result = await session.execute(select(Notification).limit(1))
    if result.scalar_one_or_none():
        return
    first_user = list(users_by_email.values())[0]
    await create_notification(
        session, first_user.id,
        "task_validated",
        "Задача принята",
        "«Дашборд продаж Q1» валидирована. +10.0 Q",
        "/my-tasks",
    )
    await create_notification(
        session, first_user.id,
        "rollover",
        "Период закрыт",
        "Период 2026-01 завершён. Main обнулён.",
        "/profile",
    )


async def run_seed() -> None:
    """Главная функция seed."""
    async with AsyncSessionLocal() as session:
        try:
            users = await ensure_users(session)
            catalog = await ensure_catalog(session)
            catalog = await ensure_proactive_catalog(session, catalog)
            await ensure_tasks(session, users, catalog)
            await ensure_shop_items(session)
            await ensure_burndown_transactions(session, users)
            await ensure_demo_notifications(session, users)
            await session.commit()
            print("Seed выполнен успешно.")
        except Exception as e:
            await session.rollback()
            raise e


if __name__ == "__main__":
    asyncio.run(run_seed())
