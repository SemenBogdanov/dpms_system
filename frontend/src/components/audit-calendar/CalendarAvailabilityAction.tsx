import { useId, useState } from 'react'
import type { CalendarState } from '@/api/auditCalendar'
import { activeChangeRequest, availabilityLocked, dateLabel } from '@/lib/auditCalendar'
import { CalendarCommandForm } from './CalendarCommandForm'

export type AvailabilityAction =
  | { kind: 'lock'; user: string; date: string }
  | { kind: 'request'; user: string; date: string }
  | { kind: 'resolve'; id: string; action: 'approve' | 'close' | 'reject' }
  | { kind: 'notify'; group: string; date: string; duration: number }

export function CalendarAvailabilityAction({ action, state, onClose, onRefresh }: { action: AvailabilityAction; state: CalendarState; onClose: () => void; onRefresh: () => Promise<unknown> }) {
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const request = action.kind === 'resolve' ? state.change_requests.find(r => r.id === action.id) : undefined
  const date = action.kind === 'resolve' ? request?.date : action.date
  const user = action.kind === 'lock' || action.kind === 'request' ? action.user : request?.user_id
  const title = action.kind === 'lock' ? 'Зафиксировать день' : action.kind === 'request' ? 'Заявка на изменение доступности' : action.kind === 'notify' ? 'Уведомить группу' : { approve: 'Открыть день по заявке', close: 'Закрыть заявку и зафиксировать день', reject: 'Отклонить заявку' }[action.action]
  function validate() {
    if (state.scope.archived) return 'Контур архивирован. Изменения недоступны.'
    if (action.kind === 'lock' && !state.actor.can_manage) return 'Фиксация дня доступна только помощнику.'
    if (!reason.trim()) return 'Укажите основание.'
    if (action.kind === 'resolve') {
      if (!state.actor.can_manage) return 'Решение по заявке доступно только помощнику.'
      if (!request || request.status !== (action.action === 'close' ? 'approved' : 'pending')) return 'Статус заявки изменился. Закройте форму и проверьте сводку.'
    } else if (action.kind === 'notify') {
      if (!state.actor.can_manage) return 'Уведомление доступно только помощнику.'
    } else {
      if (!state.actor.can_manage && action.user !== state.actor.user_id) return 'Можно изменять только собственную доступность.'
      if (action.date < state.scope.today) return 'Прошедший день нельзя изменить.'
      if (activeChangeRequest(state, action.user, action.date)) return 'По этому дню уже есть активная заявка. Проверьте сводку.'
      if (availabilityLocked(state, action.user, action.date) !== (action.kind === 'request')) return 'Состояние замка изменилось. Закройте форму и проверьте день.'
    }
    return ''
  }
  return <CalendarCommandForm title={title} version={state.scope.version} onClose={onClose} onRefresh={onRefresh} validate={validate} command={() => {
    switch (action.kind) {
      case 'lock': return { operation: 'availability.lock', payload: { user_id: action.user, date: action.date, reason: reason.trim() } }
      case 'request': return { operation: 'availability.request', payload: { user_id: action.user, date: action.date, reason: reason.trim() } }
      case 'resolve': return { operation: 'availability.resolve', payload: { id: action.id, action: action.action, reason: reason.trim() } }
      case 'notify': return { operation: 'availability.notify', payload: { group_id: action.group, date: action.date, reason: reason.trim(), duration: action.duration } }
    }
  }}>
    <p>{action.kind === 'notify' ? state.groups.find(g => g.id === action.group)?.code : state.members.find(m => m.user_id === user)?.full_name}{date ? ` · ${dateLabel(date)}` : ''}</p>
    <p className="ac-warning">{action.kind === 'lock' ? 'Доступность дня будет зафиксирована. Изменение возможно только после одобрения заявки помощником.' : action.kind === 'request' ? 'До одобрения заявки день останется закрытым. Время обращения зафиксирует сервер.' : action.kind === 'notify' ? `Участники группы получат важное уведомление: доступность заполнена, но общего свободного окна на ${action.duration} мин нет.` : action.action === 'approve' ? 'День будет открыт для изменений. При закрытии заявки доступность снова зафиксируется.' : action.action === 'close' ? 'Текущая доступность сохранится в истории, день снова будет закрыт для изменений.' : 'Заявка будет отклонена. День останется закрытым.'}</p>
    {request && <p>Обращение: {request.reason}</p>}
    <div className="ac-field"><label htmlFor={reasonId}>Основание</label><textarea id={reasonId} required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></div>
  </CalendarCommandForm>
}
