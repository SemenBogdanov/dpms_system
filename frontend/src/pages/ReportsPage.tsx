import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { PeriodReport, PeriodHistoryItem, TasksExport } from '@/api/types'
import { MetricCard } from '@/components/MetricCard'
import toast from 'react-hot-toast'
import { cn } from '@/lib/utils'

export function ReportsPage() {
  const [period, setPeriod] = useState('')
  const [report, setReport] = useState<PeriodReport | null>(null)
  const [history, setHistory] = useState<PeriodHistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [exportTasksLoading, setExportTasksLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<PeriodHistoryItem[]>('/api/admin/period-history').then(setHistory).catch(() => setHistory([]))
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

  useEffect(() => {
    if (period || history.length >= 0) {
      const p = period || new Date().toISOString().slice(0, 7)
      setPeriod(p)
    }
  }, [])

  const currentPeriod = period || new Date().toISOString().slice(0, 7)

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
