import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Lock } from 'lucide-react'
import { api } from '@/api/client'
import type { QueueTaskResponse, Task, User } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { PriorityBadge } from '@/components/PriorityBadge'
import { LeagueBadge } from '@/components/LeagueBadge'
import { QBadge } from '@/components/QBadge'
import { SkeletonTable } from '@/components/Skeleton'
import { ProactiveBlock } from '@/components/ProactiveBlock'
import { DeadlineBadge } from '@/components/DeadlineBadge'
import { TaskDetailModal } from '@/components/TaskDetailModal'

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
  const [confirmPull, setConfirmPull] = useState<QueueTaskResponse | null>(null)
  const [myTasks, setMyTasks] = useState<Task[]>([])
  const [queueFilter, setQueueFilter] = useState<'default' | 'proactive'>('default')
  const [detailTask, setDetailTask] = useState<Task | null>(null)
  const [users, setUsers] = useState<User[]>([])

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

  const doPull = async () => {
    if (!confirmPull || !currentUser) return
    setPullingId(confirmPull.id)
    try {
      await api.post('/api/queue/pull', {
        task_id: confirmPull.id,
      })
      toast.success('Задача взята!')
      setConfirmPull(null)
      setTasks((prev) => prev.filter((t) => t.id !== confirmPull.id))
      navigate('/my-tasks')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось взять задачу')
      setConfirmPull(null)
      loadQueue(queueFilter)
    } finally {
      setPullingId(null)
    }
  }

  const wipCount = myTasks.filter((t) => t.status === 'in_progress').length

  if (loading) return <SkeletonTable rows={8} />
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Глобальная очередь</h1>
        {currentUser && (
          <div className="text-sm text-slate-600">
            Лига {currentUser.league} · WIP: {wipCount} из {currentUser.wip_limit} ·{' '}
            {Number(currentUser.wallet_main).toFixed(1)}/{currentUser.mpw} Q
          </div>
        )}
      </div>

      {queueFilter === 'proactive' && (
        <button
          type="button"
          onClick={handleShowDefault}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          ← Обычная очередь
        </button>
      )}

      {tasks.length === 0 && !loading ? (
        queueFilter === 'default' ? (
          <ProactiveBlock onShowProactive={handleShowProactive} loading={loading} />
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-500">
            Нет проактивных задач в очереди
          </div>
        )
      ) : tasks.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Название
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Тип</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Сложность
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Q</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Срок</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Приоритет
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Мин. лига
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">
                  Дата
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-slate-600">
                  Действие
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {[...tasks]
                .slice()
                .sort((a, b) => {
                  const aBug = a.task_type === 'bugfix'
                  const bBug = b.task_type === 'bugfix'
                  if (aBug !== bBug) return aBug ? -1 : 1
                  if (a.priority === b.priority) {
                    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
                  }
                  const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
                  return (order[a.priority] ?? 99) - (order[b.priority] ?? 99)
                })
                .map((t) => (
                <tr
                  key={t.id}
                  className={t.locked ? 'bg-slate-50 opacity-75' : ''}
                >
                  <td className="px-4 py-3 text-sm text-slate-900">
                    <button
                      type="button"
                      onClick={() => {
                        api.get<Task>(`/api/tasks/${t.id}`).then(setDetailTask).catch(() => toast.error('Не удалось загрузить задачу'))
                      }}
                      className="cursor-pointer text-left text-primary hover:underline"
                    >
                      {t.title}
                    </button>
                    {t.task_type === 'bugfix' && (
                      <span className="ml-2 inline rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
                        🐛 Гарантийный
                      </span>
                    )}
                    {t.is_proactive && (
                      <span className="ml-2 inline rounded bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800">
                        🔄 Проактивная
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">{t.task_type}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${
                        complexityStyles[t.complexity] ?? 'bg-slate-100'
                      }`}
                    >
                      {t.complexity}
                    </span>
                  </td>
                  <td className="px-4 py-3 min-w-[60px]">
                    <span className="whitespace-nowrap"><QBadge q={t.estimated_q} /></span>
                  </td>
                  <td className="px-4 py-3">
                    <DeadlineBadge dueDate={t.due_date} zone={t.deadline_zone} />
                  </td>
                  <td className="px-4 py-3">
                    <PriorityBadge priority={t.priority as 'low' | 'medium' | 'high' | 'critical'} />
                  </td>
                  <td className="px-4 py-3">
                    <LeagueBadge league={t.min_league} />
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500">
                    {new Date(t.created_at).toLocaleDateString('ru')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {t.locked ? (
                      <span className="inline-flex items-center gap-1 text-sm text-slate-500">
                        <Lock className="h-4 w-4" />
                        {t.lock_reason ?? `Лига ${t.min_league}`}
                      </span>
                    ) : t.can_pull ? (
                      <button
                        type="button"
                        onClick={() => setConfirmPull(t)}
                        disabled={!!pullingId}
                        className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                      >
                        Взять
                      </button>
                    ) : (
                      <span
                        title={t.lock_reason ?? 'WIP-лимит исчерпан'}
                        className="cursor-help text-sm text-slate-400"
                      >
                        WIP-лимит
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <TaskDetailModal
        task={detailTask}
        onClose={() => setDetailTask(null)}
        users={users}
      />

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
    </div>
  )
}
