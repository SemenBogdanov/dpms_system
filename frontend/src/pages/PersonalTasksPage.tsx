import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Archive,
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  Circle,
  Clock3,
  Flag,
  History,
  Inbox,
  Link2,
  MessageSquare,
  Milestone,
  Pencil,
  PlayCircle,
  Plus,
  Save,
  Search,
  ShieldAlert,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  Complexity,
  DeadlineTracker,
  League,
  PersonalTask,
  PersonalTaskCategory,
  PersonalTaskCheckpoint,
  PersonalTaskCheckpointCreate,
  PersonalTaskCheckpointStatus,
  PersonalTaskDeadline,
  PersonalTaskEvent,
  PersonalTaskEventCreate,
  PersonalTaskEventType,
  PersonalTaskCreate,
  PersonalTaskPriority,
  PersonalTaskPromoteRequest,
  PersonalTaskStatus,
  PersonalTaskUpdate,
  QuickNote,
  Task,
  TaskPriority,
  TaskType,
} from '@/api/types'
import { cn } from '@/lib/utils'

type TaskFilter = PersonalTaskStatus | 'active' | 'all'

const emptyForm = {
  title: '',
  description: '',
  notes: '',
  status: 'inbox' as PersonalTaskStatus,
  priority: 'medium' as PersonalTaskPriority,
  category: 'work' as PersonalTaskCategory,
  project: '',
  context: '',
  responsible: '',
  tags: '',
  acceptanceCriteria: '',
  nextStep: '',
  nextStepAt: '',
  dueAt: '',
  waitingFor: '',
  blockedReason: '',
  impact: '',
  effort: '',
  linkedTaskId: '',
  sourceQuickNoteId: '',
}

const emptyEventForm = {
  eventType: 'meeting' as PersonalTaskEventType,
  title: '',
  body: '',
  nextStep: '',
  waitingFor: '',
  dueAt: '',
}

const emptyCheckpointForm = {
  title: '',
  status: 'planned' as PersonalTaskCheckpointStatus,
  nextStep: '',
  waitingFor: '',
  notes: '',
  dueAt: '',
}

const defaultPromote = {
  taskType: 'proactive' as TaskType,
  complexity: 'S' as Complexity,
  estimatedQ: '0',
  priority: 'medium' as TaskPriority,
  minLeague: 'C' as League,
}

const statusLabel: Record<PersonalTaskStatus, string> = {
  inbox: 'Входящие',
  planned: 'План',
  next: 'Следующее',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  blocked: 'Блок',
  done: 'Готово',
  archived: 'Архив',
}

const statusTone: Record<PersonalTaskStatus, string> = {
  inbox: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600',
  planned: 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:border-sky-700',
  next: 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-200 dark:border-indigo-700',
  in_progress: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-700',
  waiting: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-200 dark:border-violet-700',
  blocked: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:border-rose-700',
  done: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-700',
  archived: 'bg-slate-50 text-slate-500 border-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:border-slate-700',
}

const priorityLabel: Record<PersonalTaskPriority, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  critical: 'Критичный',
}

const categoryLabel: Record<PersonalTaskCategory, string> = {
  work: 'Работа',
  meeting: 'Совещание',
  follow_up: 'Follow-up',
  research: 'Разбор',
  decision: 'Решение',
  admin: 'Админ',
  other: 'Другое',
}

const filters: Array<{ value: TaskFilter; label: string }> = [
  { value: 'active', label: 'Активные' },
  { value: 'inbox', label: 'Входящие' },
  { value: 'next', label: 'Следующее' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'waiting', label: 'Ожидание' },
  { value: 'blocked', label: 'Блок' },
  { value: 'done', label: 'Готово' },
  { value: 'all', label: 'Все' },
]

function toPayloadDate(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function toInputDate(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset()
  const local = new Date(date.getTime() - offset * 60_000)
  return local.toISOString().slice(0, 16)
}

function formatDate(value: string | null): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDateShort(value: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
  })
}

function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 20)
}

function priorityRank(priority: PersonalTaskPriority): number {
  return { critical: 4, high: 3, medium: 2, low: 1 }[priority]
}

function isOverdue(task: PersonalTask): boolean {
  if (!task.due_at || task.status === 'done' || task.status === 'archived') return false
  return new Date(task.due_at).getTime() < Date.now()
}

function isDueSoon(task: PersonalTask): boolean {
  if (!task.due_at || isOverdue(task) || task.status === 'done' || task.status === 'archived') return false
  return new Date(task.due_at).getTime() - Date.now() < 3 * 24 * 60 * 60 * 1000
}

function deadlineProgress(startAt: string, dueAt: string): number {
  const start = new Date(startAt).getTime()
  const end = new Date(dueAt).getTime()
  const now = Date.now()
  if (end <= start) return 100
  return Math.max(0, Math.min(100, Math.round(((end - now) / (end - start)) * 100)))
}

function deadlineTone(startAt: string, dueAt: string): 'danger' | 'warn' | 'ok' {
  const remaining = deadlineProgress(startAt, dueAt)
  const due = new Date(dueAt).getTime()
  if (due - Date.now() < 0 || remaining <= 20) return 'danger'
  if (remaining <= 50) return 'warn'
  return 'ok'
}

function isAfterTaskDeadline(value: string | null | undefined, task: PersonalTask): boolean {
  if (!value || !task.due_at) return false
  return new Date(value).getTime() > new Date(task.due_at).getTime()
}

function deadlineDeviationLabel(value: string | null | undefined, task: PersonalTask): string {
  if (!isAfterTaskDeadline(value, task) || !task.due_at) return ''
  const deltaMs = new Date(value as string).getTime() - new Date(task.due_at).getTime()
  const days = Math.max(1, Math.ceil(deltaMs / 86_400_000))
  return `позже дедлайна на ${days} дн.`
}

function buildTaskTimeline(task: PersonalTask, taskEvents: PersonalTaskEvent[] = [], taskCheckpoints: PersonalTaskCheckpoint[] = []) {
  const points = [
    ...taskEvents
      .map((event) => ({
        id: event.id,
        type: 'event' as const,
        label: event.title || event.event_type,
        date: event.created_at,
        count: 1,
      })),
    ...taskCheckpoints
      .map((checkpoint) => ({
        id: checkpoint.id,
        type: 'checkpoint' as const,
        label: checkpoint.title,
        date: checkpoint.due_at || checkpoint.created_at,
        status: checkpoint.status,
        count: 1,
      })),
  ].filter((point) => point.date)

  const start = new Date(task.created_at).getTime()
  const maxPointDate = points.reduce((max, point) => Math.max(max, new Date(point.date).getTime()), start)
  const end = Math.max(maxPointDate, task.due_at ? new Date(task.due_at).getTime() : start)
  const span = Math.max(1, end - start)
  const due = task.due_at ? new Date(task.due_at).getTime() : null
  const typeOrder = { start: 0, deadline: 1, checkpoint: 2, event: 3 }
  const positionedPoints = [
    {
      id: 'start',
      type: 'start' as const,
      label: 'Начало',
      date: new Date(start).toISOString(),
      position: 0,
      count: 1,
    },
    ...points.map((point) => ({
      ...point,
      position: Math.max(0, Math.min(100, Math.round(((new Date(point.date).getTime() - start) / span) * 100))),
    })),
    ...(due
      ? [{
          id: 'deadline',
          type: 'deadline' as const,
          label: 'Дедлайн задачи',
          date: new Date(due).toISOString(),
          position: Math.max(0, Math.min(100, Math.round(((due - start) / span) * 100))),
          count: 1,
        }]
      : []),
  ].sort((a, b) => {
    const dateDelta = new Date(a.date).getTime() - new Date(b.date).getTime()
    if (dateDelta !== 0) return dateDelta
    return typeOrder[a.type] - typeOrder[b.type]
  })
  const clusteredPoints = Array.from(positionedPoints.reduce((clusters, point) => {
    if (point.type === 'start' || point.type === 'deadline') {
      clusters.set(`${point.type}-${point.id}`, point)
      return clusters
    }
    const key = `${point.type}-${point.position}`
    const existing = clusters.get(key)
    if (existing) {
      existing.count += 1
      if (existing.type === 'checkpoint' && point.type === 'checkpoint' && point.status === 'done') existing.status = 'done'
      return clusters
    }
    clusters.set(key, { ...point })
    return clusters
  }, new Map<string, typeof positionedPoints[number]>()).values()).sort((a, b) => {
    const dateDelta = new Date(a.date).getTime() - new Date(b.date).getTime()
    if (dateDelta !== 0) return dateDelta
    return typeOrder[a.type] - typeOrder[b.type]
  })
  const positionGroups = clusteredPoints.reduce((groups, point) => {
    const group = groups.get(point.position) || []
    group.push(point)
    groups.set(point.position, group)
    return groups
  }, new Map<number, typeof clusteredPoints>())

  return {
    start,
    end,
    ticks: timelineTicks(start, end, due),
    points: clusteredPoints.map((point) => {
      const group = positionGroups.get(point.position) || [point]
      if (group.length === 1 || point.type === 'start' || point.type === 'deadline') return { ...point, visualOffsetPx: 0 }
      const siblings = group.filter((candidate) => candidate.type !== 'start' && candidate.type !== 'deadline')
      const siblingIndex = Math.max(0, siblings.findIndex((candidate) => candidate.id === point.id && candidate.type === point.type))
      const edgeOffset = point.position <= 2
        ? (siblingIndex + 1) * 16
        : point.position >= 98
          ? -(siblingIndex + 1) * 16
          : siblingIndex === 0
            ? -12
            : 12
      return { ...point, visualOffsetPx: edgeOffset }
    }),
  }
}

function timelineTicks(start: number, end: number, due: number | null) {
  const span = Math.max(1, end - start)
  const ticks: Array<{ key: string; label: string; position: number; type: 'boundary' | 'month' | 'deadline' }> = [
    { key: 'start', label: formatDate(new Date(start).toISOString()), position: 0, type: 'boundary' },
  ]
  const cursor = new Date(start)
  cursor.setDate(1)
  cursor.setHours(0, 0, 0, 0)
  cursor.setMonth(cursor.getMonth() + 1)
  while (cursor.getTime() < end) {
    const position = Math.max(0, Math.min(100, Math.round(((cursor.getTime() - start) / span) * 100)))
    if (position > 8 && position < 92) {
      ticks.push({
        key: cursor.toISOString(),
        label: cursor.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }),
        position,
        type: 'month',
      })
    }
    cursor.setMonth(cursor.getMonth() + 1)
  }
  if (due && due > start && due < end) {
    ticks.push({
      key: 'deadline',
      label: `дедлайн ${formatDate(new Date(due).toISOString())}`,
      position: Math.max(0, Math.min(100, Math.round(((due - start) / span) * 100))),
      type: 'deadline',
    })
  }
  ticks.push({ key: 'end', label: formatDate(new Date(end).toISOString()), position: 100, type: 'boundary' })
  return ticks.sort((a, b) => a.position - b.position)
}

export function PersonalTasksPage() {
  const [tasks, setTasks] = useState<PersonalTask[]>([])
  const [quickNotes, setQuickNotes] = useState<QuickNote[]>([])
  const [deadlines, setDeadlines] = useState<PersonalTaskDeadline[]>([])
  const [deadlineTrackers, setDeadlineTrackers] = useState<DeadlineTracker[]>([])
  const [events, setEvents] = useState<Record<string, PersonalTaskEvent[]>>({})
  const [checkpoints, setCheckpoints] = useState<Record<string, PersonalTaskCheckpoint[]>>({})
  const [filter, setFilter] = useState<TaskFilter>('active')
  const [search, setSearch] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [editing, setEditing] = useState<PersonalTask | null>(null)
  const [taskFormOpen, setTaskFormOpen] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [promoting, setPromoting] = useState<PersonalTask | null>(null)
  const [promoteForm, setPromoteForm] = useState(defaultPromote)
  const [eventForm, setEventForm] = useState(emptyEventForm)
  const [checkpointForm, setCheckpointForm] = useState(emptyCheckpointForm)
  const [eventFormTaskId, setEventFormTaskId] = useState<string | null>(null)
  const [checkpointFormTaskId, setCheckpointFormTaskId] = useState<string | null>(null)
  const [deadlineCompact, setDeadlineCompact] = useState(true)
  const [trackerBusyId, setTrackerBusyId] = useState<string | null>(null)

  const loadTasks = useCallback(async () => {
    const params = new URLSearchParams()
    params.set('status', filter)
    if (search.trim()) params.set('search', search.trim())
    const data = await api.get<PersonalTask[]>(`/api/personal-tasks?${params.toString()}`)
    setTasks(data)
  }, [filter, search])

  const loadQuickNotes = useCallback(async () => {
    const data = await api.get<QuickNote[]>('/api/quick-notes?status=draft')
    setQuickNotes(data)
  }, [])

  const loadDeadlines = useCallback(async () => {
    const data = await api.get<PersonalTaskDeadline[]>('/api/personal-tasks/deadlines')
    setDeadlines(data)
  }, [])

  const loadDeadlineTrackers = useCallback(async () => {
    const data = await api.get<DeadlineTracker[]>('/api/deadline-trackers?include_archived=true&limit=300')
    setDeadlineTrackers(data)
  }, [])

  const loadTaskDetails = useCallback(async (taskId: string) => {
    const [eventData, checkpointData] = await Promise.all([
      api.get<PersonalTaskEvent[]>(`/api/personal-tasks/${taskId}/events`),
      api.get<PersonalTaskCheckpoint[]>(`/api/personal-tasks/${taskId}/checkpoints`),
    ])
    setEvents((prev) => ({ ...prev, [taskId]: eventData }))
    setCheckpoints((prev) => ({ ...prev, [taskId]: checkpointData }))
  }, [])

  const removeCheckpointFromDeadlines = useCallback((checkpointId: string) => {
    setDeadlines((current) => current.filter((item) => item.item_type !== 'checkpoint' || item.item_id !== checkpointId))
  }, [])

  useEffect(() => {
    void loadTasks().catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка загрузки личных задач'))
  }, [loadTasks])

  useEffect(() => {
    void loadQuickNotes().catch(() => undefined)
  }, [loadQuickNotes])

  useEffect(() => {
    void loadDeadlines().catch(() => undefined)
  }, [loadDeadlines])

  useEffect(() => {
    void loadDeadlineTrackers().catch(() => undefined)
  }, [loadDeadlineTrackers])

  const stats = useMemo(() => {
    const active = tasks.filter((task) => !['done', 'archived'].includes(task.status)).length
    const blocked = tasks.filter((task) => task.status === 'blocked').length
    const overdue = tasks.filter(isOverdue).length
    const next = tasks.filter((task) => task.status === 'next').length
    return { active, next, blocked, overdue }
  }, [tasks])

  const sortedTasks = useMemo(() => {
    return [...tasks].sort((a, b) => {
      if (isOverdue(a) !== isOverdue(b)) return isOverdue(a) ? -1 : 1
      if (a.status === 'next' && b.status !== 'next') return -1
      if (b.status === 'next' && a.status !== 'next') return 1
      const dueA = a.due_at ? new Date(a.due_at).getTime() : Number.MAX_SAFE_INTEGER
      const dueB = b.due_at ? new Date(b.due_at).getTime() : Number.MAX_SAFE_INTEGER
      if (dueA !== dueB) return dueA - dueB
      return priorityRank(b.priority) - priorityRank(a.priority)
    })
  }, [tasks])

  const resetForm = () => {
    setForm(emptyForm)
    setEditing(null)
    setTaskFormOpen(false)
  }

  const toggleTaskDetails = (task: PersonalTask) => {
    setExpandedId((current) => {
      const next = current === task.id ? null : task.id
      if (next) {
        setEventForm(emptyEventForm)
        setCheckpointForm(emptyCheckpointForm)
        void loadTaskDetails(task.id).catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка загрузки истории'))
      }
      return next
    })
  }

  const editTask = (task: PersonalTask) => {
    setEditing(task)
    setTaskFormOpen(true)
    setExpandedId(task.id)
    setForm({
      title: task.title,
      description: task.description || '',
      notes: task.notes || '',
      status: task.status,
      priority: task.priority,
      category: task.category,
      project: task.project || '',
      context: task.context || '',
      responsible: task.responsible || '',
      tags: task.tags.join(', '),
      acceptanceCriteria: task.acceptance_criteria || '',
      nextStep: task.next_step || '',
      nextStepAt: toInputDate(task.next_step_at),
      dueAt: toInputDate(task.due_at),
      waitingFor: task.waiting_for || '',
      blockedReason: task.blocked_reason || '',
      impact: task.impact ? String(task.impact) : '',
      effort: task.effort ? String(task.effort) : '',
      linkedTaskId: task.linked_task_id || '',
      sourceQuickNoteId: task.source_quick_note_id || '',
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const payloadFromForm = (): PersonalTaskCreate | PersonalTaskUpdate => ({
    title: form.title,
    description: form.description || null,
    notes: form.notes || null,
    status: form.status,
    priority: form.priority,
    category: form.category,
    project: form.project || null,
    context: form.context || null,
    responsible: form.responsible || null,
    tags: splitTags(form.tags),
    acceptance_criteria: form.acceptanceCriteria || null,
    next_step: form.nextStep || null,
    next_step_at: toPayloadDate(form.nextStepAt),
    due_at: toPayloadDate(form.dueAt),
    waiting_for: form.waitingFor || null,
    blocked_reason: form.blockedReason || null,
    impact: form.impact ? Number(form.impact) : null,
    effort: form.effort ? Number(form.effort) : null,
    linked_task_id: form.linkedTaskId || null,
    source_quick_note_id: form.sourceQuickNoteId || null,
  })

  const saveTask = async () => {
    if (!form.title.trim()) {
      toast.error('Укажите название')
      return
    }
    setLoading(true)
    try {
      if (editing) {
        await api.patch<PersonalTask>(`/api/personal-tasks/${editing.id}`, payloadFromForm())
        toast.success('Личная задача обновлена')
      } else {
        await api.post<PersonalTask>('/api/personal-tasks', payloadFromForm())
        toast.success('Личная задача создана')
      }
      resetForm()
      await Promise.all([loadTasks(), loadQuickNotes(), loadDeadlines()])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setLoading(false)
    }
  }

  const updateStatus = async (task: PersonalTask, status: PersonalTaskStatus) => {
    try {
      await api.patch<PersonalTask>(`/api/personal-tasks/${task.id}`, { status })
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(task.id)])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка статуса')
    }
  }

  const deleteTask = async (task: PersonalTask) => {
    if (!window.confirm(`Удалить ${task.task_key}?`)) return
    try {
      await api.delete(`/api/personal-tasks/${task.id}`)
      if (editing?.id === task.id) resetForm()
      await Promise.all([loadTasks(), loadDeadlines()])
      toast.success('Личная задача удалена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  const openPromote = (task: PersonalTask) => {
    setPromoting(task)
    setPromoteForm({
      ...defaultPromote,
      priority: task.priority === 'critical' ? 'critical' : task.priority,
    })
  }

  const promoteTask = async () => {
    if (!promoting) return
    try {
      const payload: PersonalTaskPromoteRequest = {
        task_type: promoteForm.taskType,
        complexity: promoteForm.complexity,
        estimated_q: Number(promoteForm.estimatedQ || 0),
        priority: promoteForm.priority,
        min_league: promoteForm.minLeague,
        due_date: promoting.due_at,
        tags: promoting.tags,
      }
      const task = await api.post<Task>(`/api/personal-tasks/${promoting.id}/promote`, payload)
      toast.success(`Выведено в очередь: #${task.task_number}`)
      setPromoting(null)
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(promoting.id)])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка вывода в очередь')
    }
  }

  const createEvent = async (task: PersonalTask) => {
    if (!eventForm.title.trim() && !eventForm.body.trim()) {
      toast.error('Заполните заголовок или заметку')
      return
    }
    if (isAfterTaskDeadline(toPayloadDate(eventForm.dueAt), task)) {
      const ok = window.confirm(
        `Дата следующего действия позже финального срока задачи (${formatDate(task.due_at)}). Запись можно сохранить, но это будет отклонение от дедлайна и она не изменит финальный срок задачи. Продолжить?`,
      )
      if (!ok) return
    }
    try {
      const payload: PersonalTaskEventCreate = {
        event_type: eventForm.eventType,
        title: eventForm.title || null,
        body: eventForm.body || null,
        next_step: eventForm.nextStep || null,
        waiting_for: eventForm.waitingFor || null,
        due_at: toPayloadDate(eventForm.dueAt),
      }
      await api.post<PersonalTaskEvent>(`/api/personal-tasks/${task.id}/events`, payload)
      setEventForm(emptyEventForm)
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(task.id)])
      toast.success('Запись добавлена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка записи')
    }
  }

  const createCheckpoint = async (task: PersonalTask) => {
    if (!checkpointForm.title.trim()) {
      toast.error('Укажите этап')
      return
    }
    if (isAfterTaskDeadline(toPayloadDate(checkpointForm.dueAt), task)) {
      const ok = window.confirm(
        `Срок этапа позже финального срока задачи (${formatDate(task.due_at)}). Этап можно сохранить, но он будет отмечен как отклонение. Для изменения финального срока нужно отдельно перепланировать задачу. Продолжить?`,
      )
      if (!ok) return
    }
    try {
      const payload: PersonalTaskCheckpointCreate = {
        title: checkpointForm.title,
        status: checkpointForm.status,
        next_step: checkpointForm.nextStep || null,
        waiting_for: checkpointForm.waitingFor || null,
        notes: checkpointForm.notes || null,
        due_at: toPayloadDate(checkpointForm.dueAt),
      }
      await api.post<PersonalTaskCheckpoint>(`/api/personal-tasks/${task.id}/checkpoints`, payload)
      setCheckpointForm(emptyCheckpointForm)
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(task.id)])
      toast.success('Этап добавлен')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка этапа')
    }
  }

  const updateCheckpointStatus = async (task: PersonalTask, checkpoint: PersonalTaskCheckpoint, status: PersonalTaskCheckpointStatus) => {
    try {
      await api.patch<PersonalTaskCheckpoint>(`/api/personal-tasks/${task.id}/checkpoints/${checkpoint.id}`, { status })
      if (status === 'done') removeCheckpointFromDeadlines(checkpoint.id)
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(task.id)])
      if (status === 'done') removeCheckpointFromDeadlines(checkpoint.id)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка этапа')
    }
  }

  const deleteCheckpoint = async (task: PersonalTask, checkpoint: PersonalTaskCheckpoint) => {
    if (!window.confirm('Удалить этап контроля?')) return
    try {
      await api.delete(`/api/personal-tasks/${task.id}/checkpoints/${checkpoint.id}`)
      removeCheckpointFromDeadlines(checkpoint.id)
      await Promise.all([loadDeadlines(), loadTaskDetails(task.id)])
      removeCheckpointFromDeadlines(checkpoint.id)
      toast.success('Этап удален')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления этапа')
    }
  }

  const isTaskInTracker = (taskId: string) => {
    return deadlineTrackers.some((tracker) => tracker.personal_task_id === taskId && tracker.status !== 'archived')
  }

  const toggleTracker = async (task: PersonalTask) => {
    setTrackerBusyId(task.id)
    try {
      if (isTaskInTracker(task.id)) {
        await api.delete(`/api/deadline-trackers/by-personal-task/${task.id}`)
        toast.success('Личная задача убрана из трекера')
      } else {
        await api.post<DeadlineTracker>(`/api/deadline-trackers/from-personal-task/${task.id}`, {})
        toast.success('Личная задача добавлена в трекер')
      }
      await Promise.all([loadDeadlineTrackers(), loadDeadlines()])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка трекера')
    } finally {
      setTrackerBusyId(null)
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Personal tracker</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Личные задачи</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Приватный контур для поручений, заметок, следующих шагов и подготовки задач перед выводом в глобальную очередь.
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          <div className="grid grid-cols-4 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <Metric label="активно" value={stats.active} />
            <Metric label="следующее" value={stats.next} />
            <Metric label="блок" value={stats.blocked} tone={stats.blocked ? 'danger' : 'muted'} />
            <Metric label="сроки" value={stats.overdue} tone={stats.overdue ? 'danger' : 'muted'} />
          </div>
          <button
            type="button"
            onClick={() => {
              setForm(emptyForm)
              setEditing(null)
              setTaskFormOpen(true)
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            Новая задача
          </button>
        </div>
      </div>

      {deadlines.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Контроль сроков</h2>
              <p className="text-xs text-slate-500">Задачи и этапы, где скоро нужен следующий шаг.</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-500">{deadlines.length}</span>
              <button
                type="button"
                onClick={() => setDeadlineCompact((value) => !value)}
                className="rounded-lg border border-primary/30 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
              >
                {deadlineCompact ? 'Полный вид' : 'Компактный вид'}
              </button>
            </div>
          </div>
          <div className={cn(
            'grid gap-2',
            deadlineCompact ? 'sm:grid-cols-2 xl:grid-cols-3' : 'lg:grid-cols-2 lg:gap-3',
          )}>
            {deadlines.slice(0, 8).map((item) => {
              const linkedTracker = item.item_type === 'task'
                ? deadlineTrackers.find((tracker) => tracker.personal_task_id === item.task_id && tracker.status !== 'archived')
                : null
              const timelineStartAt = linkedTracker?.starts_at || item.start_at
              const adjustedDueAt = linkedTracker?.shifted_due_at || linkedTracker?.due_at || item.due_at
              const progress = deadlineProgress(timelineStartAt, adjustedDueAt)
              const tone = deadlineTone(timelineStartAt, adjustedDueAt)
              return (
                <button
                  key={`${item.item_type}-${item.item_id}`}
                  type="button"
                  onClick={() => {
                    const task = tasks.find((candidate) => candidate.id === item.task_id)
                    if (task) toggleTaskDetails(task)
                  }}
                  className={cn(
                    'rounded-lg border border-slate-200 text-left hover:bg-slate-50',
                    deadlineCompact ? 'px-3 py-2.5' : 'p-3',
                  )}
                >
                  {deadlineCompact ? (
                    <>
                      <div className="grid grid-cols-[68px_minmax(0,1fr)_96px] gap-x-3 gap-y-1">
                        <span className="self-center rounded bg-slate-100 px-1.5 py-0.5 text-center font-mono text-[11px] font-medium text-slate-600">{item.task_key}</span>
                        <div className="min-w-0 self-center truncate text-[13px] font-semibold leading-tight text-slate-900">{item.title}</div>
                        <div className="self-center">
                          <div className="h-2 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-700/70">
                            <div
                              className={cn('ml-auto h-full rounded-full', tone === 'danger' ? 'bg-rose-500' : tone === 'warn' ? 'bg-amber-500' : 'bg-emerald-500')}
                              style={{ width: `${Math.max(progress, 2)}%` }}
                            />
                          </div>
                        </div>
                        <span className={cn('self-end text-center font-mono text-[11px] leading-none', tone === 'danger' ? 'text-rose-600' : tone === 'warn' ? 'text-amber-600' : 'text-emerald-600')}>
                          {formatDateShort(item.due_at)}
                        </span>
                        <div className="min-w-0 self-end truncate text-[11px] leading-none text-slate-500">{item.project || item.task_title || (item.item_type === 'task' ? 'задача' : 'этап')}</div>
                        <span className={cn('self-end truncate text-right font-mono text-[11px] leading-none', tone === 'danger' ? 'text-rose-600' : tone === 'warn' ? 'text-amber-600' : 'text-emerald-600')}>
                          {formatDateShort(adjustedDueAt)}
                        </span>
                      </div>
                    </>
                  ) : (
                  <>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">{item.task_key}</span>
                        <span className="shrink-0 rounded bg-white px-2 py-0.5 text-xs text-slate-500">{item.item_type === 'task' ? 'задача' : 'этап'}</span>
                      </div>
                      <p className="mt-2 truncate text-sm font-medium text-slate-900">{item.title}</p>
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {item.project || item.task_title}
                        {item.responsible ? ` · ${item.responsible}` : ''}
                      </p>
                    </div>
                    <span className={cn('shrink-0 text-xs font-medium', tone === 'danger' ? 'text-rose-600' : tone === 'warn' ? 'text-amber-600' : 'text-emerald-600')}>
                      {formatDate(item.due_at)}
                    </span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-700/70">
                    <div
                      className={cn('ml-auto h-full rounded-full', tone === 'danger' ? 'bg-rose-500' : tone === 'warn' ? 'bg-amber-500' : 'bg-emerald-500')}
                      style={{ width: `${Math.max(progress, 2)}%` }}
                    />
                  </div>
                  </>
                  )}
                </button>
              )
            })}
          </div>
        </section>
      )}

      {taskFormOpen && (
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              {editing ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            </span>
            <div>
              <h2 className="text-sm font-semibold text-slate-900">
                {editing ? `Редактирование ${editing.task_key}` : 'Новая личная задача'}
              </h2>
              <p className="text-xs text-slate-500">Минимум: название и следующий шаг. Остальное можно уточнить позже.</p>
            </div>
          </div>
          {editing && (
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              <X className="h-4 w-4" />
              Отмена
            </button>
          )}
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_180px_160px_160px]">
          <input
            value={form.title}
            onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
            placeholder="Название"
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <select
            value={form.status}
            onChange={(e) => setForm((prev) => ({ ...prev, status: e.target.value as PersonalTaskStatus }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            {Object.entries(statusLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            value={form.priority}
            onChange={(e) => setForm((prev) => ({ ...prev, priority: e.target.value as PersonalTaskPriority }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            {Object.entries(priorityLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            value={form.category}
            onChange={(e) => setForm((prev) => ({ ...prev, category: e.target.value as PersonalTaskCategory }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            {Object.entries(categoryLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-4">
          <input
            value={form.nextStep}
            onChange={(e) => setForm((prev) => ({ ...prev, nextStep: e.target.value }))}
            placeholder="Следующий шаг"
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <input
            value={form.project}
            onChange={(e) => setForm((prev) => ({ ...prev, project: e.target.value }))}
            placeholder="Проект / поток"
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <input
            value={form.context}
            onChange={(e) => setForm((prev) => ({ ...prev, context: e.target.value }))}
            placeholder="Контекст: встреча, поручение, источник"
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <input
            value={form.responsible}
            onChange={(e) => setForm((prev) => ({ ...prev, responsible: e.target.value }))}
            placeholder="Ответственный / кому поручено"
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-4">
          <input
            type="datetime-local"
            value={form.nextStepAt}
            onChange={(e) => setForm((prev) => ({ ...prev, nextStepAt: e.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <input
            type="datetime-local"
            value={form.dueAt}
            onChange={(e) => setForm((prev) => ({ ...prev, dueAt: e.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          />
          <select
            value={form.impact}
            onChange={(e) => setForm((prev) => ({ ...prev, impact: e.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            <option value="">Влияние</option>
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select
            value={form.effort}
            onChange={(e) => setForm((prev) => ({ ...prev, effort: e.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            <option value="">Усилие</option>
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>

        <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">Атрибуты tracker</summary>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <textarea
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="Описание"
              rows={4}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <textarea
              value={form.acceptanceCriteria}
              onChange={(e) => setForm((prev) => ({ ...prev, acceptanceCriteria: e.target.value }))}
              placeholder="Критерии готовности / приемки"
              rows={4}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <textarea
              value={form.notes}
              onChange={(e) => setForm((prev) => ({ ...prev, notes: e.target.value }))}
              placeholder="Рабочие заметки"
              rows={4}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <div className="grid gap-3">
              <input
                value={form.tags}
                onChange={(e) => setForm((prev) => ({ ...prev, tags: e.target.value }))}
                placeholder="Теги через запятую"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
              <input
                value={form.waitingFor}
                onChange={(e) => setForm((prev) => ({ ...prev, waitingFor: e.target.value }))}
                placeholder="Кого / чего ждем"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
              <input
                value={form.blockedReason}
                onChange={(e) => setForm((prev) => ({ ...prev, blockedReason: e.target.value }))}
                placeholder="Причина блока"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
              <select
                value={form.sourceQuickNoteId}
                onChange={(e) => setForm((prev) => ({ ...prev, sourceQuickNoteId: e.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              >
                <option value="">Без связанной заметки</option>
                {quickNotes.map((note) => (
                  <option key={note.id} value={note.id}>{note.title}</option>
                ))}
              </select>
              <input
                value={form.linkedTaskId}
                onChange={(e) => setForm((prev) => ({ ...prev, linkedTaskId: e.target.value }))}
                placeholder="UUID связанной DPMS-задачи"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
            </div>
          </div>
        </details>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void saveTask()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            <Save className="h-4 w-4" />
            {editing ? 'Сохранить' : 'Создать задачу'}
          </button>
          {!editing && (
            <button
              type="button"
              onClick={() => setForm((prev) => ({ ...prev, status: 'next' }))}
              className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              Сделать следующим
            </button>
          )}
        </div>
      </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-3 border-b border-slate-200 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
            <Search className="h-4 w-4 shrink-0 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию, проекту, заметкам"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {filters.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={cn(
                  'shrink-0 rounded-lg border px-3 py-2 text-sm',
                  filter === item.value
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="divide-y divide-slate-200">
          {sortedTasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center text-slate-500">
              <Inbox className="h-8 w-8 text-slate-300" />
              <p className="text-sm">Личных задач пока нет.</p>
            </div>
          ) : (
            sortedTasks.map((task) => (
              <article key={task.id} className="p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <button
                    type="button"
                  onClick={() => toggleTaskDetails(task)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs font-semibold text-slate-600">
                        {task.task_key}
                      </span>
                      <span className={cn('rounded-md border px-2 py-1 text-xs font-medium', statusTone[task.status])}>
                        {statusLabel[task.status]}
                      </span>
                      <span className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500">
                        {priorityLabel[task.priority]}
                      </span>
                      <span className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500">
                        {categoryLabel[task.category]}
                      </span>
                      {task.promoted_task_id && (
                        <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-700">
                          в очереди
                        </span>
                      )}
                    </div>
                    <h3 className="mt-2 break-words text-base font-semibold text-slate-950">{task.title}</h3>
                    <div className="mt-2 grid gap-2 text-sm text-slate-500 lg:grid-cols-4">
                      <Info icon={<PlayCircle className="h-4 w-4" />} text={task.next_step || 'следующий шаг не задан'} />
                      <Info icon={<CalendarClock className="h-4 w-4" />} text={`срок: ${formatDate(task.due_at)}`} danger={isOverdue(task)} warn={isDueSoon(task)} />
                      <Info icon={<Flag className="h-4 w-4" />} text={task.project || task.context || 'без проекта'} />
                      <Info icon={<UserRound className="h-4 w-4" />} text={task.responsible || 'без ответственного'} />
                    </div>
                  </button>

                  <div className="flex flex-col items-stretch gap-2 lg:items-end">
                    <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
                      <button
                        type="button"
                        onClick={() => {
                          setExpandedId(task.id)
                          setEventFormTaskId((value) => (value === task.id ? null : task.id))
                          setCheckpointFormTaskId(null)
                        }}
                        className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                      >
                        <MessageSquare className="h-4 w-4" />
                        Добавить запись в журнал
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setExpandedId(task.id)
                          setCheckpointFormTaskId((value) => (value === task.id ? null : task.id))
                          setEventFormTaskId(null)
                        }}
                        className="inline-flex items-center justify-center gap-2 rounded-lg border border-primary/40 bg-white px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10"
                      >
                        <Milestone className="h-4 w-4" />
                        Добавить этап контроля
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-2 lg:justify-end">
                      <IconButton label="Следующее" onClick={() => void updateStatus(task, 'next')}>
                        <Circle className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="В работу" onClick={() => void updateStatus(task, 'in_progress')}>
                        <Clock3 className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Ожидание" onClick={() => void updateStatus(task, 'waiting')}>
                        <UserRound className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Блок" onClick={() => void updateStatus(task, 'blocked')}>
                        <ShieldAlert className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Готово" onClick={() => void updateStatus(task, 'done')}>
                        <CheckCircle2 className="h-4 w-4" />
                      </IconButton>
                      <IconButton
                        label={isTaskInTracker(task.id) ? 'Убрать из трекера' : 'Поставить в трекер'}
                        onClick={() => void toggleTracker(task)}
                        disabled={trackerBusyId === task.id}
                      >
                        <CalendarClock className={cn('h-4 w-4', isTaskInTracker(task.id) && 'text-emerald-600')} />
                      </IconButton>
                      <IconButton label="В очередь" onClick={() => openPromote(task)} disabled={Boolean(task.promoted_task_id)}>
                        <ArrowUpRight className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Редактировать" onClick={() => editTask(task)}>
                        <Pencil className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Архив" onClick={() => void updateStatus(task, 'archived')}>
                        <Archive className="h-4 w-4" />
                      </IconButton>
                      <IconButton label="Удалить" onClick={() => void deleteTask(task)} danger>
                        <Trash2 className="h-4 w-4" />
                      </IconButton>
                    </div>
                  </div>
                </div>

                {expandedId === task.id && (
                  <div className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                    <div className="grid gap-4 lg:grid-cols-2">
                      <Detail title="Описание" text={task.description} />
                      <Detail title="Критерии готовности" text={task.acceptance_criteria} />
                      <Detail title="Заметки" text={task.notes} />
                      <div className="space-y-2">
                        <Detail title="Кого ждем" text={task.waiting_for} />
                        <Detail title="Причина блока" text={task.blocked_reason} />
                        <p className="text-xs text-slate-500">Следующий шаг: {formatDate(task.next_step_at)}</p>
                        <p className="text-xs text-slate-500">Impact/Effort: {task.impact || '-'} / {task.effort || '-'}</p>
                        {task.linked_task_id && (
                          <p className="inline-flex items-center gap-1 text-xs text-slate-500">
                            <Link2 className="h-3 w-3" />
                            Связь DPMS: {task.linked_task_id}
                          </p>
                        )}
                      </div>
                    </div>

                    {(() => {
                      const timeline = buildTaskTimeline(task, events[task.id] || [], checkpoints[task.id] || [])
                      return (
                        <section className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
                          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Линия контроля</h4>
                            <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400">
                              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-red-700 ring-1 ring-white" />старт/дедлайн</span>
                              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-blue-500 ring-1 ring-white" />журнал</span>
                              <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-emerald-500 ring-1 ring-white" />этап</span>
                            </div>
                          </div>
                          <div className="relative px-3 pb-10 pt-4">
                            <div className="relative h-[72px]">
                              <div className="absolute left-0 right-0 top-8 h-3.5 -translate-y-1/2 rounded-sm bg-slate-500/75 dark:bg-slate-500/80" />
                              {timeline.ticks.filter((tick) => tick.type === 'month').map((tick) => (
                                <span
                                  key={tick.key}
                                  className="absolute top-8 z-10 h-[18px] w-2 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-white dark:bg-slate-900"
                                  style={{ left: `${tick.position}%` }}
                                  title={tick.label}
                                />
                              ))}
                              {timeline.points.map((point) => (
                                <span
                                  key={`${point.type}-${point.id}`}
                                  className={cn(
                                    'absolute top-8 rounded-full border-2 border-white shadow-sm dark:border-white',
                                    (point.type === 'start' || point.type === 'deadline') && 'z-30 h-[22px] w-[22px] -translate-x-1/2 -translate-y-1/2 bg-red-700 dark:bg-red-600',
                                    point.type === 'event' && 'z-20 h-5 w-5 -translate-x-1/2 -translate-y-1/2 bg-blue-500 dark:bg-blue-400',
                                    point.type === 'checkpoint' && 'z-20 h-5 w-5 -translate-x-1/2 -translate-y-1/2 bg-emerald-500 dark:bg-emerald-400',
                                  )}
                                  style={{ left: `calc(${point.position}% + ${point.visualOffsetPx || 0}px)` }}
                                  title={`${point.type === 'start' || point.type === 'deadline' ? point.label : point.type === 'event' ? 'Журнал' : 'Этап'}: ${point.label} · ${formatDate(point.date)}${point.count > 1 ? ` · записей: ${point.count}` : ''}`}
                                >
                                  {point.type === 'checkpoint' && point.status === 'done' && (
                                    <CheckCircle2 className="absolute -top-5 left-1/2 h-4 w-4 -translate-x-1/2 text-emerald-400 drop-shadow-sm" aria-hidden="true" />
                                  )}
                                </span>
                              ))}
                              {timeline.ticks.map((tick) => (
                                <span
                                  key={`${tick.key}-label`}
                                  className={cn(
                                    'absolute top-[54px] max-w-28 -translate-x-1/2 whitespace-nowrap text-[10px] text-slate-500 dark:text-slate-400',
                                    tick.position === 0 && 'translate-x-0',
                                    tick.position === 100 && '-translate-x-full text-right',
                                  )}
                                  style={{ left: `${tick.position}%` }}
                                >
                                  {tick.label}
                                </span>
                              ))}
                            </div>
                          </div>
                        </section>
                      )
                    })()}

                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                      <section className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="mb-3 flex items-center justify-between gap-2">
                          <h4 className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
                            <Milestone className="h-4 w-4" />
                            Этапы контроля
                          </h4>
                          <span className="text-xs text-slate-400">{checkpoints[task.id]?.length || 0}</span>
                        </div>
                        <div className="space-y-2">
                          {(checkpoints[task.id] || []).map((checkpoint) => {
                            const deviates = isAfterTaskDeadline(checkpoint.due_at, task)
                            return (
                            <div key={checkpoint.id} className={cn('rounded-lg border p-3', deviates ? 'border-rose-200 bg-rose-50/50 dark:border-rose-700 dark:bg-rose-950/20' : 'border-slate-200')}>
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <p className="font-medium text-slate-900">{checkpoint.title}</p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    {checkpoint.next_step || 'следующий шаг не задан'}
                                  </p>
                                  <p className="mt-1 text-xs text-slate-500">
                                    срок: {formatDate(checkpoint.due_at)}
                                    {checkpoint.waiting_for ? ` · ждем: ${checkpoint.waiting_for}` : ''}
                                  </p>
                                  {deviates && (
                                    <p className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-300">{deadlineDeviationLabel(checkpoint.due_at, task)}</p>
                                  )}
                                </div>
                                <span className={cn('shrink-0 rounded border px-2 py-1 text-xs', statusTone[checkpoint.status as PersonalTaskStatus] || 'border-slate-200 text-slate-500')}>
                                  {statusLabel[checkpoint.status as PersonalTaskStatus] || checkpoint.status}
                                </span>
                              </div>
                              {checkpoint.notes && <p className="mt-2 whitespace-pre-wrap text-xs text-slate-600">{checkpoint.notes}</p>}
                              <div className="mt-3 flex flex-wrap gap-2">
                                <button type="button" onClick={() => void updateCheckpointStatus(task, checkpoint, 'in_progress')} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
                                  В работу
                                </button>
                                <button type="button" onClick={() => void updateCheckpointStatus(task, checkpoint, 'waiting')} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
                                  Ожидание
                                </button>
                                <button type="button" onClick={() => void updateCheckpointStatus(task, checkpoint, 'done')} className="rounded border border-emerald-200 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-50">
                                  Готово
                                </button>
                                <button type="button" onClick={() => void deleteCheckpoint(task, checkpoint)} className="rounded border border-rose-200 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50">
                                  Удалить
                                </button>
                              </div>
                            </div>
                            )
                          })}
                          {(checkpoints[task.id] || []).length === 0 && (
                            <p className="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-400">Этапы пока не добавлены.</p>
                          )}
                        </div>
                        {checkpointFormTaskId === task.id && (
                        <div className="mt-3 grid gap-2">
                          <input value={checkpointForm.title} onChange={(e) => setCheckpointForm((prev) => ({ ...prev, title: e.target.value }))} placeholder="Новый этап / контрольная точка" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <input value={checkpointForm.nextStep} onChange={(e) => setCheckpointForm((prev) => ({ ...prev, nextStep: e.target.value }))} placeholder="Что делаю на этом этапе" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <div className="grid gap-2 sm:grid-cols-2">
                            <input value={checkpointForm.waitingFor} onChange={(e) => setCheckpointForm((prev) => ({ ...prev, waitingFor: e.target.value }))} placeholder="Что / кого жду" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                            <input type="datetime-local" value={checkpointForm.dueAt} onChange={(e) => setCheckpointForm((prev) => ({ ...prev, dueAt: e.target.value }))} className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          </div>
                          {isAfterTaskDeadline(toPayloadDate(checkpointForm.dueAt), task) && (
                            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 dark:border-rose-700 dark:bg-rose-950/30 dark:text-rose-200">
                              Срок этапа выходит за финальный дедлайн задачи. Этап сохранится как отклонение.
                            </p>
                          )}
                          <textarea value={checkpointForm.notes} onChange={(e) => setCheckpointForm((prev) => ({ ...prev, notes: e.target.value }))} placeholder="Заметка по этапу" rows={2} className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <button type="button" onClick={() => void createCheckpoint(task)} className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                            <Plus className="h-4 w-4" />
                            Добавить этап
                          </button>
                        </div>
                        )}
                      </section>

                      <section className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="mb-3 flex items-center justify-between gap-2">
                          <h4 className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
                            <History className="h-4 w-4" />
                            Журнал
                          </h4>
                          <span className="text-xs text-slate-400">{events[task.id]?.length || 0}</span>
                        </div>
                        <div className="max-h-72 space-y-3 overflow-auto pr-1">
                          {(events[task.id] || []).map((event) => {
                            const deviates = isAfterTaskDeadline(event.due_at, task)
                            return (
                            <div key={event.id} className={cn('border-l-2 pl-3', deviates ? 'border-rose-300 dark:border-rose-500' : 'border-slate-200')}>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{event.event_type}</span>
                                <span className="text-xs text-slate-400">{formatDate(event.created_at)}</span>
                              </div>
                              <p className="mt-1 font-medium text-slate-900">{event.title || 'Запись'}</p>
                              {event.from_status && event.to_status && (
                                <p className="mt-1 text-xs text-slate-500">
                                  {statusLabel[event.from_status as PersonalTaskStatus] || event.from_status} → {statusLabel[event.to_status as PersonalTaskStatus] || event.to_status}
                                </p>
                              )}
                              {event.body && <p className="mt-1 whitespace-pre-wrap text-xs text-slate-600">{event.body}</p>}
                              {(event.next_step || event.waiting_for || event.due_at) && (
                                <p className="mt-1 text-xs text-slate-500">
                                  {event.next_step ? `шаг: ${event.next_step}` : ''}
                                  {event.waiting_for ? ` · ждем: ${event.waiting_for}` : ''}
                                  {event.due_at ? ` · срок: ${formatDate(event.due_at)}` : ''}
                                </p>
                              )}
                              {deviates && (
                                <p className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-300">{deadlineDeviationLabel(event.due_at, task)}</p>
                              )}
                            </div>
                            )
                          })}
                          {(events[task.id] || []).length === 0 && (
                            <p className="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-400">Журнал пока пуст.</p>
                          )}
                        </div>
                        {eventFormTaskId === task.id && (
                        <div className="mt-3 grid gap-2">
                          <select value={eventForm.eventType} onChange={(e) => setEventForm((prev) => ({ ...prev, eventType: e.target.value as PersonalTaskEventType }))} className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400">
                            <option value="meeting">Встреча</option>
                            <option value="follow_up">Follow-up</option>
                            <option value="note">Заметка</option>
                          </select>
                          <input value={eventForm.title} onChange={(e) => setEventForm((prev) => ({ ...prev, title: e.target.value }))} placeholder="Заголовок записи" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <textarea value={eventForm.body} onChange={(e) => setEventForm((prev) => ({ ...prev, body: e.target.value }))} placeholder="Итоги встречи, follow-up, договоренности" rows={3} className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <input value={eventForm.nextStep} onChange={(e) => setEventForm((prev) => ({ ...prev, nextStep: e.target.value }))} placeholder="Новый следующий шаг" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          <div className="grid gap-2 sm:grid-cols-2">
                            <input value={eventForm.waitingFor} onChange={(e) => setEventForm((prev) => ({ ...prev, waitingFor: e.target.value }))} placeholder="Что / кого жду" className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                            <input type="datetime-local" value={eventForm.dueAt} onChange={(e) => setEventForm((prev) => ({ ...prev, dueAt: e.target.value }))} className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400" />
                          </div>
                          {isAfterTaskDeadline(toPayloadDate(eventForm.dueAt), task) && (
                            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 dark:border-rose-700 dark:bg-rose-950/30 dark:text-rose-200">
                              Дата следующего действия позже финального дедлайна. Запись сохранится как отклонение и не изменит срок задачи.
                            </p>
                          )}
                          <button type="button" onClick={() => void createEvent(task)} className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                            <MessageSquare className="h-4 w-4" />
                            Добавить запись в журнал
                          </button>
                        </div>
                        )}
                      </section>
                    </div>

                    {task.tags.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {task.tags.map((tag) => (
                          <span key={tag} className="rounded-full bg-white px-2 py-1 text-xs text-slate-500">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </article>
            ))
          )}
        </div>
      </section>

      {promoting && (
        <div className="fixed inset-0 z-50 flex items-end bg-slate-950/40 p-3 backdrop-blur-sm sm:items-center sm:justify-center">
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Вывод в глобальную очередь</p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950">{promoting.task_key} · {promoting.title}</h2>
                <p className="mt-1 text-sm text-slate-500">После подтверждения будет создана обычная DPMS-задача со статусом в очереди.</p>
              </div>
              <button type="button" onClick={() => setPromoting(null)} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <select
                value={promoteForm.taskType}
                onChange={(e) => setPromoteForm((prev) => ({ ...prev, taskType: e.target.value as TaskType }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              >
                {(['proactive', 'widget', 'etl', 'api', 'docs', 'bugfix'] as TaskType[]).map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
              <select
                value={promoteForm.complexity}
                onChange={(e) => setPromoteForm((prev) => ({ ...prev, complexity: e.target.value as Complexity }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              >
                {(['S', 'M', 'L', 'XL'] as Complexity[]).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
              <input
                type="number"
                min="0"
                step="0.1"
                value={promoteForm.estimatedQ}
                onChange={(e) => setPromoteForm((prev) => ({ ...prev, estimatedQ: e.target.value }))}
                placeholder="Q"
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              />
              <select
                value={promoteForm.priority}
                onChange={(e) => setPromoteForm((prev) => ({ ...prev, priority: e.target.value as TaskPriority }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              >
                {(['low', 'medium', 'high', 'critical'] as TaskPriority[]).map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
              <select
                value={promoteForm.minLeague}
                onChange={(e) => setPromoteForm((prev) => ({ ...prev, minLeague: e.target.value as League }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm"
              >
                {(['C', 'B', 'A'] as League[]).map((value) => <option key={value} value={value}>Лига {value}</option>)}
              </select>
            </div>

            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <ShieldAlert className="mr-2 inline h-4 w-4" />
              Если Q/лига выбраны приблизительно, задача попадет в очередь как предварительно оцененная. Дальше ее можно уточнить в обычном контуре DPMS.
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setPromoting(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">
                Отмена
              </button>
              <button type="button" onClick={() => void promoteTask()} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                Вывести в очередь
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, tone = 'default' }: { label: string; value: number; tone?: 'default' | 'muted' | 'danger' }) {
  return (
    <div className="min-w-20 border-l border-slate-200 px-3 py-2 text-center first:border-l-0">
      <div className={cn('text-lg font-semibold', tone === 'danger' ? 'text-rose-600' : tone === 'muted' ? 'text-slate-400' : 'text-slate-950')}>
        {value}
      </div>
      <div className="text-xs text-slate-400">{label}</div>
    </div>
  )
}

function Info({ icon, text, danger, warn }: { icon: ReactNode; text: string; danger?: boolean; warn?: boolean }) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', danger ? 'text-rose-600' : warn ? 'text-amber-600' : 'text-slate-500')}>
      {icon}
      <span className="truncate">{text}</span>
    </span>
  )
}

function Detail({ title, text }: { title: string; text: string | null }) {
  if (!text) return null
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{text}</p>
    </div>
  )
}

function IconButton({
  label,
  onClick,
  children,
  danger,
  disabled,
}: {
  label: string
  onClick: () => void
  children: ReactNode
  danger?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      disabled={disabled}
      className={cn(
        'inline-flex h-9 w-9 items-center justify-center rounded-lg border text-sm transition disabled:cursor-not-allowed disabled:opacity-40',
        danger
          ? 'border-rose-200 text-rose-600 hover:bg-rose-50'
          : 'border-slate-200 text-slate-600 hover:bg-slate-50',
      )}
    >
      {children}
    </button>
  )
}
