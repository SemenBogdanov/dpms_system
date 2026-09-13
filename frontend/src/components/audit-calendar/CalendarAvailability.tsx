import { useEffect, useRef, useState } from 'react'
import { Check, Eraser, Plus, RefreshCw, X } from 'lucide-react'
import { auditCalendar, type AvailabilityPatch, type CalendarState } from '@/api/auditCalendar'
import { absentOn, addDays, clampDay, dateLabel, dateRange, errorText, slotValue, timeLabel, workSlots } from '@/lib/auditCalendar'
import { useCalendarDraftGuard, useCalendarMutation } from '@/lib/auditCalendarHooks'

type Gesture = { pointer: number; first: AvailabilityPatch; value: boolean; visited: Map<string, AvailabilityPatch>; dragged: boolean; x: number; y: number }
const valueLabel = (value: boolean | null) => value === true ? 'Свободен' : value === false ? 'Занят' : 'Не указано'
export function CalendarAvailability({ state, from, person, setPerson, day, setDay, onRefresh, onAbsence }: { state: CalendarState; from: string; person: string; setPerson: (id: string) => void; day: string; setDay: (date: string) => void; onRefresh: () => Promise<unknown>; onAbsence: (id: string) => void }) {
  const user = person || state.actor.user_id
  const days = dateRange(from, clampDay(addDays(from, 13)))
  const selected = days.includes(day) ? day : from
  const editable = !state.scope.archived && (state.actor.can_manage || user === state.actor.user_id) && !!state.members.find(m => m.user_id === user && m.active)
  const [preview, setPreview] = useState<AvailabilityPatch[]>([])
  const [pending, setPending] = useState<AvailabilityPatch[]>([])
  const [saved, setSaved] = useState('')
  const gesture = useRef<Gesture | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const suppressClick = useRef(false)
  const mutation = useCalendarMutation()
  const sendLock = useRef(false)
  useCalendarDraftGuard(pending.length > 0)
  const locked = mutation.busy || pending.length > 0
  const commitRef = useRef<(patches: AvailabilityPatch[]) => void>(() => undefined)
  async function commit(patches: AvailabilityPatch[]) {
    if (!patches.length || sendLock.current) return
    sendLock.current = true
    setPending(patches); setPreview([]); setSaved('')
    const command = { operation: 'availability.paint' as const, payload: { user_id: user, patches } }
    const result = await mutation.run(command, state.scope.version, (id, expected) => auditCalendar.command(command, id, expected))
    if (result) {
      setPending([]); setSaved(`Сохранено интервалов: ${patches.length}`)
      try { await onRefresh() } catch (e) { mutation.setError(`Изменения сохранены. ${errorText(e)}`) }
    }
    sendLock.current = false
  }
  commitRef.current = patches => { void commit(patches) }
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
      if (g.dragged) { suppressClick.current = true; commitRef.current([...g.visited.values()]) }
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
    const value = preview.find(p => p.date === date && p.start === start)?.value ?? slotValue(state.availability, user, date, start)
    const absence = absentOn(state, user, date)
    return <button type="button" key={start} data-ac-slot data-date={date} data-start={start} className={`ac-av-slot ${absence ? 'ac-absent' : value === true ? 'ac-free' : value === false ? 'ac-busy' : 'ac-unknown'}`} disabled={!editable || locked || !!absence || date < state.scope.today} title={absence ? absence.reason : valueLabel(value)} aria-label={`${date} ${timeLabel(start)}: ${absence ? 'Отсутствие' : valueLabel(value)}`}
      onPointerDown={e => {
        suppressClick.current = false
        if (e.button !== 0 || !['mouse', 'pen'].includes(e.pointerType)) return
        gesture.current = { pointer: e.pointerId, first: { date, start, end: start + 30, value }, value: value ?? true, visited: new Map(), dragged: false, x: e.clientX, y: e.clientY }
      }}
      onClick={e => { if (suppressClick.current && e.detail !== 0) { suppressClick.current = false; return }; void commit([{ date, start, end: start + 30, value: value === null ? true : value === true ? false : null }]) }}>
      {absence ? '—' : value === true ? <Check size={15} /> : value === false ? <X size={15} /> : '·'}<span className="ac-av-mobile-label">{absence ? 'Отсутствие' : valueLabel(value)}</span>
    </button>
  }
  function wholeDay(date: string) {
    return <div className="ac-whole-day"><small>00:00–24:00</small><div className="ac-actions">{([{ value: true, label: 'Свободен', Icon: Check }, { value: false, label: 'Занят', Icon: X }, { value: null, label: 'Очистить', Icon: Eraser }] as const).map(({ value, label, Icon }) => <button type="button" key={label} className="ac-icon" title={`${label} · весь день 00:00–24:00`} aria-label={`${date}: ${label}, весь день 00:00–24:00`} disabled={!editable || locked || !!absentOn(state, user, date) || date < state.scope.today} onClick={() => void commit([{ date, start: 0, end: 1440, value }])}><Icon size={16} /></button>)}</div></div>
  }
  return <section ref={root} aria-label="Доступное время"><header className="ac-section-head"><h2>Доступное время</h2><span className="ac-muted">{dateLabel(from)}–{dateLabel(days[days.length - 1])}</span></header>
    <div className="ac-toolbar"><label>Участник<select value={user} disabled={locked} onChange={e => setPerson(e.target.value)}>{state.members.map(m => <option key={m.user_id} value={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>{editable && <button type="button" disabled={locked} onClick={() => onAbsence(user)}><Plus size={16} />Отсутствие</button>}<div className="ac-legend"><span><Check size={14} />Свободен</span><span><X size={14} />Занят</span><span>· Не указано</span></div></div>
    {!editable && <p className="ac-muted">Только просмотр. Сотрудник изменяет свою доступность.</p>}
    {mutation.error && <div className="ac-error" role="alert">{mutation.error}</div>}
    {pending.length > 0 && !mutation.busy && <div className="ac-actions">{mutation.stale ? <button type="button" onClick={async () => { try { await onRefresh(); mutation.rebase() } catch (e) { mutation.setError(errorText(e)) } }}><RefreshCw size={16} />Перечитать, сохранив batch</button> : <button type="button" onClick={() => void commit(pending)}>Повторить batch ({pending.length})</button>}<button type="button" onClick={() => { setPending([]); mutation.setError(''); mutation.rebase() }}>Отменить несохранённый batch</button></div>}
    <p role="status" className="ac-muted">{mutation.busy ? 'Сохранение batch…' : preview.length ? `Выбрано интервалов: ${preview.length}` : saved}</p>
    <div className="ac-av-desktop"><div className="ac-av-row ac-av-head"><span>Дата</span>{workSlots.map(t => <span key={t}>{timeLabel(t)}</span>)}<span>Весь день</span></div>{days.map(date => <div className="ac-av-row" key={date}><strong title={absentOn(state, user, date)?.reason}>{dateLabel(date)}{absentOn(state, user, date) && <small>Отсутствие</small>}</strong>{workSlots.map(t => cell(date, t))}{wholeDay(date)}</div>)}</div>
    <div className="ac-av-mobile"><label>День<select value={selected} disabled={locked} onChange={e => setDay(e.target.value)}>{days.map(d => <option key={d} value={d}>{dateLabel(d)}</option>)}</select></label>{wholeDay(selected)}{workSlots.map(t => <div className="ac-av-time" key={t}><time>{timeLabel(t)}</time>{cell(selected, t)}</div>)}</div>
  </section>
}
