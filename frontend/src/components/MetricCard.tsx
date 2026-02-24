import { BarChart, Bar, ResponsiveContainer } from 'recharts'

interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  className?: string
  sparkData?: Array<{ percent: number }>
}

/** Универсальная карточка метрики для дашборда. */
export function MetricCard({ title, value, subtitle, className = '', sparkData }: MetricCardProps) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500">{title}</p>
          <p className="mt-1 text-2xl font-bold whitespace-nowrap text-slate-900">{value}</p>
          {subtitle != null && (
            <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
          )}
        </div>
        {sparkData && sparkData.length > 0 && (
          <div className="h-10 w-24">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sparkData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <Bar dataKey="percent" fill="#6366f1" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
