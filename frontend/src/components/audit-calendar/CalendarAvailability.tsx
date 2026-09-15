import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Eraser, Lock, MessageSquare, Plus, RefreshCw, X } from 'lucide-react'
import { auditCalendar, type AvailabilityPatch, type CalendarState } from '@/api/auditCalendar'
import { absentOn, activeChangeRequest, addDays, availabilityLocked, clampDay, dateLabel, dateRange, errorText, serverTimeLabel, slotValue, timeLabel, workSlots } from '@/lib/auditCalendar'
import { useCalendarDraftGuard, useCalendarMutation } from '@/lib/auditCalendarHooks'
import { availabilityIntent, availabilityIntentProblem, availabilityReview, type AvailabilityIntent } from '@/lib/auditCalendarAvailability'
import type { AvailabilityAction } from './CalendarAvailabilityAction'

type Gesture = { pointer: number; first: AvailabilityPatch; value: boolean; visited: Map<string, AvailabilityPatch>; dragged: boolean; x: number; y: number; baseline: CalendarState; user: string }
const valueLabel = (value: boolean | null) => value === true ? 'Свободен' : value === false ? 'Занят' : 'Не указано'
export function CalendarAvailability({ state, from, person, setPerson, day, setDay, onRefresh, onAbsence, onAction }: { state: CalendarState; from: string; person: string; setPerson: (id: string) => void; day: string; setDay: (date: string) => void; onRefresh: () => Promise<CalendarState>; onAbsence: (id: string) => void; onAction: (action: AvailabilityAction) => void }) {
  const user = person || state.actor.user_id
  const days = dateRange(from, clampDay(addDays(from, 13)))
  const selected = days.includes(day) ? day : from
  const editable = !state.scope.archived && (state.actor.can_manage || user === state.actor.user_id) && !!state.members.find(m => m.user_id === user && m.active)
  const [preview, setPreview] = useState<AvailabilityPatch[]>([])
  const [pending, setPending] = useState<AvailabilityIntent | null>(null)
  const pendingRef = useRef<AvailabilityIntent | null>(null)
  const [review, setReview] = useState<CalendarState | null>(null)
  const [approved, setApproved] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [saved, setSaved] = useState('')
  const gesture = useRef<Gesture | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const suppressClick = useRef(false)
  const mutation = useCalendarMutation()
  const sendLock = useRef(false)
  useCalendarDraftGuard(!!pending || preview.length > 0, { protectPeriod: true })
  const locked = mutation.busy || refreshing || !!pending
  const commitRef = useRef<(patches: AvailabilityPatch[], baseline: CalendarState, user: string) => void>(() => undefined)
  function clearDraft() {
    pendingRef.current = null; setPending(null); setReview(null); setApproved(false); setConfirmed(false); setPreview([])
    mutation.rebase('')
  }
  async function refreshSaved() {
    await onRefresh()
    clearDraft()
  }
  async function send(intent: AvailabilityIntent) {
    if (sendLock.current) return
    // An uncertain write may already be committed. Resolve its original UUID even
    // if a later refresh shows a newly closed day; never turn it into a new write.
    const problem = mutation.uncertain ? '' : availabilityIntentProblem(state, intent)
    if (problem) { mutation.setError(problem); return }
    sendLock.current = true
    try {
      const result = await mutation.run(intent.command, intent.version, (id, expected) => auditCalendar.command(intent.command, id, expected), {
        conflictCode: 'AVAILABILITY_CHANGED',
        conflictMessage: 'Выбранные интервалы изменены другим пользователем. Черновик сохранён.',
      })
      if (result) {
        setConfirmed(true); setSaved(`Сохранено интервалов: ${intent.command.payload.patches.length}`)
        setRefreshing(true)
        try { await refreshSaved() } catch (e) { mutation.setError(`Изменения сохранены. ${errorText(e)}`) }
      }
    } finally { sendLock.current = false; setRefreshing(false) }
  }
  function commit(patches: AvailabilityPatch[], baseline = state, target = user) {
    if (!patches.length || sendLock.current || pendingRef.current) return
    const intent = availabilityIntent(baseline, target, patches)
    pendingRef.current = intent; setPending(intent); setPreview([]); setSaved(''); setReview(null); setApproved(false)
    void send(intent)
  }
  async function refreshDraft() {
    if (sendLock.current || !pendingRef.current || mutation.uncertain) return
    sendLock.current = true; setRefreshing(true)
    try {
      if (confirmed) await refreshSaved()
      else {
        const snapshot = await onRefresh()
        setReview(snapshot); setApproved(false)
        mutation.setError(availabilityIntentProblem(snapshot, pendingRef.current))
      }
    } catch (e) { mutation.setError(errorText(e)) }
    finally { sendLock.current = false; setRefreshing(false) }
  }
  function applyReviewed() {
    if (!pending || !review || !approved || sendLock.current || mutation.uncertain) return
    const problem = availabilityIntentProblem(review, pending) || availabilityIntentProblem(state, pending)
    if (problem) { mutation.setError(problem); return }
    const intent = availabilityIntent(review, pending.command.payload.user_id, pending.command.payload.patches)
    pendingRef.current = intent; setPending(intent); setReview(null); setApproved(false)
    mutation.rebase('')
    void send(intent)
  }
  commitRef.current = (patches, baseline, target) => { commit(patches, baseline, target) }
  useEffect(() => {
    const discard = () => { gesture.current = null; setPreview([]); suppressClick.current = true }
    const move = (event: PointerEvent) => {
      const g = gesture.current
      if (!g || g.pointer !== event.pointerId) return
      if (!(event.buttons & 1)) { discard(); return }
      const visit = (x: number, y: number) => {
        const button = document.elementFromPoint(x, y)?.closest<HTMLButtonElement>('[data-ac-slot]')
        if (!button || !root.current?.contains(button) || button.disabled) return
        const date = button.dataset.date!
        const start = Number(button.dataset.start)
        if (date !== g.first.date || start !== g.first.start) g.dragged = true
        if (g.dragged) g.visited.set(`${date}/${start}`, { date, start, end: start + 30, value: g.value })
      }
      if (Math.hypot(event.clientX - g.x, event.clientY - g.y) > 6) g.dragged = true
      if (g.dragged) {
        event.preventDefault()
        g.visited.set(`${g.first.date}/${g.first.start}`, { ...g.first, value: g.value })
        const steps = Math.min(600, Math.max(1, Math.ceil(Math.hypot(event.clientX - g.x, event.clientY - g.y) / 8)))
        for (let i = 1; i <= steps; i++) visit(g.x + (event.clientX - g.x) * i / steps, g.y + (event.clientY - g.y) * i / steps)
        setPreview([...g.visited.values()])
      }
      g.x = event.clientX; g.y = event.clientY
    }
    const up = (event: PointerEvent) => {
      const g = gesture.current
      if (!g || g.pointer !== event.pointerId) return
      gesture.current = null
      if (g.dragged) { suppressClick.current = true; commitRef.current([...g.visited.values()], g.baseline, g.user) }
      else setPreview([])
    }
    const visibility = () => { if (document.hidden) discard() }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', discard)
    window.addEventListener('blur', discard)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', discard); window.removeEventListener('blur', discard)
      document.removeEventListener('visibilitychange', visibility)
      gesture.current = null
    }
  }, [])
  function cell(date: string, start: number) {
    const draft = preview.find(p => p.date === date && p.start === start) || (pending?.command.payload.user_id === user ? [...pending.command.payload.patches].reverse().find(p => p.date === date && p.start <= start && p.end > start) : undefined)
    const value = draft ? draft.value : slotValue(state.availability, user, date, start)
    const absence = absentOn(state, user, date)
    const dayLocked = availabilityLocked(state, user, date)
    return <button type="button" key={start} data-ac-slot data-date={date} data-start={start} className={`ac-av-slot ${absence ? 'ac-absent' : value === true ? 'ac-free' : value === false ? 'ac-busy' : 'ac-unknown'}`} disabled={!editable || locked || dayLocked || !!absence || date < state.scope.today} title={dayLocked ? 'День закрыт для изменений' : absence ? absence.reason : valueLabel(value)} aria-label={`${date} ${timeLabel(start)}: ${absence ? 'Отсутствие' : valueLabel(value)}`}
      onPointerDown={e => {
        suppressClick.current = false
        if (e.button !== 0 || !['mouse', 'pen'].includes(e.pointerType)) return
        gesture.current = { pointer: e.pointerId, first: { date, start, end: start + 30, value }, value: value ?? true, visited: new Map(), dragged: false, x: e.clientX, y: e.clientY, baseline: state, user }
      }}
      onClick={e => { if (suppressClick.current && e.detail !== 0) { suppressClick.current = false; return }; void commit([{ date, start, end: start + 30, value: value === null ? true : value === true ? false : null }]) }}>
      {absence ? '—' : value === true ? <Check size={15} /> : value === false ? <X size={15} /> : '·'}<span className="ac-av-mobile-label">{absence ? 'Отсутствие' : valueLabel(value)}</span>
    </button>
  }
  function wholeDay(date: string) {
    const dayLocked = availabilityLocked(state, user, date)
    const request = activeChangeRequest(state, user, date)
    const lock = state.availability_locks.find(l => l.user_id === user && l.date === date && l.locked)
    return <div className="ac-whole-day"><small>00:00–24:00</small><div className="ac-actions" role="group" aria-label={`${date}: Действия на весь день`}>{([{ value: true, label: 'Свободен', Icon: Check }, { value: false, label: 'Занят', Icon: X }, { value: null, label: 'Очистить', Icon: Eraser }] as const).map(({ value, label, Icon }) => <button type="button" key={label} className="ac-icon" title={`${label} · весь день 00:00–24:00`} aria-label={`${date}: ${label}, весь день 00:00–24:00`} disabled={!editable || locked || dayLocked || !!absentOn(state, user, date) || date < state.scope.today} onClick={() => void commit([{ date, start: 0, end: 1440, value }])}><Icon size={16} /></button>)}
        {editable && date >= state.scope.today && !request && (dayLocked || state.actor.can_manage) && <button type="button" className="ac-icon" disabled={locked} title={dayLocked ? 'Запросить изменение дня' : 'Зафиксировать день'} aria-label={`${date}: ${dayLocked ? 'Запросить изменение дня' : 'Зафиксировать день'}`} onClick={() => onAction({ kind: dayLocked ? 'request' : 'lock', user, date })}>{dayLocked ? <MessageSquare size={16} /> : <Lock size={16} />}</button>}
      </div>
      {(dayLocked || request) && <div className="ac-day-lock-actions">{dayLocked && <span className="ac-lock-label" title={`Зафиксировано, Москва: ${serverTimeLabel(lock?.locked_at || null)}`}><Lock size={14} aria-hidden="true" />Закрыт</span>}
        {request && (state.actor.can_manage || user === state.actor.user_id) && <Link className="ac-request-status-link" to={`?view=readiness&summary_tab=requests&from=${date}&to=${date}`}>{request.status === 'pending' ? 'Заявка ожидает решения' : 'Открыто по заявке'}</Link>}
      </div>}
    </div>
  }
  return <section ref={root} aria-label="Доступное время"><header className="ac-section-head"><h2>Доступное время</h2><span className="ac-muted">{dateLabel(from)}–{dateLabel(days[days.length - 1])}</span></header>
    <div className="ac-toolbar"><label>Участник<select value={user} disabled={locked} onChange={e => setPerson(e.target.value)}>{state.members.map(m => <option key={m.user_id} value={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>{editable && <button type="button" disabled={locked} onClick={() => onAbsence(user)}><Plus size={16} />Отсутствие</button>}<div className="ac-legend"><span><Check size={14} />Свободен</span><span><X size={14} />Занят</span><span>· Не указано</span></div></div>
    {!editable && <p className="ac-muted">Только просмотр. Сотрудник изменяет свою доступность.</p>}
    {mutation.error && <div className="ac-error" role="alert">{mutation.error}</div>}
    {pending && !confirmed && <section aria-label="Несохранённые интервалы">
      <h3>Несохранённые интервалы</h3>
      {review ? <div className="ac-table-wrap"><table aria-label="Проверка изменений" style={{ tableLayout: 'fixed' }}><colgroup><col style={{ width: '31%' }} /><col /><col /><col /></colgroup><thead><tr><th>Дата и время</th><th>Было</th><th>Сейчас</th><th>Мой выбор</th></tr></thead><tbody>{availabilityReview(pending, review).map(row => <tr key={`${row.date}/${row.start}`}><td><time dateTime={row.date}>{dateLabel(row.date)}</time><br />{timeLabel(row.start)}–{timeLabel(row.end)}</td><td>{valueLabel(row.expected)}</td><td>{valueLabel(row.current)}</td><td>{valueLabel(row.value)}</td></tr>)}</tbody></table></div>
        : <ul>{pending.command.payload.patches.map(patch => <li key={`${patch.date}/${patch.start}`}>{dateLabel(patch.date)} · {timeLabel(patch.start)}–{timeLabel(patch.end)} · {valueLabel(patch.value)}</li>)}</ul>}
      {review && <label className="ac-check"><input type="checkbox" checked={approved} disabled={mutation.busy || refreshing} onChange={e => setApproved(e.target.checked)} />Подтверждаю изменения выбранных интервалов</label>}
    </section>}
    {pending && !mutation.busy && <div className="ac-actions">
      {confirmed ? <button type="button" disabled={refreshing} onClick={() => void refreshDraft()}><RefreshCw size={16} />Обновить сохранённые интервалы</button>
        : review ? <button type="button" disabled={!approved || refreshing || !!availabilityIntentProblem(state, pending) || !!availabilityIntentProblem(review, pending)} onClick={applyReviewed}><Check size={16} />Применить изменения</button>
        : !mutation.stale && <button type="button" disabled={refreshing} onClick={() => void send(pending)}><RefreshCw size={16} />Повторить сохранение</button>}
      {!confirmed && !mutation.uncertain && <button type="button" disabled={refreshing} onClick={() => void refreshDraft()}><RefreshCw size={16} />Обновить и проверить изменения</button>}
      {!confirmed && <button type="button" disabled={refreshing || mutation.uncertain} onClick={() => { if (!sendLock.current) clearDraft() }}><X size={16} />Отменить несохранённые изменения</button>}
    </div>}
    <p role="status" className="ac-muted">{mutation.busy ? 'Сохранение изменений…' : refreshing ? 'Обновление данных…' : mutation.uncertain ? 'Сохранение не подтверждено. Повторите сохранение для проверки результата.' : preview.length ? `Выбрано интервалов: ${preview.length}` : saved}</p>
    <div className="ac-av-desktop"><div className="ac-av-row ac-av-head"><span>Дата</span>{workSlots.map(t => <span key={t}>{timeLabel(t)}</span>)}<span>Весь день</span></div>{days.map(date => <div className="ac-av-row" key={date}><strong title={absentOn(state, user, date)?.reason}>{dateLabel(date)}{absentOn(state, user, date) && <small>Отсутствие</small>}</strong>{workSlots.map(t => cell(date, t))}{wholeDay(date)}</div>)}</div>
    <div className="ac-av-mobile"><label>День<select value={selected} disabled={locked} onChange={e => setDay(e.target.value)}>{days.map(d => <option key={d} value={d}>{dateLabel(d)}</option>)}</select></label>{wholeDay(selected)}{workSlots.map(t => <div className="ac-av-time" key={t}><time>{timeLabel(t)}</time>{cell(selected, t)}</div>)}</div>
  </section>
}
