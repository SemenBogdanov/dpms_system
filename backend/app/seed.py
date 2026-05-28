"""Наполнение БД тестовыми данными. Запуск: python -m app.seed."""
import asyncio
import random
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update  # type: ignore[import]
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
from app.models.knowledge import KnowledgeArticle, KnowledgeStatus
from app.models.task import Task, TaskStatus, TaskType, TaskPriority
from app.models.shop import ShopItem


# --- Пользователи (6 штук) ---
USERS = [
    {"full_name": "Семёнова Ксения", "email": "semenova@ac.gov.ru", "league": League.A, "role": UserRole.teamlead, "mpw": 90, "quality_score": 95.0},
    {"full_name": "Орловская Валентина", "email": "orlovskaya@ac.gov.ru", "league": League.B, "role": UserRole.executor, "mpw": 80, "quality_score": 88.0},
    {"full_name": "Завьялова Екатерина", "email": "zavyalova@ac.gov.ru", "league": League.B, "role": UserRole.executor, "mpw": 80, "quality_score": 92.0},
    {"full_name": "Скачков Егор", "email": "petrov@ac.gov.ru", "league": League.C, "role": UserRole.executor, "mpw": 70, "quality_score": 72.0},
    {"full_name": "Богданов Семён", "email": "bogdanov@ac.gov.ru", "league": League.A, "role": UserRole.admin, "mpw": 0, "quality_score": 100.0, "feedback_enabled": True},
    {"full_name": "Админ Системы", "email": "admin@ac.gov.ru", "league": League.A, "role": UserRole.admin, "mpw": 0, "quality_score": 100.0, "feedback_enabled": True},
]

WIP_BY_LEAGUE = {"C": 2, "B": 3, "A": 4}

# --- Каталог операций (cat, name, compl, cost, desc, min_league, sort_order) ---
CATALOG = [
    # ─── Часто используемые (10-29) ───
    ("widget", "Разметка (x10)", "M", Decimal("0.5"), "Разметка", League.C, 10),
    ("widget", "Текст / Индикатор (x10)", "S", Decimal("0.75"), "Текст или индикатор", League.C, 11),
    ("widget", "Кнопочный фильтр (x4)", "M", Decimal("1.0"), "Кнопочный фильтр", League.C, 12),
    ("widget", "Event-контейнер (x2)", "M", Decimal("0.25"), "Ивент контейнер", League.C, 13),
    ("widget", "Фильтр (x5)", "L", Decimal("2.0"), "Фильтр или выбор даты", League.C, 14),
    ("widget", "Простая таблица (x1)", "M", Decimal("2.0"), "Простая таблица", League.C, 15),
    ("widget", "KPI-карточка (x1)", "M", Decimal("1.0"), "KPI-карточка", League.C, 16),
    # ─── Средняя частота (30-49) ───
    ("widget", "Line Chart (x1)", "M", Decimal("1.0"), "Линейный график", League.B, 30),
    ("widget", "Bar Chart (x1)", "M", Decimal("1.0"), "Столбчатая диаграмма", League.B, 31),
    ("widget", "Pie Chart (x1)", "M", Decimal("1.0"), "Круговая диаграмма", League.B, 32),
    ("widget", "Календарь (x1)", "M", Decimal("0.3"), "Календарь", League.C, 33),
    ("widget", "Домик (x3)", "S", Decimal("0.15"), "Домик", League.C, 34),
    ("widget", "Кнопка (x2)", "S", Decimal("0.15"), "Кнопка", League.C, 35),
    ("widget", "Отладка S", "S", Decimal("0.5"), "Отладка ошибок S-сложности", League.C, 36),
    ("widget", "Отладка M", "M", Decimal("1.0"), "Отладка ошибок M-сложности", League.C, 37),
    ("widget", "Отладка L", "L", Decimal("2.0"), "Отладка ошибок L-сложности", League.B, 38),
    # ─── Редко используемые (50-69) ───
    ("widget", "Комбинированная диаграмма (x1)", "XL", Decimal("2.5"), "Комбинированная диаграмма", League.B, 50),
    ("widget", "Geo Map (x1)", "L", Decimal("3.0"), "Геокарта", League.A, 51),
    ("widget", "Pivot Table (x1)", "L", Decimal("2.0"), "Сводная таблица", League.A, 52),
    ("widget", "Custom JS Widget (x1)", "XL", Decimal("8.0"), "Кастомный JS-виджет", League.A, 53),
    # ─── ETL (70-89) ───
    ("etl", "DDL + Нейминг", "S", Decimal("1.5"), "DDL и нейминг", League.C, 70),
    ("etl", "ФЛК (Форматно-логический контроль) (x1)", "M", Decimal("3.0"), "ФЛК", League.B, 71),
    ("etl", "Настройка NiFi / Airflow DAG (x1)", "M", Decimal("4.0"), "Настройка оркестрации", League.B, 72),
    ("etl", "Сложный SQL (JOIN 3+, оконные функции) (x1)", "L", Decimal("6.0"), "Сложный SQL", League.A, 73),
    ("etl", "Wiki-документация", "S", Decimal("2.0"), "Документация в Wiki", League.C, 74),
    ("etl", "NiFi Flow: Simple (1-3 processors)", "S", Decimal("3.0"), "NiFi Flow 1-3 процессора", League.C, 75),
    ("etl", "NiFi Flow: Medium (4-8 processors)", "M", Decimal("6.0"), "NiFi Flow 4-8 процессоров", League.C, 76),
    ("etl", "NiFi Flow: Complex (9+ processors)", "L", Decimal("12.0"), "NiFi Flow 9+ процессоров", League.B, 77),
    ("etl", "Dremio View: Simple Join", "S", Decimal("2.0"), "Dremio View простой join", League.C, 78),
    ("etl", "Dremio View: Multi-source + Transform", "M", Decimal("5.0"), "Dremio View несколько источников", League.B, 79),
    ("etl", "Dremio View: Complex Analytics", "L", Decimal("10.0"), "Dremio View сложная аналитика", League.A, 80),
    ("etl", "PostgreSQL Migration Script", "M", Decimal("4.0"), "Скрипт миграции PostgreSQL", League.C, 81),
    ("etl", "Data Quality Check", "S", Decimal("2.5"), "Проверка качества данных", League.C, 82),
    # ─── API (90-99) ───
    ("api", "API Endpoint: REST GET", "S", Decimal("3.0"), "REST GET эндпоинт", League.C, 90),
    ("api", "API Endpoint: REST POST + Validation", "M", Decimal("5.0"), "REST POST с валидацией", League.B, 91),
    ("api", "API Integration: External Service", "L", Decimal("8.0"), "Интеграция с внешним сервисом", League.B, 92),
    # ─── Docs (100-109) ───
    ("docs", "Documentation: Technical Spec", "M", Decimal("4.0"), "Техническая спецификация", League.C, 100),
    ("docs", "Documentation: User Guide", "S", Decimal("2.0"), "Руководство пользователя", League.C, 101),
]

# Проактивные операции (sort_order 200+)
PROACTIVE_CATALOG = [
    ("proactive", "Рефакторинг: оптимизация существующего потока", "M", Decimal("5.0"), "Оптимизация потока", League.C, 200),
    ("proactive", "Документация: описание процесса", "S", Decimal("3.0"), "Описание процесса", League.C, 201),
    ("proactive", "Менторинг: обучение коллеги", "M", Decimal("4.0"), "Обучение коллеги", League.B, 202),
    ("proactive", "Исследование: оценка нового инструмента", "L", Decimal("8.0"), "Оценка инструмента", League.B, 203),
    ("proactive", "Техдолг: покрытие тестами", "S", Decimal("3.0"), "Покрытие тестами", League.C, 204),
    ("proactive", "Техдолг: улучшение мониторинга", "M", Decimal("5.0"), "Улучшение мониторинга", League.B, 205),
    ("proactive", "Предварительный анализ и декомпозиция", "M", Decimal("4.0"), "Анализ сложной задачи", League.C, 206),
]

KNOWLEDGE_ARTICLES = [
    {
        "slug": "vhodnoy-brif-novichka",
        "title": "Входной бриф новичка",
        "summary": "Короткая рамка работы в системе: где брать задачи, как быть на связи и как сдавать результат.",
        "section": "start",
        "sort_order": 10,
        "body": """Обновлено: 2026-05-15

## Кратко
DPMS помогает команде видеть очередь задач, брать работу по правилам приоритета и фиксировать результат в Q.

## Первый день
- Откройте очередь и проверьте задачи, доступные вашей лиге.
- Возьмите задачу только после того, как поняли цель, срок и ожидаемый результат.
- Если формулировка неполная, задайте вопрос тимлиду до начала работы.
- В рабочее время оставайтесь доступны для оперативной связи.

## Базовый порядок
1. Проверьте приоритет задачи.
2. Возьмите задачу в работу.
3. Запустите focus timer, когда реально начали выполнять задачу.
4. Приложите результат и детальное описание при сдаче.
5. Дождитесь проверки или комментария на доработку.

## Доступность
Если сотрудник работает, он должен быть на связи. Телефон нужно брать не позднее чем через три гудка, чтобы вопросы по задаче решались без ожидания.""",
    },
    {
        "slug": "kak-rabotat-s-zadachami",
        "title": "Как работать с задачами",
        "summary": "Жизненный цикл задачи от очереди до проверки результата.",
        "section": "tasks",
        "sort_order": 20,
        "body": """Обновлено: 2026-05-15

## Очередь
В очереди находятся задачи, которые можно взять в работу. Доступность зависит от лиги, WIP-лимита, приоритета и текущих ограничений системы.

## В работе
- Берите задачу только тогда, когда готовы начать.
- Не держите задачу без движения.
- Если появилась блокировка, напишите тимлиду и зафиксируйте, что мешает продолжить.

## Сдача результата
При завершении заполните детальное описание и ссылки на результат. Эти данные нужны проверяющему и сохраняют историю выполнения.

## Доработка
Если задача возвращена, сначала разберите комментарий, затем продолжайте работу в той же задаче.""",
    },
    {
        "slug": "pravilo-dostupnosti-v-rabochie-chasy",
        "title": "Правило доступности в рабочие часы",
        "summary": "Ожидания по связи во время выполнения задач.",
        "section": "rules",
        "sort_order": 30,
        "body": """Обновлено: 2026-05-15

## Главное правило
В рабочие часы сотрудник должен быть доступен для связи по текущим задачам.

## Практический стандарт
- Телефон берется не позднее чем через три гудка.
- Сообщения по активной задаче проверяются регулярно.
- Если нужно отойти, предупредите тимлида или команду заранее.
- Если вопрос требует созвона, подключайтесь без затяжной переписки.

## Зачем это нужно
Цель правила — стопроцентная доступность для решения рабочих вопросов, чтобы задача не простаивала из-за ожидания ответа.""",
    },
    {
        "slug": "kritichnye-zadachi-i-dedlayny",
        "title": "Критичные задачи и дедлайны",
        "summary": "Что делать, если в очереди появляется критичная задача или задача со сроком.",
        "section": "tasks",
        "sort_order": 40,
        "body": """Обновлено: 2026-05-15

## Критичный приоритет
Критичная задача имеет приоритет над обычной очередью. Если такая задача доступна, следующая работа должна начинаться с нее или назначаться вручную ответственным.

## Дедлайны
- Задача без срока не считается просроченной сама по себе.
- Просрочка относится к незавершенным задачам в очереди или в работе.
- Если срок выглядит нереалистичным, сообщите тимлиду до начала выполнения.

## Поведение исполнителя
Не обходите критичную задачу ради более простой работы. Если не можете взять ее из-за лиги, доступа или контекста, сразу сообщите ответственному.""",
    },
    {
        "slug": "focus-timer-i-sdacha-rezultata",
        "title": "Focus timer и сдача результата",
        "summary": "Как фиксировать активную работу и корректно завершать задачу.",
        "section": "tasks",
        "sort_order": 50,
        "body": """Обновлено: 2026-05-15

## Focus timer
Запускайте таймер только на реальную активную работу. Если переключились на другую задачу или ушли на перерыв, остановите таймер.

## Ограничение
Один фокус-сегмент не должен превращаться в бесконтрольный многочасовой таймер. Если таймер не остановился автоматически, сообщите тимлиду или администратору.

## Сдача результата
- Заполните детальное описание того, что сделано.
- Добавьте ссылку на результат, если он находится во внешней системе.
- Укажите важные ограничения, проверки и договоренности.
- Отправляйте задачу на проверку только после самопроверки результата.""",
    },
]


async def ensure_users(session: AsyncSession) -> dict[str, User]:
    """Создать пользователей, если ещё нет. Возвращает email -> User."""
    result = await session.execute(select(User).where(User.email == "admin@ac.gov.ru"))
    if result.scalar_one_or_none():
        result = await session.execute(select(User))
        users_list = list(result.scalars().all())
        for u in users_list:
            if u.password_hash is None:
                u.password_hash = get_password_hash("demo123")
            # Обновить WIP-лимит в соответствии с лигой, если он ещё не задан явно
            league_value = getattr(u.league, "value", str(u.league))
            if not getattr(u, "wip_limit", None):
                u.wip_limit = WIP_BY_LEAGUE.get(league_value, 2)
            session.add(u)
        return {u.email: u for u in users_list}

    users_by_email: dict[str, User] = {}
    for u in USERS:
        user = User(**u)
        league_value = getattr(user.league, "value", str(user.league))
        user.wip_limit = WIP_BY_LEAGUE.get(league_value, 2)
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
    for cat, name, compl, cost, desc, min_league, sort_order in CATALOG:
        item = CatalogItem(
            category=CatalogCategory(cat),
            name=name,
            complexity=Complexity(compl),
            base_cost_q=cost,
            description=desc,
            min_league=min_league,
            sort_order=sort_order,
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
    for cat, name, compl, cost, desc, min_league, sort_order in PROACTIVE_CATALOG:
        item = CatalogItem(
            category=CatalogCategory(cat),
            name=name,
            complexity=Complexity(compl),
            base_cost_q=cost,
            description=desc,
            min_league=min_league,
            sort_order=sort_order,
        )
        session.add(item)
        await session.flush()
        added.append(item)
    return catalog_items + added


async def ensure_knowledge_articles(session: AsyncSession) -> None:
    """Добавить стартовые статьи базы знаний без перезаписи существующего контента."""
    for data in KNOWLEDGE_ARTICLES:
        result = await session.execute(
            select(KnowledgeArticle).where(KnowledgeArticle.slug == data["slug"])
        )
        if result.scalar_one_or_none():
            continue
        article = KnowledgeArticle(
            slug=data["slug"],
            title=data["title"],
            summary=data["summary"],
            section=data["section"],
            body=data["body"],
            status=KnowledgeStatus.published,
            sort_order=data["sort_order"],
            published_at=datetime.now(timezone.utc),
        )
        session.add(article)
        await session.flush()


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
        {"title": "Дашборд продаж Q1", "status": TaskStatus.done, "estimated_q": Decimal("10"), "assignee": maria, "estimator": admin, "validator": anna, "tags": ["MPRS"]},
        {"title": "ETL загрузка логов", "status": TaskStatus.done, "estimated_q": Decimal("8"), "assignee": maria, "estimator": admin, "validator": anna, "tags": ["И26"]},
        {"title": "Виджеты KPI для отчёта", "status": TaskStatus.done, "estimated_q": Decimal("7"), "assignee": maria, "estimator": admin, "validator": anna, "tags": ["MPRS", "И9"]},
        # Петров: 1 завершённая
        {"title": "Простая таблица выгрузки", "status": TaskStatus.done, "estimated_q": Decimal("5"), "assignee": ivan, "estimator": admin, "validator": anna, "tags": ["PRH2"]},
        # Завьялова: 1 завершённая (итого 5 done для калибровки)
        {"title": "Pivot отчёт по клиентам", "status": TaskStatus.done, "estimated_q": Decimal("5"), "assignee": ekaterina, "estimator": admin, "validator": anna, "tags": ["MNPR"]},
        # В очереди
        {"title": "Line Chart по регионам", "status": TaskStatus.in_queue, "estimated_q": Decimal("3"), "assignee": None, "estimator": admin, "validator": None, "tags": ["MPRS"]},
        {"title": "ФЛК справочников", "status": TaskStatus.in_queue, "estimated_q": Decimal("3"), "assignee": None, "estimator": admin, "validator": None, "tags": ["И26", "ТЕХДОЛГ"]},
        # В работе
        {"title": "Pivot по клиентам", "status": TaskStatus.in_progress, "estimated_q": Decimal("5"), "assignee": ekaterina, "estimator": admin, "validator": None, "tags": ["MNPR"]},
        {"title": "Документация API", "status": TaskStatus.in_progress, "estimated_q": Decimal("4"), "assignee": maria, "estimator": admin, "validator": None, "tags": ["PRH2", "ТЕХДОЛГ"]},
        # На проверке
        {"title": "Bar Chart сравнение", "status": TaskStatus.review, "estimated_q": Decimal("3"), "assignee": ivan, "estimator": admin, "validator": None, "tags": ["И9"]},
        # Новая
        {"title": "Geo Map офисов", "status": TaskStatus.new, "estimated_q": Decimal("6"), "assignee": None, "estimator": admin, "validator": None, "tags": ["MPRS"]},
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

        due_date = None
        sla_hours = None
        is_overdue = False
        if t["status"] in (TaskStatus.in_progress, TaskStatus.review) and t["assignee"]:
            if t["title"] == "Pivot по клиентам":
                due_date = now - timedelta(hours=3)
                sla_hours = 24
                is_overdue = True
            else:
                due_date = now + timedelta(hours=random.choice([4, 8, 16, 24, 48]))
                sla_hours = random.choice([8, 12, 16, 24])
                is_overdue = False

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
            due_date=due_date,
            sla_hours=sla_hours,
            is_overdue=is_overdue,
            tags=t.get("tags", []) or [],
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
                tags=[],
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


async def ensure_extended_test_tasks(
    session: AsyncSession,
    users_by_email: dict[str, User],
    catalog_items: list[CatalogItem],
) -> None:
    """Расширенные тестовые задачи с разными датами, статусами и возвратами."""
    result = await session.execute(
        select(Task).where(Task.title == "Интеграция с СУФД (старая)").limit(1)
    )
    if result.scalar_one_or_none():
        return

    anna = users_by_email["semenova@ac.gov.ru"]
    maria = users_by_email["orlovskaya@ac.gov.ru"]
    ekaterina = users_by_email["zavyalova@ac.gov.ru"]
    ivan = users_by_email["petrov@ac.gov.ru"]
    admin = users_by_email["admin@ac.gov.ru"]

    now = datetime.now(timezone.utc)

    extended_tasks = [
        {
            "title": "Интеграция с СУФД (старая)",
            "task_type": TaskType.api,
            "complexity": Complexity.L,
            "estimated_q": Decimal("8.0"),
            "priority": TaskPriority.high,
            "status": TaskStatus.in_queue,
            "min_league": League.B,
            "assignee": None,
            "created_ago_hours": 168,
            "tags": ["СУФД", "API"],
        },
        {
            "title": "Отчёт по госзакупкам за 2025",
            "task_type": TaskType.widget,
            "complexity": Complexity.XL,
            "estimated_q": Decimal("12.0"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.in_queue,
            "min_league": League.A,
            "assignee": None,
            "created_ago_hours": 240,
            "tags": ["Закупки", "Отчётность"],
        },
        {
            "title": "DDL для нового справочника ОКЕИ",
            "task_type": TaskType.etl,
            "complexity": Complexity.S,
            "estimated_q": Decimal("1.5"),
            "priority": TaskPriority.low,
            "status": TaskStatus.in_queue,
            "min_league": League.C,
            "assignee": None,
            "created_ago_hours": 336,
            "tags": ["Справочники", "DDL"],
        },
        {
            "title": "KPI-дашборд для зампреда",
            "task_type": TaskType.widget,
            "complexity": Complexity.L,
            "estimated_q": Decimal("7.0"),
            "priority": TaskPriority.high,
            "status": TaskStatus.in_progress,
            "min_league": League.B,
            "assignee": maria,
            "created_ago_hours": 72,
            "started_ago_hours": 48,
            "due_in_hours": 8,
            "sla_hours": 14,
            "tags": ["КПЭ", "Руководство"],
        },
        {
            "title": "NiFi flow: загрузка реестра МСП",
            "task_type": TaskType.etl,
            "complexity": Complexity.M,
            "estimated_q": Decimal("6.0"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.in_progress,
            "min_league": League.C,
            "assignee": ivan,
            "created_ago_hours": 96,
            "started_ago_hours": 24,
            "due_in_hours": 48,
            "sla_hours": 18,
            "tags": ["NiFi", "МСП"],
        },
        {
            "title": "Витрина данных по 44-ФЗ",
            "task_type": TaskType.widget,
            "complexity": Complexity.M,
            "estimated_q": Decimal("4.0"),
            "priority": TaskPriority.high,
            "status": TaskStatus.in_progress,
            "min_league": League.B,
            "assignee": ekaterina,
            "created_ago_hours": 120,
            "started_ago_hours": 72,
            "due_in_hours": -6,
            "sla_hours": 12,
            "is_overdue": True,
            "tags": ["44-ФЗ", "Витрина"],
        },
        {
            "title": "Сложный SQL: аналитика по контрактам",
            "task_type": TaskType.etl,
            "complexity": Complexity.L,
            "estimated_q": Decimal("6.0"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.in_progress,
            "min_league": League.B,
            "assignee": maria,
            "created_ago_hours": 200,
            "started_ago_hours": 120,
            "due_in_hours": 24,
            "sla_hours": 12,
            "rejection_count": 2,
            "rejection_comment": "Некорректная агрегация по подразделениям, пересчитать",
            "tags": ["SQL", "Контракты"],
        },
        {
            "title": "Geo Map филиалов с KPI",
            "task_type": TaskType.widget,
            "complexity": Complexity.L,
            "estimated_q": Decimal("5.0"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.review,
            "min_league": League.B,
            "assignee": ekaterina,
            "created_ago_hours": 180,
            "started_ago_hours": 100,
            "due_in_hours": 16,
            "sla_hours": 10,
            "rejection_count": 1,
            "tags": ["GeoMap", "КПЭ"],
        },
        {
            "title": "ETL: миграция справочника ОКПД-2",
            "task_type": TaskType.etl,
            "complexity": Complexity.S,
            "estimated_q": Decimal("2.0"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.done,
            "min_league": League.C,
            "assignee": ivan,
            "created_ago_hours": 400,
            "started_ago_hours": 350,
            "completed_ago_hours": 320,
            "rejection_count": 0,
            "tags": ["ОКПД", "Справочники"],
        },
        {
            "title": "Дашборд мониторинга NiFi",
            "task_type": TaskType.widget,
            "complexity": Complexity.L,
            "estimated_q": Decimal("7.0"),
            "priority": TaskPriority.high,
            "status": TaskStatus.done,
            "min_league": League.B,
            "assignee": maria,
            "created_ago_hours": 500,
            "started_ago_hours": 450,
            "completed_ago_hours": 400,
            "rejection_count": 1,
            "tags": ["NiFi", "Мониторинг"],
        },
        {
            "title": "Документация API: руководство разработчика",
            "task_type": TaskType.docs,
            "complexity": Complexity.M,
            "estimated_q": Decimal("4.0"),
            "priority": TaskPriority.low,
            "status": TaskStatus.done,
            "min_league": League.C,
            "assignee": ivan,
            "created_ago_hours": 600,
            "started_ago_hours": 550,
            "completed_ago_hours": 500,
            "rejection_count": 3,
            "tags": ["Документация", "API"],
        },
        {
            "title": "Pivot: сводка по исполнению бюджета",
            "task_type": TaskType.widget,
            "complexity": Complexity.M,
            "estimated_q": Decimal("4.5"),
            "priority": TaskPriority.medium,
            "status": TaskStatus.done,
            "min_league": League.B,
            "assignee": ekaterina,
            "created_ago_hours": 350,
            "started_ago_hours": 300,
            "completed_ago_hours": 270,
            "rejection_count": 0,
            "tags": ["Бюджет", "Pivot"],
        },
        {
            "title": "Срочная выгрузка для коллегии",
            "task_type": TaskType.widget,
            "complexity": Complexity.M,
            "estimated_q": Decimal("3.0"),
            "priority": TaskPriority.critical,
            "status": TaskStatus.in_progress,
            "min_league": League.C,
            "assignee": ivan,
            "assigned_by": anna,
            "created_ago_hours": 30,
            "started_ago_hours": 26,
            "due_in_hours": 4,
            "sla_hours": 9,
            "tags": ["Руководство", "Срочное"],
        },
    ]

    for t in extended_tasks:
        created_at = now - timedelta(hours=t.get("created_ago_hours", 0))
        started_at = now - timedelta(hours=t["started_ago_hours"]) if t.get("started_ago_hours") else None
        completed_at = now - timedelta(hours=t["completed_ago_hours"]) if t.get("completed_ago_hours") else None
        validated_at = completed_at + timedelta(hours=1) if completed_at else None

        due_date = None
        if t.get("due_in_hours") is not None:
            due_date = now + timedelta(hours=t["due_in_hours"])

        task = Task(
            title=t["title"],
            description=f"Тестовая задача: {t['title']}",
            task_type=t["task_type"],
            complexity=t["complexity"],
            estimated_q=t["estimated_q"],
            priority=t["priority"],
            status=t["status"],
            min_league=t["min_league"],
            assignee_id=t["assignee"].id if t.get("assignee") else None,
            assigned_by_id=t["assigned_by"].id if t.get("assigned_by") else None,
            estimator_id=admin.id,
            validator_id=anna.id if t["status"] == TaskStatus.done else None,
            started_at=started_at,
            completed_at=completed_at,
            validated_at=validated_at,
            due_date=due_date,
            sla_hours=t.get("sla_hours"),
            is_overdue=t.get("is_overdue", False),
            rejection_count=t.get("rejection_count", 0),
            rejection_comment=t.get("rejection_comment"),
            tags=t.get("tags", []),
        )
        session.add(task)
        await session.flush()

        await session.execute(
            update(Task).where(Task.id == task.id).values(created_at=created_at)
        )

        if t["status"] == TaskStatus.done and t.get("assignee"):
            await credit_q(
                session,
                t["assignee"].id,
                t["estimated_q"],
                reason=f"Задача #{task.id} принята",
                task_id=task.id,
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


async def ensure_capacity_history(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Транзакции за 6 недель для спарклайна ёмкости."""
    result = await session.execute(
        select(QTransaction.id).where(QTransaction.reason == "Capacity history seed").limit(1)
    )
    if result.scalar_one_or_none():
        return

    now = datetime.now(timezone.utc)
    executors = [u for u in users_by_email.values() if u.role.value == "executor"]

    weekly_data = [
        (5, [Decimal("18.0"), Decimal("15.0"), Decimal("12.0")]),
        (4, [Decimal("20.0"), Decimal("18.0"), Decimal("8.0")]),
        (3, [Decimal("25.0"), Decimal("20.0"), Decimal("15.0")]),
        (2, [Decimal("22.0"), Decimal("16.0"), Decimal("10.0")]),
        (1, [Decimal("30.0"), Decimal("25.0"), Decimal("18.0")]),
    ]

    for weeks_ago, amounts in weekly_data:
        week_center = now - timedelta(weeks=weeks_ago) + timedelta(days=random.randint(0, 4))
        for i, amount in enumerate(amounts):
            if i >= len(executors):
                break
            t = QTransaction(
                user_id=executors[i].id,
                amount=amount,
                wallet_type=WalletType.main,
                reason="Capacity history seed",
            )
            session.add(t)
            await session.flush()
            await session.execute(
                update(QTransaction).where(QTransaction.id == t.id).values(created_at=week_center)
            )


async def ensure_wallets_under_mpw(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Гарантировать, что wallet_main не превышает mpw после изменений MPW."""
    for user in users_by_email.values():
        # Для админов mpw=0 допускает любой wallet_main, т.к. они не выполняют задачи
        if user.mpw > 0 and user.wallet_main > user.mpw:
            user.wallet_main = user.mpw
            session.add(user)


async def ensure_karma_demo(session: AsyncSession, users_by_email: dict[str, User]) -> None:
    """Начислить карму для демо магазина."""
    maria = users_by_email.get("orlovskaya@ac.gov.ru")
    if not maria or float(maria.wallet_karma) > 0:
        return

    maria.wallet_karma = Decimal("15.0")
    t = QTransaction(
        user_id=maria.id,
        amount=Decimal("15.0"),
        wallet_type=WalletType.karma,
        reason="Перевыполнение плана за январь 2026",
    )
    session.add(t)

    ekaterina = users_by_email.get("zavyalova@ac.gov.ru")
    if ekaterina and float(ekaterina.wallet_karma) == 0:
        ekaterina.wallet_karma = Decimal("8.0")
        t2 = QTransaction(
            user_id=ekaterina.id,
            amount=Decimal("8.0"),
            wallet_type=WalletType.karma,
            reason="Перевыполнение плана за январь 2026",
        )
        session.add(t2)


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
            await ensure_knowledge_articles(session)
            await ensure_tasks(session, users, catalog)
            await ensure_extended_test_tasks(session, users, catalog)
            await ensure_shop_items(session)
            await ensure_burndown_transactions(session, users)
            await ensure_capacity_history(session, users)
            await ensure_karma_demo(session, users)
            await ensure_demo_notifications(session, users)
            await ensure_wallets_under_mpw(session, users)
            await session.commit()
            print("Seed выполнен успешно.")
        except Exception as e:
            await session.rollback()
            raise e


if __name__ == "__main__":
    asyncio.run(run_seed())
