import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type {
  CapacityGauge,
  TeamSummary,
  PeriodStats,
  TeamMemberSummary,
  BurndownData,
} from '@/api/types'
import { GlassGauge } from '@/components/GlassGauge'
import { MetricCard } from '@/components/MetricCard'
import { TeamPulseTable } from '@/components/TeamPulseTable'
import { BurndownChart } from '@/components/BurndownChart'
import { exportTeamCSV } from '@/lib/csv'

export function DashboardPage() {
  const [capacity, setCapacity] = useState<CapacityGauge | null>(null)
  const [team, setTeam] = useState<TeamSummary | null>(null)
  const [periodStats, setPeriodStats] = useState<PeriodStats | null>(null)
  const [burndown, setBurndown] = useState<BurndownData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [cap, sum, period, bd] = await Promise.all([
        api.get<CapacityGauge>('/api/dashboard/capacity'),
        api.get<TeamSummary>('/api/dashboard/team-summary'),
        api.get<PeriodStats>('/api/dashboard/period-stats'),
        api.get<BurndownData>('/api/dashboard/burndown'),
      ])
      setCapacity(cap)
      setTeam(sum)
      setPeriodStats(period)
      setBurndown(bd)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [load])

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  const loadVal = Number(capacity?.load ?? 0)
  const capVal = Number(capacity?.capacity ?? 0)
  const util = Number(capacity?.utilization ?? 0)
  const status = (capacity?.status ?? 'green') as 'green' | 'yellow' | 'red'

  const allMembers: TeamMemberSummary[] = []
  if (team?.by_league) {
    Object.values(team.by_league).forEach((arr) => arr.forEach((m) => allMembers.push(m)))
  }

  const avgTimeDays =
    periodStats?.avg_completion_time_hours != null
      ? Number(periodStats.avg_completion_time_hours / 24).toFixed(1)
      : '—'

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

      {/* Строка 1 — 4 карточки метрик */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Ёмкость команды"
          value={`${Number(capVal).toFixed(0)} Q`}
        />
        <MetricCard
          title="Текущая нагрузка"
          value={`${Number(loadVal).toFixed(0)} Q`}
          subtitle={`${Number(util).toFixed(0)}%`}
        />
        <MetricCard
          title="Задач завершено"
          value={periodStats?.tasks_completed ?? 0}
          subtitle="в этом месяце"
        />
        <MetricCard
          title="Среднее время"
          value={avgTimeDays === '—' ? '—' : `${avgTimeDays} д.`}
          subtitle="выполнения задачи"
        />
      </div>

      {/* Строка 2 — Стакан + Пульс команды */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_2.5fr]">
        <div className="space-y-2">
          {capacity && (
            <GlassGauge
              load={loadVal}
              capacity={capVal}
              utilization={util}
              status={status}
            />
          )}
          <p className="text-sm text-slate-600">
            Ёмкость: {Number(capVal).toFixed(0)} Q · Нагрузка: {Number(loadVal).toFixed(0)} Q · Утилизация: {Number(util).toFixed(1)}%
          </p>
        </div>
        <div>
          <h2 className="mb-2 font-medium text-slate-800">Пульс команды</h2>
          <TeamPulseTable members={allMembers} />
        </div>
      </div>

      {/* Burn-down */}
      {burndown && burndown.points.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 font-medium text-slate-800">Burn-down: План vs Факт</h2>
          <BurndownChart data={burndown} />
        </div>
      )}

      {/* Строка 3 — По лигам */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {['A', 'B', 'C'].map((league) => {
          const list = team?.by_league?.[league] ?? []
          const count = list.length
          const avg =
            count > 0
              ? Number(list.reduce((s, m) => s + m.percent, 0) / count).toFixed(0)
              : '—'
          return (
            <MetricCard
              key={league}
              title={`Лига ${league}`}
              value={count === 0 ? '—' : `${count} чел, avg ${avg}%`}
            />
          )
        })}
      </div>
    </div>
  )
}
