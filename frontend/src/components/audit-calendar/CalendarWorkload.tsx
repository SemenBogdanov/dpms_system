import { useEffect, useId, useRef, useState } from 'react'
import { RefreshCw, AlertTriangle } from 'lucide-react'
import { auditCalendar, type CalendarState, type CalendarWorkload as Workload } from '@/api/auditCalendar'
import { ApiError } from '@/api/client'
import { calendarRoles, dateLabel, errorText, numberLabel, periodError, timeLabel } from '@/lib/auditCalendar'

type Props = {
  state: CalendarState
  from: string
  to: string
  groupId: string
  enabled: boolean
  onGroupChange: (group: string) => void
}
type Result = {
  query: string
  source: CalendarState
  data: Workload | null
  error: string
  loading: boolean
}

function percentage(value: number | null, missing: string) {
  return value === null || !Number.isFinite(value) ? missing : `${numberLabel(value)} %`
}

export function CalendarWorkload({ state, from, to, groupId, enabled, onGroupChange }: Props) {
  const groupFieldId = useId()
  const [result, setResult] = useState<Result | null>(null)
  const [retry, setRetry] = useState(0)
  const [denied, setDenied] = useState(false)
  const revoked = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const validation = periodError(from, to)
  const query = JSON.stringify({ from, to, group: groupId })

  useEffect(() => {
    const revoke = () => {
      revoked.current = true
      controller.current?.abort()
      setDenied(true)
      setResult(null)
    }
    window.addEventListener('audit-calendar:access-revoked', revoke)
    return () => window.removeEventListener('audit-calendar:access-revoked', revoke)
  }, [])

  useEffect(() => {
    if (!enabled || validation || revoked.current) return
    const abort = new AbortController()
    controller.current = abort
    const current = { query, source: state }
    setResult({ ...current, data: null, error: '', loading: true })
    void auditCalendar.workload({ from, to, ...(groupId && { group: groupId }) }, abort.signal)
      .then(data => {
        if (abort.signal.aborted || revoked.current) return
        if (data.period.from !== from || data.period.to !== to || data.period.group_id !== (groupId || null)) {
          throw new Error('Период отчёта не совпадает с выбранным. Обновите отчёт.')
        }
        if (data.version < state.scope.version) {
          throw new Error('Версия отчёта устарела. Обновите отчёт.')
        }
        setResult({ ...current, data, error: '', loading: false })
      })
      .catch(error => {
        if (abort.signal.aborted || revoked.current) return
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          revoked.current = true
          setDenied(true)
          setResult(null)
          return
        }
        setResult({ ...current, data: null, error: errorText(error), loading: false })
      })
    return () => abort.abort()
  }, [enabled, validation, state, from, to, groupId, query, retry])

  const current = enabled && result?.query === query && result.source === state ? result : null
  const data = !denied && !validation ? current?.data : null
  const loading = !denied && !validation && (!current || current.loading)
  return <section className="ac-workload" aria-label="Отчётность" aria-busy={loading}>
    <header className="ac-workload-head">
      <div><h2>Плановая загрузка сотрудников</h2><p className="ac-muted">{dateLabel(from)} – {dateLabel(to)}</p></div>
      <div className="ac-workload-controls">
        <div className="ac-field"><label htmlFor={groupFieldId}>Группа отчёта</label><select id={groupFieldId} name="workload-group" value={groupId} disabled={denied || !enabled} onChange={event => onGroupChange(event.target.value)}>
          <option value="">Все группы</option>{state.groups.map(group => <option key={group.id} value={group.id}>{group.code} · {group.label}{group.archived ? ' (архив)' : ''}</option>)}
        </select></div>
        <button type="button" className="ac-icon" title="Обновить отчёт" aria-label="Обновить отчёт" disabled={loading || denied || !enabled || !!validation} onClick={() => setRetry(value => value + 1)}><RefreshCw size={18} aria-hidden="true" /></button>
      </div>
    </header>
    {denied ? <p className="ac-error" role="alert">Доступ к отчётности отозван. Обратитесь к администратору контура.</p>
      : validation ? <p className="ac-error" role="alert">{validation}</p>
      : current?.error ? <div className="ac-error" role="alert"><strong>Отчёт не загружен</strong><p>{current.error}</p><button type="button" onClick={() => setRetry(value => value + 1)}><RefreshCw size={16} aria-hidden="true" />Повторить загрузку отчёта</button></div>
      : loading ? <p className="ac-empty" role="status">Загрузка отчётности…</p> : null}
    {data && <>
      <div className="ac-workload-period"><span>Рабочих дней: <strong>{numberLabel(data.working_days)}</strong></span><span>Пн–Пт · {timeLabel(data.working_window.start)}–{timeLabel(data.working_window.end)} · Europe/Moscow</span><span>Сотрудников: <strong>{numberLabel(data.members.length)}</strong></span></div>
      {data.members.length === 0 ? <p className="ac-empty" role="status">В выбранной группе нет сотрудников за этот период.</p>
        : <div className="ac-workload-table-wrap"><table className="ac-workload-table" role="table" aria-label="Плановая загрузка сотрудников">
          <thead><tr><th scope="col">Сотрудник</th><th scope="col">Заполнено дней</th><th scope="col">Встречи за весь период</th><th scope="col">Свободные слоты<small>по {data.working_window.slot_minutes} мин</small></th><th scope="col">Загрузка, %</th></tr></thead>
          <tbody>{data.members.map(member => <tr key={member.user_id}>
            <th scope="row" className="ac-workload-person"><strong>{member.full_name}</strong><span>{member.code} · {calendarRoles[member.role]}{!member.active && ' · Неактивен'}</span>
              <details className="ac-workload-details"><summary aria-label={`Подробности: ${member.full_name}`}>Подробности</summary><dl className="ac-workload-metrics">
                <div><dt>Норма встреч</dt><dd>{numberLabel(member.target)}</dd></div>
                <div><dt>План к норме</dt><dd>{percentage(member.norm_percent, 'Нет нормы')}</dd></div>
                <div><dt>Отсутствие, дней</dt><dd>{numberLabel(member.absence_days)}</dd></div>
                <div><dt>Не заполнено, дней</dt><dd>{numberLabel(member.unfilled_days)}</dd></div>
                <div><dt>План в рабочее время, мин</dt><dd>{numberLabel(member.planned_work_minutes)}</dd></div>
                {member.outside_work_minutes > 0 && <div><dt>Вне рабочего времени, мин</dt><dd>{numberLabel(member.outside_work_minutes)}</dd></div>}
              </dl></details>
            </th>
            <td data-label="Заполнено дней"><strong>{numberLabel(member.filled_days)} из {numberLabel(data.working_days)}</strong>{member.partial_days > 0 && <span>Частично: {numberLabel(member.partial_days)}</span>}</td>
            <td data-label="Встречи за весь период"><strong>{numberLabel(member.planned_meetings)}</strong><span>{numberLabel(member.planned_minutes)} мин</span></td>
            <td data-label="Свободные слоты"><strong>{numberLabel(member.free_slots)}</strong><span>{numberLabel(member.free_minutes)} мин</span></td>
            <td data-label="Загрузка, %"><strong className={member.power_percent !== null && Number.isFinite(member.power_percent) && member.power_percent > 100 ? 'ac-workload-overbooked' : undefined}>
              {percentage(member.power_percent, 'Нет свободного времени')}
              {member.power_percent !== null && Number.isFinite(member.power_percent) && member.power_percent > 100 && <span className="ac-workload-overbooked-mark" title="План превышает свободное время"><AlertTriangle size={15} aria-hidden="true" /><span className="sr-only">План превышает свободное время</span></span>}
            </strong></td>
          </tr>)}</tbody>
        </table></div>}
    </>}
  </section>
}
