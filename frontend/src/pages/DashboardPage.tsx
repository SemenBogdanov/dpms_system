import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { CapacityGauge, TeamSummary, TeamMemberSummary } from '@/api/types'
import { GlassGauge } from '@/components/GlassGauge'

export function DashboardPage() {
  const [capacity, setCapacity] = useState<CapacityGauge | null>(null)
  const [team, setTeam] = useState<TeamSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [cap, sum] = await Promise.all([
          api.get<CapacityGauge>('/api/dashboard/capacity'),
          api.get<TeamSummary>('/api/dashboard/team-summary'),
        ])
        if (!cancelled) {
          setCapacity(cap)
          setTeam(sum)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  const load = Number(capacity?.load ?? 0)
  const cap = Number(capacity?.capacity ?? 0)
  const utilization = Number(capacity?.utilization ?? 0)
  const status = (capacity?.status ?? 'green') as 'green' | 'yellow' | 'red'
  const byLeague = team?.by_league && typeof team.by_league === 'object' ? team.by_league : {}

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Дашборд</h1>
      {capacity && (
        <GlassGauge
          load={load}
          capacity={cap}
          utilization={utilization}
          status={status}
        />
      )}
      {team && (
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="font-medium text-slate-800">План / Факт по команде</h2>
          <p className="mt-1 text-sm text-slate-500">
            Сумма earned: {(Number(team.total_earned) ?? 0).toFixed(1)} Q · Загрузка: {(Number(team.total_load) ?? 0).toFixed(1)} Q
          </p>
          <div className="mt-4 space-y-3">
            {Object.entries(byLeague).map(([league, members]) => (
              <div key={league}>
                <h3 className="text-sm font-medium text-slate-600">Лига {league}</h3>
                <ul className="mt-1 space-y-1">
                  {(Array.isArray(members) ? members : []).map((m: TeamMemberSummary) => (
                    <li key={m.user_id} className="flex items-center justify-between text-sm">
                      <span>{m.full_name}</span>
                      <span className="text-slate-500">
                        {(Number(m.earned) ?? 0).toFixed(1)} / {(Number(m.target) ?? 0).toFixed(0)} Q ({(Number(m.percent) ?? 0).toFixed(0)}%)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
      {!capacity && !team && <p className="text-slate-500">Нет данных для отображения.</p>}
    </div>
  )
}
