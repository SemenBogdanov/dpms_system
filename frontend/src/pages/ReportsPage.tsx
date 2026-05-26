import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type {
  ActivityEvent,
  EmployeePeriodSummary,
  EmployeeSummaryTask,
  PeriodHistoryItem,
  PeriodReport,
  TasksExport,
  User,
} from '@/api/types'
import { MetricCard } from '@/components/MetricCard'
import toast from 'react-hot-toast'
import { cn } from '@/lib/utils'
import { FileText, Search } from 'lucide-react'

const eventLabels: Record<string, string> = {
  login_success: 'Вход',
  task_created: 'Задача создана',
  task_updated: 'Задача изменена',
  task_due_date_updated: 'Срок изменен',
  task_cancelled: 'Задача отменена',
  task_pulled: 'Задача взята',
  task_assigned: 'Задача назначена',
  task_submitted: 'Сдано на проверку',
  task_verified: 'Задача принята',
  task_rejected: 'Задача отклонена',
  focus_start: 'Фокус старт',
  focus_pause: 'Фокус пауза',
  focus_auto_pause: 'Фокус автопауза',
  focus_time_corrected: 'Время исправлено',
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function monthStartIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

function currentPeriodIso(): string {
  return new Date().toISOString().slice(0, 7)
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatHours(seconds: number): string {
  if (!seconds) return '0 ч'
  const hours = seconds / 3600
  return `${hours.toFixed(hours >= 10 ? 0 : 1)} ч`
}

function taskStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    in_queue: 'В очереди',
    in_progress: 'В работе',
    review: 'На проверке',
    done: 'Принята',
    cancelled: 'Отменена',
  }
  return labels[status] ?? status
}

function TaskSummaryTable({ title, tasks }: { title: string; tasks: EmployeeSummaryTask[] }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-medium text-slate-800">{title}</h3>
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500">{tasks.length}</span>
      </div>
      {tasks.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-3 py-2 text-left font-medium text-slate-600">Задача</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Статус</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Q</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Фокус</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Паузы</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Принята</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-800">#{task.task_number} {task.title}</div>
                    <div className="text-xs text-slate-500">{task.task_type} · {task.priority}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{taskStatusLabel(task.status)}</td>
                  <td className="px-3 py-2 text-slate-600">{Number(task.estimated_q).toFixed(1)}</td>
                  <td className="px-3 py-2 text-slate-600">{formatHours(task.active_seconds)}</td>
                  <td className="px-3 py-2 text-slate-600">{task.pause_count + task.auto_pause_count}</td>
                  <td className="px-3 py-2 text-slate-600">{formatDateTime(task.validated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Нет задач в этом блоке.</p>
      )}
    </section>
  )
}

function ActivityTable({ events }: { events: ActivityEvent[] }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 font-medium text-slate-800">Последняя активность</h3>
      {events.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-3 py-2 text-left font-medium text-slate-600">Время</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Действие</th>
                <th className="px-3 py-2 text-left font-medium text-slate-600">Задача</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2 text-slate-600">{formatDateTime(event.occurred_at)}</td>
                  <td className="px-3 py-2 font-medium text-slate-700">{eventLabels[event.event_type] ?? event.event_type}</td>
                  <td className="px-3 py-2 text-slate-600">
                    {event.task_number ? `#${event.task_number} ${event.task_title ?? ''}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500">Активность за период пока не зафиксирована.</p>
      )}
    </section>
  )
}

export function ReportsPage() {
  const [period, setPeriod] = useState(currentPeriodIso())
  const [report, setReport] = useState<PeriodReport | null>(null)
  const [history, setHistory] = useState<PeriodHistoryItem[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [summaryStartDate, setSummaryStartDate] = useState(monthStartIso())
  const [summaryEndDate, setSummaryEndDate] = useState(todayIso())
  const [employeeSummary, setEmployeeSummary] = useState<EmployeePeriodSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [exportTasksLoading, setExportTasksLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)

  useEffect(() => {
    api.get<PeriodHistoryItem[]>('/api/admin/period-history').then(setHistory).catch(() => setHistory([]))
    api
      .get<User[]>('/api/users', { is_active: 'true' })
      .then((items) => {
        setUsers(items)
        const firstExecutor = items.find((u) => u.role === 'executor') ?? items[0]
        if (firstExecutor) setSelectedUserId(firstExecutor.id)
      })
      .catch(() => setUsers([]))
  }, [])

  const loadReport = useCallback(() => {
    const p = period || new Date().toISOString().slice(0, 7)
    setLoading(true)
    setError(null)
    api
      .get<PeriodReport>(`/api/reports/${p}`)
      .then(setReport)
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Ошибка')
        setReport(null)
      })
      .finally(() => setLoading(false))
  }, [period])

  const currentPeriod = period || currentPeriodIso()

  const loadEmployeeSummary = useCallback(() => {
    if (!selectedUserId) {
      setSummaryError('Выберите сотрудника')
      return
    }
    setSummaryLoading(true)
    setSummaryError(null)
    api
      .get<EmployeePeriodSummary>('/api/reports/employee-summary', {
        user_id: selectedUserId,
        start_date: summaryStartDate,
        end_date: summaryEndDate,
      })
      .then(setEmployeeSummary)
      .catch((e) => {
        setSummaryError(e instanceof Error ? e.message : 'Ошибка')
        setEmployeeSummary(null)
      })
      .finally(() => setSummaryLoading(false))
  }, [selectedUserId, summaryEndDate, summaryStartDate])

  const handleExport = () => {
    if (!report) return
    const header = 'ФИО,Лига,% Выполнения,Задач завершено\n'
    const body = report.team_members
        .map((m) => `${m.full_name},${m.league},${Number(m.percent).toFixed(1)},${m.tasks_completed}`)
        .join('\n')
    const blob = new Blob(['\ufeff' + header + body], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dpms-report-${report.period}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleExportTasks = () => {
    setExportTasksLoading(true)
    api
      .get<TasksExport>('/api/tasks/export', { period: currentPeriod })
      .then((data) => {
        const header = 'Название,Категория,Сложность,Оценка (Q),Исполнитель,Начало,Завершение,Время (ч),Валидатор,Статус\n'
        const body = data.rows
          .map((r) =>
            [
              `"${r.title.replace(/"/g, '""')}"`,
              r.category,
              r.complexity,
              Number(r.estimated_q).toFixed(1),
              `"${(r.assignee_name || '').replace(/"/g, '""')}"`,
              r.started_at ?? '',
              r.completed_at ?? '',
              r.duration_hours != null ? Number(r.duration_hours).toFixed(1) : '',
              r.validator_name ? `"${r.validator_name.replace(/"/g, '""')}"` : '',
              r.status,
            ].join(',')
          )
          .join('\n')
        const blob = new Blob(['\ufeff' + header + body], { type: 'text/csv;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `dpms-tasks-${data.period}.csv`
        a.click()
        URL.revokeObjectURL(url)
        toast.success(`Выгружено задач: ${data.total_tasks}`)
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка выгрузки'))
      .finally(() => setExportTasksLoading(false))
  }
    /*
    const by_league: Record<string, Array<{ full_name: string; league: string; mpw: number; earned: number; percent: number; karma: number; in_progress_q: number; is_at_risk: boolean }>> = { A: [], B: [], C: [] }
    report.team_members.forEach((m) => {
      const row = {
        full_name: m.full_name,
        league: m.league,
        mpw: 0,
        earned: 0,
        percent: m.percent,
        karma: 0,
        in_progress_q: 0,
        is_at_risk: m.percent < 50,
      }
      const key = m.league in by_league ? m.league : 'C'
      by_league[key].push(row)
    })
    exportTeamCSV({ by_league }) 
  }*/

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Отчёты за период</h1>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">Текущий месяц</option>
            {history.map((h) => (
              <option key={h.period} value={h.period}>{h.period}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={loadReport}
            disabled={loading}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? '...' : 'Сформировать'}
          </button>
          {report && (
            <button
              type="button"
              onClick={handleExport}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              📊 Экспорт CSV
            </button>
          )}
          <button
            type="button"
            onClick={handleExportTasks}
            disabled={exportTasksLoading}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {exportTasksLoading ? '...' : '📋 Выгрузить задачи (CSV)'}
          </button>
        </div>
      </div>

      {error && <p className="text-red-600">{error}</p>}

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-medium text-slate-800">Сводка по сотруднику</h2>
            <p className="text-sm text-slate-500">План, факт, эффективность, задачи и работа с фокусом за период.</p>
          </div>
          <button
            type="button"
            onClick={loadEmployeeSummary}
            disabled={summaryLoading || !selectedUserId}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Search className="h-4 w-4" />
            {summaryLoading ? 'Формируется...' : 'Сформировать сводку'}
          </button>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(220px,1fr)_170px_170px]">
          <label className="space-y-1 text-sm">
            <span className="font-medium text-slate-600">Сотрудник</span>
            <select
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">Выберите сотрудника</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name} · {u.role}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-slate-600">Начало</span>
            <input
              type="date"
              value={summaryStartDate}
              onChange={(e) => setSummaryStartDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="font-medium text-slate-600">Окончание</span>
            <input
              type="date"
              value={summaryEndDate}
              onChange={(e) => setSummaryEndDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            />
          </label>
        </div>
        {summaryError && <p className="mt-3 text-sm text-red-600">{summaryError}</p>}
      </section>

      {employeeSummary && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{employeeSummary.full_name}</h2>
              <p className="text-sm text-slate-500">
                {employeeSummary.start_date} — {employeeSummary.end_date} · Лига {employeeSummary.league} · {employeeSummary.role}
              </p>
            </div>
            <span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600">
              <FileText className="h-4 w-4" />
              Сводка для доклада
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard title="План" value={Number(employeeSummary.plan_q).toFixed(1)} subtitle="Q" />
            <MetricCard title="Факт" value={Number(employeeSummary.completed_q).toFixed(1)} subtitle="Q принято" />
            <MetricCard title="Эффективность" value={`${Number(employeeSummary.efficiency_percent).toFixed(1)}%`} />
            <MetricCard title="Фокус" value={Number(employeeSummary.focus.total_focus_hours).toFixed(1)} subtitle="часов" />
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h3 className="mb-3 font-medium text-slate-800">Контрольные показатели</h3>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4 lg:grid-cols-8">
              <div>
                <p className="text-slate-500">Принято задач</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.completed_tasks_count}</p>
              </div>
              <div>
                <p className="text-slate-500">В работе</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.in_progress_tasks_count}</p>
              </div>
              <div>
                <p className="text-slate-500">На проверке</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.review_tasks_count}</p>
              </div>
              <div>
                <p className="text-slate-500">Возвраты</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.rejected_tasks_count}</p>
              </div>
              <div>
                <p className="text-slate-500">Отсутствия</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.absence_working_days} дн.</p>
              </div>
              <div>
                <p className="text-slate-500">Стартов фокуса</p>
                <p className="text-lg font-semibold text-slate-900">{employeeSummary.focus.focus_start_count}</p>
              </div>
              <div>
                <p className="text-slate-500">Пауз</p>
                <p className="text-lg font-semibold text-slate-900">
                  {employeeSummary.focus.focus_pause_count + employeeSummary.focus.focus_auto_pause_count}
                </p>
              </div>
              <div>
                <p className="text-slate-500">Пауз/задачу</p>
                <p className="text-lg font-semibold text-slate-900">{Number(employeeSummary.focus.avg_pauses_per_task).toFixed(2)}</p>
              </div>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <TaskSummaryTable title="Принятые задачи" tasks={employeeSummary.completed_tasks} />
            <TaskSummaryTable title="Задачи в работе" tasks={employeeSummary.in_progress_tasks} />
            <TaskSummaryTable title="На проверке" tasks={employeeSummary.review_tasks} />
            <TaskSummaryTable title="Возвращались на доработку" tasks={employeeSummary.rejected_tasks} />
          </div>

          <ActivityTable events={employeeSummary.recent_activity} />
        </div>
      )}

      {report && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard title="Ёмкость" value={Number(report.total_capacity).toFixed(0)} subtitle="Q" />
            <MetricCard title="Заработано" value={Number(report.total_earned).toFixed(1)} subtitle="Q" />
            <MetricCard title="Утилизация" value={`${Number(report.utilization_percent).toFixed(1)}%`} />
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 font-medium text-slate-800">Команда</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  <th className="px-4 py-2 text-left font-medium text-slate-600">ФИО</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Лига</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">%</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Задач завершено</th>
                </tr>
              </thead>
              <tbody>
                {report.team_members.map((m, i) => {
                  const isTop = report.top_performers.some((t) => t.full_name === m.full_name)
                  const isUnder = report.underperformers.some((u) => u.full_name === m.full_name)
                  return (
                    <tr
                      key={m.full_name + i}
                      className={cn(
                        'border-b border-slate-100',
                        isTop && 'bg-amber-50',
                        isUnder && 'bg-red-50'
                      )}
                    >
                      <td className="px-4 py-2">
                        {isTop && '🏆 '}
                        {isUnder && '⚠️ '}
                        {m.full_name}
                      </td>
                      <td className="px-4 py-2">{m.league}</td>
                      <td className="px-4 py-2">{Number(m.percent).toFixed(1)}</td>
                      <td className="px-4 py-2">{m.tasks_completed}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Задач создано</p>
              <p className="text-2xl font-semibold text-slate-900">{report.tasks_overview.total_created}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Задач завершено</p>
              <p className="text-2xl font-semibold text-slate-900">{report.tasks_overview.total_completed}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Ср. время (ч)</p>
              <p className="text-2xl font-semibold text-slate-900">
                {report.tasks_overview.avg_time_hours != null
                  ? Number(report.tasks_overview.avg_time_hours).toFixed(1)
                  : '—'}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">По категориям</p>
              <p className="text-sm text-slate-700">
                {Object.entries(report.tasks_overview.by_category).map(([k, v]) => `${k}: ${v}`).join(', ') || '—'}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="font-medium text-slate-800">Магазин</h3>
              <p className="text-sm text-slate-600">Покупок: {report.shop_activity.total_purchases}</p>
              <p className="text-sm text-slate-600">Кармы потрачено: {Number(report.shop_activity.total_karma_spent).toFixed(1)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <h3 className="font-medium text-slate-800">Калибровка</h3>
              <p className="text-sm text-slate-600">Точные: {report.calibration_summary.accurate_count}</p>
              <p className="text-sm text-slate-600">Завышена: {report.calibration_summary.overestimated_count}</p>
              <p className="text-sm text-slate-600">Занижена: {report.calibration_summary.underestimated_count}</p>
            </div>
          </div>
        </>
      )}

      {!report && !loading && !error && (
        <p className="text-slate-500">Выберите период и нажмите «Сформировать».</p>
      )}
    </div>
  )
}
