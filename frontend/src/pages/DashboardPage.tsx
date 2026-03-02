import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type {
  CapacityGauge,
  CapacityHistoryPoint,
  TeamSummary,
  TeamMemberSummary,
  BurndownData,
  Task,
  User,
  FocusStatusItem,
} from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { MetricCard } from '@/components/MetricCard'
import { TeamPulseTable } from '@/components/TeamPulseTable'
import { BurndownChart } from '@/components/BurndownChart'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import { SkeletonCard } from '@/components/Skeleton'
import { exportTeamCSV } from '@/lib/csv'

export function DashboardPage() {
  const { user: currentUser } = useAuth()
  const [capacity, setCapacity] = useState<CapacityGauge | null>(null)
  const [capacityHistory, setCapacityHistory] = useState<CapacityHistoryPoint[]>([])
  const [team, setTeam] = useState<TeamSummary | null>(null)
  const [burndown, setBurndown] = useState<BurndownData | null>(null)
  const [tasksInWorkCount, setTasksInWorkCount] = useState(0)
  const [overdueTasks, setOverdueTasks] = useState<Task[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [detailTask, setDetailTask] = useState<Task | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [focusStatuses, setFocusStatuses] = useState<FocusStatusItem[]>([])

  const isTeamleadOrAdmin = currentUser?.role === 'teamlead' || currentUser?.role === 'admin'

  const load = useCallback(async () => {
    try {
      const [cap, sum, bd, ip, rv] = await Promise.all([
        api.get<CapacityGauge>('/api/dashboard/capacity'),
        api.get<TeamSummary>('/api/dashboard/team-summary'),
        api.get<BurndownData>('/api/dashboard/burndown'),
        api.get<Task[]>('/api/tasks?status=in_progress'),
        api.get<Task[]>('/api/tasks?status=review'),
      ])
      setCapacity(cap)
      setTeam(sum)
      setBurndown(bd)
      setTasksInWorkCount((ip?.length ?? 0) + (rv?.length ?? 0))
      setError(null)
      const history = await api.get<{ weeks: CapacityHistoryPoint[] }>('/api/dashboard/capacity-history').catch(() => ({ weeks: [] }))
      setCapacityHistory(history.weeks ?? [])
      if (currentUser?.role === 'teamlead' || currentUser?.role === 'admin') {
        const od = await api.get<Task[]>('/api/tasks?is_overdue=true').catch(() => [])
        setOverdueTasks(od.filter((t) => t.status === 'in_progress' || t.status === 'review'))
        const fs = await api
          .get<FocusStatusItem[]>('/api/dashboard/focus-status')
          .catch(() => [])
        setFocusStatuses(fs)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [currentUser?.role])

  useEffect(() => {
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load])

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <SkeletonCard key={i} />
        ))}
        <div className="sm:col-span-2 lg:col-span-4">
          <SkeletonCard />
        </div>
      </div>
    )
  }
  if (error) return <div className="text-red-600">{error}</div>

  const loadVal = Number(capacity?.load ?? 0)
  const capVal = Number(capacity?.capacity ?? 0)
  const util = Number(capacity?.utilization ?? 0)
  const status = (capacity?.status ?? 'green') as 'green' | 'yellow' | 'red'

  const allMembers: TeamMemberSummary[] = []
  if (team?.by_league) {
    Object.values(team.by_league).forEach((arr) => arr.forEach((m) => allMembers.push(m)))
  }
  const avgQualityScore =
    allMembers.length > 0
      ? Number(
          allMembers.reduce((s, m) => s + m.quality_score, 0) / allMembers.length
        ).toFixed(0)
      : '—'
  const capacityPercent = capVal > 0 ? (loadVal / capVal) * 100 : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Дашборд руководителя</h1>
        {team && (
          <button
            type="button"
            onClick={() => exportTeamCSV(team)}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            📊 Экспорт CSV
          </button>
        )}
      </div>

      {/* Строка 1 — три метрики */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard
          title="Ёмкость команды"
          value={`${Number(util).toFixed(0)}%`}
          sparkData={capacityHistory}
        />
        <MetricCard
          title="Задач в работе"
          value={tasksInWorkCount}
        />
        <MetricCard
          title="Среднее качество"
          value={avgQualityScore === '—' ? '—' : `QS: ${avgQualityScore}`}
        />
      </div>

      {/* Строка 2 — прогресс-бар ёмкости */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-700">Ёмкость команды</span>
          <span className="whitespace-nowrap text-sm font-semibold text-slate-900">
            {Number(loadVal).toFixed(1)} / {Number(capVal).toFixed(1)} Q
          </span>
        </div>
        <div className="h-4 w-full overflow-hidden rounded-full bg-slate-200">
          <div
            className={`h-full rounded-full transition-all ${
              status === 'green' ? 'bg-emerald-500' : status === 'yellow' ? 'bg-amber-500' : 'bg-red-500'
            }`}
            style={{ width: `${Math.min(100, capacityPercent)}%` }}
          />
        </div>
      </div>

      {/* Строка 3 — таблица команды */}
      <div>
        <h2 className="mb-2 font-medium text-slate-800">Команда</h2>
        <TeamPulseTable members={allMembers} />
      </div>

      {/* Строка 4 — просроченные (только teamlead/admin) */}
      {isTeamleadOrAdmin && overdueTasks.length > 0 && (
        <div className="rounded-xl border border-red-200 bg-red-50/50 p-4 shadow-sm">
          <h2 className="mb-2 font-medium text-red-800">
            ⚠️ Просроченные задачи ({overdueTasks.length})
          </h2>
          <ul className="space-y-1">
            {overdueTasks.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setDetailTask(t)}
                  className="text-left text-sm text-red-800 hover:underline"
                >
                  🔴 «{t.title}» — {users.find((u) => u.id === t.assignee_id)?.full_name ?? '—'} — просрочено
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Строка 5 — Команда сейчас (только teamlead/admin) */}
      {isTeamleadOrAdmin && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 font-medium text-slate-800">👥 Команда сейчас</h2>
          {focusStatuses.length === 0 ? (
            <p className="text-sm text-slate-500">Нет активных исполнителей.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {focusStatuses.map((s) => (
                <li key={s.user_id} className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <span>
                      {s.status === 'focused' ? '🟢' : s.status === 'paused' ? '⏸' : '💤'}
                    </span>
                    <span className="font-medium text-slate-900">{s.full_name}</span>
                  </span>
                  <span className="text-right text-slate-600">
                    {s.status === 'focused' && s.focused_task_title
                      ? `${s.focused_task_title} — ${Math.round(s.focus_duration_minutes)}м`
                      : s.status === 'paused'
                        ? 'на паузе'
                        : 'нет задач в работе'}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {focusStatuses.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              В фокусе:{' '}
              {
                focusStatuses.filter((s) => s.status === 'focused')
                  .length
              }{' '}
              из {focusStatuses.length} исполнителей
            </p>
          )}
        </div>
      )}

      <TaskDetailModal
        task={detailTask}
        onClose={() => setDetailTask(null)}
        users={users}
      />

      {/* Строка 6 — Burn-down */}
      {burndown && burndown.points.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 font-medium text-slate-800">Burn-down: План vs Факт</h2>
          <BurndownChart data={burndown} />
        </div>
      )}
    </div>
  )
}
