import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CalibrationReport, User } from '@/api/types'
import { MetricCard } from '@/components/MetricCard'
import { cn } from '@/lib/utils'

export function CalibrationPage() {
  const [report, setReport] = useState<CalibrationReport | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState('')
  const [period, setPeriod] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const currentUser = users.find((u) => u.id === currentUserId)
  const canView = currentUser?.role === 'teamlead' || currentUser?.role === 'admin'

  const load = useCallback(() => {
    if (!canView) return
    const params = period ? { period } : {}
    api
      .get<CalibrationReport>('/api/dashboard/calibration', params)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [canView, period])

  useEffect(() => {
    api.get<User[]>('/api/users').then((list) => {
      setUsers(list)
      if (list.length && !currentUserId) setCurrentUserId(list[0].id)
    }).catch(() => setUsers([]))
  }, [])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  const itemsWithDeviation = report?.items.filter((i) => i.recommendation !== 'OK').length ?? 0
  const accuracyColor =
    (report?.overall_accuracy_percent ?? 0) > 80
      ? 'text-emerald-600'
      : (report?.overall_accuracy_percent ?? 0) >= 60
        ? 'text-amber-600'
        : 'text-red-600'

  if (!canView && users.length > 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Калибровка</h1>
        <p className="text-slate-600">Доступ разрешён только тимлидам и администраторам.</p>
        {users.length > 0 && (
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </select>
        )}
      </div>
    )
  }

  if (loading && !report) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Калибровка нормативов</h1>
        {users.length > 0 && (
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </select>
        )}
      </div>

      {report && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              title="Точность нормативов"
              value={`${Number(report.overall_accuracy_percent).toFixed(1)}%`}
              subtitle={report.period === 'all' ? 'За всё время' : `Период ${report.period}`}
              className={accuracyColor}
            />
            <MetricCard
              title="Задач проанализировано"
              value={report.total_tasks_analyzed}
            />
            <MetricCard
              title="Операций с отклонением"
              value={itemsWithDeviation}
            />
          </div>

          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-slate-700">Период:</label>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">Текущий месяц</option>
              <option value="all">Все данные</option>
            </select>
          </div>

          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Операция</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Категория</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Сложность</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Норматив (Q)</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Задач</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Ср. оценка</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Ср. факт (ч)</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Отклонение</th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">Рекомендация</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {[...report.items]
                  .sort((a, b) => {
                    const da = a.deviation_percent != null ? Math.abs(a.deviation_percent) : 0
                    const db = b.deviation_percent != null ? Math.abs(b.deviation_percent) : 0
                    return db - da
                  })
                  .map((item) => (
                  <tr
                    key={item.catalog_item_id}
                    className={cn(
                      'bg-white',
                      item.recommendation === 'Завышена' && 'bg-amber-50',
                      item.recommendation === 'Занижена' && 'bg-red-50'
                    )}
                    title={item.recommendation !== 'OK' ? 'Рекомендуется пересмотреть base_cost_q' : undefined}
                  >
                    <td className="px-4 py-2 font-medium text-slate-900">{item.name}</td>
                    <td className="px-4 py-2 text-slate-600">{item.category}</td>
                    <td className="px-4 py-2 text-slate-600">{item.complexity}</td>
                    <td className="px-4 py-2">{Number(item.base_cost_q).toFixed(1)}</td>
                    <td className="px-4 py-2">{item.tasks_count}</td>
                    <td className="px-4 py-2">{Number(item.avg_estimated_q).toFixed(1)}</td>
                    <td className="px-4 py-2">
                      {item.avg_actual_hours != null ? Number(item.avg_actual_hours).toFixed(1) : '—'}
                    </td>
                    <td className="px-4 py-2">
                      {item.deviation_percent != null ? `${Number(item.deviation_percent).toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-2">
                      {item.recommendation === 'OK' && '✅ OK'}
                      {item.recommendation === 'Завышена' &&
                        `⬆️ Завышена на ${item.deviation_percent != null ? Math.abs(Number(item.deviation_percent)).toFixed(0) : 0}%`}
                      {item.recommendation === 'Занижена' &&
                        `⬇️ Занижена на ${item.deviation_percent != null ? Math.abs(Number(item.deviation_percent)).toFixed(0) : 0}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {report.items.length === 0 && (
              <p className="p-6 text-center text-slate-500">Нет данных для анализа</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
