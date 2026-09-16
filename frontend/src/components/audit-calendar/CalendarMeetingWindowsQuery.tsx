import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '@/api/client'
import { auditCalendar, type CalendarMeetingWindowPrefill, type CalendarState } from '@/api/auditCalendar'
import { allSlots, dateRange, errorText, periodError, workSlots } from '@/lib/auditCalendar'
import { calendarInstant, clockSample, expiredWindow, useCalendarClock, type ClockSample } from './useCalendarClock'

export type CalendarMeetingWindowsProps = {
  duration: number
  speakerId: string
  enabled: boolean
  sourceKey: string
  sourceError?: string
  onControlsChange: (changes: Record<string, string>) => void
  onRefresh: () => Promise<unknown>
  onSelect: (date: string, start: number, prefill: CalendarMeetingWindowPrefill) => void
}
export type CalendarMeetingWindowsContext = CalendarMeetingWindowsProps & { state: CalendarState; from: string; to: string; groupId: string; fullDay: boolean }

export function checkWindowVersion(version: number, now: string, state: CalendarState) {
  if (!Number.isInteger(version) || version !== state.scope.version || !Number.isFinite(Date.parse(now))) {
    throw new Error('Данные календаря изменились или устарели. Обновите доступные окна.')
  }
}

export function useCalendarMeetingWindows(context: Omit<CalendarMeetingWindowsContext, 'onControlsChange' | 'onRefresh' | 'onSelect'>) {
  const { state, from, to, duration, groupId, speakerId, fullDay, enabled, sourceKey } = context
  const validation = periodError(from, to)
    || (Math.round((Date.parse(to) - Date.parse(from)) / 86400000) + 1 > 31 ? 'Поиск доступных окон ограничен 31 днём. Сократите период; график встреч остаётся доступен.' : '')
    || (!Number.isInteger(duration) || duration < 30 || duration > 480 || duration % 30 !== 0 ? 'Длительность окна: от 30 до 480 минут, шаг 30.' : '')
    || (speakerId && !state.members.some(m => m.user_id === speakerId && m.active && m.role === 'speaker') ? 'Выбранный докладчик неактивен или недоступен. Выберите другого докладчика.' : '')
  const request = useMemo(() => !enabled || validation ? null : async (signal: AbortSignal) => {
    const data = await auditCalendar.meetingWindows({ from, to, duration, ...(groupId && { group: groupId }), ...(speakerId && { speaker_id: speakerId }), full_day: fullDay }, signal)
    checkWindowVersion(data.version, data.now, state)
    const p = data.period
    if (!p || p.from !== from || p.to !== to || p.duration !== duration || p.group_id !== (groupId || null) || p.speaker_id !== (speakerId || null) || p.full_day !== fullDay) {
      throw new Error('Параметры доступных окон не совпадают с выбранными. Повторите поиск.')
    }
    const expected = new Set(dateRange(from, to).flatMap(date => (fullDay ? allSlots : workSlots).map(start => `${date}:${start}`)))
    if (!Array.isArray(data.cells) || data.cells.length !== expected.size || data.cells.some(cell => {
      const valid = expected.delete(`${cell.date}:${cell.start}`)
        && Number.isInteger(cell.confirmed) && cell.confirmed >= 0 && Number.isInteger(cell.uncertain) && cell.uncertain >= 0
        && cell.confirmed + cell.uncertain <= 2000
        && cell.status === (cell.confirmed > 0 ? (calendarInstant(cell.date, cell.start) < Date.parse(data.now) ? 'expired' : 'available') : cell.uncertain > 0 ? 'warning' : 'unavailable')
        && !(cell.uncertain > 0 && cell.confirmed === 0 && calendarInstant(cell.date, cell.start) < Date.parse(data.now))
      return !valid
    })) throw new Error('Получен неполный или некорректный набор окон. Повторите поиск.')
    return data
  }, [enabled, validation, from, to, duration, groupId, speakerId, fullDay, state])
  const result = useCalendarWindowRequest(request, sourceKey, state.scope.version)
  const clock = useCalendarClock(result.data?.now || state.scope.now, result.started)
  const cells = new Map(result.data?.cells.map(cell => [`${cell.date}:${cell.start}`, expiredWindow(cell, clock.now)]))
  return { ...result, cells, error: validation || context.sourceError || result.error, enabled: enabled && !validation }
}

// Each request identity is disposable, including an A -> B -> A parameter change.
export function useCalendarWindowRequest<T>(request: ((signal: AbortSignal) => Promise<T>) | null, sourceKey: string, version: number) {
  const identity = useMemo(() => ({ request, sourceKey, version }), [request, sourceKey, version])
  const [result, setResult] = useState<{ identity: typeof identity; data?: T; error?: string; started?: ClockSample } | null>(null)
  const revoked = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    const revoke = () => { revoked.current = true; controller.current?.abort(); setResult(null) }
    window.addEventListener('audit-calendar:access-revoked', revoke)
    return () => window.removeEventListener('audit-calendar:access-revoked', revoke)
  }, [])
  useEffect(() => {
    if (!identity.request || revoked.current) return
    const abort = new AbortController()
    const started = clockSample()
    controller.current = abort
    void identity.request(abort.signal).then(data => {
      if (!abort.signal.aborted && !revoked.current) setResult({ identity, data, started })
    }).catch(error => {
      if (abort.signal.aborted || revoked.current) return
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        window.dispatchEvent(new Event('audit-calendar:access-revoked'))
        return
      }
      setResult({ identity, error: error instanceof ApiError && error.status === 422
        ? `${errorText(error)} Выберите группу или докладчика и повторите поиск.` : errorText(error) })
    })
    return () => abort.abort()
  }, [identity])
  const current = request && !revoked.current && result?.identity === identity ? result : null
  return { data: current?.data, started: current?.started, error: current?.error || '', loading: !!request && !current }
}
