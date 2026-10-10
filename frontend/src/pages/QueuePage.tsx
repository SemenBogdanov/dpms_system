import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { FileSpreadsheet, Lock, Pencil, Search } from 'lucide-react'
import { api } from '@/api/client'
import type { AssignCandidate, DeadlineTracker, QueueTaskResponse, Task, User, TaskStatus } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { PriorityBadge } from '@/components/PriorityBadge'
import { LeagueBadge } from '@/components/LeagueBadge'
import { QBadge } from '@/components/QBadge'
import { SkeletonTable } from '@/components/Skeleton'
import { DeadlineBadge } from '@/components/DeadlineBadge'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import { BugfixModal, useTaskDialogProtection } from '@/components/BugfixModal'
import { TaskImportModal } from '@/components/TaskImportModal'

const complexityStyles: Record<string, string> = {
  S: 'bg-gray-50 text-gray-400 ring-1 ring-gray-100',
  M: 'bg-accent-lighter text-accent-dark',
  L: 'bg-orange-50 text-orange-500',
  XL: 'bg-red-50 text-red-500',
}

const QUEUE_PAGE_SIZE = 50
const TASK_TITLE_MAX_LENGTH = 120

function formatQueueDuration(hours: number | undefined): string {
  const totalMinutes = Math.max(0, Math.round((hours ?? 0) * 60))
  if (totalMinutes < 60) return `${totalMinutes} мин`

  const totalHours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (totalHours < 24) {
    return minutes > 0 ? `${totalHours} ч ${minutes} мин` : `${totalHours} ч`
  }

  const totalDays = Math.floor(totalHours / 24)
  const hoursRest = totalHours % 24
  if (totalDays < 14) {
    return hoursRest > 0 ? `${totalDays} д ${hoursRest} ч` : `${totalDays} д`
  }

  const weeks = Math.floor(totalDays / 7)
  const daysRest = totalDays % 7
  return daysRest > 0 ? `${weeks} нед ${daysRest} д` : `${weeks} нед`
}

function formatCreatedDate(value: string): string {
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function formatCreatedDateTitle(value: string): string {
  return `Дата постановки: ${new Date(value).toLocaleString('ru', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })}`
}

type RowItem = (QueueTaskResponse & { status?: TaskStatus }) | Task

export function QueuePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTaskId = searchParams.get('task')
  const { user: currentUser } = useAuth()
  const [tasks, setTasks] = useState<QueueTaskResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pullingId, setPullingId] = useState<string | null>(null)
  const [confirmPull, setConfirmPull] = useState<QueueTaskResponse | Task | null>(null)
  const [myTasks, setMyTasks] = useState<Task[]>([])
  const [detailTask, setDetailTask] = useState<Task | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailRevision, setDetailRevision] = useState(0)
  const queueGeneration = useRef(0)
  const archiveGeneration = useRef(0)
  const [archiveError, setArchiveError] = useState('')
  const [archiveLoading, setArchiveLoading] = useState(false)
  const [deadlineTrackers, setDeadlineTrackers] = useState<DeadlineTracker[]>([])
  const [trackerBusyId, setTrackerBusyId] = useState<string | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [allTasks, setAllTasks] = useState<Task[]>([])
  const [activeTag, setActiveTag] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [sortField, setSortField] = useState<'title' | 'estimated_q' | 'priority' | 'due_date' | 'status'>('priority')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [bugfixParent, setBugfixParent] = useState<Task | null>(null)
  const [bugfixTitle, setBugfixTitle] = useState('')
  const [bugfixDescription, setBugfixDescription] = useState('')
  const [bugfixBusy, setBugfixBusy] = useState(false)
  const [assignTask, setAssignTask] = useState<QueueTaskResponse | null>(null)
  const [assignCandidates, setAssignCandidates] = useState<AssignCandidate[]>([])
  const [selectedExecutorId, setSelectedExecutorId] = useState<string | null>(null)
  const [assignBusy, setAssignBusy] = useState(false)
  const [editTask, setEditTask] = useState<RowItem | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editPriority, setEditPriority] = useState<'low' | 'medium' | 'high' | 'critical'>('medium')
  const [editTags, setEditTags] = useState('')
  const [editBusy, setEditBusy] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const canSetCriticalPriority = currentUser?.role === 'admin'
  const editDialog = useTaskDialogProtection(Boolean(editTask), editBusy, Boolean(editTask && (editTitle !== editTask.title || editDescription !== (editTask.description || '') || editPriority !== editTask.priority || editTags !== (editTask.tags || []).join(', '))), () => setEditTask(null))
  const editInFlight = useRef(false)
  const bugfixInFlight = useRef(false)
  const deadlinePending = useRef(new Set<string>())

  const loadQueue = useCallback(() => {
    if (!currentUser) return
    const generation = ++queueGeneration.current
    setLoading(true); setError(null)
    api
      .get<QueueTaskResponse[]>('/api/queue')
      .then((data) => { if (generation === queueGeneration.current) setTasks(data) })
      .catch((e) => { if (generation === queueGeneration.current) setError(e instanceof Error ? e.message : 'Ошибка') })
      .finally(() => { if (generation === queueGeneration.current) setLoading(false) })
  }, [currentUser])

  const loadDeadlineTrackers = useCallback(async () => {
    try {
      const list = await api.get<DeadlineTracker[]>('/api/deadline-trackers?include_archived=true&limit=300')
      setDeadlineTrackers(list)
    } catch {
      setDeadlineTrackers([])
    }
  }, [])

  const openDetail = useCallback((id: string | null) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      if (id) next.set('task', id)
      else next.delete('task')
      return next
    })
  }, [setSearchParams])

  const loadArchivedTasks = useCallback(() => {
    if (!currentUser) return
    const endpoint =
      currentUser.role === 'executor'
        ? `/api/tasks?assignee_id=${currentUser.id}&status=done`
        : '/api/tasks'
    const generation = ++archiveGeneration.current
    setArchiveLoading(true); setArchiveError('')
    api.get<Task[]>(endpoint)
      .then((data) => { if (generation === archiveGeneration.current) setAllTasks(data) })
      .catch((cause) => { if (generation === archiveGeneration.current) setArchiveError(cause instanceof Error ? cause.message : 'Не удалось загрузить архив') })
      .finally(() => { if (generation === archiveGeneration.current) setArchiveLoading(false) })
  }, [currentUser])

  useEffect(() => {
    if (!currentUser) return
    loadQueue()
    void loadDeadlineTrackers()
  }, [currentUser, loadQueue, loadDeadlineTrackers])

  useEffect(() => {
    if (!currentUser) return
    api
      .get<Task[]>(`/api/tasks?assignee_id=${currentUser.id}`)
      .then(setMyTasks)
      .catch(() => setMyTasks([]))
  }, [currentUser])

  useEffect(() => {
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([]))
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setDetailError(''); setDetailTask(null); setDetailLoading(Boolean(requestedTaskId))
    if (requestedTaskId) {
      void api.get<Task>(`/api/tasks/${requestedTaskId}`, undefined, { signal: controller.signal })
        .then((task) => { if (!controller.signal.aborted) setDetailTask(task) })
        .catch((cause) => { if (!controller.signal.aborted) setDetailError(cause instanceof Error ? cause.message : 'Не удалось загрузить задачу') })
        .finally(() => { if (!controller.signal.aborted) setDetailLoading(false) })
    }
    return () => controller.abort()
  }, [requestedTaskId, detailRevision])

  const isTaskInTracker = useCallback((taskId: string) => {
    return deadlineTrackers.some((tracker) => tracker.linked_task_id === taskId && tracker.status !== 'archived')
  }, [deadlineTrackers])

  const handleToggleTracker = useCallback(async (task: Task) => {
    setTrackerBusyId(task.id)
    try {
      if (isTaskInTracker(task.id)) {
        await api.delete(`/api/deadline-trackers/by-task/${task.id}`)
        toast.success('Задача убрана из трекера')
      } else {
        await api.post<DeadlineTracker>(`/api/deadline-trackers/from-task/${task.id}`, {})
        toast.success('Задача добавлена в трекер')
      }
      await loadDeadlineTrackers()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка трекера')
    } finally {
      setTrackerBusyId(null)
    }
  }, [isTaskInTracker, loadDeadlineTrackers])

  useEffect(() => {
    if (!includeArchived) {
      archiveGeneration.current += 1
      setArchiveLoading(false); setArchiveError(''); setAllTasks([])
      return
    }
    loadArchivedTasks()
  }, [includeArchived, loadArchivedTasks])

  const displayList: RowItem[] = includeArchived
    ? currentUser?.role === 'executor'
      ? [...tasks.map((t) => ({ ...t, status: 'in_queue' as TaskStatus })), ...allTasks]
      : allTasks
    : tasks.map((t) => ({ ...t, status: 'in_queue' as TaskStatus }))

  const filteredBySearch = displayList.filter((t) => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toUpperCase()
      const matchTitle = t.title.toUpperCase().includes(q)
      const matchNumber = `#${t.task_number}`.includes(q) || String(t.task_number).includes(q)
      const tags = (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []
      const matchTag = tags.some((tag: string) => tag.toUpperCase().includes(q))
      return matchTitle || matchNumber || matchTag
    }
    return true
  })

  const filteredByTag = activeTag
    ? filteredBySearch.filter((t) => {
        const tags = (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []
        return tags.includes(activeTag)
      })
    : filteredBySearch

  const priorityOrder: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 }
  const priorityLabels: Record<string, string> = {
    critical: 'Критические',
    high: 'Высокие',
    medium: 'Средние',
    low: 'Низкие',
    proactive: 'Проактивные',
  }
  const sortedTasks = [...filteredByTag].sort((a, b) => {
    const aBug = (a as QueueTaskResponse).task_type === 'bugfix' || (a as Task).task_type === 'bugfix'
    const bBug = (b as QueueTaskResponse).task_type === 'bugfix' || (b as Task).task_type === 'bugfix'
    if (aBug !== bBug) return aBug ? -1 : 1
    // Проактивные — после обычных задач
    const aProactive = isProactive(a as RowItem)
    const bProactive = isProactive(b as RowItem)
    if (aProactive !== bProactive) return aProactive ? 1 : -1
    const aStatus = (a as Task).status ?? 'in_queue'
    const bStatus = (b as Task).status ?? 'in_queue'
    const aPri = priorityOrder[(a as QueueTaskResponse).priority ?? (a as Task).priority] ?? 0
    const bPri = priorityOrder[(b as QueueTaskResponse).priority ?? (b as Task).priority] ?? 0
    if (sortField === 'priority') {
      const diff = sortDir === 'desc' ? bPri - aPri : aPri - bPri
      if (diff !== 0) return diff
    }
    if (sortField === 'title') {
      const cmp = (a.title ?? '').localeCompare(b.title ?? '')
      return sortDir === 'asc' ? cmp : -cmp
    }
    if (sortField === 'estimated_q') {
      const diff = (a.estimated_q ?? 0) - (b.estimated_q ?? 0)
      return sortDir === 'asc' ? diff : -diff
    }
    if (sortField === 'due_date') {
      const aD = (a as QueueTaskResponse).due_date ?? (a as Task).due_date
      const bD = (b as QueueTaskResponse).due_date ?? (b as Task).due_date
      const aT = aD ? new Date(aD).getTime() : 0
      const bT = bD ? new Date(bD).getTime() : 0
      return sortDir === 'asc' ? aT - bT : bT - aT
    }
    if (sortField === 'status') {
      const cmp = String(aStatus).localeCompare(String(bStatus))
      return sortDir === 'asc' ? cmp : -cmp
    }
    return new Date((a as QueueTaskResponse).created_at ?? (a as Task).created_at).getTime() - new Date((b as QueueTaskResponse).created_at ?? (b as Task).created_at).getTime()
  })

  useEffect(() => {
    setPage(1)
  }, [searchQuery, activeTag, includeArchived, sortField, sortDir, tasks.length, allTasks.length])

  const totalTasks = sortedTasks.length
  const totalPages = Math.max(1, Math.ceil(totalTasks / QUEUE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageStart = totalTasks === 0 ? 0 : (currentPage - 1) * QUEUE_PAGE_SIZE + 1
  const pageEnd = Math.min(currentPage * QUEUE_PAGE_SIZE, totalTasks)
  const pageTasks = sortedTasks.slice((currentPage - 1) * QUEUE_PAGE_SIZE, currentPage * QUEUE_PAGE_SIZE)

  const handleSort = (field: typeof sortField) => {
    if (sortField === field) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('desc')
    }
  }

  const allTags = [...new Set(displayList.flatMap((t) => (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []))].sort()
  const isTeamleadOrAdmin = currentUser?.role === 'teamlead' || currentUser?.role === 'admin'
  const isAdmin = currentUser?.role === 'admin'

  const doPull = async () => {
    if (!confirmPull || !currentUser) return
    setPullingId(confirmPull.id)
    try {
      await api.post('/api/queue/pull', {
        task_id: confirmPull.id,
      })
      toast.success('Задача взята!')
      setConfirmPull(null)
      if (includeArchived) {
        loadArchivedTasks()
      } else {
        setTasks((prev) => prev.filter((t) => t.id !== confirmPull.id))
      }
      navigate('/my-tasks')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось взять задачу')
      setConfirmPull(null)
      if (includeArchived) {
        loadArchivedTasks()
      } else {
        loadQueue()
      }
    } finally {
      setPullingId(null)
    }
  }

  const wipCount = myTasks.filter((t) => t.status === 'in_progress').length

  if (loading && !tasks.length && !requestedTaskId) return <SkeletonTable rows={8} />

  const handleOpenBugfix = (task: Task) => {
    openDetail(null)
    setBugfixParent(task)
    setBugfixTitle(`Баг: ${task.title}`.slice(0, TASK_TITLE_MAX_LENGTH))
    setBugfixDescription('')
  }

  const handleCreateBugfix = async () => {
    if (!bugfixParent || !bugfixTitle.trim() || bugfixInFlight.current) return
    if (bugfixTitle.trim().length > TASK_TITLE_MAX_LENGTH) {
      toast.error(`Название задачи не длиннее ${TASK_TITLE_MAX_LENGTH} символов`)
      return
    }
    bugfixInFlight.current = true
    setBugfixBusy(true)
    try {
      await api.post('/api/tasks/bugfix', {
        parent_task_id: bugfixParent.id,
        title: bugfixTitle.trim(),
        description: bugfixDescription.trim() || undefined,
      })
      toast.success('Баг-фикс создан')
      setBugfixParent(null)
      setBugfixTitle('')
      setBugfixDescription('')
      if (includeArchived) {
        loadArchivedTasks()
      } else {
        loadQueue()
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось создать баг-фикс')
    } finally {
      bugfixInFlight.current = false
      setBugfixBusy(false)
    }
  }

  const handleDelete = (t: RowItem) => {
    const title = t.title
    if (!window.confirm(`Отменить задачу «${title}»?`)) return
    api
      .delete(`/api/tasks/${t.id}`)
      .then(() => {
        toast.success('Задача отменена')
        if (includeArchived) {
          loadArchivedTasks()
        } else {
          loadQueue()
        }
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  const handleOpenEdit = (t: RowItem) => {
    setEditTask(t)
    setEditTitle(t.title)
    setEditDescription(t.description ?? '')
    setEditPriority(((t as QueueTaskResponse).priority ?? (t as Task).priority) as 'low' | 'medium' | 'high' | 'critical')
    setEditTags(taskTags(t).join(', '))
  }

  const handleSaveEdit = async () => {
    if (!editTask || !editTitle.trim() || editInFlight.current) return
    if (editTitle.trim().length > TASK_TITLE_MAX_LENGTH) {
      toast.error(`Название задачи не длиннее ${TASK_TITLE_MAX_LENGTH} символов`)
      return
    }
    editInFlight.current = true
    setEditBusy(true)
    try {
      const updated = await api.patch<Task>(`/api/tasks/${editTask.id}`, {
        title: editTitle.trim(),
        description: editDescription.trim() || null,
        priority: editPriority,
        tags: editTags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      })
      toast.success('Заявка обновлена')
      setEditTask(null)
      if (detailTask?.id === updated.id) {
        setDetailTask(updated)
      }
      if (includeArchived) {
        loadArchivedTasks()
      } else {
        loadQueue()
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сохранить заявку')
    } finally {
      editInFlight.current = false
      setEditBusy(false)
    }
  }

  const taskStatus = (t: RowItem): TaskStatus => (t as Task).status ?? 'in_queue'
  const canPull = (t: RowItem) => (t as QueueTaskResponse).can_pull === true
  const locked = (t: RowItem) => (t as QueueTaskResponse).locked === true
  const lockReason = (t: RowItem) => (t as QueueTaskResponse).lock_reason
  const taskTags = (t: RowItem) => (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []
  const taskType = (t: RowItem) => (t as QueueTaskResponse).task_type ?? (t as Task).task_type
  function isProactive(t: RowItem): boolean {
    return (t as QueueTaskResponse).is_proactive === true || (t as Task).task_type === 'proactive'
  }

  const hasTaskMeta = (t: RowItem): boolean =>
    taskType(t) === 'bugfix' ||
    isProactive(t) ||
    ((t as Task).rejection_count ?? 0) > 0 ||
    (t as QueueTaskResponse).is_stale === true ||
    (!(t as QueueTaskResponse).is_stale && ((t as QueueTaskResponse).hours_in_queue ?? 0) > 24) ||
    (t as QueueTaskResponse).recommended === true ||
    (t as QueueTaskResponse).acceptance_mode === 'criteria' ||
    (t as Task).acceptance_mode === 'criteria' ||
    taskTags(t).length > 0 ||
    Boolean((t as QueueTaskResponse).assigned_by_name)

  return (
    <div className="space-y-6">
      {error && <div role="alert">{error}<button type="button" onClick={loadQueue}>Повторить загрузку очереди</button></div>}
      {includeArchived && archiveError && <div role="alert">{archiveError}<button type="button" onClick={loadArchivedTasks}>Повторить загрузку архива</button></div>}
      {detailLoading && <p role="status">Загрузка задачи...</p>}
      {detailError && <div role="alert">{detailError}<button type="button" onClick={() => setDetailRevision((value) => value + 1)}>Повторить загрузку задачи</button><button type="button" onClick={() => openDetail(null)}>Закрыть карточку</button></div>}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-gray-700">Глобальная очередь</h1>
          {isTeamleadOrAdmin && (
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to="/calculator"
                className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark transition-colors"
              >
                ➕ Создать задачу
              </Link>
              <button
                type="button"
                onClick={() => setImportModalOpen(true)}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
              >
                <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
                Импорт CSV
              </button>
            </div>
          )}
        </div>
        {currentUser && (
          <div className="text-sm text-gray-600 whitespace-nowrap">
            Лига {currentUser.league} · WIP: {wipCount} из {currentUser.wip_limit} ·{' '}
            {Number(currentUser.wallet_main).toFixed(1)}/{currentUser.mpw} Q
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
          <input
            type="text"
            placeholder="Поиск по названию или тегу..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-10 pr-4 text-sm"
          />
        </div>
        <label className="flex items-center gap-2 whitespace-nowrap text-sm text-gray-600">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="rounded border-gray-300"
          />
          Включая закрытые
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500">Проекты:</span>
        <button
          type="button"
          onClick={() => setActiveTag(null)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition ${
            activeTag === null ? 'bg-primary text-primary-foreground' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
          }`}
        >
          Все
        </button>
        {allTags.map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => setActiveTag(activeTag === tag ? null : tag)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition ${
              activeTag === tag ? 'bg-primary text-primary-foreground' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
            }`}
          >
            {tag}
          </button>
        ))}
      </div>
      {activeTag && (
        <div className="text-sm text-gray-600">
          Проект <span className="font-semibold">{activeTag}</span>: {filteredByTag.length} задач,{' '}
          <span className="whitespace-nowrap font-semibold">
            {Number(filteredByTag.reduce((sum, t) => sum + Number(t.estimated_q), 0)).toFixed(1)} Q
          </span>
        </div>
      )}

      {displayList.length === 0 && !loading ? (
        <div className="rounded-xl border border-gray-200 bg-white p-12 text-center text-gray-500">
          Очередь пуста. Создайте задачу через калькулятор.
        </div>
      ) : (includeArchived ? archiveLoading || archiveError : loading || error) ? (
        <p role="status">{loading || archiveLoading ? 'Загрузка задач...' : 'Список не обновлён'}</p>
      ) : sortedTasks.length === 0 ? (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center text-gray-500">
          {searchQuery.trim()
            ? `По запросу «${searchQuery}» задач не найдено`
            : activeTag
              ? `Нет задач по проекту ${activeTag}`
              : 'Нет задач'}
        </div>
      ) : (
        <>
        <div className="overflow-x-auto rounded-2xl border border-gray-100 bg-white">
          <table className="min-w-[1320px] table-fixed divide-y divide-gray-100 xl:min-w-full">
            <colgroup>
              <col className="w-[36%]" />
              <col className="w-[7%]" />
              <col className="w-[7%]" />
              <col className="w-[6%]" />
              <col className="w-[6%]" />
              <col className="w-[9%]" />
              <col className="w-[8%]" />
              <col className="w-[7%]" />
              <col className="w-[8%]" />
              <col className="w-[6%]" />
            </colgroup>
            <thead className="bg-gray-50/50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600" aria-sort={sortField === 'title' ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  <button type="button" className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => handleSort('title')}>Название <span aria-hidden="true">{sortField === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span></button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600" aria-sort={sortField === 'status' ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  <button type="button" className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => handleSort('status')}>Статус <span aria-hidden="true">{sortField === 'status' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span></button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Тип</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Сложность</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 min-w-[60px]" aria-sort={sortField === 'estimated_q' ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  <button type="button" className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => handleSort('estimated_q')}>Q <span aria-hidden="true">{sortField === 'estimated_q' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span></button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600" aria-sort={sortField === 'due_date' ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  <button type="button" className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => handleSort('due_date')}>Срок <span aria-hidden="true">{sortField === 'due_date' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span></button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600" aria-sort={sortField === 'priority' ? (sortDir === 'asc' ? 'ascending' : 'descending') : undefined}>
                  <button type="button" className="min-h-11 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => handleSort('priority')}>Приоритет <span aria-hidden="true">{sortField === 'priority' ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span></button>
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Мин. лига</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-600">Дата постановки</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-600">Действие</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                let lastPriority: string | null = null
                let proactiveSectionShown = false
                const rows: Array<{ type: 'section'; priority: string } | { type: 'task'; task: RowItem }> = []
                pageTasks.forEach((t) => {
                  const isProact = isProactive(t as RowItem)
                  // Разделитель «Проактивные» перед первой проактивной задачей
                  if (isProact && !proactiveSectionShown) {
                    rows.push({ type: 'section', priority: 'proactive' })
                    proactiveSectionShown = true
                  }
                  // Разделители по приоритету только для обычных задач
                  if (!isProact) {
                    const p = (t as QueueTaskResponse).priority ?? (t as Task).priority ?? 'medium'
                    if (p !== lastPriority) {
                      rows.push({ type: 'section', priority: p })
                      lastPriority = p
                    }
                  }
                  rows.push({ type: 'task', task: t })
                })
                return rows.map((row, idx) =>
                  row.type === 'section' ? (
                    <tr key={`section-${row.priority}-${idx}`} className="queue-priority-section bg-gray-50/50">
                      <td colSpan={10} className="px-4 py-2 text-xs font-medium text-gray-400 tracking-wide uppercase">
                        {priorityLabels[row.priority] ?? row.priority}
                      </td>
                    </tr>
                  ) : (
                    <tr
                      key={(row.task as Task).id}
                      className={`queue-task-row ${locked(row.task) ? 'opacity-60' : ''} ${taskType(row.task) === 'bugfix' ? 'border-l-3 border-red-300 bg-red-50/30' : ''}`}
                    >
                      <td className="px-4 py-3 text-sm text-gray-700 align-top">
                        <div className="min-w-0 space-y-1">
                          <div className="flex min-w-0 items-center gap-3">
                            <span className="shrink-0 font-mono text-xs font-semibold leading-5 text-gray-400">
                              #{row.task.task_number}
                            </span>
                            <button
                              type="button"
                              onClick={() => openDetail(row.task.id)}
                              className="min-w-0 flex-1 cursor-pointer whitespace-normal break-words text-left font-medium leading-5 text-gray-700 transition-colors hover:text-accent-dark [overflow-wrap:anywhere]"
                              title={row.task.title}
                            >
                              {row.task.title}
                            </button>
                          </div>
                          {hasTaskMeta(row.task) && (
                            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                              {taskType(row.task) === 'bugfix' && (
                                <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-medium leading-5 text-red-500">
                                  Гарантийный
                                </span>
                              )}
                              {isProactive(row.task) && (
                                <span className="inline-flex items-center rounded-full bg-accent-lighter px-2.5 py-0.5 text-xs font-medium leading-5 text-accent-dark">
                                  Проактивная
                                </span>
                              )}
                              {(row.task as Task).rejection_count > 0 && (
                                <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium leading-5 text-amber-500">
                                  ↩ {(row.task as Task).rejection_count}
                                </span>
                              )}
                              {((row.task as QueueTaskResponse).acceptance_mode ?? (row.task as Task).acceptance_mode) === 'criteria' && (
                                <span
                                  className="inline-flex items-center rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-medium leading-5 text-sky-700"
                                  title="Задача принимается по заранее заданным критериям"
                                >
                                  Приемка: {(row.task as QueueTaskResponse).acceptance_required_count ?? (row.task as Task).acceptance_required_count} обяз.
                                </span>
                              )}
                              {(row.task as QueueTaskResponse).is_stale && (
                                <span className="inline-flex items-center rounded-full bg-orange-50 px-2.5 py-0.5 text-xs font-medium leading-5 text-orange-500">
                                  Застряла {formatQueueDuration((row.task as QueueTaskResponse).hours_in_queue)}
                                </span>
                              )}
                              {!(row.task as QueueTaskResponse).is_stale && ((row.task as QueueTaskResponse).hours_in_queue ?? 0) > 24 && (
                                <span className="inline-flex items-center rounded-full bg-gray-50 px-2.5 py-0.5 text-xs font-medium leading-5 text-gray-400">
                                  {formatQueueDuration((row.task as QueueTaskResponse).hours_in_queue)} в очереди
                                </span>
                              )}
                              {(row.task as QueueTaskResponse).recommended && (
                                <span className="inline-flex items-center rounded-full bg-accent-lighter px-2.5 py-0.5 text-xs font-medium leading-5 text-accent-dark">
                                  Рекомендуем
                                </span>
                              )}
                              {taskTags(row.task).map((tag) => (
                                <span key={tag} className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs leading-5 text-gray-600">
                                  {tag}
                                </span>
                              ))}
                              {(row.task as QueueTaskResponse).assigned_by_name && (
                                <span className="text-xs leading-5 text-gray-500">
                                  Назначил: {(row.task as QueueTaskResponse).assigned_by_name}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                  <td className="px-4 py-3 text-xs text-gray-600 whitespace-nowrap">
                    {taskStatus(row.task) === 'in_queue' && 'В очереди'}
                    {taskStatus(row.task) === 'in_progress' && 'В работе'}
                    {taskStatus(row.task) === 'review' && 'На проверке'}
                    {taskStatus(row.task) === 'done' && 'Готово'}
                    {taskStatus(row.task) === 'cancelled' && 'Отменена'}
                    {taskStatus(row.task) === 'new' && 'Новая'}
                    {taskStatus(row.task) === 'estimated' && 'Оценена'}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{taskType(row.task)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${complexityStyles[(row.task as QueueTaskResponse).complexity ?? (row.task as Task).complexity] ?? 'bg-gray-100'}`}>
                      {(row.task as QueueTaskResponse).complexity ?? (row.task as Task).complexity}
                    </span>
                  </td>
                  <td className="px-4 py-3 min-w-[60px]">
                    <span className="whitespace-nowrap"><QBadge q={row.task.estimated_q} /></span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col items-start gap-0.5">
                      {((row.task as QueueTaskResponse).due_date ?? (row.task as Task).due_date) ? (
                        <DeadlineBadge
                          dueDate={(row.task as QueueTaskResponse).due_date ?? (row.task as Task).due_date}
                          zone={(row.task as QueueTaskResponse).deadline_zone ?? (row.task as Task).deadline_zone}
                          status={taskStatus(row.task)}
                          showLabel={false}
                        />
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <PriorityBadge priority={((row.task as QueueTaskResponse).priority ?? (row.task as Task).priority) as 'low' | 'medium' | 'high' | 'critical'} />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <LeagueBadge league={(row.task as QueueTaskResponse).min_league ?? (row.task as Task).min_league} />
                  </td>
                  <td
                    className="whitespace-nowrap px-4 py-3"
                    title={formatCreatedDateTitle((row.task as QueueTaskResponse).created_at ?? (row.task as Task).created_at)}
                  >
                    <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                      {formatCreatedDate((row.task as QueueTaskResponse).created_at ?? (row.task as Task).created_at)}
                    </span>
                  </td>
	                  <td className="px-4 py-3 text-right">
	                    <div className="flex items-center justify-end gap-2 whitespace-nowrap">
	                      {isTeamleadOrAdmin && taskStatus(row.task) !== 'done' && taskStatus(row.task) !== 'cancelled' && (
	                        <button
	                          type="button"
	                          onClick={() => handleOpenEdit(row.task)}
	                          className="rounded p-1 text-gray-400 hover:bg-gray-50 hover:text-gray-700"
	                          title="Редактировать заявку"
	                        >
	                          <Pencil className="h-4 w-4" />
	                        </button>
	                      )}
	                      {isTeamleadOrAdmin && taskStatus(row.task) !== 'done' && taskStatus(row.task) !== 'cancelled' && (
	                        <button
	                          type="button"
	                          onClick={() => handleDelete(row.task)}
	                          className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600"
	                          title="Отменить задачу"
	                        >
	                          🗑️
	                        </button>
                      )}
                      {isTeamleadOrAdmin && taskStatus(row.task) === 'in_queue' && (row.task as QueueTaskResponse).can_assign && (
                        <button
                          type="button"
                          onClick={() => {
                            setAssignTask(row.task as QueueTaskResponse)
                            setSelectedExecutorId(null)
                            api.get<AssignCandidate[]>(`/api/queue/candidates/${row.task.id}`).then(setAssignCandidates).catch(() => setAssignCandidates([]))
                          }}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        >
                          Назначить
                        </button>
                      )}
                      {locked(row.task) ? (
                        <span className="inline-flex items-center gap-1 text-sm text-gray-500">
                          <Lock className="h-4 w-4" />
                          <span className="hidden sm:inline">{lockReason(row.task) ?? `Лига ${(row.task as QueueTaskResponse).min_league}`}</span>
                        </span>
                      ) : canPull(row.task) ? (
	                        <button
	                          type="button"
	                          onClick={() => setConfirmPull(row.task)}
	                          disabled={!!pullingId}
	                          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50 transition-colors"
	                        >
	                          Взять
	                        </button>
                      ) : taskStatus(row.task) === 'in_queue' ? (
                        <span title={lockReason(row.task) ?? 'WIP-лимит исчерпан'} className="cursor-help text-sm text-gray-400">
                          WIP
                        </span>
                      ) : null}
                    </div>
                  </td>
                </tr>
                  )
                )
              })()}
            </tbody>
          </table>
        </div>
        {totalTasks > QUEUE_PAGE_SIZE && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-gray-100 bg-white px-4 py-3 text-sm text-gray-600">
            <span>
              {pageStart}-{pageEnd} из {totalTasks} задач
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={currentPage === 1}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Назад
              </button>
              <span className="whitespace-nowrap text-xs text-gray-500">
                Страница {currentPage} из {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={currentPage === totalPages}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Вперёд
              </button>
            </div>
          </div>
        )}
        </>
      )}

      <TaskImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onImported={() => {
          if (includeArchived) {
            loadArchivedTasks()
          } else {
            loadQueue()
          }
        }}
      />

      <TaskDetailModal
        task={detailTask}
        onClose={() => openDetail(null)}
        users={users}
        isTeamleadOrAdmin={isTeamleadOrAdmin}
        onOpenBugfix={isAdmin ? handleOpenBugfix : undefined}
        onOpenDeadline={(task) => {
          if (deadlinePending.current.has(task.id)) return
          const hours = prompt('Срок выполнения (часов от сейчас):')
          if (!hours || Number.isNaN(Number(hours))) return
          const dueDate = new Date(Date.now() + Number(hours) * 3600000).toISOString()
          deadlinePending.current.add(task.id)
          api
            .patch<Task>(`/api/tasks/${task.id}/due-date`, { due_date: dueDate })
            .then((updated) => {
              toast.success('Дедлайн установлен')
              setTasks((previous) => previous.map((row) => row.id === task.id ? { ...row, ...updated, due_date: updated.due_date || dueDate } : row))
              setAllTasks((previous) => previous.map((row) => row.id === task.id ? { ...row, ...updated, due_date: updated.due_date || dueDate } : row))
              setDetailTask((current) => current?.id === task.id ? { ...current, ...updated, due_date: updated.due_date || dueDate } : current)
            })
            .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
            .finally(() => deadlinePending.current.delete(task.id))
        }}
        onAcceptanceUpdated={() => { loadQueue(); if (includeArchived) loadArchivedTasks(); setDetailRevision((value) => value + 1) }}
        onToggleTracker={handleToggleTracker}
        isInTracker={detailTask ? isTaskInTracker(detailTask.id) : false}
        trackerBusy={detailTask ? trackerBusyId === detailTask.id : false}
      />

      {bugfixParent && (
        <BugfixModal
          open={Boolean(bugfixParent)}
          parentTask={bugfixParent}
          author={users.find((u) => u.id === bugfixParent.assignee_id) ?? null}
          title={bugfixTitle}
          description={bugfixDescription}
          onTitleChange={setBugfixTitle}
          onDescriptionChange={setBugfixDescription}
          onClose={() => {
            setBugfixParent(null)
            setBugfixTitle('')
            setBugfixDescription('')
          }}
          onSubmit={handleCreateBugfix}
          busy={bugfixBusy}
        />
      )}

      {editTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          aria-label="Редактировать заявку"
          onKeyDown={(e) => e.key === 'Escape' && editDialog.requestClose()}
        >
          <div ref={editDialog.panelRef} tabIndex={-1} className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-lg">
            <h3 className="text-lg font-semibold text-gray-700">Редактировать заявку</h3>
            <p className="mt-1 text-sm text-gray-500">#{editTask.task_number}</p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Название <span className="text-red-600">*</span>
                </label>
                <input
                  type="text"
                  aria-label="Название заявки"
                  disabled={editBusy}
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  maxLength={TASK_TITLE_MAX_LENGTH}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                <p className="mt-1 text-xs text-slate-400">
                  {editTitle.trim().length}/{TASK_TITLE_MAX_LENGTH} символов
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Описание</label>
                <textarea
                  aria-label="Описание заявки"
                  disabled={editBusy}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-gray-700">Приоритет</label>
                  <select
                    aria-label="Приоритет заявки"
                    value={editPriority}
                    onChange={(e) => setEditPriority(e.target.value as 'low' | 'medium' | 'high' | 'critical')}
                    disabled={editBusy || (!canSetCriticalPriority && editPriority === 'critical')}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  >
                    {(canSetCriticalPriority || editPriority === 'critical') && (
                      <option value="critical" disabled={!canSetCriticalPriority}>
                        critical
                      </option>
                    )}
                    <option value="high">high</option>
                    <option value="medium">medium</option>
                    <option value="low">low</option>
                  </select>
                  {!canSetCriticalPriority && editPriority === 'critical' && (
                    <p className="mt-1 text-xs text-gray-500">
                      Критический приоритет меняет только администратор.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700">Теги</label>
                  <input
                    type="text"
                    aria-label="Теги заявки"
                  disabled={editBusy}
                  value={editTags}
                    onChange={(e) => setEditTags(e.target.value)}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    placeholder="через запятую"
                  />
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={editDialog.requestClose}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                disabled={editBusy || !editTitle.trim() || editTitle.trim().length > TASK_TITLE_MAX_LENGTH}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-dark disabled:opacity-50"
              >
                {editBusy ? '...' : 'Сохранить'}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmPull && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setConfirmPull(null)}
        >
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg">
            <p className="text-gray-800">
              Взять задачу #{confirmPull.task_number} «{confirmPull.title}» за {confirmPull.estimated_q} Q?
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmPull(null)}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={doPull}
                disabled={!!pullingId}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50 transition-colors"
              >
                {pullingId ? '...' : 'Взять'}
              </button>
            </div>
          </div>
        </div>
      )}

      {assignTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setAssignTask(null)}
        >
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-lg">
            <h3 className="text-lg font-semibold text-gray-700">Назначить задачу</h3>
            <p className="mt-1 text-sm text-gray-600">#{assignTask.task_number} «{assignTask.title}»</p>
            <p className="mt-3 text-sm font-medium text-gray-700">Выберите исполнителя:</p>
            <ul className="mt-2 max-h-60 overflow-y-auto rounded border border-gray-200">
              {assignCandidates.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    disabled={!c.is_available}
                    onClick={() => c.is_available && setSelectedExecutorId(c.id)}
                    className={`w-full px-4 py-2 text-left text-sm ${c.is_available ? 'hover:bg-gray-50' : 'cursor-not-allowed bg-gray-50 text-gray-400'}`}
                  >
                    <span className="font-medium">{c.full_name}</span>
                    {c.role === 'teamlead' && (
                      <span className="ml-2 rounded-full bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">
                        тимлид
                      </span>
                    )}
                    <span className="ml-2 text-gray-500">Лига {c.league}</span>
                    <span className="ml-2 text-gray-500">WIP: {c.wip_current}/{c.wip_limit}</span>
                    {!c.is_available && <span className="ml-2 text-xs">(занят)</span>}
                  </button>
                </li>
              ))}
            </ul>
            {assignCandidates.length === 0 && <p className="py-4 text-center text-sm text-gray-500">Нет доступных кандидатов</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setAssignTask(null)}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Отмена
              </button>
              <button
                type="button"
                disabled={!selectedExecutorId || assignBusy}
                onClick={async () => {
                  if (!selectedExecutorId || !assignTask) return
                  setAssignBusy(true)
                  try {
                    await api.post('/api/queue/assign', { task_id: assignTask.id, executor_id: selectedExecutorId })
                    const name = assignCandidates.find((c) => c.id === selectedExecutorId)?.full_name ?? ''
                    toast.success(`Задача назначена на ${name}`)
                    setAssignTask(null)
                    loadQueue()
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Ошибка назначения')
                  } finally {
                    setAssignBusy(false)
                  }
                }}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark disabled:opacity-50 transition-colors"
              >
                {assignBusy ? '...' : 'Назначить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
