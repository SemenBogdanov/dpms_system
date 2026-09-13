import type { CalendarAvailability, CalendarState } from '@/api/auditCalendar'

export const MIN_DATE = '2000-01-01'
export const MAX_DATE = '2100-12-31'
export const calendarRoles = { auditor: 'Аудитор', tech: 'Техспециалист', speaker: 'Докладчик', observer: 'Наблюдатель' }
export const calendarStatuses = { draft: 'Черновик', planned: 'Запланировано', cancelled: 'Отменено', completed: 'Проведено' }
export const calendarTargetScopes = { team: 'Команда', group: 'Группа' }
export function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < MIN_DATE || value > MAX_DATE) return false
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}
export function addDays(date: string, count: number) {
  const next = new Date(`${date}T00:00:00Z`)
  next.setUTCDate(next.getUTCDate() + count)
  return next.toISOString().slice(0, 10)
}
export function clampDay(date: string) { return date < MIN_DATE ? MIN_DATE : date > MAX_DATE ? MAX_DATE : date }
export function periodError(from: string, to: string) {
  if (!validDate(from) || !validDate(to)) return 'Даты должны быть в диапазоне 2000–2100.'
  if (from > to) return 'Дата «По» не может быть раньше даты «С».'
  if ((Date.parse(to) - Date.parse(from)) / 86400000 >= 366) return 'Период не может превышать 366 дней.'
  return ''
}
export function dateRange(from: string, to: string) {
  if (periodError(from, to)) return []
  return Array.from({ length: Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1 }, (_, i) => addDays(from, i))
}
export function moscowToday() { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
export function dateLabel(date: string) { return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T00:00:00Z`)) }
export function timeLabel(minute: number) { return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}` }
export function numberLabel(value: number) { return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value) }
export function calendarDailyTarget(state: CalendarState, date: string, groupId: string | null = null) {
  if (date < state.scope.baseline || [0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay())) return 0
  const effective = state.norms.filter(n => n.group_id === groupId && n.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  return effective ? effective.value / (groupId ? 10 : 1) : 0
}
export const workSlots = Array.from({ length: 16 }, (_, i) => 600 + i * 30)
export const allSlots = Array.from({ length: 48 }, (_, i) => i * 30)
export function slotValue(windows: CalendarAvailability[], person: string, date: string, start: number): boolean | null {
  const matching = windows.filter(w => w.user_id === person && w.date === date && w.start < start + 30 && w.end > start)
  if (matching.some(w => !w.available)) return false
  let covered = start
  for (const w of matching.sort((a, b) => a.start - b.start)) {
    if (w.start > covered) break
    covered = Math.max(covered, w.end)
  }
  return covered >= start + 30 ? true : null
}
export function absentOn(state: CalendarState, person: string, date: string) {
  return state.absences.find(a => a.status === 'active' && a.user_id === person && a.start_date <= date && a.end_date >= date)
}
export function csvCell(value: unknown) {
  const text = String(value ?? '')
  return `"${(/^[\s]*[=+@-]/.test(text) ? `'${text}` : text).replace(/"/g, '""')}"`
}
export function errorText(error: unknown) { return error instanceof Error ? error.message : 'Не удалось выполнить запрос.' }
