import type { CalendarFact, CalendarPlan, CalendarState } from '@/api/auditCalendar'
import { allSlots, calendarDailyTarget, dateLabel, dateRange, numberLabel, timeLabel, workSlots } from '@/lib/auditCalendar'
import { AlertTriangle, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CalendarMeetingWindowsCell, CalendarMeetingWindowsStatus, CalendarMeetingWindowsDetails } from './CalendarMeetingWindows'
import { useCalendarMeetingWindows, type CalendarMeetingWindowsProps } from './CalendarMeetingWindowsQuery'

type Meeting = CalendarPlan | CalendarFact
export function CalendarGraph({ state, from, to, day, groupId = null, setDay, onOpen, windows }: { state: CalendarState; from: string; to: string; day: string; groupId?: string | null; setDay: (day: string) => void; onOpen: (date: string, start: number, plan?: CalendarPlan, fact?: CalendarFact) => void; windows: CalendarMeetingWindowsProps }) {
  const days = dateRange(from, to)
  const selected = days.includes(day) ? day : from
  const outside = [...state.plans, ...state.facts].some(p => p.start < 600 || p.start + p.duration > 1080)
  const canCreate = state.actor.can_manage && !state.scope.archived
  const windowContext = { ...windows, state, from, to, groupId: groupId || '', fullDay: outside }
  const availableWindows = useCalendarMeetingWindows(windowContext)
  const targetContext = useMemo(() => ({ from, to, selected, groupId, duration: windows.duration, speakerId: windows.speakerId, sourceKey: windows.sourceKey, outside }), [from, to, selected, groupId, windows.duration, windows.speakerId, windows.sourceKey, outside])
  const [windowTarget, setWindowTarget] = useState<{ context: typeof targetContext; date: string; start: number } | null>(null)
  function windowCell(date: string, start: number) {
    return <CalendarMeetingWindowsCell key={start} date={date} start={start} duration={windows.duration} cell={availableWindows.cells.get(`${date}:${start}`)} loading={availableWindows.loading} error={availableWindows.error} onOpen={() => setWindowTarget({ context: targetContext, date, start })} />
  }
  function label(record: Meeting) {
    return `${state.groups.find(g => g.id === record.group_id)?.code || '—'} ${record.activity || 'Без активности'} ${state.members.find(m => m.user_id === record.speaker_id)?.code || '—'}`
  }
  function entry(record: Meeting, layer: 'plan' | 'fact') {
    const plan = layer === 'plan' ? record as CalendarPlan : undefined
    const fact = layer === 'fact' ? record as CalendarFact : undefined
    const attention = plan && (plan.issues.length > 0 || plan.warnings.length > 0)
    return <button key={record.id} type="button" className={`ac-meeting ac-${layer} ${attention ? 'ac-attention' : ''} ${plan?.status === 'cancelled' || fact?.outcome === 'cancelled' ? 'ac-cancelled' : ''}`} title={`${timeLabel(record.start)}–${timeLabel(record.start + record.duration)} · ${label(record)}`} onClick={event => { event.currentTarget.focus(); onOpen(record.date, record.start, plan, fact) }}>{attention && <AlertTriangle size={12} />}<span>{label(record)}</span></button>
  }
  function desktopRow(date: string, layer: 'plan' | 'fact') {
    const rows: Meeting[] = (layer === 'plan' ? state.plans : state.facts).filter(p => p.date === date)
    const tracks: Meeting[][] = []
    for (const record of [...rows].sort((a, b) => a.start - b.start)) {
      let track = tracks.find(t => t.every(p => p.start + p.duration <= record.start || record.start + record.duration <= p.start))
      if (!track) { track = []; tracks.push(track) }
      track.push(record)
    }
    return <div className="ac-graph-row"><span className="ac-layer-label">{layer === 'plan' ? 'План' : 'Факт'}</span><div className="ac-grid-tracks">
      {(tracks.length ? tracks : [[]]).map((track, i) => <div className="ac-track" key={i}>
        {workSlots.map(t => <div className="ac-cell" key={t} style={{ gridColumn: (t - 600) / 30 + 1, gridRow: 1 }}>{layer === 'plan' && canCreate && date >= state.scope.today && !rows.some(p => p.start < t + 30 && p.start + p.duration > t) && i === 0 && <button type="button" className="ac-empty-slot" aria-label={`Создать план ${date} ${timeLabel(t)}`} title={`План · ${timeLabel(t)}`} onClick={() => onOpen(date, t)}><Plus size={12} /></button>}</div>)}
        {track.filter(r => r.start < 1080 && r.start + r.duration > 600).map(r => <div key={r.id} className="ac-meeting-span" style={{ gridColumn: `${Math.max(1, (r.start - 600) / 30 + 1)} / span ${Math.min(1080, r.start + r.duration) / 30 - Math.max(600, r.start) / 30}`, gridRow: 1 }}>{entry(r, layer)}</div>)}
      </div>)}
    </div></div>
  }
  const slots = outside ? allSlots : workSlots
  return <section aria-label="График встреч" className={outside ? 'ac-graph ac-force-day' : 'ac-graph'} onClickCapture={event => (event.target as Element).closest<HTMLButtonElement>('button')?.focus()}>
    <CalendarMeetingWindowsStatus sourceError={windows.sourceError || ''} loading={availableWindows.loading || !windows.enabled} error={availableWindows.error} />
    <div className="ac-desktop-graph"><div className="ac-graph-heading"><span>Дата / нагрузка</span><div>{workSlots.map(t => <span key={t}>{timeLabel(t)}</span>)}</div></div>
      {days.map(date => <div className={`ac-day ${[0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay()) ? 'ac-weekend' : ''}`} key={date}><div className="ac-day-label"><strong>{dateLabel(date)}</strong><span title="Запланировано / цель дня">{state.plans.filter(p => p.date === date && p.status === 'planned').length} / {numberLabel(calendarDailyTarget(state, date, groupId))}</span><small>план / цель</small></div><div className="ac-day-layers">{desktopRow(date, 'plan')}{desktopRow(date, 'fact')}</div><div className="ac-window-row"><span>Доступные окна</span><div className="ac-window-track">{workSlots.map(start => windowCell(date, start))}</div></div></div>)}
    </div>
    <div className="ac-day-graph"><label className="ac-day-select">День<select value={selected} onChange={e => setDay(e.target.value)}>{days.map(d => <option key={d} value={d}>{dateLabel(d)} · {d}</option>)}</select></label>{outside && <p className="ac-muted">Встречи вне 10:00–18:00 · полный день</p>}
      <div className="ac-vertical-heading ac-window-vertical"><span>Время</span><span>План</span><span>Факт</span><span title="Доступные окна" aria-label="Доступные окна">Окна</span></div>
      {slots.map(t => <div className="ac-vertical-row ac-window-vertical" key={t}><time>{timeLabel(t)}</time>{(['plan', 'fact'] as const).map(layer => {
        const records: Meeting[] = (layer === 'plan' ? state.plans : state.facts).filter(p => p.date === selected && p.start < t + 30 && p.start + p.duration > t)
        return <div key={layer}>{records.map(p => p.start === t ? entry(p, layer) : <span className="ac-continuation" key={p.id}>Продолжение до {timeLabel(p.start + p.duration)}</span>)}{!records.length && layer === 'plan' && canCreate && selected >= state.scope.today && <button className="ac-empty-slot" type="button" aria-label={`Создать план ${selected} ${timeLabel(t)}`} onClick={() => onOpen(selected, t)}><Plus size={16} /></button>}</div>
      })}<div className="ac-window-mobile-cell">{windowCell(selected, t)}</div></div>)}
    </div>
    {windowTarget?.context === targetContext && <CalendarMeetingWindowsDetails context={{ ...windowContext, enabled: !!availableWindows.enabled }} target={windowTarget} onClose={() => setWindowTarget(null)} />}
  </section>
}
