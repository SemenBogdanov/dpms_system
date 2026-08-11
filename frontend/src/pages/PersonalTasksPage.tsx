import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Archive,
  ArchiveRestore,
  AlertOctagon,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Flag,
  History,
  Inbox,
  Link2,
  ListStart,
  MessageSquare,
  Milestone,
  Pencil,
  Play,
  PlayCircle,
  Plus,
  Save,
  Search,
  ShieldAlert,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
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
import { WorkEntityBacklinks } from '@/components/WorkEntityBacklinks'
import { PersonalTaskArtifactsPanel } from '@/components/PersonalTaskArtifactsPanel'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

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
  startAt: '',
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

const emptyStatusContext = {
  reason: '',
  nextStep: '',
  nextStepAt: '',
}

type StatusDialog = {
  task: PersonalTask
  status: 'waiting' | 'blocked' | 'in_progress'
  duplicateWarning?: boolean
  conflictMessage?: string
}

const statusLabel: Record<PersonalTaskStatus, string> = {
  inbox: 'Входящие',
  planned: 'План',
  next: 'Следующая',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  blocked: 'Заблокирована',
  done: 'Готово',
  archived: 'Архив',
}

const statusTone: Record<PersonalTaskStatus, string> = {
  inbox: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600',
  planned: 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-200 dark:border-sky-700',
  next: 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-200 dark:border-indigo-700',
  in_progress: 'border-primary/30 bg-primary/10 text-primary',
  waiting: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-700',
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
  { value: 'next', label: 'Следующие' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'waiting', label: 'Ожидание' },
  { value: 'blocked', label: 'Заблокированные' },
  { value: 'done', label: 'Готово' },
  { value: 'archived', label: 'Архив' },
  { value: 'all', label: 'Все' },
]

const globalTaskStatusLabel: Record<Task['status'], string> = {
  new: 'Новая',
  estimated: 'Оценена',
  in_queue: 'В глобальной очереди',
  in_progress: 'В работе',
  review: 'На приемке',
  done: 'Готово',
  cancelled: 'Отменена',
}

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

function newTaskForm() {
  return { ...emptyForm, startAt: toInputDate(new Date().toISOString()) }
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

  const start = new Date(task.start_at || task.created_at).getTime()
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
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedTaskId = searchParams.get('task')
  const [tasks, setTasks] = useState<PersonalTask[]>([])
  const [quickNotes, setQuickNotes] = useState<QuickNote[]>([])
  const [deadlines, setDeadlines] = useState<PersonalTaskDeadline[]>([])
  const [deadlineTrackers, setDeadlineTrackers] = useState<DeadlineTracker[]>([])
  const [events, setEvents] = useState<Record<string, PersonalTaskEvent[]>>({})
  const [checkpoints, setCheckpoints] = useState<Record<string, PersonalTaskCheckpoint[]>>({})
  const [filter, setFilter] = useState<TaskFilter>(requestedTaskId ? 'all' : 'active')
  const [search, setSearch] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [editing, setEditing] = useState<PersonalTask | null>(null)
  const [taskFormOpen, setTaskFormOpen] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [promoting, setPromoting] = useState<PersonalTask | null>(null)
  const [promoteForm, setPromoteForm] = useState(defaultPromote)
  const [promoteBusy, setPromoteBusy] = useState(false)
  const [queueDetailsTask, setQueueDetailsTask] = useState<PersonalTask | null>(null)
  const [statusDialog, setStatusDialog] = useState<StatusDialog | null>(null)
  const [statusContext, setStatusContext] = useState(emptyStatusContext)
  const [statusBusy, setStatusBusy] = useState(false)
  const [statusActionTaskId, setStatusActionTaskId] = useState<string | null>(null)
  const [eventForm, setEventForm] = useState(emptyEventForm)
  const [checkpointForm, setCheckpointForm] = useState(emptyCheckpointForm)
  const [eventFormTaskId, setEventFormTaskId] = useState<string | null>(null)
  const [checkpointFormTaskId, setCheckpointFormTaskId] = useState<string | null>(null)
  const [deadlineCompact, setDeadlineCompact] = useState(true)
  const [trackerBusyId, setTrackerBusyId] = useState<string | null>(null)
  const taskFormRef = useRef<HTMLElement>(null)

  const scrollToTaskForm = () => {
    window.requestAnimationFrame(() => {
      taskFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

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

  useEffect(() => {
    if (!requestedTaskId) return
    if (filter !== 'all') {
      setFilter('all')
      return
    }
    if (!tasks.some((task) => task.id === requestedTaskId) || expandedId === requestedTaskId) {
      return
    }
    setExpandedId(requestedTaskId)
    void loadTaskDetails(requestedTaskId)
    window.requestAnimationFrame(() => {
      document
        .getElementById(`personal-task-${requestedTaskId}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [expandedId, filter, loadTaskDetails, requestedTaskId, tasks])

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
      startAt: toInputDate(task.start_at || task.created_at),
      dueAt: toInputDate(task.due_at),
      waitingFor: task.waiting_for || '',
      blockedReason: task.blocked_reason || '',
      impact: task.impact ? String(task.impact) : '',
      effort: task.effort ? String(task.effort) : '',
      linkedTaskId: task.linked_task_id || '',
      sourceQuickNoteId: task.source_quick_note_id || '',
    })
    scrollToTaskForm()
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
    start_at: toPayloadDate(form.startAt),
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
    const startAt = toPayloadDate(form.startAt)
    const dueAt = toPayloadDate(form.dueAt)
    if (startAt && dueAt && new Date(dueAt).getTime() <= new Date(startAt).getTime()) {
      toast.error('Дедлайн должен быть позже даты старта')
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
      await Promise.all([loadTasks(), loadQuickNotes(), loadDeadlines(), loadDeadlineTrackers()])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setLoading(false)
    }
  }

  const updateStatus = async (
    task: PersonalTask,
    status: PersonalTaskStatus,
    changes: PersonalTaskUpdate = {},
  ): Promise<boolean> => {
    if (task.status === status && Object.keys(changes).length === 0) return true
    if (statusActionTaskId === task.id) return false
    setStatusActionTaskId(task.id)
    try {
      await api.patch<PersonalTask>(`/api/personal-tasks/${task.id}`, { ...changes, status })
      await Promise.all([loadTasks(), loadDeadlines(), loadTaskDetails(task.id)])
      toast.success(`Статус: ${statusLabel[status]}`)
      return true
    } catch (e) {
      if (status === 'in_progress' && e instanceof Error && (
        e.message.includes('Связанная задача Q')
        || e.message.includes('связаны две разные Q-задачи')
      )) {
        setStatusContext(emptyStatusContext)
        setStatusDialog({ task, status, duplicateWarning: true, conflictMessage: e.message })
        return false
      }
      toast.error(e instanceof Error ? e.message : 'Ошибка статуса')
      return false
    } finally {
      setStatusActionTaskId(null)
    }
  }

  const isWorkedByAnotherExecutor = (task: PersonalTask) => {
    const globalTask = task.execution_task || task.promoted_task
    return Boolean(
      globalTask
      && globalTask.assignee_id !== task.owner_id
      && ['in_progress', 'review'].includes(globalTask.status),
    )
  }

  const hasAmbiguousExecutionLinks = (task: PersonalTask) => Boolean(
    task.promoted_task_id
    && task.linked_task_id
    && task.promoted_task_id !== task.linked_task_id,
  )

  const openStatusTransition = async (task: PersonalTask, status: PersonalTaskStatus) => {
    if (status === 'waiting' || status === 'blocked') {
      setStatusContext({
        reason: status === 'waiting' ? task.waiting_for || '' : task.blocked_reason || '',
        nextStep: task.next_step || '',
        nextStepAt: toInputDate(task.next_step_at),
      })
      setStatusDialog({ task, status })
      return
    }
    if (status === 'in_progress' && (task.promoted_task_id || task.linked_task_id)) {
      try {
        const freshTask = await api.get<PersonalTask>(`/api/personal-tasks/${task.id}`)
        setTasks((current) => current.map((item) => (item.id === freshTask.id ? freshTask : item)))
        if (isWorkedByAnotherExecutor(freshTask)) {
          setStatusContext(emptyStatusContext)
          setStatusDialog({ task: freshTask, status, duplicateWarning: true })
          return
        }
        task = freshTask
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Не удалось проверить состояние глобальной очереди')
        return
      }
    }
    void updateStatus(task, status)
  }

  const submitStatusTransition = async () => {
    if (!statusDialog) return
    const { task, status, duplicateWarning } = statusDialog
    if (duplicateWarning) return
    const reason = statusContext.reason.trim()
    if (!duplicateWarning && !reason) {
      toast.error(status === 'waiting' ? 'Укажите, что или кого ждем' : 'Укажите причину блокировки')
      return
    }
    setStatusBusy(true)
    const changes: PersonalTaskUpdate = status === 'waiting'
        ? {
            waiting_for: reason,
            blocked_reason: null,
            next_step: statusContext.nextStep.trim() || task.next_step,
            next_step_at: toPayloadDate(statusContext.nextStepAt),
          }
        : {
            blocked_reason: reason,
            waiting_for: null,
            next_step: statusContext.nextStep.trim() || null,
            next_step_at: toPayloadDate(statusContext.nextStepAt),
          }
    const updated = await updateStatus(task, status, changes)
    setStatusBusy(false)
    if (updated) {
      setStatusDialog(null)
      setStatusContext(emptyStatusContext)
    }
  }

  const deleteTask = async (task: PersonalTask) => {
    if (!window.confirm(`Безвозвратно удалить ${task.task_key} из архива?`)) return
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

  const openQueueAction = (task: PersonalTask) => {
    if (task.promoted_task_id || task.linked_task_id) {
      setQueueDetailsTask(task)
      return
    }
    openPromote(task)
  }

  const promoteTask = async () => {
    if (!promoting || promoteBusy) return
    setPromoteBusy(true)
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
    } finally {
      setPromoteBusy(false)
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
              setForm(newTaskForm())
              setEditing(null)
              setTaskFormOpen(true)
              scrollToTaskForm()
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
      <section ref={taskFormRef} className="scroll-mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
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

        <div className="mt-3 grid gap-3 lg:grid-cols-5">
          <label className="grid gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            С
            <input
              type="datetime-local"
              value={form.startAt}
              onChange={(e) => setForm((prev) => ({ ...prev, startAt: e.target.value }))}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-700 outline-none focus:border-slate-400"
            />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Следующий шаг
            <input
              type="datetime-local"
              value={form.nextStepAt}
              onChange={(e) => setForm((prev) => ({ ...prev, nextStepAt: e.target.value }))}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-700 outline-none focus:border-slate-400"
            />
          </label>
          <label className="grid gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Дедлайн
            <input
              type="datetime-local"
              value={form.dueAt}
              onChange={(e) => setForm((prev) => ({ ...prev, dueAt: e.target.value }))}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-700 outline-none focus:border-slate-400"
            />
          </label>
          <select
            value={form.impact}
            onChange={(e) => setForm((prev) => ({ ...prev, impact: e.target.value }))}
            className="self-end rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
          >
            <option value="">Влияние</option>
            {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select
            value={form.effort}
            onChange={(e) => setForm((prev) => ({ ...prev, effort: e.target.value }))}
            className="self-end rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
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
              <article id={`personal-task-${task.id}`} key={task.id} className="p-4">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0 flex-1">
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
                      {(task.promoted_task_id || task.linked_task_id) && (
                        <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 dark:border-blue-700 dark:bg-blue-950/40 dark:text-blue-200">
                          Q{task.execution_task ? ` #${task.execution_task.task_number}` : ''}
                          {' · '}
                          {task.execution_task ? globalTaskStatusLabel[task.execution_task.status] : 'Связана'}
                          {task.execution_task?.assignee_name ? ` · ${task.execution_task.assignee_name}` : ''}
                        </span>
                      )}
                    </div>
                    <h3 className="mt-2 break-words text-base font-semibold leading-6 text-slate-950 dark:text-slate-50">
                      <button
                        type="button"
                        onClick={() => toggleTaskDetails(task)}
                        aria-expanded={expandedId === task.id}
                        aria-controls={`personal-task-details-${task.id}`}
                        className="w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                      >
                        {task.title}
                      </button>
                    </h3>
                    <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
                      <TaskNextStep value={task.next_step} />
                      <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-3 xl:grid-cols-4">
                        <TaskMeta
                          icon={<History className="h-3.5 w-3.5" />}
                          label="Старт"
                          value={formatDate(task.start_at)}
                        />
                        <TaskMeta
                          icon={<CalendarClock className="h-3.5 w-3.5" />}
                          label="Дедлайн"
                          value={formatDate(task.due_at)}
                          danger={isOverdue(task)}
                          warn={isDueSoon(task)}
                          hint={isOverdue(task) ? 'Просрочен' : isDueSoon(task) ? 'Срок скоро' : undefined}
                        />
                        <TaskMeta
                          icon={<Flag className="h-3.5 w-3.5" />}
                          label="Проект"
                          value={task.project || 'Без проекта'}
                        />
                        <TaskMeta
                          icon={<UserRound className="h-3.5 w-3.5" />}
                          label="Ответственный"
                          value={task.responsible || 'Не назначен'}
                        />
                      </dl>
                    </div>
                  </div>

                  <div className="flex flex-col items-stretch gap-2 xl:items-end">
                    <div className="flex flex-col gap-2 sm:flex-row xl:flex-col">
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
                    <div className="flex scroll-mb-28 flex-wrap items-center gap-1.5 sm:scroll-mb-0 xl:justify-end" role="group" aria-label={`Действия с ${task.task_key}`}>
                      {task.status !== 'archived' ? (
                        <>
                          <ActionButton
                            label="Сделать следующей: задача готова и будет выполняться сразу после текущей работы"
                            onClick={() => void openStatusTransition(task, 'next')}
                            disabled={statusActionTaskId === task.id}
                            active={task.status === 'next'}
                            tone="next"
                          >
                            <ListStart className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton
                            label="Начать работу над задачей"
                            onClick={() => void openStatusTransition(task, 'in_progress')}
                            disabled={statusActionTaskId === task.id}
                            active={task.status === 'in_progress'}
                            tone="success"
                          >
                            <Play className="h-4 w-4 fill-current" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton
                            label="Перевести в ожидание и указать, что или кого ждем"
                            onClick={() => void openStatusTransition(task, 'waiting')}
                            disabled={statusActionTaskId === task.id}
                            active={task.status === 'waiting'}
                            tone="waiting"
                          >
                            <Clock3 className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton
                            label="Зафиксировать препятствие, которое требует устранения или эскалации"
                            onClick={() => void openStatusTransition(task, 'blocked')}
                            disabled={statusActionTaskId === task.id}
                            active={task.status === 'blocked'}
                            tone="danger"
                          >
                            <AlertOctagon className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <span className="mx-0.5 hidden h-6 w-px bg-slate-200 sm:block dark:bg-slate-700" aria-hidden="true" />
                          <ActionButton
                            label={isTaskInTracker(task.id) ? 'Убрать из контроля сроков' : 'Поставить в контроль сроков'}
                            onClick={() => void toggleTracker(task)}
                            disabled={trackerBusyId === task.id}
                            active={isTaskInTracker(task.id)}
                            tone="tracker"
                          >
                            <CalendarClock className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton
                            label={(task.promoted_task_id || task.linked_task_id) ? 'Открыть состояние задачи в глобальной очереди' : 'Вывести задачу в глобальную очередь Q'}
                            onClick={() => openQueueAction(task)}
                            active={Boolean(task.promoted_task_id || task.linked_task_id)}
                            tone="queue"
                          >
                            <QueueGlyph className="h-4 w-4" />
                          </ActionButton>
                          <ActionButton label="Редактировать задачу" onClick={() => editTask(task)}>
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton label="Перенести задачу в архив" onClick={() => void updateStatus(task, 'archived')} disabled={statusActionTaskId === task.id}>
                            <Archive className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <span className="mx-0.5 hidden h-6 w-px bg-slate-200 sm:block dark:bg-slate-700" aria-hidden="true" />
                          <ActionButton
                            label="Готово: завершить задачу"
                            shortLabel="Готово"
                            onClick={() => void openStatusTransition(task, 'done')}
                            disabled={statusActionTaskId === task.id}
                            active={task.status === 'done'}
                            tone="success"
                            showLabel
                          >
                            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                        </>
                      ) : (
                        <>
                          <ActionButton label="Редактировать задачу" onClick={() => editTask(task)}>
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton
                            label="Вернуть задачу из архива в план"
                            onClick={() => void updateStatus(task, 'planned')}
                            disabled={statusActionTaskId === task.id}
                            tone="primary"
                          >
                            <ArchiveRestore className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                          <ActionButton label="Безвозвратно удалить задачу из архива" onClick={() => void deleteTask(task)} danger>
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </ActionButton>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {expandedId === task.id && (
                  <div
                    id={`personal-task-details-${task.id}`}
                    className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600"
                  >
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

                    <WorkEntityBacklinks targetType="personal_task" targetId={task.id} />

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

                    <PersonalTaskArtifactsPanel task={task} onChanged={() => void loadTaskDetails(task.id)} />

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

      {statusDialog && (
        <ProtectedModal>
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {statusDialog.duplicateWarning
                    ? 'Проверка двойной работы'
                    : statusDialog.status === 'waiting'
                      ? 'Перевод в ожидание'
                      : 'Фиксация блокировки'}
                </p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-100">
                  {statusDialog.task.task_key} · {statusDialog.task.title}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setStatusDialog(null)}
                aria-label="Закрыть"
                title="Закрыть"
                className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-slate-700 dark:hover:bg-slate-800"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {statusDialog.duplicateWarning ? (
              <div className="mt-4 space-y-3">
                <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100">
                  <p className="font-semibold">
                    {hasAmbiguousExecutionLinks(statusDialog.task)
                      ? 'У личной задачи две разные Q-связи.'
                      : 'Связанная Q-задача уже находится в активном исполнении.'}
                  </p>
                  {!hasAmbiguousExecutionLinks(statusDialog.task) && (
                    <p className="mt-1">
                      {(statusDialog.task.execution_task || statusDialog.task.promoted_task)?.assignee_name || 'Исполнитель не указан'}
                      {' · '}
                      {statusDialog.task.execution_task ? globalTaskStatusLabel[statusDialog.task.execution_task.status] : 'В работе'}.
                    </p>
                  )}
                </div>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {statusDialog.conflictMessage || 'Та же работа не может выполняться параллельно. Откройте Q-задачу и согласуйте отдельную часть с собственными границами и результатом.'}
                </p>
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                <div className={cn(
                  'rounded-lg border p-3 text-sm',
                  statusDialog.status === 'waiting'
                    ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100'
                    : 'border-rose-200 bg-rose-50 text-rose-900 dark:border-rose-700 dark:bg-rose-950/30 dark:text-rose-100',
                )}>
                  {statusDialog.status === 'waiting'
                    ? 'Ожидание — известная зависимость от человека, события или срока. Задача не требует активной работы прямо сейчас.'
                    : 'Блокировка — препятствие, которое нужно устранить или эскалировать. Простого ожидания недостаточно.'}
                </div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
                  {statusDialog.status === 'waiting' ? 'Что или кого ждем *' : 'Что блокирует задачу *'}
                  <textarea
                    autoFocus
                    value={statusContext.reason}
                    onChange={(event) => setStatusContext((current) => ({ ...current, reason: event.target.value }))}
                    rows={3}
                    maxLength={statusDialog.status === 'waiting' ? 200 : undefined}
                    placeholder={statusDialog.status === 'waiting' ? 'Например: ответ Петрова по смете' : 'Например: нет доступа к тестовой базе'}
                    className="mt-1.5 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
                  Следующий шаг
                  <input
                    value={statusContext.nextStep}
                    onChange={(event) => setStatusContext((current) => ({ ...current, nextStep: event.target.value }))}
                    maxLength={500}
                    placeholder={statusDialog.status === 'waiting' ? 'Что сделаем после получения ответа' : 'Как будем снимать блокировку'}
                    className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
                  Вернуться к задаче
                  <input
                    type="datetime-local"
                    value={statusContext.nextStepAt}
                    onChange={(event) => setStatusContext((current) => ({ ...current, nextStepAt: event.target.value }))}
                    className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                {isAfterTaskDeadline(toPayloadDate(statusContext.nextStepAt), statusDialog.task) && (
                  <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 dark:border-rose-700 dark:bg-rose-950/30 dark:text-rose-200">
                    Дата возврата позже дедлайна задачи. Статус сохранится, но финальный срок автоматически не изменится.
                  </p>
                )}
              </div>
            )}

            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => setStatusDialog(null)}
                disabled={statusBusy}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Отмена
              </button>
              {statusDialog.duplicateWarning ? (
                <>
                  {hasAmbiguousExecutionLinks(statusDialog.task) && (
                    <button
                      type="button"
                      onClick={() => {
                        const task = statusDialog.task
                        setStatusDialog(null)
                        editTask(task)
                      }}
                      className="rounded-lg border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-900 hover:bg-amber-50 dark:border-amber-700 dark:bg-slate-900 dark:text-amber-100 dark:hover:bg-slate-800"
                    >
                      Исправить связь
                    </button>
                  )}
                  {(statusDialog.task.execution_task || statusDialog.task.promoted_task) && (
                    <button
                      type="button"
                      onClick={() => {
                        const executionTask = statusDialog.task.execution_task || statusDialog.task.promoted_task
                        if (!executionTask) return
                        setStatusDialog(null)
                        navigate(`/queue?task=${executionTask.id}`)
                      }}
                      className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                    >
                      Открыть Q #{(statusDialog.task.execution_task || statusDialog.task.promoted_task)?.task_number}
                    </button>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => void submitStatusTransition()}
                  disabled={statusBusy}
                  className={cn(
                    'rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50',
                    statusDialog.status === 'waiting'
                      ? 'bg-amber-400 text-amber-950 hover:bg-amber-300'
                      : 'bg-rose-600 text-white hover:bg-rose-500',
                  )}
                >
                  {statusBusy
                    ? 'Сохраняем...'
                    : statusDialog.status === 'waiting'
                      ? 'Перевести в ожидание'
                      : 'Зафиксировать блокировку'}
                </button>
              )}
            </div>
          </div>
        </ProtectedModal>
      )}

      {queueDetailsTask && (
        <ProtectedModal>
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-300">Глобальная очередь Q</p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950 dark:text-slate-100">
                  {queueDetailsTask.execution_task ? `Q #${queueDetailsTask.execution_task.task_number}` : 'Задача связана'}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Источник: {queueDetailsTask.task_key} · {queueDetailsTask.title}</p>
              </div>
              <button
                type="button"
                onClick={() => setQueueDetailsTask(null)}
                aria-label="Закрыть"
                title="Закрыть"
                className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-slate-700 dark:hover:bg-slate-800"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <dl className="mt-4 grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2 dark:border-slate-700 dark:bg-slate-950/60">
              <div>
                <dt className="text-xs text-slate-400">Состояние</dt>
                <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                  {queueDetailsTask.execution_task ? globalTaskStatusLabel[queueDetailsTask.execution_task.status] : 'Синхронизация состояния'}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">Исполнитель</dt>
                <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                  {queueDetailsTask.execution_task?.assignee_name || 'Не назначен — задача свободна'}
                </dd>
              </div>
            </dl>
            <div className={cn(
              'mt-4 rounded-lg border p-3 text-sm',
              isWorkedByAnotherExecutor(queueDetailsTask)
                ? 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100'
                : 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-100',
            )}>
              {isWorkedByAnotherExecutor(queueDetailsTask)
                ? 'Другой исполнитель уже работает над Q-задачей. Личная задача остается контуром контроля, но повторно выполнять тот же результат нельзя. Отдельную часть оформите новой именованной задачей или операцией.'
                : 'Личная задача остается вашим контуром контроля. Когда глобальную задачу возьмут в работу, здесь появятся исполнитель и актуальный статус.'}
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setQueueDetailsTask(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800">
                Закрыть
              </button>
              {queueDetailsTask.execution_task && (
                <button
                  type="button"
                  onClick={() => {
                    const taskId = queueDetailsTask.execution_task?.id
                    if (!taskId) return
                    setQueueDetailsTask(null)
                    navigate(`/queue?task=${taskId}`)
                  }}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  Открыть Q #{queueDetailsTask.execution_task.task_number}
                </button>
              )}
            </div>
          </div>
        </ProtectedModal>
      )}

      {promoting && (
        <ProtectedModal>
          <div className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-4 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Вывод в глобальную очередь</p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950">{promoting.task_key} · {promoting.title}</h2>
                <p className="mt-1 text-sm text-slate-500">После подтверждения будет создана обычная DPMS-задача со статусом в очереди.</p>
              </div>
              <button type="button" onClick={() => setPromoting(null)} aria-label="Закрыть" title="Закрыть" className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
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
              <button type="button" onClick={() => setPromoting(null)} disabled={promoteBusy} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                Отмена
              </button>
              <button type="button" onClick={() => void promoteTask()} disabled={promoteBusy} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {promoteBusy ? 'Публикуем...' : 'Вывести в очередь'}
              </button>
            </div>
          </div>
        </ProtectedModal>
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

function TaskNextStep({ value }: { value: string | null }) {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <PlayCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
      <div className="min-w-0">
        <span className="block text-[11px] font-medium leading-4 text-slate-500 dark:text-slate-400">Следующий шаг</span>
        <span className="mt-0.5 block break-words text-sm leading-5 text-slate-700 dark:text-slate-200">
          {value || 'Не задан'}
        </span>
      </div>
    </div>
  )
}

function TaskMeta({
  icon,
  label,
  value,
  danger,
  warn,
  hint,
}: {
  icon: ReactNode
  label: string
  value: string
  danger?: boolean
  warn?: boolean
  hint?: string
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-[11px] font-medium leading-4 text-slate-500 dark:text-slate-400">
        <span aria-hidden="true">{icon}</span>
        {label}
      </dt>
      <dd
        className={cn(
          'mt-0.5 block break-words text-sm leading-5 tabular-nums',
          danger
            ? 'font-semibold text-rose-600 dark:text-rose-300'
            : warn
              ? 'font-semibold text-amber-700 dark:text-amber-300'
              : 'text-slate-700 dark:text-slate-200',
        )}
      >
        {value}
        {hint && <span className="ml-1.5 inline-block whitespace-nowrap text-[11px] font-medium">· {hint}</span>}
      </dd>
    </div>
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

type ActionTone = 'neutral' | 'primary' | 'next' | 'waiting' | 'danger' | 'success' | 'tracker' | 'queue'

const activeActionTone: Record<ActionTone, string> = {
  neutral: 'border-slate-400 bg-slate-100 text-slate-800 shadow-inner dark:border-slate-500 dark:bg-slate-700 dark:text-slate-100',
  primary: 'border-primary/35 bg-primary/10 text-primary shadow-inner hover:bg-primary/15',
  next: 'border-indigo-300 bg-indigo-50 text-indigo-700 shadow-inner hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/45 dark:text-indigo-200',
  waiting: 'border-amber-300 bg-amber-50 text-amber-800 shadow-inner hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950/45 dark:text-amber-200',
  danger: 'border-rose-300 bg-rose-50 text-rose-700 shadow-inner hover:bg-rose-100 dark:border-rose-700 dark:bg-rose-950/45 dark:text-rose-200',
  success: 'border-emerald-300 bg-emerald-50 text-emerald-700 shadow-inner hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-950/45 dark:text-emerald-200',
  tracker: 'border-emerald-300 bg-emerald-50 text-emerald-700 shadow-inner hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-950/45 dark:text-emerald-200',
  queue: 'border-blue-300 bg-blue-50 text-blue-700 shadow-inner hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-950/45 dark:text-blue-200',
}

function ActionButton({
  label,
  shortLabel,
  onClick,
  children,
  danger,
  disabled,
  active,
  tone = 'neutral',
  showLabel,
}: {
  label: string
  shortLabel?: string
  onClick: () => void
  children: ReactNode
  danger?: boolean
  disabled?: boolean
  active?: boolean
  tone?: ActionTone
  showLabel?: boolean
}) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        aria-pressed={active === undefined ? undefined : active}
        disabled={disabled}
        className={cn(
          'inline-flex h-11 items-center justify-center gap-1.5 rounded-lg border text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 sm:h-9 disabled:cursor-not-allowed disabled:opacity-40',
          showLabel ? 'min-w-11 px-2.5' : 'w-11 sm:w-9',
          active
            ? activeActionTone[tone]
            : danger
              ? 'border-rose-200 bg-white text-rose-600 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-300 dark:hover:bg-rose-950/40'
              : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800',
        )}
      >
        {children}
        {showLabel && <span className="whitespace-nowrap text-xs">{shortLabel || label}</span>}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-[calc(100%+0.45rem)] left-1/2 z-50 hidden w-max max-w-72 -translate-x-1/2 rounded-md bg-slate-950 px-2.5 py-1.5 text-center text-xs font-normal leading-4 text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:block"
      >
        {label}
      </span>
    </span>
  )
}

function QueueGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M3 7h2" />
      <path d="M3 12h2" />
      <path d="M3 17h2" />
      <circle cx="13" cy="11.5" r="6" />
      <path d="m14.5 14.5 3.5 3.5" />
    </svg>
  )
}

function ProtectedModal({ children }: { children: ReactNode }) {
  const panelRef = useProtectedModal<HTMLDivElement>()
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-3 backdrop-blur-sm sm:items-center"
      onPointerDown={preventBackdropDismiss}
    >
      <div ref={panelRef} tabIndex={-1} className="contents">
        {children}
      </div>
    </div>
  )
}
