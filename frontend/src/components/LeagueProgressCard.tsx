import type { LeagueProgress as LeagueProgressType } from '@/api/types'
import { cn } from '@/lib/utils'

interface LeagueProgressCardProps {
  data: LeagueProgressType | null
  loading?: boolean
  error?: string | null
}

/** Блок прогресса к следующей лиге на странице профиля. */
export function LeagueProgressCard({ data, loading, error }: LeagueProgressCardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="h-6 w-48 animate-pulse rounded bg-slate-200" />
        <div className="mt-4 h-4 w-full animate-pulse rounded bg-slate-100" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm text-sm text-red-600">
        {error}
      </div>
    )
  }
  if (!data) return null

  if (data.at_max) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">🏆 Максимальная лига</h3>
        <p className="mt-2 text-slate-600">{data.message}</p>
      </div>
    )
  }

  const monthLabels: Record<string, string> = {}
  const formatPeriod = (p: string) => {
    if (monthLabels[p]) return monthLabels[p]
    const [y, m] = p.split('-').map(Number)
    const d = new Date(y, (m ?? 1) - 1)
    const short = d.toLocaleDateString('ru-RU', { month: 'short' })
    monthLabels[p] = short.charAt(0).toUpperCase() + short.slice(1)
    return monthLabels[p]
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-slate-900">
        🎯 Путь к лиге {data.next_league}
      </h3>

      <div className="mt-4">
        <div className="flex items-center gap-2">
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.min(100, data.overall_progress)}%` }}
            />
          </div>
          <span className="text-sm font-medium text-slate-700">
            {Number(data.overall_progress).toFixed(0)}% — общий прогресс
          </span>
        </div>
      </div>

      <div className="mt-6 space-y-4">
        {data.criteria.map((c) => (
          <div key={c.name}>
            <div className="flex items-center gap-2 text-sm">
              <span>{c.met ? '✅' : '🔄'}</span>
              <span className="font-medium text-slate-800">
                {c.name} ({c.completed} из {c.required})
              </span>
            </div>
            {c.details && c.details.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {c.details.map((d) => (
                  <div
                    key={d.period}
                    className={cn(
                      'rounded border px-2 py-1 text-xs',
                      d.current
                        ? 'border-amber-300 bg-amber-50 text-amber-800'
                        : d.met
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                          : 'border-slate-200 bg-slate-50 text-slate-600'
                    )}
                  >
                    <span className="font-medium">{formatPeriod(d.period)}</span>
                    {d.value != null && (
                      <span className="ml-1">
                        {typeof d.value === 'number' && d.value < 100 ? `${Number(d.value).toFixed(0)}%` : d.value}
                      </span>
                    )}
                    <span className="ml-1">{d.met ? '✅' : d.current ? '🔄' : '❌'}</span>
                  </div>
                ))}
              </div>
            )}
            {c.details?.length === 1 && c.required > 1 && (
              <div className="mt-1 flex h-2 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${c.progress_percent}%` }}
                />
              </div>
            )}
            {c.details && c.details.length > 1 && (
              <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${c.progress_percent}%` }}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="mt-4 text-sm text-slate-600">💡 {data.message}</p>
    </div>
  )
}
