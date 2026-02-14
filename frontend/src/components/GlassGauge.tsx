import { cn } from '@/lib/utils'

interface GlassGaugeProps {
  /** Загрузка (текущая) в единицах */
  load: number
  /** Ёмкость (план) в единицах */
  capacity: number
  /** Процент утилизации (0–100+) */
  utilization: number
  /** green | yellow | red */
  status: 'green' | 'yellow' | 'red'
  className?: string
}

/** Визуализация «Стакан»: загрузка vs ёмкость. */
export function GlassGauge({ load, capacity, utilization, status, className }: GlassGaugeProps) {
  const percent = capacity > 0 ? Math.min(100, (load / capacity) * 100) : 0
  const color =
    status === 'green'
      ? 'bg-emerald-500'
      : status === 'yellow'
        ? 'bg-amber-500'
        : 'bg-red-500'

  return (
    <div className={cn('rounded-xl border border-slate-200 bg-white p-4 shadow-sm', className)}>
      <div className="flex items-end justify-between gap-4">
        <div className="flex-1">
          <p className="text-sm font-medium text-slate-700">Загрузка / Ёмкость</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">
            {Number(load).toFixed(1)} / {Number(capacity).toFixed(1)} Q
          </p>
          <div className="mt-2 h-3 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={cn('h-full rounded-full transition-all', color)}
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">Утилизация: {Number(utilization).toFixed(1)}%</p>
        </div>
        <span
          className={cn(
            'rounded-full px-3 py-1 text-sm font-medium',
            status === 'green' && 'bg-emerald-100 text-emerald-800',
            status === 'yellow' && 'bg-amber-100 text-amber-800',
            status === 'red' && 'bg-red-100 text-red-800'
          )}
        >
          {status === 'green' && 'Норма'}
          {status === 'yellow' && 'Средняя'}
          {status === 'red' && 'Перегруз'}
        </span>
      </div>
    </div>
  )
}
