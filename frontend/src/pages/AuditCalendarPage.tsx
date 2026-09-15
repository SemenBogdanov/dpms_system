import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CalendarDays, Clock3, ListChecks, BarChart3, Database, Users, Settings2, History, Upload, ChevronLeft, ChevronRight, RefreshCw, Search, HelpCircle } from 'lucide-react'
import { auditCalendar, type CalendarFact, type CalendarMeetingWindowPrefill, type CalendarPlan, type CalendarState } from '@/api/auditCalendar'
import { ApiError } from '@/api/client'
import { addDays, calendarTargetScopes, clampDay, errorText, MAX_DATE, MIN_DATE, moscowToday, numberLabel, periodError, readinessEnd } from '@/lib/auditCalendar'
import { CalendarGraph } from '@/components/audit-calendar/CalendarGraph'
import { CalendarMeetingEditor } from '@/components/audit-calendar/CalendarMeetingEditor'
import { CalendarAvailability } from '@/components/audit-calendar/CalendarAvailability'
import { CalendarReadiness } from '@/components/audit-calendar/CalendarReadiness'
import { CalendarWorkload } from '@/components/audit-calendar/CalendarWorkload'
import { CalendarAvailabilityAction, type AvailabilityAction } from '@/components/audit-calendar/CalendarAvailabilityAction'
import { CalendarActionEditor, CalendarDirectories, CalendarManagement, AbsenceList, type CalendarAction } from '@/components/audit-calendar/CalendarManagement'
import { CalendarDataset } from '@/components/audit-calendar/CalendarDataset'
import { CalendarHistory } from '@/components/audit-calendar/CalendarHistory'
import { CalendarImports, CalendarRestoreEditor } from '@/components/audit-calendar/CalendarImports'
import '@/components/audit-calendar/audit-calendar.css'

const views = [
  { id: 'graph', label: 'График встреч', Icon: CalendarDays }, { id: 'availability', label: 'Доступное время', Icon: Clock3 },
  { id: 'readiness', label: 'Сводка доступности', Icon: ListChecks },
  { id: 'workload', label: 'Отчётность', Icon: BarChart3 },
  { id: 'dataset', label: 'Датасет', Icon: Database }, { id: 'directories', label: 'Справочники', Icon: Users },
  { id: 'management', label: 'Управление', Icon: Settings2, helper: true }, { id: 'history', label: 'Журнал', Icon: History, helper: true },
  { id: 'imports', label: 'Импорт', Icon: Upload, helper: true }, { id: 'help', label: 'Справка', Icon: HelpCircle },
]
type MeetingSelection = { date: string; start: number; plan?: CalendarPlan; fact?: CalendarFact; prefill?: CalendarMeetingWindowPrefill }
export function AuditCalendarPage() {
  const [params, setParams] = useSearchParams()
  const [initialToday] = useState(moscowToday)
  const rawFrom = params.get('from') || initialToday
  const rawTo = params.get('to') || clampDay(addDays(initialToday, 6))
  const urlError = periodError(rawFrom, rawTo)
  const from = urlError ? initialToday : rawFrom
  const view = views.some(v => v.id === params.get('view')) ? params.get('view')! : 'graph'
  const periodTo = urlError ? clampDay(addDays(initialToday, 6)) : rawTo
  const to = view === 'readiness' ? readinessEnd(from, periodTo) : periodTo
  const group = params.get('group') || ''
  const person = params.get('person') || ''
  const q = params.get('q') || ''
  const windowDuration = Number(params.get('window_duration') ?? 30)
  const windowSpeaker = params.get('window_speaker') || ''
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')
  const [draftFrom, setDraftFrom] = useState(from)
  const [draftTo, setDraftTo] = useState(to)
  const [search, setSearch] = useState(q)
  const [validation, setValidation] = useState('')
  const [data, setData] = useState<CalendarState | null>(null)
  const [error, setError] = useState('')
  const [denied, setDenied] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dataQuery, setDataQuery] = useState('')
  const [meeting, setMeeting] = useState<MeetingSelection | null>(null)
  const [action, setAction] = useState<CalendarAction | null>(null)
  const [restore, setRestore] = useState<CalendarPlan | null>(null)
  const [availabilityAction, setAvailabilityAction] = useState<AvailabilityAction | null>(null)
  const requestSequence = useRef(0)
  const stateController = useRef<AbortController | null>(null)
  const errorPanel = useRef<HTMLDivElement | null>(null)
  const queryTo = view === 'availability' ? clampDay(addDays(from, 13)) : to
  const query = JSON.stringify({ from, to: queryTo, group, person, q, view })
  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current
    stateController.current?.abort()
    const controller = new AbortController()
    stateController.current = controller
    setLoading(true)
    try {
      const result = await auditCalendar.state({ from, to: queryTo, ...(group && view !== 'readiness' && { group }), ...(person && !['availability', 'readiness', 'workload'].includes(view) && { person }), ...(q && !['readiness', 'workload'].includes(view) && { q }) }, controller.signal)
      if (sequence === requestSequence.current) { setData(result); setDataQuery(query); setError(''); setDenied(false) }
      return result
    } catch (e) {
      if (sequence === requestSequence.current) {
        const forbidden = e instanceof ApiError && [401, 403].includes(e.status)
        setError(errorText(e)); setDenied(forbidden)
        if (forbidden) { setMeeting(null); setAction(null); setRestore(null); setAvailabilityAction(null); setData(null) }
      }
      throw e
    } finally { if (sequence === requestSequence.current) setLoading(false) }
  }, [from, queryTo, group, person, q, view, query])
  useEffect(() => {
    void refresh().catch(() => undefined)
    return () => { requestSequence.current += 1; stateController.current?.abort() }
  }, [refresh])
  useEffect(() => {
    const focus = () => {
      if (document.visibilityState === 'visible' && view === 'graph' && !denied) void refresh().catch(() => undefined)
    }
    const visibility = () => { setVisible(document.visibilityState === 'visible'); focus() }
    window.addEventListener('focus', focus)
    document.addEventListener('visibilitychange', visibility)
    return () => { window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', visibility) }
  }, [refresh, view, denied])
  useEffect(() => {
    if (data && !params.has('from') && !params.has('to')) {
      const next = new URLSearchParams(params)
      next.set('from', data.scope.today); next.set('to', clampDay(addDays(data.scope.today, 6)))
      setParams(next, { replace: true })
    }
  }, [data, params, setParams])
  useEffect(() => {
    const revoke = () => {
      requestSequence.current += 1
      stateController.current?.abort()
      setLoading(false)
      setData(null); setMeeting(null); setAction(null); setRestore(null); setAvailabilityAction(null); setDenied(true); setError('Доступ отозван. Обратитесь к администратору контура.')
    }
    window.addEventListener('audit-calendar:access-revoked', revoke)
    return () => window.removeEventListener('audit-calendar:access-revoked', revoke)
  }, [])
  useEffect(() => { setDraftFrom(from); setDraftTo(to); setSearch(q) }, [from, to, q])
  useEffect(() => { if (denied) errorPanel.current?.focus() }, [denied])
  const update = (changes: Record<string, string>) => {
    // BrowserRouter commits history before its deferred render; merge rapid edits
    // into that latest URL instead of overwriting them with a render's snapshot.
    const next = new URLSearchParams(window.location.search)
    Object.entries(changes).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    setParams(next)
  }
  const applyPeriod = (first: string, last: string) => {
    const problem = periodError(first, last)
    if (problem) { setValidation(problem); return }
    const end = view === 'readiness' ? readinessEnd(first, last) : last
    setDraftFrom(first); setDraftTo(end)
    setValidation(''); update({ from: first, to: end, day: first })
  }
  const open = (date: string, start: number, plan?: CalendarPlan, fact?: CalendarFact) => setMeeting({ date, start, plan, fact })
  const selectedDay = params.get('day') || from
  const windowsEnabled = !loading && dataQuery === query && !error && !urlError && visible
  const canView = (item: typeof views[number]) => !item.helper || data?.actor.can_manage || (item.id === 'management' && data?.actor.can_archive)
  return <div className="ac ac-page"><header className="ac-page-head"><div><h1>Сетевой план-график</h1><p className="ac-muted">{data?.scope.name || 'Календарь аудита'} · Europe/Moscow</p></div>{data && !denied && <div className="ac-kpis" aria-label="Показатели периода">{([{ key: 'plan', label: 'План' }, { key: 'fact', label: 'Факт' }, { key: 'attention', label: 'Внимание' }, { key: 'target', label: 'Цель' }] as const).map(k => <div key={k.key} className={`ac-kpi ac-kpi-${k.key}`}><strong>{numberLabel(data.stats[k.key])}</strong><span>{k.label}</span></div>)}</div>}</header>
    <div className="ac-workspace"><aside className="ac-local-column"><div className="ac-local-context"><CalendarDays size={22} /><strong>Аудит</strong><span>{data?.scope.archived ? 'Архив' : data?.actor.can_manage ? 'Помощник' : 'Просмотр'}</span></div><nav aria-label="Представления календаря">{views.filter(canView).map(({ id, label, Icon }) => { const next = new URLSearchParams(params); next.set('view', id); if (id === 'readiness') next.set('to', readinessEnd(from, to)); return <Link key={id} to={`?${next}`} aria-current={view === id ? 'page' : undefined}><Icon size={18} /><span>{label}</span></Link> })}</nav></aside>
      <main className="ac-content" aria-busy={loading}>
        <div className="ac-filters"><form className="ac-period" onSubmit={e => { e.preventDefault(); applyPeriod(draftFrom, draftTo) }}><label>С<input type="date" min={MIN_DATE} max={MAX_DATE} required value={draftFrom} onChange={e => setDraftFrom(e.target.value)} /></label><label>По<input type="date" min={MIN_DATE} max={MAX_DATE} required value={draftTo} onChange={e => setDraftTo(e.target.value)} /></label><button type="submit">Применить</button></form><div className="ac-actions"><button className="ac-icon" type="button" aria-label="Предыдущий период" title="Предыдущий период" onClick={() => { const n = Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1; applyPeriod(clampDay(addDays(from, -n)), clampDay(addDays(to, -n))) }}><ChevronLeft size={18} /></button><button type="button" onClick={() => { const today = data?.scope.today || initialToday; applyPeriod(today, clampDay(addDays(today, 6))) }}>Сегодня</button>{[7, 14].map(n => <button type="button" key={n} onClick={() => applyPeriod(from, clampDay(addDays(from, n - 1)))}>{n} дней</button>)}<button className="ac-icon" type="button" aria-label="Следующий период" title="Следующий период" onClick={() => { const n = Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1; applyPeriod(clampDay(addDays(from, n)), clampDay(addDays(to, n))) }}><ChevronRight size={18} /></button><button type="button" className="ac-icon" disabled={loading} aria-label="Обновить календарь" title="Обновить календарь" onClick={() => void refresh().catch(() => undefined)}><RefreshCw size={16} /></button></div></div>
        {(validation || urlError) && <p className="ac-error" role="alert">{validation || urlError}</p>}
        {data && !denied && !['readiness', 'workload'].includes(view) && <div className="ac-toolbar"><label>Группа<select value={group} onChange={e => update({ group: e.target.value })}><option value="">Все группы</option>{data.groups.map(g => <option key={g.id} value={g.id}>{g.code}</option>)}</select></label>{view !== 'availability' && <label>Участник<select value={person} onChange={e => update({ person: e.target.value })}><option value="">Все участники</option>{data.members.map(m => <option key={m.user_id} value={m.user_id}>{m.code} · {m.full_name}</option>)}</select></label>}<form className="ac-search" onSubmit={e => { e.preventDefault(); update({ q: search.trim() }) }}><label><span className="sr-only">Поиск активности</span><input type="search" value={search} maxLength={200} placeholder="Активность…" onChange={e => setSearch(e.target.value)} /></label><button className="ac-icon" type="submit" title="Найти" aria-label="Найти"><Search size={16} /></button></form><div className="ac-legend"><span className="ac-plan-label">План</span><span className="ac-fact-label">Факт</span><span>△ Внимание</span></div></div>}
        {error && <div className="ac-error" role="alert" ref={errorPanel} tabIndex={-1}><strong>{denied ? 'Нет доступа к контуру' : 'Данные не обновлены'}</strong><p>{error}</p><button type="button" onClick={() => void refresh().catch(() => undefined)}>Повторить</button></div>}
        {loading && !data && <p className="ac-empty" role="status">Загрузка календаря…</p>}
        {data && !denied && <div className="ac-bound-content" ref={node => node?.toggleAttribute('inert', loading || dataQuery !== query)} aria-busy={loading || dataQuery !== query}>{view !== 'workload' && <p className="ac-scope-caption">Цель: {calendarTargetScopes[data.stats.target_scope]}. Поиск и участник не меняют цель и накопленный недобор.{data.scope.archived ? ' Контур архивирован, изменения заблокированы.' : ''}</p>}
          {view === 'graph' && <CalendarGraph state={data} from={from} to={to} day={selectedDay} groupId={group || null} setDay={day => update({ day })} onOpen={open} windows={{ duration: windowDuration, speakerId: windowSpeaker, enabled: windowsEnabled, sourceKey: query, sourceError: error || urlError, onControlsChange: update, onRefresh: refresh, onSelect: (date, start, prefill) => {
            if (windowsEnabled && data.actor.can_manage && !data.scope.archived && prefill.version === data.scope.version) setMeeting({ date, start, prefill })
          } }} />}
          {view === 'availability' && <><CalendarAvailability state={data} from={from} person={params.get('availability_person') || data.actor.user_id} setPerson={availability_person => update({ availability_person })} day={selectedDay} setDay={day => update({ day })} onRefresh={refresh} onAbsence={user => setAction({ kind: 'absence', user })} onAction={setAvailabilityAction} /><h3>Отсутствия</h3><AbsenceList state={data} onAction={setAction} /></>}
          {view === 'readiness' && <CalendarReadiness state={data} from={from} to={to} onAction={setAvailabilityAction} />}
          {view === 'workload' && <CalendarWorkload state={data} from={from} to={to} groupId={group} enabled={!loading && dataQuery === query && !error && !urlError} onGroupChange={value => update({ group: value })} />}
          {view === 'dataset' && <CalendarDataset state={data} onOpen={open} onRestore={setRestore} />}
          {view === 'directories' && <CalendarDirectories state={data} onAction={setAction} />}
          {view === 'management' && (data.actor.can_manage || data.actor.can_archive) && <CalendarManagement state={data} onAction={setAction} />}
          {view === 'history' && data.actor.can_manage && <CalendarHistory />}
          {view === 'imports' && data.actor.can_manage && <CalendarImports state={data} onRefresh={refresh} />}
          {!canView(views.find(v => v.id === view)!) && <p className="ac-empty">Представление доступно помощнику контура.</p>}
          {view === 'help' && <CalendarHelp />}
        </div>}
      </main>
    </div>
    {data && !denied && meeting && <CalendarMeetingEditor state={data} {...meeting} prefillEnabled={windowsEnabled} onClose={() => setMeeting(null)} onRefresh={refresh} />}
    {data && !denied && action && <CalendarActionEditor action={action} state={data} onClose={() => setAction(null)} onRefresh={refresh} />}
    {data && !denied && restore && <CalendarRestoreEditor plan={restore} state={data} onClose={() => setRestore(null)} onRefresh={refresh} />}
    {data && !denied && availabilityAction && <CalendarAvailabilityAction action={availabilityAction} state={data} onClose={() => setAvailabilityAction(null)} onRefresh={refresh} />}
  </div>
}

function CalendarHelp() {
  return <section className="ac-help" aria-label="Справка календаря"><h2>Календарь аудита</h2><details open><summary>План и факт</summary><p>План не подтверждает проведение. Факт содержит реальное время, состав, основание и снимок плана; после фиксации он неизменяем. Отмена не считается выполнением.</p></details><details><summary>Доступность и отсутствие</summary><p>Неуказанное время не является свободным. Если свободных окон за день нет, V5 допускает предупреждение; занятость и отсутствие блокируют назначение. При наличии свободных окон встреча должна целиком помещаться в них. Отсутствие включает обе граничные даты.</p></details><details><summary>Цели и недобор</summary><p>Рабочие дни: Пн–Пт, время контура: Москва. Командная норма и групповая квота независимы. Квота группы задаётся на 10 будней. Новая норма действует с указанной даты, не изменяя прошлое. Отпуск не уменьшает цель.</p><p>Недобор накапливается от baseline до завершённого вчерашнего дня или конца периода, если он раньше. Последующее перевыполнение погашает недобор; будущие дни не учитываются. KPI рассчитывает сервер по разрешённым данным.</p></details><details><summary>Права и восстановление</summary><p>Сотрудник изменяет свои доступность и отсутствия. Помощник управляет расписанием своего контура. Статус администратора сам по себе этих прав не даёт.</p><p>При конфликте версии ввод сохраняется. Перечитайте данные, проверьте изменения и повторите сохранение. Исторический факт требует проверенной строки источника и явного подтверждения состава либо его неизвестности.</p></details></section>
}

export default AuditCalendarPage
