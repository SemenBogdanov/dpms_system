import type { CalendarState } from '@/api/auditCalendar'
import { isWorkingDay, numberLabel } from '@/lib/auditCalendar'
import { X } from 'lucide-react'
import { useCalendarMeetingWindows } from './CalendarMeetingWindowsQuery'

export function CalendarExpiredWindows({ state, from, to, groupId, enabled, retry }: {
  state: CalendarState; from: string; to: string; groupId: string; enabled: boolean; retry: number
}) {
  const result = useCalendarMeetingWindows({ state, from, to, groupId, enabled, duration: 30,
    speakerId: '', fullDay: false, sourceKey: `expired:${retry}` })
  const expired = [...result.cells.values()].filter(cell => cell.status === 'expired'
    && isWorkingDay(cell.date))
  return <section className="ac-expired-report" aria-label="Истекшие свободные окна" aria-busy={result.loading}>
    <div><X size={18} aria-hidden="true" /><h3>Истекшие свободные окна</h3>
      <strong aria-label="Количество истекших окон">{result.data && !result.error ? numberLabel(expired.length) : '—'}</strong></div>
    {result.error ? <p className="ac-error" role="status">{result.error}</p>
      : result.loading ? <p className="ac-muted" role="status">Расчёт окон…</p> : null}
    <p className="ac-muted">По сохранённой доступности · Пн–Пт, 10:00–18:00 · окна по 30 минут. Один интервал считается один раз, даже если свободны несколько групп. Не является фактом пропущенной встречи.</p>
  </section>
}
