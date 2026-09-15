import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, ArrowRight, Check, Clock3, Minus, RefreshCw } from 'lucide-react'
import { auditCalendar, type CalendarMeetingWindowCell, type CalendarMeetingWindowOption, type CalendarState } from '@/api/auditCalendar'
import { timeLabel } from '@/lib/auditCalendar'
import { CalendarModal } from './CalendarModal'
import { checkWindowVersion, useCalendarWindowRequest, type CalendarMeetingWindowsContext as Context } from './CalendarMeetingWindowsQuery'
type Target = { date: string; start: number }

export function CalendarMeetingWindowsControls({ state, duration, speakerId, onControlsChange }: Pick<Context, 'state' | 'duration' | 'speakerId' | 'onControlsChange'>) {
  const speakers = state.members.filter(m => m.active && m.role === 'speaker')
  return <section className="ac-window-controls" aria-label="Поиск доступных окон">
      <label>Докладчик<select aria-label="Докладчик окна" name="window_speaker" value={speakerId} onChange={event => onControlsChange({ window_speaker: event.target.value })}>
        <option value="">Все докладчики</option>
        {speakerId && !speakers.some(m => m.user_id === speakerId) && <option value={speakerId} disabled>Недоступный докладчик</option>}
        {speakers.map(m => <option key={m.user_id} value={m.user_id}>{m.code} · {m.full_name}</option>)}
      </select></label>
      <label>Окно (мин)<input name="window_duration" type="number" min={30} max={480} step={30} required value={Number.isFinite(duration) ? duration : ''} onChange={event => onControlsChange({ window_duration: event.target.value || '0' })} /></label>
  </section>
}

export function CalendarMeetingWindowsStatus({ sourceError, loading, error }: { sourceError: string; loading: boolean; error: string }) {
  return <div className="ac-window-status" aria-live="polite">
    {sourceError ? <p>Подбор недоступен до обновления календаря.</p> : error ? <p className="ac-error" role="alert">{error}</p> : loading ? <p role="status"><Clock3 size={14} aria-hidden="true" />Проверка доступных окон…</p> : null}
  </div>
}

export function CalendarMeetingWindowsCell({ date, start, duration, cell, loading, error, onOpen }: {
  date: string; start: number; duration: number; cell?: CalendarMeetingWindowCell; loading: boolean; error: string; onOpen: () => void
}) {
  const status = cell?.status || (error ? 'error' : 'pending')
  const count = cell ? cell.confirmed + cell.uncertain : 0
  const Icon = status === 'available' ? Check : status === 'warning' || status === 'error' ? AlertTriangle : status === 'pending' ? Clock3 : Minus
  const detail = cell ? `Вариантов: ${count}; подтверждено: ${cell.confirmed}; с неизвестной доступностью: ${cell.uncertain}` : error || 'Доступность не проверена'
  const interval = Number.isInteger(duration) && duration >= 30 && duration <= 480 && duration % 30 === 0 ? `${timeLabel(start)}–${timeLabel(start + duration)}` : timeLabel(start)
  const label = `Доступные окна ${date} ${interval} · ${detail}`
  return <button type="button" className={`ac-window-cell ac-window-${status}`} data-date={date} data-start={start} aria-label={label} title={label} aria-busy={loading} disabled={!cell || cell.status === 'unavailable'} onClick={event => { event.currentTarget.focus(); onOpen() }}>
    <Icon size={12} aria-hidden="true" />{count > 0 && <span>{count}</span>}
  </button>
}

function optionMatchesState(option: CalendarMeetingWindowOption, state: CalendarState, date: string) {
  const group = state.groups.find(g => g.id === option.group_id && !g.archived && !g.legacy)
  const composition = group?.versions.filter(v => v.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]
  return composition?.id === option.group_version_id && composition.auditor_id === option.auditor_id && composition.tech_id === option.tech_id
    && ([['auditor', option.auditor_id], ['tech', option.tech_id], ['speaker', option.speaker_id]] as const)
      .every(([role, id]) => state.members.some(m => m.user_id === id && m.role === role && m.active))
}

export function CalendarMeetingWindowsDetails({ context, target, onClose }: { context: Context; target: Target; onClose: () => void }) {
  const { state, duration, groupId, speakerId, enabled, sourceKey, onSelect, onRefresh } = context
  const { date, start } = target
  const [page, setPage] = useState(0)
  const refreshButton = useRef<HTMLButtonElement>(null)
  const request = useMemo(() => !enabled ? null : async (signal: AbortSignal) => {
    const data = await auditCalendar.meetingWindowOptions({ date, start, duration, ...(groupId && { group: groupId }), ...(speakerId && { speaker_id: speakerId }) }, signal)
    checkWindowVersion(data.version, data.now, state)
    const q = data.query
    if (!q || q.date !== date || q.start !== start || q.duration !== duration || q.group_id !== (groupId || null) || q.speaker_id !== (speakerId || null)
      || !Array.isArray(data.options) || data.options.length > 2000 || data.options.some(option =>
        !optionMatchesState(option, state, date) || (groupId && option.group_id !== groupId) || (speakerId && option.speaker_id !== speakerId)
        || !['available', 'warning'].includes(option.status) || !Array.isArray(option.warnings)
        || (option.status === 'available' && option.warnings.length > 0))) {
      throw new Error('Состав или параметры вариантов изменились. Обновите доступные окна.')
    }
    return data
  }, [enabled, date, start, duration, groupId, speakerId, state])
  const result = useCalendarWindowRequest(request, sourceKey, state.scope.version)
  const error = context.sourceError || result.error
  useEffect(() => {
    const dialog = refreshButton.current?.closest('[role="dialog"]')
    if (dialog && !dialog.contains(document.activeElement)) refreshButton.current?.focus()
  }, [result.data, error, enabled])
  const canSelect = enabled && state.actor.can_manage && !state.scope.archived && !!result.data
  const name = useCallback((id: string) => {
    const member = state.members.find(m => m.user_id === id)
    return member ? `${member.code} · ${member.full_name}` : id
  }, [state.members])
  const options = result.data?.options || []
  const currentPage = Math.min(page, Math.max(0, Math.ceil(options.length / 50) - 1))
  // Keep the modal interactive while the graph's source refresh makes its content inert.
  return createPortal(<CalendarModal title="Доступные окна" onClose={onClose}>
    <div className="ac-window-detail">
      <div className="ac-window-detail-head"><strong>{date} · {timeLabel(start)}–{timeLabel(start + duration)} · {duration} мин</strong><button ref={refreshButton} type="button" className="ac-icon" aria-label="Обновить варианты окна" title="Обновить варианты окна" onClick={() => void onRefresh().catch(() => undefined)}><RefreshCw size={18} aria-hidden="true" /></button></div>
      {!state.actor.can_manage || state.scope.archived ? <p className="ac-muted">Только просмотр. {state.scope.archived ? 'Контур архивирован.' : 'Назначение доступно помощнику контура.'}</p> : null}
      <div aria-live="polite">{error ? <p className="ac-error" role="alert">{error}</p> : !result.data ? <p role="status">Проверка вариантов окна…</p> : <p>Вариантов: {options.length}. Подтверждено: {options.filter(o => o.status === 'available').length}. С неизвестной доступностью: {options.filter(o => o.status === 'warning').length}.</p>}</div>
      {result.data && !options.length && <p className="ac-muted">Для этого интервала вариантов больше нет.</p>}
      <ul className="ac-window-options">{options.slice(currentPage * 50, (currentPage + 1) * 50).map(option => {
        const group = state.groups.find(g => g.id === option.group_id)!
        return <li className="ac-window-option" key={`${option.group_id}:${option.group_version_id}:${option.speaker_id}`}>
          <div className="ac-window-option-head"><strong>{group.code} · {group.label}</strong><span className={`ac-window-option-status ac-window-${option.status}`}>{option.status === 'available' ? <Check size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}{option.status === 'available' ? 'Подтверждено' : 'Доступность неизвестна'}</span></div>
          <dl className="ac-window-participants"><dt>Аудитор</dt><dd>{name(option.auditor_id)}</dd><dt>Техспециалист</dt><dd>{name(option.tech_id)}</dd><dt>Докладчик</dt><dd>{name(option.speaker_id)}</dd></dl>
          {option.warnings.map((warning, i) => <p className="ac-warning" key={`${warning.code}:${warning.user_id || ''}:${i}`}>{warning.participant_name || (warning.user_id ? name(warning.user_id) : warning.participant_code) ? <strong>{warning.participant_name || (warning.user_id ? name(warning.user_id) : warning.participant_code)}: </strong> : null}{warning.message}</p>)}
          {canSelect && <button type="button" aria-label={`Выбрать ${group.code}, докладчик ${name(option.speaker_id)}`} onClick={() => {
            if (!canSelect || !result.data || !optionMatchesState(option, state, date)) return
            onClose()
            onSelect(date, start, { duration, group_id: option.group_id, speaker_id: option.speaker_id, version: result.data.version })
          }}><ArrowRight size={16} aria-hidden="true" />Выбрать</button>}
        </li>
      })}</ul>
      {options.length > 50 && <nav className="ac-window-pagination" aria-label="Страницы вариантов"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Назад</button><span>{currentPage + 1} / {Math.ceil(options.length / 50)}</span><button type="button" disabled={(currentPage + 1) * 50 >= options.length} onClick={() => setPage(currentPage + 1)}>Далее</button></nav>}
    </div>
  </CalendarModal>, document.body)
}
