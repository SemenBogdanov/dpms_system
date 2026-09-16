import { useEffect, useMemo, useState } from 'react'
import type { CalendarMeetingWindowCell } from '@/api/auditCalendar'

export const clockSample = () => ({ wall: Date.now(), monotonic: performance.now() })
export type ClockSample = ReturnType<typeof clockSample>

export function calendarInstant(date: string, start: number) {
  return Date.parse(`${date}T00:00:00+03:00`) + start * 60000
}

export function expiredWindow(cell: CalendarMeetingWindowCell, now: number): CalendarMeetingWindowCell {
  if (calendarInstant(cell.date, cell.start) >= now) return cell
  return { ...cell, status: cell.confirmed ? 'expired' : 'unavailable', uncertain: cell.confirmed ? cell.uncertain : 0 }
}

// Server time drives deadlines. Wall elapsed also covers OS sleep; forward clock
// corrections can only close an old window early, never reopen an expired one.
export function useCalendarClock(serverNow: string, started?: ClockSample) {
  const current = useMemo(() => {
    const epoch = Date.parse(serverNow)
    const sample = started || clockSample()
    let latest = epoch
    return () => {
      latest = Math.max(latest, epoch + Math.max(0, Date.now() - sample.wall, performance.now() - sample.monotonic))
      return latest
    }
  }, [serverNow, started])
  const [, tick] = useState(0)
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const update = () => {
      clearTimeout(timer)
      tick(value => value + 1)
      const now = current()
      timer = setTimeout(update, Number.isFinite(now) ? Math.max(1, Math.min(60000, 1800000 - now % 1800000 + 1)) : 60000)
    }
    update()
    window.addEventListener('pageshow', update)
    window.addEventListener('focus', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('pageshow', update)
      window.removeEventListener('focus', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [current])
  return { now: current(), current }
}
