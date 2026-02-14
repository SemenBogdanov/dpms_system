import type { TeamSummary } from '@/api/types'

/** Экспорт Team Summary в CSV с BOM для корректной кириллицы в Excel. */
export function exportTeamCSV(summary: TeamSummary): void {
  const rows = Object.values(summary.by_league).flat()
  const header =
    'ФИО,Лига,План (MPW),Факт (Main),% Выполнения,Карма,В работе (Q),Статус\n'
  const body = rows
    .map(
      (r) =>
        `${r.full_name},${r.league},${r.mpw},${Number(r.earned).toFixed(1)},${Number(r.percent).toFixed(1)},${Number(r.karma).toFixed(1)},${Number(r.in_progress_q).toFixed(1)},${r.is_at_risk ? 'Отстаёт' : 'OK'}`
    )
    .join('\n')
  const blob = new Blob(['\ufeff' + header + body], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `dpms-team-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
