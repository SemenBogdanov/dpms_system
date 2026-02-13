interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  className?: string
}

/** Универсальная карточка метрики для дашборда. */
export function MetricCard({ title, value, subtitle, className = '' }: MetricCardProps) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}
    >
      <p className="text-sm font-medium text-slate-600">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {subtitle != null && (
        <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
      )}
    </div>
  )
}
