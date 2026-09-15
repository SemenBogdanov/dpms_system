import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarDays, Check, ChevronLeft, ChevronRight, HelpCircle, Lock, RefreshCw, UserPlus, X } from 'lucide-react'
import { auditCalendar, type CalendarMember, type CalendarState, type CalendarTimeline, type CalendarTimelineMeeting } from '@/api/auditCalendar'
import { ApiError } from '@/api/client'
import { addDays, allSlots, calendarRoles, dateLabel, dateRange, errorText, serverTimeLabel, timeLabel, validDate, workSlots } from '@/lib/auditCalendar'
import { commonTimelineStatus, indexTimeline, indexedTimelineSlot, MAX_TIMELINE_PARTICIPANTS, overlapsSlot, personMeetings, timelineLanes, timelineRoles, timelineSlot, timelineStatusLabels, type TimelineStatus } from '@/lib/auditCalendarTimeline'
import { CalendarModal } from './CalendarModal'

const commonLabels = { free: 'Все свободны', unknown: 'Не все указали время', blocked: 'Общего свободного окна нет', empty: 'Участники не выбраны' }
const roleAllowed = (member: CalendarMember) => timelineRoles.some(role => role.id === member.role)
function SlotIcon({ status }: { status: TimelineStatus }) {
  return status === 'free' ? <Check size={13} aria-hidden="true" /> : status === 'unknown' ? <span aria-hidden="true">·</span> : status === 'booked' ? <CalendarDays size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />
}

function ParticipantPicker({ members, selected, onApply, onClose }: { members: CalendarMember[]; selected: string[]; onApply: (ids: string[]) => void; onClose: () => void }) {
  const [chosen, setChosen] = useState(selected)
  const [search, setSearch] = useState('')
  const visible = members.filter(m => `${m.full_name} ${m.code}`.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')))
  const dirty = [...chosen].sort().join() !== [...selected].sort().join()
  return <CalendarModal title="Участники сводки" dirty={dirty} onClose={onClose}>
    <label>Поиск сотрудника<input type="search" autoComplete="off" value={search} onChange={event => setSearch(event.target.value)} /></label>
    <div className="ac-actions ac-timeline-picker-tools"><button type="button" onClick={() => setChosen([...new Set([...chosen, ...visible.map(m => m.user_id)])])}><Check size={16} />Выбрать найденных</button><button type="button" onClick={() => setChosen(chosen.filter(id => !visible.some(m => m.user_id === id)))}><X size={16} />Снять выбор</button></div>
    <div className="ac-timeline-picker-list">{timelineRoles.map(role => <section key={role.id} aria-label={role.label}><h3>{role.label}</h3>{visible.filter(m => m.role === role.id).map(member => <label key={member.user_id} className="ac-check"><input type="checkbox" checked={chosen.includes(member.user_id)} onChange={event => setChosen(event.target.checked ? [...chosen, member.user_id] : chosen.filter(id => id !== member.user_id))} />{member.code} · {member.full_name}{!member.active && ' · неактивен'}</label>)}</section>)}{!visible.length && <p className="ac-empty">Сотрудники не найдены.</p>}</div>
    {chosen.length > MAX_TIMELINE_PARTICIPANTS && <p className="ac-error" role="alert">Выбрано {chosen.length} участников. Максимум: {MAX_TIMELINE_PARTICIPANTS}.</p>}
    <footer className="ac-actions"><button type="button" className="ac-primary" disabled={chosen.length > MAX_TIMELINE_PARTICIPANTS} onClick={() => onApply(chosen.filter(id => members.some(m => m.user_id === id)))}><Check size={16} />Применить ({chosen.length})</button></footer>
  </CalendarModal>
}

export function CalendarAvailabilityTimeline({ state, from, to, reload, onReload, onRefresh }: { state: CalendarState; from: string; to: string; reload: number; onReload: () => void; onRefresh: () => Promise<unknown> }) {
  const [params, setParams] = useSearchParams()
  const date = params.get('summary_day') || (state.scope.today >= from && state.scope.today <= to ? state.scope.today : from)
  const invalidDate = !validDate(date) || date < from || date > to
  const fullDay = params.get('summary_full_day') === 'true'
  const slots = fullDay ? allSlots : workSlots
  const first = slots[0], end = slots[slots.length - 1] + 30
  const query = `${date}/${state.scope.version}/${reload}`
  const [loaded, setLoaded] = useState<{ query: string; data: CalendarTimeline } | null>(null)
  const [failure, setFailure] = useState<{ query: string; message: string; stale?: boolean } | null>(null)
  const [picker, setPicker] = useState(false)
  const [nextSelection, setNextSelection] = useState<string[] | null>(null)
  const [inspect, setInspect] = useState<{ user?: string; start?: number; meeting?: CalendarTimelineMeeting } | null>(null)
  const current = !invalidDate && loaded?.query === query ? loaded.data : null
  const index = useMemo(() => current ? indexTimeline(current) : null, [current])
  const statusAt = (user: string, start: number) => indexedTimelineSlot(index!, user, start)
  const error = failure?.query === query ? failure : null
  const loading = !invalidDate && !current && !error
  useEffect(() => {
    if (invalidDate) return
    const controller = new AbortController()
    setLoaded(null); setFailure(null); setInspect(null); setPicker(false)
    auditCalendar.timeline(date, controller.signal).then(data => {
      if (controller.signal.aborted) return
      if (data.date !== date || data.version !== state.scope.version) { setFailure({ query, message: 'Данные сводки изменились. Обновите календарь.', stale: true }); return }
      setLoaded({ query, data })
    }).catch(error => {
      if (controller.signal.aborted) return
      setFailure({ query, message: errorText(error) })
      if (error instanceof ApiError && [401, 403].includes(error.status)) window.dispatchEvent(new Event('audit-calendar:access-revoked'))
    })
    return () => controller.abort()
  }, [date, invalidDate, query, state.scope.version])
  // Apply URL preferences only after the protected picker releases navigation.
  useEffect(() => {
    if (picker || nextSelection === null) return
    const next = new URLSearchParams(params); next.set('summary_members', nextSelection.join(',')); setParams(next); setNextSelection(null)
  }, [nextSelection, picker, params, setParams])
  const members = (current?.members || []).filter(roleAllowed)
  const requested = params.has('summary_members') ? [...new Set((params.get('summary_members') || '').split(',').filter(Boolean))] : members.filter(m => m.active).slice(0, MAX_TIMELINE_PARTICIPANTS).map(m => m.user_id)
  const selected = members.filter(m => requested.includes(m.user_id))
  const tooMany = selected.length > MAX_TIMELINE_PARTICIPANTS
  const users = selected.map(m => m.user_id)
  const update = (values: Record<string, string>) => { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => next.set(key, value)); setParams(next) }
  const style = { '--ac-timeline-slots': slots.length } as CSSProperties
  const missing = current && requested.some(id => !members.some(m => m.user_id === id))
  const unassigned = current?.meetings.filter(meeting => !meeting.participants.length) || []
  const hiddenRoles = current?.meetings.filter(meeting => meeting.participants.some(person => !members.some(member => member.user_id === person.user_id))) || []
  const outside = current?.meetings.filter(m => m.start < first || m.start + m.duration > end).length || 0
  const dateChange = (date: string) => update({ summary_day: date })
  const inspectUsers = inspect?.user ? selected.filter(m => m.user_id === inspect.user) : selected
  return <section className="ac-timeline" aria-label="Доступность участников по времени" aria-busy={loading}>
    <div className="ac-timeline-controls"><div className="ac-actions"><button type="button" className="ac-icon" aria-label="Предыдущий день сводки" title="Предыдущий день" disabled={invalidDate || date <= from} onClick={() => dateChange(addDays(date, -1))}><ChevronLeft size={16} /></button><label>День<select aria-label="День сводки" value={invalidDate ? '' : date} onChange={event => dateChange(event.target.value)}>{invalidDate && <option value="">Выберите день</option>}{dateRange(from, to).map(day => <option key={day} value={day}>{dateLabel(day)}</option>)}</select></label><button type="button" className="ac-icon" aria-label="Следующий день сводки" title="Следующий день" disabled={invalidDate || date >= to} onClick={() => dateChange(addDays(date, 1))}><ChevronRight size={16} /></button></div>
      <label className="ac-check"><input type="checkbox" checked={fullDay} onChange={event => update({ summary_full_day: String(event.target.checked) })} />Все часы</label>
      <button type="button" disabled={!current} onClick={() => setPicker(true)}><UserPlus size={16} />Участники{current ? ` (${selected.length})` : ''}</button>
      <div className="ac-legend ac-timeline-legend"><span><i className="ac-timeline-key-free" />Свободен</span><span><i className="ac-timeline-key-busy" />Занят</span><span><i className="ac-timeline-key-unknown" />Не указано</span><span><CalendarDays size={14} />Встреча</span></div>
    </div>
    {invalidDate && <p className="ac-error" role="alert">Выберите день в установленном периоде.</p>}
    {loading && <p className="ac-empty" role="status">Загрузка доступности…</p>}
    {error && <div className="ac-error" role="alert">{error.message}<button type="button" onClick={() => error.stale ? void onRefresh().then(onReload).catch(() => undefined) : onReload()}><RefreshCw size={16} />{error.stale ? 'Обновить календарь и сводку' : 'Повторить загрузку'}</button></div>}
    {current && <>
      {missing && <p className="ac-warning">Некоторые выбранные сотрудники недоступны. Проверьте список участников.</p>}
      {!params.has('summary_members') && members.filter(m => m.active).length > MAX_TIMELINE_PARTICIPANTS && <p className="ac-warning">Показано участников: {selected.length} из {members.filter(m => m.active).length}.</p>}
      {tooMany && <p className="ac-error" role="alert">Выбрано {selected.length} участников. Максимум: {MAX_TIMELINE_PARTICIPANTS}.</p>}
      {outside > 0 && !fullDay && <button type="button" className="ac-text-button" onClick={() => update({ summary_full_day: 'true' })}>Встречи за пределами 10:00–18:00: {outside}</button>}
      {!selected.length ? <p className="ac-empty">Участники не выбраны.</p> : !tooMany && <div className="ac-timeline-scroll" tabIndex={0} role="region" aria-label="Временная шкала выбранных участников"><table className="ac-timeline-table" style={{ ...style, minWidth: 220 + slots.length * 52 }}><colgroup><col className="ac-timeline-name-col" /><col span={slots.length} /></colgroup>
        <thead><tr><th scope="col">Участники · {dateLabel(date)}</th>{slots.map(start => <th key={start} scope="col">{timeLabel(start)}</th>)}</tr></thead>
        <tbody><tr className="ac-timeline-common"><th scope="row">Общее время<small>{selected.length} участников</small></th><td colSpan={slots.length}><div className="ac-timeline-cells">{slots.map(start => { const result = commonTimelineStatus(users.map(user => statusAt(user, start))); const status = missing && result === 'free' ? 'unknown' : result; return <button key={start} type="button" className={`ac-timeline-cell ac-common-${status}`} title={commonLabels[status]} aria-label={`${timeLabel(start)}–${timeLabel(start + 30)}: ${commonLabels[status]}`} onClick={() => setInspect({ start })}>{status === 'free' ? <Check size={14} aria-hidden="true" /> : status === 'unknown' ? <HelpCircle size={14} aria-hidden="true" /> : <span aria-hidden="true">—</span>}</button> })}</div></td></tr></tbody>
          {timelineRoles.map(role => {
            const people = selected.filter(member => member.role === role.id)
            return people.length > 0 && <tbody key={role.id} className="ac-timeline-role-body"><tr className="ac-timeline-role"><th colSpan={slots.length + 1} scope="rowgroup">{role.label} · {people.length}</th></tr>{people.map(member => {
              const lanes = timelineLanes(index!.meetings.get(member.user_id) || [], first, end)
              const lock = current.locks.find(lock => lock.user_id === member.user_id && lock.date === date && lock.locked)
              return <tr key={member.user_id}><th scope="row"><div className="ac-timeline-person"><div><strong>{member.code}</strong> · {member.full_name}{!member.active && <small>Неактивен</small>}{lock && <span role="img" className="ac-timeline-lock" aria-label="День закрыт" title={`Зафиксировано: ${serverTimeLabel(lock.locked_at)}`}><Lock size={12} /></span>}</div><button type="button" className="ac-icon" aria-label={`Убрать из сводки: ${member.full_name}`} title="Убрать из сводки" onClick={() => update({ summary_members: users.filter(id => id !== member.user_id).join(',') })}><X size={13} /></button></div></th><td colSpan={slots.length}><div className="ac-timeline-track" style={{ '--ac-timeline-lanes': Math.max(1, ...lanes.map(item => item.lane + 1)) } as CSSProperties}>
                <div className="ac-timeline-cells">{slots.map(start => { const status = statusAt(member.user_id, start); return <button key={start} type="button" className={`ac-timeline-cell ac-time-${status}`} title={timelineStatusLabels[status]} aria-label={`${member.code}, ${timeLabel(start)}–${timeLabel(start + 30)}: ${timelineStatusLabels[status]}`} onClick={() => setInspect({ user: member.user_id, start })}><SlotIcon status={status} /></button> })}</div>
                <div className="ac-timeline-events">{lanes.map(({ meeting, lane, first, last }) => <button key={`${meeting.kind}/${meeting.id}`} type="button" className={`ac-timeline-event ac-event-${meeting.kind} ${meeting.status === 'draft' ? 'ac-event-draft' : ''}`} style={{ gridColumn: `${first} / ${last}`, gridRow: lane + 1 }} title={`${meeting.group_code} · ${meeting.activity}`} aria-label={`${member.code}: ${meeting.activity}, ${timeLabel(meeting.start)}–${timeLabel(meeting.start + meeting.duration)}${meeting.status === 'draft' ? ', черновик' : meeting.kind === 'fact' ? ', факт' : ', план'}`} onClick={() => setInspect({ meeting })}><span>{meeting.status === 'draft' ? 'Черновик' : meeting.kind === 'fact' ? 'Факт' : 'План'} · {meeting.activity || meeting.group_code || 'Встреча'}</span></button>)}</div>
              </div></td></tr>
            })}</tbody>
          })}
      </table></div>}
      {unassigned.length > 0 && <details className="ac-timeline-unassigned"><summary>Встречи без установленного состава ({unassigned.length})</summary>{unassigned.map(meeting => <button type="button" key={`${meeting.kind}/${meeting.id}`} onClick={() => setInspect({ meeting })}>{timeLabel(meeting.start)} · {meeting.activity || 'Встреча'}</button>)}</details>}
      {hiddenRoles.length > 0 && <details className="ac-timeline-unassigned ac-warning"><summary>Встречи участников вне отображаемых ролей ({hiddenRoles.length})</summary>{hiddenRoles.map(meeting => <button type="button" key={`${meeting.kind}/${meeting.id}`} onClick={() => setInspect({ meeting })}>{timeLabel(meeting.start)} · {meeting.activity || 'Встреча'}</button>)}</details>}
    </>}
    {picker && current && <ParticipantPicker members={members} selected={users} onClose={() => setPicker(false)} onApply={ids => { setPicker(false); setNextSelection(ids) }} />}
    {inspect && current && <CalendarModal title={inspect.meeting ? 'Встреча в сводке' : 'Доступность интервала'} onClose={() => setInspect(null)}>
      <p>{dateLabel(date)} · {timeLabel(inspect.meeting?.start ?? inspect.start!)}–{timeLabel(inspect.meeting ? inspect.meeting.start + inspect.meeting.duration : inspect.start! + 30)}</p>
      {inspect.meeting ? <><h3>{inspect.meeting.activity || 'Без активности'}</h3><p>{inspect.meeting.group_code} · {inspect.meeting.status === 'draft' ? 'Черновик' : inspect.meeting.kind === 'fact' ? 'Факт' : 'План'}</p><ul>{inspect.meeting.participants.map(person => <li key={`${person.user_id}/${person.role}`}>{current.members.find(m => m.user_id === person.user_id)?.full_name || 'Участник недоступен'} · {calendarRoles[person.role]}</li>)}</ul>{!inspect.meeting.participants.length && <p className="ac-warning">Состав не установлен. Встреча не отнесена к конкретным сотрудникам.</p>}</> : <div className="ac-timeline-detail">{inspectUsers.map(member => <section key={member.user_id}><h3>{member.code} · {member.full_name}</h3><p>{timelineStatusLabels[timelineSlot(current, member.user_id, inspect.start!)]}</p>{current.absences.filter(a => a.user_id === member.user_id && a.status === 'active').map(a => <p key={a.id}>{a.reason}</p>)}{personMeetings(current, member.user_id).filter(m => overlapsSlot(m, inspect.start!)).map(m => <p key={`${m.kind}/${m.id}`}>{timeLabel(m.start)}–{timeLabel(m.start + m.duration)} · {m.activity} · {m.status === 'draft' ? 'Черновик' : m.kind === 'fact' ? 'Факт' : 'План'}</p>)}</section>)}</div>}
    </CalendarModal>}
  </section>
}
