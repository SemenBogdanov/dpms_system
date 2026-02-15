"""
Логика повышения/понижения лиги на основе PeriodSnapshot.

Правила:
  C → B: 3 месяца подряд выполнение плана ≥ 90%, минимум 10 завершённых задач за последний месяц
  B → A: 3 месяца подряд выполнение плана ≥ 95%, минимум 15 завершённых задач за последний месяц
  A → B: 2 месяца подряд выполнение плана < 60%
  B → C: 2 месяца подряд выполнение плана < 50%
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import PeriodSnapshot
from app.models.user import User, League
from app.schemas.leagues import LeagueEvaluation, LeagueChange


def _percent(snapshot: PeriodSnapshot) -> float:
    """Процент выполнения плана за период (mpw > 0)."""
    if snapshot.mpw <= 0:
        return 100.0
    return round(float(snapshot.earned_main) / snapshot.mpw * 100, 1)


async def evaluate_league_change(db: AsyncSession, user_id: UUID) -> LeagueEvaluation:
    """
    Оценить, подходит ли пользователь для смены лиги.
    Возвращает current_league, suggested_league, reason, eligible, history (последние 3 снэпшота).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return LeagueEvaluation(
            user_id=str(user_id),
            full_name="",
            current_league="C",
            suggested_league="C",
            reason="Пользователь не найден",
            eligible=False,
            history=[],
        )

    snapshots_result = await db.execute(
        select(PeriodSnapshot)
        .where(PeriodSnapshot.user_id == user_id)
        .order_by(PeriodSnapshot.period.desc())
        .limit(12)
    )
    snapshots = list(snapshots_result.scalars().all())
    history = [{"period": s.period, "percent": _percent(s)} for s in snapshots]

    current = user.league
    suggested = current
    reason = "Без изменений"
    eligible = False

    if not snapshots:
        return LeagueEvaluation(
            user_id=str(user.id),
            full_name=user.full_name,
            current_league=current.value,
            suggested_league=current.value,
            reason="Нет снимков периодов",
            eligible=False,
            history=[],
        )

    last = snapshots[0]
    last_percent = _percent(last)
    last_tasks = last.tasks_completed

    # Понижение A → B: 2 месяца подряд < 60%
    if current == League.A and len(snapshots) >= 2:
        if _percent(snapshots[0]) < 60 and _percent(snapshots[1]) < 60:
            suggested = League.B
            reason = "2 месяца подряд выполнение плана < 60%"
            eligible = True

    # Понижение B → C: 2 месяца подряд < 50%
    if current == League.B and len(snapshots) >= 2 and not eligible:
        if _percent(snapshots[0]) < 50 and _percent(snapshots[1]) < 50:
            suggested = League.C
            reason = "2 месяца подряд выполнение плана < 50%"
            eligible = True

    # Повышение C → B: 3 месяца подряд ≥ 90%, последний месяц ≥ 10 задач
    if current == League.C and not eligible and len(snapshots) >= 3:
        if (
            _percent(snapshots[0]) >= 90
            and _percent(snapshots[1]) >= 90
            and _percent(snapshots[2]) >= 90
            and last_tasks >= 10
        ):
            suggested = League.B
            reason = "3 месяца подряд ≥ 90%, в последнем месяце ≥ 10 задач"
            eligible = True

    # Повышение B → A: 3 месяца подряд ≥ 95%, последний месяц ≥ 15 задач
    if current == League.B and not eligible and len(snapshots) >= 3:
        if (
            _percent(snapshots[0]) >= 95
            and _percent(snapshots[1]) >= 95
            and _percent(snapshots[2]) >= 95
            and last_tasks >= 15
        ):
            suggested = League.A
            reason = "3 месяца подряд ≥ 95%, в последнем месяце ≥ 15 задач"
            eligible = True

    return LeagueEvaluation(
        user_id=str(user.id),
        full_name=user.full_name,
        current_league=current.value,
        suggested_league=suggested.value,
        reason=reason,
        eligible=eligible and suggested != current,
        history=history[:3],
    )


async def apply_league_changes(db: AsyncSession, admin_id: UUID) -> list[LeagueChange]:
    """
    Применить все повышения/понижения лиг. Только для admin.
    Для каждого пользователя: evaluate → если eligible → обновить user.league.
    Возвращает список изменений.
    """
    from app.models.user import UserRole

    admin_result = await db.execute(select(User).where(User.id == admin_id))
    admin = admin_result.scalar_one_or_none()
    if not admin or admin.role != UserRole.admin:
        return []

    users_result = await db.execute(
        select(User).where(User.is_active.is_(True))
    )
    users = users_result.scalars().all()
    changes: list[LeagueChange] = []

    for user in users:
        ev = await evaluate_league_change(db, user.id)
        if not ev.eligible or ev.suggested_league == ev.current_league:
            continue
        old_league = user.league
        user.league = League(ev.suggested_league)
        changes.append(
            LeagueChange(
                user_id=str(user.id),
                full_name=user.full_name,
                old_league=old_league.value,
                new_league=ev.suggested_league,
                reason=ev.reason,
            )
        )
        from app.services.notifications import create_notification
        await create_notification(
            db,
            user.id,
            "league_change",
            "Изменение лиги",
            message=f"Ваша лига изменена: {old_league.value} → {ev.suggested_league}",
            link="/profile",
        )
    return changes
