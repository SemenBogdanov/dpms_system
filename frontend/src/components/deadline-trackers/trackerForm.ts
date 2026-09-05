import type { DeadlineTracker, DeadlineTrackerCreate } from '@/api/types'

export interface TrackerOrganization {
  id: string
  name: string
  color: string | null
  sort_order: number
  is_archived: boolean
  is_collapsed?: boolean
  legacy_type?: string | null
}

export interface TrackerForm {
  title: string
  groupId: string
  categoryId: string
  mode: 'once' | 'recurring'
  startsAt: string
  dueAt: string
  frequency: 'day' | 'week' | 'month' | 'year'
  interval: string
  timezone: string
  end: 'never' | 'date' | 'count'
  until: string
  count: string
  reminders: Array<{ value: string; unit: 'minute' | 'hour' | 'day' | 'week' }>
  url: string
  description: string
  tags: string
  nextAction: string
  personalTaskId: string
}

export function localDateInput(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function newTrackerForm(): TrackerForm {
  return {
    title: '', groupId: '', categoryId: '', mode: 'once', startsAt: localDateInput(new Date().toISOString()), dueAt: '',
    frequency: 'month', interval: '1', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    end: 'never', until: '', count: '12', reminders: [], url: '', description: '', tags: '', nextAction: '', personalTaskId: '',
  }
}

export const reminderMinutes = { minute: 1, hour: 60, day: 1440, week: 10080 } as const

export function validateTrackerForm(form: TrackerForm, linked: boolean): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.title.trim()) errors.title = 'Укажите название'
  else if (form.title.trim().length > 200) errors.title = 'Не более 200 символов'
  if (!linked) {
    const start = new Date(form.startsAt).getTime()
    const due = new Date(form.dueAt).getTime()
    if (!Number.isFinite(start)) errors.startsAt = 'Укажите дату старта'
    if (!Number.isFinite(due)) errors.dueAt = 'Укажите дедлайн'
    else if (Number.isFinite(start) && due <= start) errors.dueAt = 'Дедлайн должен быть позже старта'
  }
  if (form.mode === 'recurring' && !linked) {
    if (!/^\d+$/.test(form.interval) || Number(form.interval) < 1 || Number(form.interval) > 1000) errors.interval = 'Укажите целый интервал от 1 до 1000'
    try { new Intl.DateTimeFormat('ru', { timeZone: form.timezone }).format() } catch { errors.timezone = 'Укажите часовой пояс IANA, например Europe/Moscow' }
    if (form.end === 'date' && (!form.until || form.until < form.dueAt.slice(0, 10))) errors.until = 'Дата окончания не может быть раньше первого срока'
    if (form.end === 'count' && (!/^\d+$/.test(form.count) || Number(form.count) < 1 || Number(form.count) > 100000)) errors.count = 'Укажите целое число повторений от 1 до 100000'
  }
  const seen = new Set<number>()
  form.reminders.forEach((point, index) => {
    const minutes = Number(point.value) * reminderMinutes[point.unit]
    if (!/^\d+$/.test(point.value) || !Number.isSafeInteger(minutes) || minutes < 0) errors[`reminder-${index}`] = 'Укажите целое неотрицательное число'
    else if (seen.has(minutes)) errors[`reminder-${index}`] = 'Эта точка уже добавлена'
    else if (minutes > 366 * 1440) errors[`reminder-${index}`] = 'Не ранее чем за 366 дней до срока'
    seen.add(minutes)
  })
  if (form.reminders.length > 10) errors.reminders = 'Можно добавить не более 10 точек'
  if (form.url.trim()) {
    try { if (!['https:', 'http:'].includes(new URL(form.url.trim()).protocol)) throw new Error() } catch { errors.url = 'Укажите URL, начинающийся с https:// или http://' }
  }
  if (form.nextAction.length > 500) errors.nextAction = 'Не более 500 символов'
  const tags = form.tags.split(',').map((tag) => tag.trim()).filter(Boolean)
  if (tags.length > 20 || tags.some((tag) => tag.length > 40)) errors.tags = 'Не более 20 тегов по 40 символов'
  return errors
}

export function formFromTracker(tracker: DeadlineTracker): TrackerForm {
  const recurrence = tracker.recurrence
  return {
    ...newTrackerForm(), title: tracker.title, groupId: tracker.group_id || '', categoryId: tracker.category_id || '',
    mode: recurrence ? 'recurring' : 'once', startsAt: localDateInput(tracker.starts_at), dueAt: localDateInput(tracker.due_at),
    frequency: recurrence?.frequency || 'month', interval: String(recurrence?.interval || 1),
    timezone: recurrence?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    end: recurrence?.end_type === 'until' ? 'date' : recurrence?.end_type || 'never', until: localDateInput(recurrence?.until).slice(0, 10), count: String(recurrence?.count || 12),
    reminders: (tracker.reminders || []).map((point) => ({ ...point, value: String(point.value) })),
    url: tracker.url || '', description: tracker.description || '', tags: tracker.tags.join(', '), nextAction: tracker.next_action || '', personalTaskId: tracker.personal_task_id || '',
  }
}

export function trackerFormPayload(form: TrackerForm): DeadlineTrackerCreate {
  return {
    title: form.title.trim(), group_id: form.groupId || null, category_id: form.categoryId || null,
    starts_at: new Date(form.startsAt).toISOString(), due_at: new Date(form.dueAt).toISOString(),
    recurrence: form.mode === 'recurring' ? {
      frequency: form.frequency, interval: Number(form.interval), timezone: form.timezone,
      end_type: form.end === 'date' ? 'until' : form.end,
      ...(form.end === 'date' ? { until: new Date(`${form.until}T23:59:59`).toISOString() } : {}),
      ...(form.end === 'count' ? { count: Number(form.count) } : {}),
    } : null,
    reminders: form.reminders.map((point) => ({ ...point, value: Number(point.value) })),
    url: form.url.trim() || null, description: form.description.trim() || null, next_action: form.nextAction.trim() || null,
    tags: [...new Set(form.tags.split(',').map((tag) => tag.trim()).filter(Boolean))],
    ...(form.personalTaskId ? { personal_task_id: form.personalTaskId } : {}),
  }
}
