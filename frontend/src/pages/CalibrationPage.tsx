import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CalibrationReportNew } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { MetricCard } from '@/components/MetricCard'

function deviationColor(pct: number): string {
  const abs = Math.abs(pct)
  if (abs <= 15) return 'text-emerald-600'
  if (abs <= 30) return 'text-amber-600'
  return 'text-red-600'
}

export function CalibrationPage() {
  const { user: currentUser } = useAuth()
  const [data, setData] = useState<CalibrationReportNew | null>(null)
  const [period, setPeriod] = useState<string>('')
  const [activeTab, setActiveTab] = useState<'tasks' | 'estimators' | 'popularity'>('tasks')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const canView = currentUser?.role === 'teamlead' || currentUser?.role === 'admin'

  const load = useCallback(() => {
    if (!canView) return
    setLoading(true)
    const params = period ? { period } : undefined
    api
      .get<CalibrationReportNew>('/api/dashboard/calibration', params)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [canView, period])

  useEffect(() => {
    load()
  }, [load])

  if (!canView) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Калибровка</h1>
        <p className="text-slate-600">Доступ разрешён только тимлидам и администраторам.</p>
      </div>
    )
  }

  if (loading && !data) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Калибровка нормативов</h1>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
          Период:
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">Текущий месяц</option>
            <option value="all">Все данные</option>
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricCard title="Точность оценок" value={`${data.overall_accuracy_pct}%`} />
        <MetricCard title="Задач проанализировано" value={data.total_tasks_analyzed} />
        <MetricCard
          title="Ср. отклонение"
          value={`${data.avg_deviation_pct > 0 ? '+' : ''}${data.avg_deviation_pct}%`}
        />
      </div>

      <div className="flex gap-1 border-b border-slate-200 pb-2">
        {[
          { key: 'tasks' as const, label: 'По задачам' },
          { key: 'estimators' as const, label: 'По оценщикам' },
          { key: 'popularity' as const, label: 'Популярность операций' },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-md px-4 py-2 text-sm font-medium ${
              activeTab === tab.key
                ? 'bg-primary text-primary-foreground'
                : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'tasks' && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Задача</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Тип</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Слож.</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Оценка Q</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Продуктивное время</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Откл.</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Оценщик</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Исполнитель</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Теги</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.task_calibrations.map((tc) => (
                <tr key={tc.task_id} className="bg-white">
                  <td className="px-4 py-2 font-medium text-slate-900">{tc.title}</td>
                  <td className="px-4 py-2 text-slate-600">{tc.task_type}</td>
                  <td className="px-4 py-2 text-slate-600">{tc.complexity}</td>
                  <td className="px-4 py-2">{Number(tc.estimated_q).toFixed(1)}</td>
                  <td className="px-4 py-2">
                    {tc.actual_hours > 0 ? (
                      `${Number(tc.actual_hours).toFixed(1)}ч`
                    ) : (
                      <span className="text-slate-500">⚠️ wall-clock</span>
                    )}
                  </td>
                  <td className={`px-4 py-2 font-semibold ${deviationColor(tc.deviation_pct)}`}>
                    {tc.deviation_pct > 0 ? '+' : ''}{tc.deviation_pct}%
                  </td>
                  <td className="px-4 py-2 text-slate-600">{tc.estimator_name}</td>
                  <td className="px-4 py-2 text-slate-600">{tc.assignee_name}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {tc.tags.length > 0 ? tc.tags.join(', ') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.task_calibrations.length === 0 && (
            <p className="p-6 text-center text-slate-500">Нет завершённых задач за период</p>
          )}
        </div>
      )}

      {activeTab === 'estimators' && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Оценщик</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Задач</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Точность</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Ср.откл.</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Тенденция</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Завышает</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Занижает</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {data.estimator_calibrations.map((ec) => (
                <tr key={ec.estimator_name} className="bg-white">
                  <td className="px-4 py-2 font-medium text-slate-900">{ec.estimator_name}</td>
                  <td className="px-4 py-2">{ec.tasks_count}</td>
                  <td className="px-4 py-2">{ec.accuracy_pct}%</td>
                  <td className="px-4 py-2">
                    {ec.avg_deviation_pct > 0 ? '+' : ''}{ec.avg_deviation_pct}%
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={
                        ec.bias === 'точно'
                          ? 'text-emerald-600'
                          : ec.bias === 'завышает'
                            ? 'text-amber-600'
                            : 'text-red-600'
                      }
                    >
                      {ec.bias === 'точно' ? '✅' : ec.bias === 'завышает' ? '📈' : '📉'} {ec.bias}
                    </span>
                  </td>
                  <td className="px-4 py-2">{ec.overestimates}</td>
                  <td className="px-4 py-2">{ec.underestimates}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.estimator_calibrations.length === 0 && (
            <p className="p-6 text-center text-slate-500">Нет данных по оценщикам</p>
          )}
        </div>
      )}

      {activeTab === 'popularity' && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          {data.widget_popularity.length === 0 ? (
            <p className="p-6 text-center text-slate-500">
              Нет данных за период. Задачи с декомпозицией из калькулятора появятся после создания.
            </p>
          ) : (
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Операция</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Задач</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">%</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Доля</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {data.widget_popularity.map((wp) => (
                  <tr key={wp.name} className="bg-white">
                    <td className="px-4 py-2 text-sm text-slate-900">{wp.name}</td>
                    <td className="px-4 py-2 text-sm text-slate-600">{wp.tasks_count}</td>
                    <td className="px-4 py-2 text-sm text-slate-600">{wp.usage_percent}%</td>
                    <td className="px-4 py-2 w-48">
                      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className="h-full rounded-full bg-indigo-500 transition-all"
                          style={{ width: `${Math.min(100, wp.usage_percent)}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
