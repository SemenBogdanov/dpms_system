import { useState } from 'react'
import type { CalendarPlan, CalendarState } from '@/api/auditCalendar'
import { calendarStatuses, timeLabel } from '@/lib/auditCalendar'

export type MeetingDraft = Pick<CalendarPlan, 'date' | 'start' | 'duration' | 'group_id' | 'activity' | 'speaker_id' | 'status'>
const fields = { date: 'Дата', start: 'Начало', duration: 'Длительность, мин', group_id: 'Группа', activity: 'Активность', speaker_id: 'Докладчик', status: 'Статус' } as const
type Field = keyof MeetingDraft

export function CalendarMeetingConflict({ state, baseline, draft, onResolve }: { state: CalendarState; baseline?: CalendarPlan; draft: MeetingDraft; onResolve: (draft: MeetingDraft, plan?: CalendarPlan) => void }) {
  const current = state.plans.find(p => p.id === baseline?.id)
  const [choices, setChoices] = useState<Partial<Record<Field, 'local' | 'server'>>>({})
  if (!state.actor.can_manage || state.scope.archived || (baseline && (!current || current.fact_outcome || state.facts.some(f => f.plan_id === baseline.id)))) {
    return <p className="ac-warning" role="alert">План больше недоступен для редактирования в текущей выборке или уже зафиксирован. Ввод сохранён в форме. Повторная запись заблокирована.</p>
  }
  const changed = baseline && current ? (Object.keys(fields) as Field[]).filter(field => current[field] !== baseline[field]) : []
  const conflicts = changed.filter(field => draft[field] !== baseline![field] && draft[field] !== current![field])
  const label = (field: Field, value: MeetingDraft[Field]) => {
    if (field === 'start') return timeLabel(Number(value))
    if (field === 'group_id') return state.groups.find(g => g.id === value)?.code || value || 'Не указана'
    if (field === 'speaker_id') return state.members.find(m => m.user_id === value)?.full_name || value || 'Не указан'
    if (field === 'status') return calendarStatuses[value as CalendarPlan['status']]
    return String(value ?? '')
  }
  function accept() {
    if (conflicts.some(field => !choices[field])) return
    const merged = { ...draft }
    for (const field of changed) {
      if (!conflicts.includes(field) || choices[field] === 'server') Object.assign(merged, { [field]: current![field] })
    }
    onResolve(merged, current)
  }
  return <section aria-label="Согласование плана" className="ac-conflict">
    <h3>Согласование плана</h3>
    <p>{changed.length ? 'Изменения сервера показаны ниже. Незатронутые вами поля будут обновлены; ваш остальной ввод сохранится.' : 'Поля плана на сервере не изменились. Ваш ввод сохранён.'}</p>
    {changed.map(field => <div key={field} className="ac-conflict-field"><strong>{fields[field]}</strong><dl className="ac-details"><dt>При открытии</dt><dd>{label(field, baseline![field])}</dd><dt>Сейчас на сервере</dt><dd>{label(field, current![field])}</dd><dt>Ваш ввод</dt><dd>{label(field, draft[field])}</dd></dl>
      {conflicts.includes(field) && <label>Решение: {fields[field]}<select value={choices[field] || ''} onChange={e => setChoices(value => ({ ...value, [field]: e.target.value as 'local' | 'server' }))}><option value="">Выберите значение</option><option value="server">Принять серверное</option><option value="local">Оставить мой ввод</option></select></label>}
    </div>)}
    <button type="button" disabled={conflicts.some(field => !choices[field])} onClick={accept}>Согласовать изменения</button>
  </section>
}
