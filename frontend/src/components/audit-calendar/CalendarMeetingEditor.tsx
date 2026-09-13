import { useState } from 'react'
import type { CalendarFact, CalendarPlan, CalendarState } from '@/api/auditCalendar'
import { MAX_DATE, MIN_DATE, calendarStatuses, timeLabel, allSlots } from '@/lib/auditCalendar'
import { CalendarCommandForm } from './CalendarCommandForm'
import { CalendarModal } from './CalendarModal'

type Props = { state: CalendarState; date: string; start: number; plan?: CalendarPlan; fact?: CalendarFact; onClose: () => void; onRefresh: () => Promise<unknown> }
export function CalendarMeetingEditor({ state, date: initialDate, start: initialStart, plan, fact, onClose, onRefresh }: Props) {
  const frozenFact = fact || state.facts.find(f => f.plan_id === plan?.id)
  const [mode, setMode] = useState<'plan' | 'fact' | 'notice'>('plan')
  const [changed, setChanged] = useState(false)
  const [date, setDate] = useState(plan?.date || initialDate)
  const [start, setStart] = useState(plan?.start ?? initialStart)
  const [duration, setDuration] = useState(plan?.duration || 60)
  const [group, setGroup] = useState(plan?.group_id || '')
  const [activity, setActivity] = useState(plan?.activity || '')
  const [speaker, setSpeaker] = useState(plan?.speaker_id || '')
  const [status, setStatus] = useState<CalendarPlan['status']>(plan?.status || 'planned')
  const [outcome, setOutcome] = useState<CalendarFact['outcome']>('completed')
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [absentMinutes, setAbsentMinutes] = useState(0)
  const [noticeUser, setNoticeUser] = useState('')
  const [reportedAt, setReportedAt] = useState(`${state.scope.today}T10:00`)
  const [workingRevision, setWorkingRevision] = useState(false)
  const editable = state.actor.can_manage && !state.scope.archived && !frozenFact
  const selectedGroup = state.groups.find(g => g.id === group)
  const composition = selectedGroup?.versions.filter(v => v.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  const participants = [composition?.auditor_id, composition?.tech_id, speaker].filter(Boolean)
  const personName = (id: string | null | undefined) => state.members.find(m => m.user_id === id)?.full_name || 'Не указан'
  if (frozenFact || !editable) {
    const record = frozenFact || plan
    return <CalendarModal title={frozenFact ? 'Факт встречи' : 'План встречи'} onClose={onClose}>
      {record && <><dl className="ac-details"><dt>Дата и время</dt><dd>{record.date}, {timeLabel(record.start)}–{timeLabel(record.start + record.duration)}</dd><dt>Группа</dt><dd>{state.groups.find(g => g.id === record.group_id)?.code || 'Без группы'}</dd><dt>Активность</dt><dd>{record.activity || 'Не указана'}</dd><dt>Докладчик</dt><dd>{personName(record.speaker_id)}</dd><dt>Статус</dt><dd>{calendarStatuses[frozenFact ? frozenFact.outcome : plan!.status]}</dd><dt>Происхождение</dt><dd>{record.origin}</dd>
        {frozenFact && <><dt>Основание</dt><dd>{frozenFact.reason || 'Не указано'}</dd><dt>Подтверждение</dt><dd>{frozenFact.evidence || 'Не указано'}</dd><dt>Ответственный</dt><dd>{personName(frozenFact.recorded_by_id)}</dd><dt>Зафиксировано</dt><dd>{new Date(frozenFact.recorded_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</dd><dt>Состав</dt><dd>{frozenFact.composition_unknown ? 'Состав не установлен' : <pre>{JSON.stringify(frozenFact.participant_snapshot, null, 2)}</pre>}</dd></>}
      </dl>{frozenFact && <details><summary tabIndex={0}>Неизменяемый снимок плана</summary><pre>{JSON.stringify(frozenFact.planned_snapshot, null, 2)}</pre></details>}
      <p className="ac-muted">{frozenFact ? 'Факт и снимок плана неизменяемы.' : 'Только просмотр.'}</p></>}
    </CalendarModal>
  }
  const validate = () => {
    if (mode === 'notice') return !noticeUser ? 'Выберите участника встречи.' : ''
    if (start + duration > 1440) return 'Встреча не может переходить через полночь.'
    if (mode === 'plan' && !plan && date < state.scope.today) return 'Новый план нельзя назначить задним числом.'
    if (mode === 'plan' && plan?.source_id && !workingRevision) return 'Для изменения источника явно выберите рабочую редакцию.'
    if (mode === 'fact' && absentMinutes > 5 && outcome !== 'cancelled') return 'Отсутствие аудитора более 5 минут: результат должен быть «Отменено».'
    return ''
  }
  return <CalendarCommandForm title={mode === 'fact' ? 'Зафиксировать факт' : mode === 'notice' ? 'Уведомление об отсутствии' : plan ? 'Редакция плана' : 'План встречи'} version={state.scope.version} onClose={onClose} onRefresh={onRefresh} validate={validate} command={() => mode === 'notice' ? { operation: 'notice.record', payload: { plan_id: plan!.id, user_id: noticeUser, reported_at: `${reportedAt}:00+03:00`, reason } } : mode === 'fact' ? { operation: 'fact.record', payload: { plan_id: plan!.id, date, start, duration, group_id: group, activity, speaker_id: speaker || null, outcome, reason, evidence, auditor_absent_minutes: absentMinutes } } : plan?.source_id ? { operation: 'plan.revise', payload: { id: plan.id, date, start, duration, group_id: group, activity, speaker_id: speaker || null, status, reason } } : { operation: 'plan.save', payload: { ...(plan && { id: plan.id }), date, start, duration, group_id: group, activity, speaker_id: speaker || null, status, reason } }}>
    <div onChange={() => setChanged(true)}>
      {mode === 'plan' && plan?.source_id && <><label className="ac-check"><input type="checkbox" checked={workingRevision} onChange={e => setWorkingRevision(e.target.checked)} />Создать рабочую редакцию источника</label><p className="ac-warning">Оригинал сохраняется. Перенос на будущую дату требует современного состава А+Т и не даёт исторического исключения.</p></>}
      {plan && <div className="ac-segments" aria-label="Действие с планом">{(['plan', 'fact', 'notice'] as const).map(value => <button type="button" key={value} disabled={changed && mode !== value} aria-pressed={mode === value} onClick={() => setMode(value)}>{value === 'plan' ? 'План' : value === 'fact' ? 'Факт' : 'Уведомление'}</button>)}</div>}
      {mode === 'notice' ? <><label>Участник<select required value={noticeUser} onChange={e => setNoticeUser(e.target.value)}><option value="">Выберите участника</option>{state.members.filter(m => participants.includes(m.user_id)).map(m => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}</select></label><label>Сообщено, Москва<input type="datetime-local" min={`${MIN_DATE}T00:00`} max={`${state.scope.today}T23:59`} value={reportedAt} onChange={e => setReportedAt(e.target.value)} required /></label></> : <>
        <div className="ac-form-grid"><label>Дата<input type="date" required min={mode === 'plan' && !plan ? state.scope.today : MIN_DATE} max={MAX_DATE} value={date} onChange={e => setDate(e.target.value)} /></label><label>Начало<select value={start} onChange={e => setStart(Number(e.target.value))}>{allSlots.map(t => <option key={t} value={t}>{timeLabel(t)}</option>)}</select></label><label>Длительность, мин<input type="number" min={30} max={1440 - start} step={30} value={duration} onChange={e => setDuration(Number(e.target.value))} required /></label></div>
        <label>Группа<select required value={group} onChange={e => setGroup(e.target.value)}><option value="">Выберите группу</option>{state.groups.filter(g => (!g.archived && !g.legacy) || g.id === group).map(g => <option value={g.id} key={g.id}>{g.code} · {g.label}</option>)}</select></label>
        <p className="ac-muted">А: {personName(composition?.auditor_id)} · Т: {personName(composition?.tech_id)}</p>
        <label>Активность<input autoComplete="off" maxLength={120} required={mode === 'fact' || status === 'planned'} value={activity} onChange={e => setActivity(e.target.value)} /></label>
        <label>Докладчик<select value={speaker} required={mode === 'fact' || status === 'planned'} onChange={e => setSpeaker(e.target.value)}><option value="">Не указан</option>{state.members.filter(m => m.active || m.user_id === speaker).map(m => <option value={m.user_id} key={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>
        {mode === 'plan' ? <label>Статус<select value={status} onChange={e => setStatus(e.target.value as CalendarPlan['status'])}>{(['draft', 'planned', 'cancelled'] as const).map(s => <option key={s} value={s}>{calendarStatuses[s]}</option>)}</select></label> : <><div className="ac-form-grid"><label>Результат<select value={outcome} onChange={e => setOutcome(e.target.value as CalendarFact['outcome'])}><option value="completed">Проведено</option><option value="cancelled">Отменено</option></select></label><label>Отсутствие аудитора, мин<input type="number" min={0} max={1440} step={1} value={absentMinutes} onChange={e => { const n = Number(e.target.value); setAbsentMinutes(n); if (n > 5) setOutcome('cancelled') }} /></label></div><label>Подтверждение<textarea required maxLength={4000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label><p className="ac-warning">После сохранения факт и состав нельзя изменить.</p></>}
      </>}
      <label>Основание<textarea required={mode !== 'plan' || status === 'cancelled' || !!plan} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>
      {plan && <><p className="ac-muted">Источник: {plan.origin}{plan.source_id ? ` · ${plan.source_id}` : ''}</p>{[...plan.issues, ...plan.warnings].map((issue, i) => <p className="ac-warning" key={`${issue.code}-${i}`}>{issue.message}</p>)}{state.notices.filter(n => n.plan_id === plan.id).map(n => <p key={n.id} className="ac-muted">{personName(n.user_id)}: {n.reason} · {new Date(n.reported_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</p>)}</>}
    </div>
  </CalendarCommandForm>
}
