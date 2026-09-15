import { useEffect, useState } from 'react'
import { auditCalendar, type CalendarMeetingOptions } from '@/api/auditCalendar'
import { errorText, validDate } from '@/lib/auditCalendar'

type Query = { date: string; start: number; duration: number; speaker: string; planId?: string; version: number; enabled: boolean }
type Result = { key: string; data?: CalendarMeetingOptions; error?: string }

export function useCalendarMeetingOptions({ date, start, duration, speaker, planId, version, enabled }: Query) {
  const [result, setResult] = useState<Result | null>(null)
  const [attempt, setAttempt] = useState(0)
  const valid = validDate(date) && Number.isInteger(start) && start >= 0 && start < 1440 && start % 30 === 0
    && Number.isInteger(duration) && duration >= 30 && duration % 30 === 0 && start + duration <= 1440
  const key = JSON.stringify([enabled, date, start, duration, speaker, planId, version, attempt])

  useEffect(() => {
    setResult({ key })
    if (!enabled || !valid) return
    const controller = new AbortController()
    let current = true
    void auditCalendar.meetingOptions({
      date, start, duration,
      ...(speaker && { speaker_id: speaker }), ...(planId && { plan_id: planId }),
    }, controller.signal).then(data => {
      if (!current) return
      if (data.date !== date || data.start !== start || data.duration !== duration
        || !Number.isInteger(data.version) || data.version < version || !Array.isArray(data.groups)) {
        throw new Error('Получен устаревший список групп. Повторите проверку.')
      }
      setResult({ key, data })
    }).catch(error => {
      if (current) setResult({ key, error: errorText(error) })
    })
    return () => { current = false; controller.abort() }
  }, [enabled, valid, date, start, duration, speaker, planId, version, key])

  // Hide the previous query immediately, before effect cleanup or the next response.
  const matching = enabled && valid && result?.key === key ? result : null
  const error = enabled && !valid ? 'Укажите корректные дату, начало и длительность встречи.' : matching?.error || ''
  return { data: matching?.data, error, loading: enabled && valid && !matching?.data && !matching?.error, retry: () => setAttempt(n => n + 1) }
}
