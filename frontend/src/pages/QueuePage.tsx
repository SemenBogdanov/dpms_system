import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Lock } from 'lucide-react'
import { api } from '@/api/client'
import type { AssignCandidate, QueueTaskResponse, Task, User, TaskStatus } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { PriorityBadge } from '@/components/PriorityBadge'
import { LeagueBadge } from '@/components/LeagueBadge'
import { QBadge } from '@/components/QBadge'
import { SkeletonTable } from '@/components/Skeleton'
import { ProactiveBlock } from '@/components/ProactiveBlock'
import { DeadlineBadge } from '@/components/DeadlineBadge'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import { BugfixModal } from '@/components/BugfixModal'

const complexityStyles: Record<string, string> = {
  S: 'bg-slate-100 text-slate-700',
  M: 'bg-blue-100 text-blue-800',
  L: 'bg-orange-100 text-orange-800',
  XL: 'bg-red-100 text-red-800',
}

export function QueuePage() {
  const navigate = useNavigate()
  const { user: currentUser } = useAuth()
  const [tasks, setTasks] = useState<QueueTaskResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pullingId, setPullingId] = useState<string | null>(null)
  const [confirmPull, setConfirmPull] = useState<QueueTaskResponse | Task | null>(null)
  const [myTasks, setMyTasks] = useState<Task[]>([])
  const [queueFilter, setQueueFilter] = useState<'default' | 'proactive'>('default')
  const [detailTask, setDetailTask] = useState<Task | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [allTasks, setAllTasks] = useState<Task[]>([])
  const [activeTag, setActiveTag] = useState<string | null>(null)
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

  const loadQueue = (category: 'default' | 'proactive') => {
    if (!currentUser) return
    setLoading(true)
    const params = category === 'proactive' ? { category: 'proactive' } : undefined
    api
      .get<QueueTaskResponse[]>('/api/queue', params)
      .then(setTasks)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!currentUser) return
    loadQueue(queueFilter)
  }, [currentUser, queueFilter])

  const handleShowProactive = () => {
    setQueueFilter('proactive')
  }
  const handleShowDefault = () => {
    setQueueFilter('default')
  }

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
    if (!includeArchived) return
    api.get<Task[]>('/api/tasks').then(setAllTasks).catch(() => setAllTasks([]))
  }, [includeArchived])

  type RowItem = (QueueTaskResponse & { status?: TaskStatus }) | Task
  const displayList: RowItem[] = includeArchived
    ? allTasks
    : tasks.map((t) => ({ ...t, status: 'in_queue' as TaskStatus }))

  const filteredBySearch = displayList.filter((t) => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toUpperCase()
      const matchTitle = t.title.toUpperCase().includes(q)
      const tags = (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []
      const matchTag = tags.some((tag: string) => tag.toUpperCase().includes(q))
      return matchTitle || matchTag
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
  const priorityLabels: Record<string, string> = { critical: '🔴 Критические', high: '🟠 Высокие', medium: '🟡 Средние', low: '🟢 Низкие' }
  const sortedTasks = [...filteredByTag].sort((a, b) => {
    const aBug = (a as QueueTaskResponse).task_type === 'bugfix' || (a as Task).task_type === 'bugfix'
    const bBug = (b as QueueTaskResponse).task_type === 'bugfix' || (b as Task).task_type === 'bugfix'
    if (aBug !== bBug) return aBug ? -1 : 1
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
        api.get<Task[]>('/api/tasks').then(setAllTasks).catch(() => setAllTasks([]))
      } else {
        setTasks((prev) => prev.filter((t) => t.id !== confirmPull.id))
      }
      navigate('/my-tasks')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось взять задачу')
      setConfirmPull(null)
      if (includeArchived) {
        api.get<Task[]>('/api/tasks').then(setAllTasks).catch(() => setAllTasks([]))
      } else {
        loadQueue(queueFilter)
      }
    } finally {
      setPullingId(null)
    }
  }

  const wipCount = myTasks.filter((t) => t.status === 'in_progress').length

  if (loading) return <SkeletonTable rows={8} />
  if (error) return <div className="text-red-600">{error}</div>

  const openDetail = (id: string) => {
    api.get<Task>(`/api/tasks/${id}`).then(setDetailTask).catch(() => toast.error('Не удалось загрузить задачу'))
  }

  const handleOpenBugfix = (task: Task) => {
    setDetailTask(null)
    setBugfixParent(task)
    setBugfixTitle(`Баг: ${task.title}`)
    setBugfixDescription('')
  }

  const handleCreateBugfix = async () => {
    if (!bugfixParent || !bugfixTitle.trim()) return
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
        api.get<Task[]>('/api/tasks').then(setAllTasks).catch(() => setAllTasks([]))
      } else {
        loadQueue(queueFilter)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось создать баг-фикс')
    } finally {
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
          api.get<Task[]>('/api/tasks').then(setAllTasks).catch(() => setAllTasks([]))
        } else {
          loadQueue(queueFilter)
        }
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  const taskStatus = (t: RowItem): TaskStatus => (t as Task).status ?? 'in_queue'
  const canPull = (t: RowItem) => (t as QueueTaskResponse).can_pull === true || (taskStatus(t) === 'in_queue' && (t as QueueTaskResponse).locked !== true)
  const locked = (t: RowItem) => (t as QueueTaskResponse).locked === true
  const lockReason = (t: RowItem) => (t as QueueTaskResponse).lock_reason
  const taskTags = (t: RowItem) => (t as QueueTaskResponse).tags ?? (t as Task).tags ?? []
  const taskType = (t: RowItem) => (t as QueueTaskResponse).task_type ?? (t as Task).task_type
  const isProactive = (t: RowItem) => (t as QueueTaskResponse).is_proactive === true || (t as Task).task_type === 'proactive'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">Глобальная очередь</h1>
          {isTeamleadOrAdmin && (
            <Link
              to="/calculator"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              ➕ Создать задачу
            </Link>
          )}
        </div>
        {currentUser && (
          <div className="text-sm text-slate-600 whitespace-nowrap">
            Лига {currentUser.league} · WIP: {wipCount} из {currentUser.wip_limit} ·{' '}
            {Number(currentUser.wallet_main).toFixed(1)}/{currentUser.mpw} Q
          </div>
        )}
      </div>

      {queueFilter === 'proactive' && !includeArchived && (
        <button
          type="button"
          onClick={handleShowDefault}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          ← Обычная очередь
        </button>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">🔍</span>
          <input
            type="text"
            placeholder="Поиск по названию или тегу..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-sm"
          />
        </div>
        <label className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-600">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="rounded border-slate-300"
          />
          Включая закрытые
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-slate-500">Проекты:</span>
        <button
          type="button"
          onClick={() => setActiveTag(null)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition ${
            activeTag === null ? 'bg-primary text-primary-foreground' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
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
              activeTag === tag ? 'bg-primary text-primary-foreground' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {tag}
          </button>
        ))}
      </div>
      {activeTag && (
        <div className="text-sm text-slate-600">
          Проект <span className="font-semibold">{activeTag}</span>: {filteredByTag.length} задач,{' '}
          <span className="whitespace-nowrap font-semibold">
            {Number(filteredByTag.reduce((sum, t) => sum + Number(t.estimated_q), 0)).toFixed(1)} Q
          </span>
        </div>
      )}

      {displayList.length === 0 && !loading ? (
        queueFilter === 'default' && !includeArchived ? (
          <div className="space-y-2">
            <ProactiveBlock onShowProactive={handleShowProactive} loading={loading} />
            <p className="text-center text-sm text-slate-500">
              Очередь задач пуста. Создайте задачу через калькулятор.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-500">
            {includeArchived ? 'Нет задач' : 'Нет проактивных задач в очереди'}
          </div>
        )
      ) : sortedTasks.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-500">
          {searchQuery.trim()
            ? `По запросу «${searchQuery}» задач не найдено`
            : activeTag
              ? `Нет задач по проекту ${activeTag}`
              : 'Нет задач'}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="cursor-pointer select-none px-4 py-3 text-left text-xs font-medium text-slate-600" onClick={() => handleSort('title')}>
                  Название {sortField === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th className="cursor-pointer select-none px-4 py-3 text-left text-xs font-medium text-slate-600" onClick={() => handleSort('status')}>
                  Статус {sortField === 'status' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Тип</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Сложность</th>
                <th className="cursor-pointer select-none px-4 py-3 text-left text-xs font-medium text-slate-600 min-w-[60px]" onClick={() => handleSort('estimated_q')}>
                  Q {sortField === 'estimated_q' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th className="cursor-pointer select-none px-4 py-3 text-left text-xs font-medium text-slate-600" onClick={() => handleSort('due_date')}>
                  Срок {sortField === 'due_date' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th className="cursor-pointer select-none px-4 py-3 text-left text-xs font-medium text-slate-600" onClick={() => handleSort('priority')}>
                  Приоритет {sortField === 'priority' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Мин. лига</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Дата</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-600">Действие</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {(() => {
                let lastPriority: string | null = null
                const rows: Array<{ type: 'section'; priority: string } | { type: 'task'; task: RowItem }> = []
                sortedTasks.forEach((t) => {
                  const p = (t as QueueTaskResponse).priority ?? (t as Task).priority ?? 'medium'
                  if (p !== lastPriority) {
                    rows.push({ type: 'section', priority: p })
                    lastPriority = p
                  }
                  rows.push({ type: 'task', task: t })
                })
                return rows.map((row, idx) =>
                  row.type === 'section' ? (
                    <tr key={`section-${row.priority}-${idx}`} className="bg-slate-100">
                      <td colSpan={10} className="px-4 py-1.5 text-xs font-medium text-slate-600">
                        ─── {priorityLabels[row.priority] ?? row.priority} ───
                      </td>
                    </tr>
                  ) : (
                    <tr
                      key={(row.task as Task).id}
                      className={`${locked(row.task) ? 'bg-slate-50 opacity-75' : ''} ${taskType(row.task) === 'bugfix' ? 'border-l-4 border-red-400 bg-red-50/50' : ''}`}
                    >
                      <td className="px-4 py-3 text-sm text-slate-900">
                    <button
                      type="button"
                      onClick={() => openDetail(row.task.id)}
                      className="cursor-pointer text-left text-primary hover:underline"
                    >
                      {row.task.title}
                    </button>
                    {taskType(row.task) === 'bugfix' && (
                      <span className="ml-2 inline rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                        🐛 Гарантийный
                      </span>
                    )}
                    {isProactive(row.task) && (
                      <span className="ml-2 inline rounded bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800">
                        🔄 Проактивная
                      </span>
                    )}
                    {taskTags(row.task).length > 0 && (
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {taskTags(row.task).map((tag) => (
                          <span key={tag} className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                    {(row.task as Task).rejection_count > 0 && (
                      <span className="ml-2 inline rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                        🔄 {(row.task as Task).rejection_count}
                      </span>
                    )}
                    {(row.task as QueueTaskResponse).is_stale && (
                      <span className="ml-2 inline rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                        🔥 Застряла {Math.round((row.task as QueueTaskResponse).hours_in_queue ?? 0)}ч
                      </span>
                    )}
                    {!(row.task as QueueTaskResponse).is_stale && ((row.task as QueueTaskResponse).hours_in_queue ?? 0) > 24 && (
                      <span className="ml-2 inline rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                        ⏳ {Math.round((row.task as QueueTaskResponse).hours_in_queue ?? 0)}ч в очереди
                      </span>
                    )}
                    {(row.task as QueueTaskResponse).recommended && (
                      <span className="ml-2 inline rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                        ⚡ Рекомендуем
                      </span>
                    )}
                    {(row.task as QueueTaskResponse).assigned_by_name && (
                      <span className="ml-2 text-xs text-slate-500">
                        Назначил: {(row.task as QueueTaskResponse).assigned_by_name}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {taskStatus(row.task) === 'in_queue' && 'В очереди'}
                    {taskStatus(row.task) === 'in_progress' && 'В работе'}
                    {taskStatus(row.task) === 'review' && 'На проверке'}
                    {taskStatus(row.task) === 'done' && 'Готово'}
                    {taskStatus(row.task) === 'cancelled' && 'Отменена'}
                    {taskStatus(row.task) === 'new' && 'Новая'}
                    {taskStatus(row.task) === 'estimated' && 'Оценена'}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">{taskType(row.task)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${complexityStyles[(row.task as QueueTaskResponse).complexity ?? (row.task as Task).complexity] ?? 'bg-slate-100'}`}>
                      {(row.task as QueueTaskResponse).complexity ?? (row.task as Task).complexity}
                    </span>
                  </td>
                  <td className="px-4 py-3 min-w-[60px]">
                    <span className="whitespace-nowrap"><QBadge q={row.task.estimated_q} /></span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col items-start gap-0.5">
                      <DeadlineBadge
                        dueDate={(row.task as QueueTaskResponse).due_date ?? (row.task as Task).due_date}
                        zone={(row.task as QueueTaskResponse).deadline_zone ?? (row.task as Task).deadline_zone}
                      />
                      {((row.task as QueueTaskResponse).due_date ?? (row.task as Task).due_date) && (
                        <span className="whitespace-nowrap text-xs text-slate-500">
                          {new Date(((row.task as QueueTaskResponse).due_date ?? (row.task as Task).due_date)!).toLocaleDateString('ru', {
                            day: 'numeric',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <PriorityBadge priority={((row.task as QueueTaskResponse).priority ?? (row.task as Task).priority) as 'low' | 'medium' | 'high' | 'critical'} />
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <LeagueBadge league={(row.task as QueueTaskResponse).min_league ?? (row.task as Task).min_league} />
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {new Date((row.task as QueueTaskResponse).created_at ?? (row.task as Task).created_at).toLocaleDateString('ru')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                      {isTeamleadOrAdmin && taskStatus(row.task) !== 'done' && taskStatus(row.task) !== 'cancelled' && (
                        <button
                          type="button"
                          onClick={() => handleDelete(row.task)}
                          className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
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
                          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                        >
                          Назначить
                        </button>
                      )}
                      {locked(row.task) ? (
                        <span className="inline-flex items-center gap-1 text-sm text-slate-500">
                          <Lock className="h-4 w-4" />
                          <span className="hidden sm:inline">{lockReason(row.task) ?? `Лига ${(row.task as QueueTaskResponse).min_league}`}</span>
                        </span>
                      ) : canPull(row.task) ? (
                        <button
                          type="button"
                          onClick={() => setConfirmPull(row.task)}
                          disabled={!!pullingId}
                          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                        >
                          Взять
                        </button>
                      ) : taskStatus(row.task) === 'in_queue' ? (
                        <span title={lockReason(row.task) ?? 'WIP-лимит исчерпан'} className="cursor-help text-sm text-slate-400">
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
      )}

      <TaskDetailModal
        task={detailTask}
        onClose={() => setDetailTask(null)}
        users={users}
        isTeamleadOrAdmin={isTeamleadOrAdmin}
        onOpenBugfix={handleOpenBugfix}
        onOpenDeadline={(task) => {
          setDetailTask(null)
          const hours = prompt('Срок выполнения (часов от сейчас):')
          if (!hours || Number.isNaN(Number(hours))) return
          const dueDate = new Date(Date.now() + Number(hours) * 3600000).toISOString()
          api
            .patch(`/api/tasks/${task.id}/due-date`, { due_date: dueDate })
            .then(() => {
              toast.success('Дедлайн установлен')
              openDetail(task.id)
            })
            .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
        }}
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

      {confirmPull && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setConfirmPull(null)}
        >
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg">
            <p className="text-slate-800">
              Взять задачу «{confirmPull.title}» за {confirmPull.estimated_q} Q?
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmPull(null)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={doPull}
                disabled={!!pullingId}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
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
            <h3 className="text-lg font-semibold text-slate-900">Назначить задачу</h3>
            <p className="mt-1 text-sm text-slate-600">«{assignTask.title}»</p>
            <p className="mt-3 text-sm font-medium text-slate-700">Выберите исполнителя:</p>
            <ul className="mt-2 max-h-60 overflow-y-auto rounded border border-slate-200">
              {assignCandidates.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    disabled={!c.is_available}
                    onClick={() => c.is_available && setSelectedExecutorId(c.id)}
                    className={`w-full px-4 py-2 text-left text-sm ${c.is_available ? 'hover:bg-slate-50' : 'cursor-not-allowed bg-slate-50 text-slate-400'}`}
                  >
                    <span className="font-medium">{c.full_name}</span>
                    <span className="ml-2 text-slate-500">Лига {c.league}</span>
                    <span className="ml-2 text-slate-500">WIP: {c.wip_current}/{c.wip_limit}</span>
                    {!c.is_available && <span className="ml-2 text-xs">(занят)</span>}
                  </button>
                </li>
              ))}
            </ul>
            {assignCandidates.length === 0 && <p className="py-4 text-center text-sm text-slate-500">Нет доступных кандидатов</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setAssignTask(null)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
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
                    loadQueue(queueFilter)
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : 'Ошибка назначения')
                  } finally {
                    setAssignBusy(false)
                  }
                }}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
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
