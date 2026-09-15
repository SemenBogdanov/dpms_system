import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, Bell, Check, Lock, RefreshCw, Unlock, X } from 'lucide-react'
import { auditCalendar, type CalendarReadiness as Readiness, type CalendarState } from '@/api/auditCalendar'
import { ApiError } from '@/api/client'
import { calendarRoles, calendarStatuses, dateLabel, errorText, isWorkingDay, requestStatuses, serverTimeLabel, timeLabel } from '@/lib/auditCalendar'
import type { AvailabilityAction } from './CalendarAvailabilityAction'
import { CalendarAvailabilityTimeline } from './CalendarAvailabilityTimeline'

const employeeStatuses = { missing: 'Не заполнено', partial: 'Частично', filled: 'Заполнено', absent: 'Отсутствие' }
const groupStatuses = { no_composition: 'Нет состава', missing: 'Доступность не заполнена', absent: 'Отсутствие участника', no_overlap: 'Нет общего свободного окна', booked: 'Общие окна заняты встречами', available: 'Есть свободное окно' }
const windowLabel = (windows: { start: number; end: number }[]) => windows.map(w => `${timeLabel(w.start)}–${timeLabel(w.end)}`).join(', ') || '—'

function availabilityHref(user: string, date: string) {
  return `/audit-calendar?${new URLSearchParams({ view: 'availability', from: date, to: date, day: date, availability_person: user })}`
}

export function CalendarReadiness({ state, from, to, onAction, onRefresh }: { state: CalendarState; from: string; to: string; onAction: (action: AvailabilityAction) => void; onRefresh: () => Promise<unknown> }) {
  const [params, setParams] = useSearchParams()
  const tab = ['timeline', 'employees', 'groups', 'requests'].includes(params.get('summary_tab') || '') ? params.get('summary_tab')! : 'timeline'
  const needsReadiness = tab === 'employees' || tab === 'groups'
  const rawDuration = Number(params.get('duration') || 30)
  const duration = Number.isInteger(rawDuration) && rawDuration >= 30 && rawDuration <= 480 && rawDuration % 30 === 0 ? rawDuration : 30
  const [result, setResult] = useState<Readiness | null>(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const query = JSON.stringify({ from, to, duration, version: state.scope.version })
  const [loadedQuery, setLoadedQuery] = useState('')
  useEffect(() => {
    if (!needsReadiness) return
    const controller = new AbortController()
    setError(''); setLoadedQuery('')
    auditCalendar.readiness({ from, to, duration }, controller.signal).then(data => {
      if (!controller.signal.aborted) { setResult(data); setLoadedQuery(query) }
    }).catch(e => {
      if (controller.signal.aborted) return
      if (e instanceof ApiError && [401, 403].includes(e.status)) window.dispatchEvent(new Event('audit-calendar:access-revoked'))
      setError(errorText(e)); setResult(null)
    })
    return () => controller.abort()
  }, [from, to, duration, query, reload, needsReadiness])
  const loading = needsReadiness && !error && loadedQuery !== query
  const current = !loading && !error ? result : null
  const stale = !!current && current.scope_version !== state.scope.version
  const canNotify = state.actor.can_manage && !state.scope.archived && !stale
  const requests = state.change_requests.filter(r => r.date >= from && r.date <= to && (state.actor.can_manage || r.user_id === state.actor.user_id)).sort((a, b) => b.requested_at.localeCompare(a.requested_at))
  const name = (id: string | null) => state.members.find(m => m.user_id === id)?.full_name || id || '—'
  const inPeriod = (date: string) => date >= from && date <= to && isWorkingDay(date)
  const personLink = (id: string, date: string, label = name(id)) => <Link className="ac-readiness-link" to={availabilityHref(id, date)}>{label}<ArrowRight size={14} aria-hidden="true" /></Link>
  return <section className="ac-readiness" aria-label="Сводка доступности">
    <header className="ac-section-head"><div><h2>Сводка доступности</h2><small>{dateLabel(from)}–{dateLabel(to)} · Пн–Пт · {timeLabel(current?.working_start ?? 600)}–{timeLabel(current?.working_end ?? 1080)} · Europe/Moscow</small></div><button type="button" className="ac-icon" title="Обновить сводку" aria-label="Обновить сводку" disabled={loading} onClick={() => setReload(n => n + 1)}><RefreshCw size={16} /></button></header>
    <div className="ac-summary-controls"><nav className="ac-summary-tabs" aria-label="Вкладки сводки">{([{ id: 'timeline', label: 'По времени' }, { id: 'employees', label: 'Заполненность' }, { id: 'groups', label: 'Группы' }, { id: 'requests', label: 'Заявки' }]).map(item => {
      const next = new URLSearchParams(params); next.set('summary_tab', item.id)
      return <Link key={item.id} to={`?${next}`} aria-current={tab === item.id ? 'page' : undefined}>{item.label}{item.id === 'requests' ? ` (${requests.filter(r => ['pending', 'approved'].includes(r.status)).length})` : ''}</Link>
    })}</nav>{tab === 'groups' && <label className="ac-duration-field">Окно (мин)<select aria-label="Окно встречи, мин" value={duration} onChange={e => { const next = new URLSearchParams(params); next.set('duration', e.target.value); setParams(next) }}>{Array.from({ length: 16 }, (_, i) => (i + 1) * 30).map(n => <option key={n} value={n}>{n}</option>)}</select></label>}</div>
    {needsReadiness && <>
      {error && <div className="ac-error" role="alert">{error}<button type="button" onClick={() => setReload(n => n + 1)}>Повторить загрузку сводки</button></div>}
      {loading && <p className="ac-empty" role="status">Загрузка сводки…</p>}
      {stale && <p className="ac-warning" role="status">Версия сводки отличается от календаря. Обновите календарь перед отправкой уведомлений.</p>}
    </>}
    {tab === 'timeline' && <CalendarAvailabilityTimeline state={state} from={from} to={to} reload={reload} onReload={() => setReload(n => n + 1)} onRefresh={onRefresh} />}
    {tab === 'employees' && current && <div className="ac-readiness-list">{current.employees.length ? current.employees.map(employee => <section className="ac-readiness-person" key={employee.user_id} aria-label={employee.full_name}>
      <header className="ac-section-head"><h3>{employee.code} · {employee.full_name}</h3><span className="ac-muted">{calendarRoles[employee.role]} · заполнено {employee.filled_days} из {employee.total_days}</span></header>
      <div className="ac-readiness-days">{employee.days.filter(d => inPeriod(d.date)).map(day => <Link key={day.date} className={`ac-readiness-day ac-readiness-${day.status}`} to={availabilityHref(employee.user_id, day.date)} aria-label={`${employee.full_name}, ${day.date}: ${employeeStatuses[day.status]}${day.locked ? ', день закрыт' : ''}`}>
        <strong>{dateLabel(day.date)}</strong><span>{employeeStatuses[day.status]}</span><small>{day.free_minutes} мин свободно</small><span className="ac-lock-label">{day.locked ? <><Lock size={14} aria-hidden="true" />Закрыт</> : <><Unlock size={14} aria-hidden="true" />Открыт</>}</span>
      </Link>)}</div>
    </section>) : <p className="ac-empty">Сотрудников в сводке нет.</p>}</div>}
    {tab === 'groups' && current && <div className="ac-readiness-list">{current.groups.length ? current.groups.map(group => <section className="ac-readiness-group" key={group.group_id} aria-label={group.code}>
      <h3>{group.code} · {group.label}</h3>
      {group.days.filter(d => inPeriod(d.date)).map(day => <div className="ac-readiness-group-day" key={day.date} data-date={day.date}>
        <div><strong>{dateLabel(day.date)}</strong><p className={`ac-readiness-status ac-readiness-${day.status}`}>{groupStatuses[day.status]}</p><div className="ac-readiness-members">{day.member_ids.map(id => <span key={id}>{personLink(id, day.date)}{day.missing_user_ids.includes(id) && <small>Не заполнено полностью</small>}</span>)}</div></div>
        <div className="ac-readiness-windows"><dl><dt>Общие окна</dt><dd>{windowLabel(day.common_windows)}</dd><dt>Свободные окна</dt><dd>{windowLabel(day.free_windows)}</dd></dl>
          {day.slots.length > 0 && <details><summary>Начало встречи ({day.slots.length})</summary><p>{windowLabel(day.slots)}</p></details>}
          {day.plans.length > 0 && <details><summary>Встречи ({day.plans.length})</summary>{day.plans.map(plan => <p key={plan.id}>{timeLabel(plan.start)}–{timeLabel(plan.start + plan.duration)} · {plan.activity} · {calendarStatuses[plan.status as keyof typeof calendarStatuses] || plan.status}</p>)}</details>}
        </div>
        <div className="ac-readiness-notify">{day.last_notified_at && <small>Уведомлено, Москва: <time dateTime={day.last_notified_at}>{serverTimeLabel(day.last_notified_at)}</time></small>}{canNotify && day.status === 'no_overlap' && day.date >= state.scope.today && <button type="button" onClick={() => onAction({ kind: 'notify', group: group.group_id, date: day.date, duration })}><Bell size={16} />Уведомить группу</button>}</div>
      </div>)}
    </section>) : <p className="ac-empty">Групп в сводке нет.</p>}</div>}
    {tab === 'requests' && <div className="ac-request-list">{requests.length ? requests.map(request => <article className="ac-request" key={request.id} aria-label={`Заявка ${name(request.user_id)} ${request.date}`}>
      <header className="ac-section-head"><h3>{personLink(request.user_id, request.date)} · {dateLabel(request.date)}</h3><strong>{requestStatuses[request.status]}</strong></header>
      <p>{request.reason}</p>
      <dl className="ac-request-times"><div><dt>Обращение, Москва</dt><dd><time dateTime={request.requested_at}>{serverTimeLabel(request.requested_at)}</time><small>{name(request.requested_by_id)}</small></dd></div><div><dt>Открыто, Москва</dt><dd>{serverTimeLabel(request.opened_at)}<small>{name(request.opened_by_id)}</small></dd></div><div><dt>Закрыто, Москва</dt><dd>{serverTimeLabel(request.closed_at)}<small>{name(request.closed_by_id)}</small></dd></div></dl>
      {request.resolution && <p>Решение: {request.resolution}</p>}
      {state.actor.can_manage && !state.scope.archived && <div className="ac-actions">{request.status === 'pending' && <><button type="button" onClick={() => onAction({ kind: 'resolve', id: request.id, action: 'approve' })}><Check size={16} />Одобрить и открыть день</button><button type="button" onClick={() => onAction({ kind: 'resolve', id: request.id, action: 'reject' })}><X size={16} />Отклонить</button></>}{request.status === 'approved' && <button type="button" onClick={() => onAction({ kind: 'resolve', id: request.id, action: 'close' })}><Lock size={16} />Закрыть заявку и день</button>}</div>}
    </article>) : <p className="ac-empty">Заявок за период нет.</p>}</div>}
  </section>
}
