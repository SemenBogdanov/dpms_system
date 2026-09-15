import type { CalendarTimeline, CalendarTimelineMeeting } from '@/api/auditCalendar'

export const timelineRoles = [
  { id: 'speaker', label: 'Докладчики' }, { id: 'tech', label: 'Техники' }, { id: 'auditor', label: 'Аудиторы' },
] as const
export type TimelineStatus = 'free' | 'busy' | 'unknown' | 'absent' | 'booked'
export const MAX_TIMELINE_PARTICIPANTS = 50
export const timelineStatusLabels: Record<TimelineStatus, string> = { free: 'Свободен', busy: 'Занят', unknown: 'Не указано', absent: 'Отсутствие', booked: 'Встреча' }
export const overlapsSlot = (meeting: CalendarTimelineMeeting, start: number) => meeting.start < start + 30 && meeting.start + meeting.duration > start
export function indexTimeline(data: CalendarTimeline) {
  const meetings = new Map<string, CalendarTimelineMeeting[]>()
  const availability = new Map<string, CalendarTimeline['availability']>()
  const absent = new Set<string>()
  for (const meeting of data.meetings) for (const user of new Set(meeting.participants.map(p => p.user_id))) {
    const rows = meetings.get(user) || []; rows.push(meeting); meetings.set(user, rows)
  }
  for (const window of data.availability) if (window.date === data.date) {
    const rows = availability.get(window.user_id) || []; rows.push(window); availability.set(window.user_id, rows)
  }
  for (const absence of data.absences) if (absence.status === 'active' && absence.start_date <= data.date && absence.end_date >= data.date) absent.add(absence.user_id)
  return { meetings, availability, absent }
}
export function indexedTimelineSlot(index: ReturnType<typeof indexTimeline>, user: string, start: number): TimelineStatus {
  if (index.absent.has(user)) return 'absent'
  if (index.meetings.get(user)?.some(m => overlapsSlot(m, start))) return 'booked'
  const windows = index.availability.get(user) || []
  if (windows.some(a => a.available === false && a.start < start + 30 && a.end > start)) return 'busy'
  return windows.some(a => a.available && a.start <= start && a.end >= start + 30) ? 'free' : 'unknown'
}
export function personMeetings(data: CalendarTimeline, user: string) {
  return data.meetings.filter(meeting => meeting.participants.some(p => p.user_id === user))
}
export function timelineSlot(data: CalendarTimeline, user: string, start: number): TimelineStatus {
  return indexedTimelineSlot(indexTimeline(data), user, start)
}
export function commonTimelineStatus(statuses: TimelineStatus[]) {
  if (!statuses.length) return 'empty'
  if (statuses.some(status => ['busy', 'absent', 'booked'].includes(status))) return 'blocked'
  return statuses.every(status => status === 'free') ? 'free' : 'unknown'
}
export function commonTimelineSlot(data: CalendarTimeline, users: string[], start: number) {
  const index = indexTimeline(data)
  return commonTimelineStatus(users.map(user => indexedTimelineSlot(index, user, start)))
}
export function timelineLanes(meetings: CalendarTimelineMeeting[], start: number, end: number) {
  const ends: number[] = []
  return [...meetings].filter(m => m.start < end && m.start + m.duration > start).sort((a, b) => a.start - b.start || a.id.localeCompare(b.id)).map(meeting => {
    let lane = ends.findIndex(value => value <= meeting.start)
    if (lane < 0) lane = ends.length
    ends[lane] = meeting.start + meeting.duration
    return { meeting, lane, first: (Math.max(meeting.start, start) - start) / 30 + 1, last: (Math.min(meeting.start + meeting.duration, end) - start) / 30 + 1 }
  })
}
