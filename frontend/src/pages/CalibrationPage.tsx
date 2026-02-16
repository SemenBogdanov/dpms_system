import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CalibrationReport, TeamleadAccuracy as TeamleadAccuracyType } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { MetricCard } from '@/components/MetricCard'
import { cn } from '@/lib/utils'

export function CalibrationPage() {
  const { user: currentUser } = useAuth()
  const [report, setReport] = useState<CalibrationReport | null>(null)
  const [teamleadAccuracy, setTeamleadAccuracy] = useState<TeamleadAccuracyType[]>([])
  const [period, setPeriod] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const canView =
    currentUser?.role === 'teamlead' || currentUser?.role === 'admin'

  const load = useCallback(() => {
    if (!canView) return
    const params: Record<string, string> | undefined = period
      ? { period }
      : undefined
    setLoading(true)
    api
      .get<CalibrationReport>('/api/dashboard/calibration', params)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
    api
      .get<TeamleadAccuracyType[]>('/api/dashboard/teamlead-accuracy')
      .then(setTeamleadAccuracy)
      .catch(() => setTeamleadAccuracy([]))
      .finally(() => setLoading(false))
  }, [canView, period])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  const itemsWithDeviation =
    report?.items.filter((i) => i.recommendation !== 'OK').length ?? 0
  const accuracyColor =
    (report?.overall_accuracy_percent ?? 0) > 80
      ? 'text-emerald-600'
      : (report?.overall_accuracy_percent ?? 0) >= 60
        ? 'text-amber-600'
        : 'text-red-600'

  if (!canView) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold text-slate-900">Калибровка</h1>
        <p className="text-slate-600">
          Доступ разрешён только тимлидам и администраторам.
        </p>
      </div>
    )
  }

  if (loading && !report)
    return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">
          Калибровка нормативов
        </h1>
      </div>

      {report && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              title="Точность нормативов"
              value={`${Number(report.overall_accuracy_percent).toFixed(1)}%`}
              subtitle={
                report.period === 'all'
                  ? 'За всё время'
                  : `Период ${report.period}`
              }
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
            <label className="text-sm font-medium text-slate-700">
              Период:
            </label>
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
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Операция
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Категория
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Сложность
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Норматив (Q)
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Задач
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Ср. оценка
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Ср. факт (ч)
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Отклонение
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-slate-600">
                    Рекомендация
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {[...report.items]
                  .sort((a, b) => {
                    const da =
                      a.deviation_percent != null
                        ? Math.abs(a.deviation_percent)
                        : 0
                    const db =
                      b.deviation_percent != null
                        ? Math.abs(b.deviation_percent)
                        : 0
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
                      title={
                        item.recommendation !== 'OK'
                          ? 'Рекомендуется пересмотреть base_cost_q'
                          : undefined
                      }
                    >
                      <td className="px-4 py-2 font-medium text-slate-900">
                        {item.name}
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {item.category}
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {item.complexity}
                      </td>
                      <td className="px-4 py-2">
                        {Number(item.base_cost_q).toFixed(1)}
                      </td>
                      <td className="px-4 py-2">{item.tasks_count}</td>
                      <td className="px-4 py-2">
                        {Number(item.avg_estimated_q).toFixed(1)}
                      </td>
                      <td className="px-4 py-2">
                        {item.avg_actual_hours != null
                          ? Number(item.avg_actual_hours).toFixed(1)
                          : '—'}
                      </td>
                      <td className="px-4 py-2">
                        {item.deviation_percent != null
                          ? `${Number(item.deviation_percent).toFixed(1)}%`
                          : '—'}
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
              <p className="p-6 text-center text-slate-500">
                Нет данных для анализа
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">
              📊 Точность оценок тимлидов
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-slate-600">ФИО</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-600">Задач</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-600">Точность</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-600">Смещение</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-600">Тренд</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {teamleadAccuracy.map((tl) => {
                    const accColor =
                      tl.accuracy_percent > 80
                        ? 'text-emerald-600'
                        : tl.accuracy_percent >= 60
                          ? 'text-amber-600'
                          : 'text-red-600'
                    const trendLabel =
                      tl.trend === 'improving'
                        ? '↗️ Улучшается'
                        : tl.trend === 'declining'
                          ? '↘️ Ухудшается'
                          : '→ Стабильно'
                    const trendColor =
                      tl.trend === 'improving'
                        ? 'text-emerald-600'
                        : tl.trend === 'declining'
                          ? 'text-red-600'
                          : 'text-slate-600'
                    const biasLabel =
                      tl.bias === 'overestimates'
                        ? `Завышает ${Number(tl.bias_percent).toFixed(0)}%`
                        : tl.bias === 'underestimates'
                          ? `Занижает ${Number(Math.abs(tl.bias_percent)).toFixed(0)}%`
                          : 'Нейтрально'
                    return (
                      <tr key={tl.user_id} className="bg-white">
                        <td className="px-4 py-2 font-medium text-slate-900">{tl.full_name}</td>
                        <td className="px-4 py-2">{tl.tasks_evaluated}</td>
                        <td className={cn('px-4 py-2 font-medium', accColor)}>
                          {Number(tl.accuracy_percent).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-slate-600">{biasLabel}</td>
                        <td className={cn('px-4 py-2', trendColor)}>{trendLabel}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              {teamleadAccuracy.length === 0 && (
                <p className="p-4 text-center text-slate-500">Нет данных по тимлидам</p>
              )}
            </div>
            {teamleadAccuracy.length > 0 && (() => {
              const maxBias = teamleadAccuracy.reduce(
                (max, tl) =>
                  Math.abs(tl.bias_percent) > Math.abs(max.bias_percent) ? tl : max,
                teamleadAccuracy[0]
              )
              if (maxBias.bias === 'neutral') return null
              return (
                <p className="mt-4 text-sm text-slate-600">
                  💡 {maxBias.full_name} систематически{' '}
                  {maxBias.bias === 'overestimates' ? 'завышает' : 'занижает'} оценки
                  {maxBias.bias === 'overestimates' ? '' : ' ETL-'}задач на{' '}
                  {Number(Math.abs(maxBias.bias_percent)).toFixed(0)}%.
                  Рекомендуется провести калибровку с командой.
                </p>
              )
            })()}
          </div>
        </>
      )}
    </div>
  )
}
