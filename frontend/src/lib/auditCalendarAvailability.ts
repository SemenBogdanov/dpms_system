import type { AvailabilityPatch, CalendarState } from '@/api/auditCalendar'
import { absentOn, availabilityLocked, slotValue } from './auditCalendar'

export type AvailabilityIntent = ReturnType<typeof availabilityIntent>
export type AvailabilityReview = AvailabilityPatch & { expected: boolean | null; current: boolean | null }

export function availabilityIntent(state: CalendarState, user: string, patches: AvailabilityPatch[]) {
  const cells = new Map<string, AvailabilityPatch>()
  for (const patch of patches) {
    for (let start = patch.start; start < patch.end; start += 30) {
      cells.set(`${patch.date}/${start}`, { date: patch.date, start, end: start + 30, value: slotValue(state.availability, user, patch.date, start) })
    }
  }
  return {
    scopeId: state.scope.id,
    actorId: state.actor.user_id,
    version: state.scope.version,
    command: { operation: 'availability.paint' as const, payload: { user_id: user, patches: patches.map(patch => ({ ...patch })), expected: [...cells.values()] } },
  }
}

export function availabilityIntentProblem(state: CalendarState, intent: AvailabilityIntent) {
  const { user_id: user, patches } = intent.command.payload
  if (intent.scopeId !== state.scope.id || intent.actorId !== state.actor.user_id) return 'Контур или текущий пользователь изменился. Черновик сохранён.'
  if (state.scope.archived) return 'Контур календаря находится в архиве и недоступен для изменений. Черновик сохранён.'
  if ((!state.actor.can_manage && user !== state.actor.user_id) || !state.members.some(member => member.user_id === user && member.active)) return 'Нет прав изменять доступность этого участника. Черновик сохранён.'
  if (patches.some(patch => availabilityLocked(state, user, patch.date))) return 'День закрыт для изменений. Подайте заявку на изменение дня. Черновик сохранён.'
  if (patches.some(patch => absentOn(state, user, patch.date) || patch.date < state.scope.today)) return 'День недоступен для изменения: отсутствие или прошедшая дата. Черновик сохранён.'
  return ''
}

export function availabilityReview(intent: AvailabilityIntent, state: CalendarState): AvailabilityReview[] {
  const { user_id: user, patches, expected } = intent.command.payload
  const finalPatches = [...patches].reverse()
  const rows: AvailabilityReview[] = []
  for (const cell of [...expected].sort((a, b) => a.date.localeCompare(b.date) || a.start - b.start)) {
    const requested = finalPatches.find(patch => patch.date === cell.date && patch.start <= cell.start && patch.end >= cell.end)!
    const row = { ...cell, expected: cell.value, current: slotValue(state.availability, user, cell.date, cell.start), value: requested.value }
    const previous = rows[rows.length - 1]
    if (previous && previous.date === row.date && previous.end === row.start && previous.expected === row.expected && previous.current === row.current && previous.value === row.value) previous.end = row.end
    else rows.push(row)
  }
  return rows
}
