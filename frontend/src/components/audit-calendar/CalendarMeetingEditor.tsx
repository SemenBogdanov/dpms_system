import { useId, useState } from 'react'
import { CalendarDays, Pencil, RefreshCw } from 'lucide-react'
import type { CalendarFact, CalendarIssue, CalendarMeetingWindowPrefill, CalendarPlan, CalendarState } from '@/api/auditCalendar'
import { MAX_DATE, MIN_DATE, calendarStatuses, timeLabel, allSlots, validDate } from '@/lib/auditCalendar'
import { CalendarCommandForm } from './CalendarCommandForm'
import { CalendarModal } from './CalendarModal'
import { useCalendarMeetingOptions } from './useCalendarMeetingOptions'
import { calendarInstant, useCalendarClock } from './useCalendarClock'

function MeetingIssues({ issues }: { issues: CalendarIssue[] }) {
  const seen = new Set<string>()
  return <>{issues.filter(issue => {
    const key = `${issue.code}:${issue.message}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).map(issue => <p className="ac-warning" key={`${issue.code}:${issue.message}`}>{issue.message}</p>)}</>
}

type Props = { state: CalendarState; date: string; start: number; plan?: CalendarPlan; fact?: CalendarFact; prefill?: CalendarMeetingWindowPrefill; prefillEnabled?: boolean; onClose: () => void; onRefresh: () => Promise<unknown> }
export function CalendarMeetingEditor({ state, date: initialDate, start: initialStart, plan, fact, prefill, prefillEnabled = true, onClose, onRefresh }: Props) {
  const optionsStatusId = useId()
  const timeFieldsId = useId()
  const frozenFact = fact || state.facts.find(f => f.plan_id === plan?.id)
  const [mode, setMode] = useState<'plan' | 'fact' | 'notice'>('plan')
  const [changed, setChanged] = useState(false)
  const [date, setDate] = useState(plan?.date || initialDate)
  const [start, setStart] = useState(plan?.start ?? initialStart)
  const [duration, setDuration] = useState(plan?.duration ?? prefill?.duration ?? 30)
  const [group, setGroup] = useState(plan?.group_id || prefill?.group_id || '')
  const [activity, setActivity] = useState(plan?.activity || '')
  const [speaker, setSpeaker] = useState(plan?.speaker_id || prefill?.speaker_id || '')
  const [status, setStatus] = useState<CalendarPlan['status']>(plan?.status || 'planned')
  const [outcome, setOutcome] = useState<CalendarFact['outcome']>('completed')
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [absentMinutes, setAbsentMinutes] = useState(0)
  const [noticeUser, setNoticeUser] = useState('')
  const [reportedAt, setReportedAt] = useState(`${state.scope.today}T10:00`)
  const [workingRevision, setWorkingRevision] = useState(false)
  const [timeEditing, setTimeEditing] = useState(false)
  const clock = useCalendarClock(prefill?.server_now || state.scope.now, prefill?.clock_started)
  const editable = state.actor.can_manage && !state.scope.archived && !frozenFact && !plan?.fact_outcome
  const needsOptions = editable && mode === 'plan' && status !== 'cancelled'
  const options = useCalendarMeetingOptions({ date, start, duration, speaker, planId: plan?.id, version: state.scope.version, enabled: needsOptions && (!prefill || prefillEnabled) })
  const selectedOption = options.data?.groups.find(g => g.id === group)
  const eligibleGroups = options.data?.groups.filter(g => g.eligible === true) || []
  const optionIssues = selectedOption ? [...selectedOption.issues, ...selectedOption.warnings] : []
  const savedIssues = plan ? [...plan.issues, ...plan.warnings].filter(issue => !optionIssues.some(current => current.code === issue.code && current.message === issue.message)) : []
  const selectedGroup = state.groups.find(g => g.id === group)
  const composition = selectedGroup?.versions.filter(v => v.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  const participants = [composition?.auditor_id, composition?.tech_id, speaker].filter(Boolean)
  const personName = (id: string | null | undefined) => state.members.find(m => m.user_id === id)?.full_name || id || 'Не указан'
  const reasonRequired = mode !== 'plan' || status === 'cancelled' || !!plan
  const timeError = !validDate(date) ? 'Укажите дату в диапазоне 2000–2100.'
    : !Number.isInteger(start) || start < 0 || start >= 1440 || start % 30 !== 0 ? 'Укажите начало встречи с шагом 30 минут.'
    : !Number.isInteger(duration) || duration < 30 || duration % 30 !== 0 ? 'Длительность должна быть не меньше 30 минут и кратна 30.'
    : start + duration > 1440 ? 'Встреча не может переходить через полночь.' : ''
  if (frozenFact || !editable) {
    const record = frozenFact || plan
    return <CalendarModal title={frozenFact ? 'Факт встречи' : 'План встречи'} onClose={onClose}>
      {!record && <p className="ac-muted">Только просмотр. {state.scope.archived ? 'Контур архивирован.' : 'Назначение доступно помощнику контура.'}</p>}
      {!frozenFact && plan?.fact_outcome && <p className="ac-muted">Результат зафиксирован вне текущей выборки: {calendarStatuses[plan.fact_outcome]}. План неизменяем.</p>}
      {record && <><dl className="ac-details"><dt>Дата и время</dt><dd>{record.date}, {timeLabel(record.start)}–{timeLabel(record.start + record.duration)}</dd><dt>Группа</dt><dd>{state.groups.find(g => g.id === record.group_id)?.code || 'Без группы'}</dd><dt>Активность</dt><dd>{record.activity || 'Не указана'}</dd><dt>Докладчик</dt><dd>{personName(record.speaker_id)}</dd><dt>Статус</dt><dd>{calendarStatuses[frozenFact ? frozenFact.outcome : plan!.status]}</dd><dt>Происхождение</dt><dd>{record.origin}</dd>
        {frozenFact && <><dt>Основание</dt><dd>{frozenFact.reason || 'Не указано'}</dd><dt>Подтверждение</dt><dd>{frozenFact.evidence || 'Не указано'}</dd><dt>Ответственный</dt><dd>{personName(frozenFact.recorded_by_id)}</dd><dt>Зафиксировано</dt><dd>{new Date(frozenFact.recorded_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</dd><dt>Состав</dt><dd>{frozenFact.composition_unknown ? 'Состав не установлен' : <pre>{JSON.stringify(frozenFact.participant_snapshot, null, 2)}</pre>}</dd></>}
      </dl>{frozenFact && <details><summary tabIndex={0}>Неизменяемый снимок плана</summary><pre>{JSON.stringify(frozenFact.planned_snapshot, null, 2)}</pre></details>}
      {plan && <MeetingIssues issues={[...plan.issues, ...plan.warnings]} />}
      <p className="ac-muted">{frozenFact ? 'Факт и снимок плана неизменяемы.' : 'Только просмотр.'}</p></>}
    </CalendarModal>
  }
  const validate = () => {
    if (prefill && !prefillEnabled) return 'Дождитесь обновления календаря перед сохранением.'
    if (prefill && mode === 'plan' && calendarInstant(date, start) < clock.current()) return 'Выбранное окно истекло. Укажите новое время встречи.'
    if (mode === 'notice') return !noticeUser ? 'Выберите участника встречи.' : ''
    if (timeError) { setTimeEditing(true); return timeError }
    if (mode === 'plan' && !plan && date < state.scope.today) { setTimeEditing(true); return 'Новый план нельзя назначить задним числом.' }
    if (mode === 'plan' && plan?.source_id && !workingRevision) return 'Для изменения источника явно выберите рабочую редакцию.'
    if (needsOptions && status === 'planned') {
      if (options.error) return options.error
      if (!options.data) return 'Дождитесь проверки доступности групп для выбранного времени.'
      if (!selectedOption?.eligible) return 'Выберите доступную группу для выбранного времени.'
    }
    if (mode === 'fact' && absentMinutes > 5 && outcome !== 'cancelled') return 'Отсутствие аудитора более 5 минут: результат должен быть «Отменено».'
    return ''
  }
  return <CalendarCommandForm title={mode === 'fact' ? 'Зафиксировать факт' : mode === 'notice' ? 'Уведомление об отсутствии' : plan ? 'Редакция плана' : 'План встречи'} version={prefill?.version ?? state.scope.version} initialDirty={!!prefill} onClose={onClose} onRefresh={onRefresh} validate={validate} command={() => mode === 'notice' ? { operation: 'notice.record', payload: { plan_id: plan!.id, user_id: noticeUser, reported_at: `${reportedAt}:00+03:00`, reason } } : mode === 'fact' ? { operation: 'fact.record', payload: { plan_id: plan!.id, date, start, duration, group_id: group, activity, speaker_id: speaker || null, outcome, reason, evidence, auditor_absent_minutes: absentMinutes } } : plan?.source_id ? { operation: 'plan.revise', payload: { id: plan.id, date, start, duration, group_id: group, activity, speaker_id: speaker || null, status, reason } } : { operation: 'plan.save', payload: { ...(plan && { id: plan.id }), date, start, duration, group_id: group, activity, speaker_id: speaker || null, status, reason } }}>
    <div className="ac-meeting-fields" onChange={() => setChanged(true)}>
      {mode === 'plan' && plan?.source_id && <><label className="ac-check"><input type="checkbox" checked={workingRevision} onChange={e => setWorkingRevision(e.target.checked)} />Создать рабочую редакцию источника</label><p className="ac-warning">Оригинал сохраняется. Перенос на будущую дату требует современного состава А+Т и не даёт исторического исключения.</p></>}
      {plan && <div className="ac-segments" aria-label="Действие с планом">{(['plan', 'fact', 'notice'] as const).map(value => <button type="button" key={value} disabled={changed && mode !== value} aria-pressed={mode === value} onClick={() => setMode(value)}>{value === 'plan' ? 'План' : value === 'fact' ? 'Факт' : 'Уведомление'}</button>)}</div>}
      {mode === 'notice' ? <><label>Участник<select required value={noticeUser} onChange={e => setNoticeUser(e.target.value)}><option value="">Выберите участника</option>{state.members.filter(m => participants.includes(m.user_id)).map(m => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}</select></label><label>Сообщено, Москва<input type="datetime-local" min={`${MIN_DATE}T00:00`} max={`${state.scope.today}T23:59`} value={reportedAt} onChange={e => setReportedAt(e.target.value)} required /></label></> : <>
        {mode === 'plan' && <div className="ac-meeting-time" aria-label="Дата и время встречи"><div><CalendarDays size={16} aria-hidden="true" /><time dateTime={validDate(date) ? date : undefined}>{validDate(date) ? new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC' }).format(new Date(`${date}T00:00:00Z`)) : 'Дата не указана'}</time><span>{timeError ? 'Время требует уточнения' : `${timeLabel(start)}–${timeLabel(start + duration)} · ${duration} мин`}</span></div><button type="button" className="ac-icon" aria-label="Изменить дату и время встречи" title={timeEditing ? 'Свернуть дату и время' : 'Изменить дату и время встречи'} aria-expanded={timeEditing} aria-controls={timeFieldsId} onClick={() => setTimeEditing(value => !value)}><Pencil size={16} /></button></div>}
        {(mode === 'fact' || timeEditing) && <div id={timeFieldsId} className="ac-form-grid ac-meeting-time-fields"><label>Дата<input type="date" required min={mode === 'plan' && !plan ? state.scope.today : MIN_DATE} max={MAX_DATE} value={date} onChange={e => setDate(e.target.value)} /></label><label>Начало<select value={start} onChange={e => setStart(Number(e.target.value))}>{allSlots.map(t => <option key={t} value={t}>{timeLabel(t)}</option>)}</select></label><label>Длительность, мин<input type="number" min={30} max={1440 - start} step={30} value={duration} onChange={e => setDuration(Number(e.target.value))} required /></label></div>}
        <div className="ac-meeting-primary">
        <label>Группа<select required value={group} disabled={needsOptions && !options.data} aria-busy={needsOptions && options.loading} aria-describedby={needsOptions ? optionsStatusId : undefined} onChange={e => setGroup(e.target.value)}><option value="">Выберите группу</option>{needsOptions ? <>
          {group && !eligibleGroups.some(g => g.id === group) && <option value={group} disabled>{selectedOption?.code || selectedGroup?.code || group} · {options.data ? 'недоступна для выбранного времени' : 'доступность не проверена'}</option>}
          {eligibleGroups.map(g => <option value={g.id} key={g.id}>{g.code} · {g.label}</option>)}
        </> : <>
          {group && !selectedGroup && <option value={group}>{group} · сохранена в плане</option>}
          {state.groups.filter(g => (!g.archived && !g.legacy) || g.id === group).map(g => <option value={g.id} key={g.id}>{g.code} · {g.label}</option>)}
        </>}</select></label>
        <label>Активность<input autoComplete="off" maxLength={120} required={mode === 'fact' || status === 'planned'} value={activity} onChange={e => setActivity(e.target.value)} /></label>
        <label>Докладчик<select value={speaker} required={mode === 'fact' || status === 'planned'} onChange={e => setSpeaker(e.target.value)}><option value="">Не указан</option>{speaker && !state.members.some(m => m.user_id === speaker && m.active && m.role === 'speaker') && <option value={speaker} disabled>{personName(speaker)} · {speaker === plan?.speaker_id ? 'сохранён в плане' : 'выбранный докладчик недоступен'}</option>}{state.members.filter(m => m.active && m.role === 'speaker').map(m => <option value={m.user_id} key={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>
        </div>
        {needsOptions && <div id={optionsStatusId} aria-live="polite">
          {options.loading && <p className="ac-muted" role="status">Проверка доступности групп…</p>}
          {options.error && <div className="ac-error"><p>{options.error}</p><button type="button" onClick={options.retry}><RefreshCw size={16} />Повторить проверку групп</button></div>}
          {options.data && <>
            {!eligibleGroups.length && <p className="ac-warning">Нет доступных групп для выбранного времени.</p>}
            {group && !selectedOption?.eligible && <p className="ac-warning">Выбранная группа недоступна для выбранного времени. Выбор сохранён.</p>}
            <MeetingIssues issues={optionIssues} />
            {options.data.groups.some(g => !g.eligible && g.id !== group) && <details><summary>Недоступные группы</summary>{options.data.groups.filter(g => !g.eligible && g.id !== group).map(g => <div key={g.id}><strong>{g.code} · {g.label}</strong><MeetingIssues issues={[...g.issues, ...g.warnings]} /></div>)}</details>}
          </>}
        </div>}
        {group && <p className="ac-muted ac-meeting-composition">А: {personName(composition?.auditor_id)} · Т: {personName(composition?.tech_id)}</p>}
        {mode === 'plan' ? <label>Статус<select value={status} onChange={e => setStatus(e.target.value as CalendarPlan['status'])}>{(['draft', 'planned', 'cancelled'] as const).map(s => <option key={s} value={s}>{calendarStatuses[s]}</option>)}</select></label> : <><div className="ac-form-grid"><label>Результат<select value={outcome} onChange={e => setOutcome(e.target.value as CalendarFact['outcome'])}><option value="completed">Проведено</option><option value="cancelled">Отменено</option></select></label><label>Отсутствие аудитора, мин<input type="number" min={0} max={1440} step={1} value={absentMinutes} onChange={e => { const n = Number(e.target.value); setAbsentMinutes(n); if (n > 5) setOutcome('cancelled') }} /></label></div><label>Подтверждение<textarea required maxLength={4000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label><p className="ac-warning">После сохранения факт и состав нельзя изменить.</p></>}
      </>}
      {(reasonRequired || reason) && <label>Основание<textarea required={reasonRequired} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>}
      {plan && <><p className="ac-muted">Источник: {plan.origin}{plan.source_id ? ` · ${plan.source_id}` : ''}</p>{savedIssues.length > 0 && <div><strong>Замечания к сохранённому плану</strong><MeetingIssues issues={savedIssues} /></div>}{state.notices.filter(n => n.plan_id === plan.id).map(n => <p key={n.id} className="ac-muted">{personName(n.user_id)}: {n.reason} · {new Date(n.reported_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</p>)}</>}
    </div>
  </CalendarCommandForm>
}
