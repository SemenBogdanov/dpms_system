import { cn } from '@/lib/utils'
import type { RunRate } from '@/api/types'

const STATUS_CONFIG = {
  on_track: { label: 'В графике', color: 'text-emerald-700', bg: 'bg-emerald-100', bar: 'bg-emerald-500' },
  slightly_behind: { label: 'Чуть отстаёт', color: 'text-amber-700', bg: 'bg-amber-100', bar: 'bg-amber-500' },
  at_risk: { label: 'Под угрозой', color: 'text-orange-700', bg: 'bg-orange-100', bar: 'bg-orange-500' },
  critical: { label: 'Критично', color: 'text-red-700', bg: 'bg-red-100', bar: 'bg-red-500' },
} as const

interface RunRateCardProps {
  data: RunRate | null
  loading?: boolean
  error?: string | null
  compact?: boolean
}

export function RunRateCard({ data, loading, error, compact }: RunRateCardProps) {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm animate-pulse">
        <div className="h-4 w-32 rounded bg-slate-200 mb-3" />
        <div className="h-3 w-full rounded bg-slate-200" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    )
  }

  if (!data) return null

  const cfg = STATUS_CONFIG[data.status]
  const pct = Math.min(100, Math.max(0, data.run_rate_percent))

  // Компактный вариант для MyTasksPage
  if (compact) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', cfg.bg, cfg.color)}>
          {cfg.label}
        </span>
        <span className="text-slate-600">
          Прогноз: {data.projected.toFixed(1)} / {data.mpw} Q ({data.run_rate_percent.toFixed(0)}%)
        </span>
      </div>
    )
  }

  // Полный вариант для ProfilePage
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-slate-800">Run Rate</h3>
        <span className={cn('rounded-full px-3 py-1 text-sm font-medium', cfg.bg, cfg.color)}>
          {cfg.label}
        </span>
      </div>

      {/* Прогресс-бар */}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="text-slate-600">Прогноз на конец месяца</span>
          <span className="font-medium text-slate-900">{data.run_rate_percent.toFixed(0)}%</span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-200">
          <div
            className={cn('h-full transition-all', cfg.bar)}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Метрики */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-slate-500">Темп</p>
          <p className="text-lg font-semibold text-slate-900">{data.rate_daily.toFixed(2)} Q/д</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Прогноз</p>
          <p className="text-lg font-semibold text-slate-900">{data.projected.toFixed(1)} Q</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Заработано</p>
          <p className="text-lg font-semibold text-slate-900">{data.earned.toFixed(1)} / {data.mpw} Q</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Нужный темп</p>
          <p className="text-lg font-semibold text-slate-900">
            {data.required_rate != null ? `${data.required_rate.toFixed(2)} Q/д` : '—'}
          </p>
        </div>
      </div>

      {/* Дни */}
      <p className="text-xs text-slate-400">
        День {data.days_elapsed} из {data.days_total} рабочих (осталось {data.days_remaining})
      </p>
    </div>
  )
}
