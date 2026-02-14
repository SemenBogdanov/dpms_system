import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { BurndownData } from '@/api/types'

interface BurndownChartProps {
  data: BurndownData
}

/** График burn-down: идеал vs факт по дням месяца. */
export function BurndownChart({ data }: BurndownChartProps) {
  const chartData = data.points.map((p) => ({
    day: p.day.slice(8, 10),
    fullDay: p.day,
    ideal: p.ideal,
    actual: p.actual,
    isFuture: p.actual == null,
  }))

  return (
    <div className="w-full" style={{ height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="day"
            tick={{ fontSize: 12 }}
            tickFormatter={(v, i) => {
              const pt = chartData[i]
              return pt?.fullDay?.slice(5) ?? v
            }}
          />
          <YAxis tick={{ fontSize: 12 }} label={{ value: 'Q', angle: 0, position: 'insideLeft' }} />
          <Tooltip
            formatter={(value: number) => [value != null ? Number(value).toFixed(1) : '—', '']}
            labelFormatter={(_, payload) => {
              const p = payload?.[0]?.payload
              return p?.fullDay ?? ''
            }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const p = payload[0].payload
              return (
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-md">
                  <p className="text-sm font-medium text-slate-700">День: {p?.fullDay}</p>
                  <p className="text-xs text-slate-500">
                    Идеал: {p?.ideal != null ? Number(p.ideal).toFixed(1) : '—'} Q
                  </p>
                  <p className="text-xs text-slate-500">
                    Факт: {p?.actual != null ? Number(p.actual).toFixed(1) : '—'} Q
                  </p>
                </div>
              )
            }}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="ideal"
            name="Идеал"
            stroke="#94a3b8"
            strokeDasharray="4 4"
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="actual"
            name="Факт"
            stroke="#10b981"
            strokeWidth={2}
            dot={(props) => {
              const { cx, cy, payload } = props
              if (payload.actual == null) return null
              const behind = payload.actual < payload.ideal
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={3}
                  fill={behind ? '#ef4444' : '#10b981'}
                  stroke="white"
                  strokeWidth={1}
                />
              )
            }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
