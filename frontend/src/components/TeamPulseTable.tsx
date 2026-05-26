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
            <th className="px-4 py-3 text-left font-medium text-slate-700">QS</th>
            <th className="px-4 py-3 text-left font-medium text-slate-700">Статус</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((m) => {
            const targetAdjusted = Math.abs(Number(m.effective_mpw) - Number(m.mpw)) > 0.05
            return (
            <tr
              key={m.id}
              onClick={() => navigate(`/profile?user_id=${m.id}`)}
              className={`border-b border-slate-100 transition-colors hover:bg-slate-50 cursor-pointer ${
                m.is_at_risk ? 'bg-red-50' : m.percent >= 100 ? 'team-pulse-row-complete' : ''
              }`}
            >
              <td className="px-4 py-2 font-medium text-slate-900">{m.full_name}</td>
              <td className="px-4 py-2">
                <LeagueBadge league={m.league as 'C' | 'B' | 'A'} />
              </td>
              <td className="px-4 py-2 text-slate-600 whitespace-nowrap min-w-[64px]">
                <span>{Number(m.effective_mpw).toFixed(1)}</span>
                {targetAdjusted && <span className="block text-xs text-slate-400">из {m.mpw}</span>}
              </td>
              <td className="px-4 py-2 text-slate-600 whitespace-nowrap">{Number(m.earned).toFixed(1)}</td>
              <td className="px-4 py-2 w-24">
                <ProgressBar percent={m.percent} variant="risk" />
                <span className="text-xs text-slate-500">{Number(m.percent).toFixed(0)}%</span>
              </td>
              <td className="px-4 py-2 text-slate-600 whitespace-nowrap">{Number(m.karma).toFixed(1)}</td>
              <td className="px-4 py-2 text-slate-600 whitespace-nowrap min-w-[52px]">{Number(m.in_progress_q).toFixed(1)}</td>
              <td className="px-4 py-2 text-slate-600">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    m.quality_score >= 90
                      ? 'bg-emerald-50 text-emerald-700'
                      : m.quality_score >= 70
                      ? 'bg-amber-50 text-amber-700'
                      : m.quality_score >= 50
                      ? 'bg-orange-50 text-orange-700'
                      : 'bg-red-50 text-red-700'
                  }`}
                >
                  {Number(m.quality_score).toFixed(0)}%
                </span>
              </td>
              <td className="px-4 py-2">
                {m.has_overdue && <span title="Есть просроченные задачи">🔴</span>}
                {!m.has_overdue && m.is_at_risk && <span title="Отстаёт от темпа">⚠️</span>}
                {!m.has_overdue && !m.is_at_risk && m.percent >= 100 && <span>✅</span>}
                {m.onboarding_active && <span title="Адаптационный план" className="ml-1 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">Новый</span>}
                {m.absent_today && <span title="Сегодня отсутствует" className="ml-1 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">Отсутствует</span>}
                {!m.absent_today && m.absence_working_days > 0 && (
                  <span title="План скорректирован из-за отсутствий" className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    -{m.absence_working_days} дн.
                  </span>
                )}
              </td>
            </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
