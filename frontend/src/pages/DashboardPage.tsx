import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
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

type DashboardSection = 'core' | 'history' | 'overdue' | 'focus'

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
  const [loading, setLoading] = useState<Record<DashboardSection, boolean>>({ core: true, history: true, overdue: true, focus: true })
  const [error, setError] = useState<string | null>(null)
  const [focusStatuses, setFocusStatuses] = useState<FocusStatusItem[]>([])
  const [focusError, setFocusError] = useState<string | null>(null)
  const [overdueError, setOverdueError] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const request = useRef(0)
  const pending = useRef(new Set<DashboardSection>())

  const isTeamleadOrAdmin = currentUser?.role === 'teamlead' || currentUser?.role === 'admin'

  const loadSection = useCallback(async <T,>(
    section: DashboardSection,
    read: () => Promise<T>,
    commit: (result: T) => void,
    setFailure: Dispatch<SetStateAction<string | null>>,
    failureMessage?: string,
  ) => {
    if (pending.current.has(section)) return
    const revision = request.current
    pending.current.add(section)
    setLoading((previous) => ({ ...previous, [section]: true }))
    try {
      const result = await read()
      if (request.current !== revision) return
      commit(result)
      setFailure(null)
    } catch (e) {
      if (request.current === revision) setFailure(failureMessage ?? (e instanceof Error ? e.message : 'Ошибка загрузки дашборда'))
    } finally {
      if (request.current === revision) {
        pending.current.delete(section)
        setLoading((previous) => ({ ...previous, [section]: false }))
      }
    }
  }, [])

  const loadCore = useCallback(() => loadSection('core', () => Promise.all([
    api.get<CapacityGauge>('/api/dashboard/capacity'),
    api.get<TeamSummary>('/api/dashboard/team-summary'),
    api.get<BurndownData>('/api/dashboard/burndown'),
    api.get<Task[]>('/api/tasks?status=in_progress'),
    api.get<Task[]>('/api/tasks?status=review'),
  ]), ([cap, sum, bd, ip, rv]) => {
    setCapacity(cap)
    setTeam(sum)
    setBurndown(bd)
    setTasksInWorkCount((ip?.length ?? 0) + (rv?.length ?? 0))
  }, setError), [loadSection])

  const loadHistory = useCallback(() => loadSection('history',
    () => api.get<{ weeks: CapacityHistoryPoint[] }>('/api/dashboard/capacity-history'),
    (history) => setCapacityHistory(history.weeks ?? []), setHistoryError,
    'Не удалось обновить историю ёмкости. Ранее загруженные данные могут быть устаревшими.',
  ), [loadSection])

  const loadOverdue = useCallback(() => loadSection('overdue',
    () => api.get<Task[]>('/api/tasks?is_overdue=true'),
    (tasks) => setOverdueTasks(tasks.filter((task) => task.status === 'in_queue' || task.status === 'in_progress')),
    setOverdueError, 'Не удалось обновить просроченные задачи. Ранее загруженные данные могут быть устаревшими.',
  ), [loadSection])

  const loadFocus = useCallback(() => loadSection('focus',
    () => api.get<FocusStatusItem[]>('/api/dashboard/focus-status'), setFocusStatuses,
    setFocusError, 'Не удалось обновить состояние команды. Ранее загруженные данные могут быть устаревшими.',
  ), [loadSection])

  const load = useCallback(() => {
    void loadCore()
    void loadHistory()
    if (isTeamleadOrAdmin) {
      void loadOverdue()
      void loadFocus()
    }
  }, [isTeamleadOrAdmin, loadCore, loadHistory, loadOverdue, loadFocus])

  useEffect(() => {
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  useEffect(() => {
    const pendingSections = pending.current
    void load()
    const t = setInterval(load, 30000)
    return () => {
      clearInterval(t)
      request.current += 1
      pendingSections.clear()
    }
  }, [load])

  if (loading.core && !capacity) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <p role="status" className="text-sm text-slate-500 sm:col-span-2 lg:col-span-4">Загрузка основных данных...</p>
        {[1, 2, 3, 4].map((i) => (
          <SkeletonCard key={i} />
        ))}
        <div className="sm:col-span-2 lg:col-span-4">
          <SkeletonCard />
        </div>
      </div>
    )
  }

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
      <div className="flex flex-wrap items-center justify-between gap-3">
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

      {loading.core && <p role="status" className="text-sm text-slate-500">Обновление основных данных...</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          <p>{error}{capacity ? ' Показаны ранее загруженные данные.' : ''}</p>
          <button type="button" disabled={loading.core} onClick={() => void loadCore()} className="mt-2 rounded border px-3 py-2 disabled:opacity-50">Повторить загрузку дашборда</button>
        </div>
      )}
      {loading.history && <p role="status" className="text-sm text-slate-500">Обновление истории ёмкости...</p>}
      {historyError && (
        <div role="alert" className="text-sm text-red-600">
          <p>{historyError}</p>
          <button type="button" disabled={loading.history} onClick={() => void loadHistory()} className="mt-2 rounded border px-3 py-2 disabled:opacity-50">Повторить загрузку истории</button>
        </div>
      )}

      {/* Строка 1 — три метрики */}
      {capacity && team && <>
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
      </>}

      {/* Строка 4 — просроченные (только teamlead/admin) */}
      {isTeamleadOrAdmin && (overdueTasks.length > 0 || overdueError || loading.overdue) && (
        <div className="overdue-panel rounded-xl border-2 border-red-300 bg-white p-4 shadow-sm">
          <h2 className="overdue-panel-title mb-2 font-medium text-red-700">
            ⚠️ Просроченные задачи{!overdueError && !loading.overdue && ` (${overdueTasks.length})`}
          </h2>
          {loading.overdue && <p role="status" className="mb-3 text-sm text-slate-500">Обновление просроченных задач...</p>}
          {overdueError && (
            <div role="alert" className="mb-3 text-sm text-red-600">
              <p>{overdueError}</p>
              <button type="button" disabled={loading.overdue} onClick={() => void loadOverdue()} className="mt-2 rounded border px-3 py-2 disabled:opacity-50">Повторить загрузку просрочек</button>
            </div>
          )}
          <ul className="space-y-1">
            {overdueTasks.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setDetailTask(t)}
                  className="overdue-panel-item text-left text-sm font-medium text-red-700 hover:underline"
                >
                  🔴 #{t.task_number} «{t.title}» — {users.find((u) => u.id === t.assignee_id)?.full_name ?? '—'} — просрочено
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
          {loading.focus && <p role="status" className="mb-3 text-sm text-slate-500">Обновление состояния команды...</p>}
          {focusError && (
            <div role="alert" className="mb-3 text-sm text-red-600">
              <p>{focusError}</p>
              <button type="button" disabled={loading.focus} onClick={() => void loadFocus()} className="mt-2 rounded border px-3 py-2 disabled:opacity-50">Повторить загрузку команды</button>
            </div>
          )}
          {focusStatuses.length === 0 ? (
            !focusError && !loading.focus && <p className="text-sm text-slate-500">Нет активных исполнителей.</p>
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
