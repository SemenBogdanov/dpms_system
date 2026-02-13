import { useNavigate } from 'react-router-dom'
import type { TeamMemberSummary } from '@/api/types'
import { ProgressBar } from './ProgressBar'
import { LeagueBadge } from './LeagueBadge'

interface TeamPulseTableProps {
  members: TeamMemberSummary[]
}

/** Таблица «Пульс команды»: сортировка по is_at_risk, потом по %. */
export function TeamPulseTable({ members }: TeamPulseTableProps) {
  const navigate = useNavigate()
  const sorted = [...members].sort((a, b) => {
    if (a.is_at_risk !== b.is_at_risk) return a.is_at_risk ? -1 : 1
    return a.percent - b.percent
  })

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50">
            <th className="px-4 py-3 text-left font-medium text-slate-700">ФИО</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">Лига</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">План (MPW)</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">Факт (Main)</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">%</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">Карма</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">В работе (Q)</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">Статус</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((m) => (
            <tr
              key={m.id}
              onClick={() => navigate(`/profile?user_id=${m.id}`)}
              className={`border-b border-slate-100 transition-colors hover:bg-slate-50 cursor-pointer ${
                m.is_at_risk ? 'bg-red-50' : m.percent >= 100 ? 'bg-green-50' : ''
              }`}
            >
              <td className="px-4 py-2 font-medium text-slate-900">{m.full_name}</td>
              <td className="px-4 py-2">
                <LeagueBadge league={m.league as 'C' | 'B' | 'A'} />
              </td>
              <td className="px-4 py-2 text-slate-600">{m.mpw}</td>
              <td className="px-4 py-2 text-slate-600">{m.earned.toFixed(1)}</td>
              <td className="px-4 py-2 w-24">
                <ProgressBar percent={m.percent} variant="risk" />
                <span className="text-xs text-slate-500">{m.percent.toFixed(0)}%</span>
              </td>
              <td className="px-4 py-2 text-slate-600">{m.karma.toFixed(1)}</td>
              <td className="px-4 py-2 text-slate-600">{m.in_progress_q.toFixed(1)}</td>
              <td className="px-4 py-2">
                {m.is_at_risk && <span title="Отстаёт от темпа">⚠️</span>}
                {!m.is_at_risk && m.percent >= 100 && <span>✅</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
