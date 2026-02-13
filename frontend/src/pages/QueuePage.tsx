import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Lock } from 'lucide-react'
import { api } from '@/api/client'
import type { QueueTaskResponse, User, Task } from '@/api/types'
import { PriorityBadge } from '@/components/PriorityBadge'
import { LeagueBadge } from '@/components/LeagueBadge'
import { QBadge } from '@/components/QBadge'

const FALLBACK_USER_ID = ''

const complexityStyles: Record<string, string> = {
  S: 'bg-slate-100 text-slate-700',
  M: 'bg-blue-100 text-blue-800',
  L: 'bg-orange-100 text-orange-800',
  XL: 'bg-red-100 text-red-800',
}

export function QueuePage() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState<QueueTaskResponse[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState(FALLBACK_USER_ID)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pullingId, setPullingId] = useState<string | null>(null)
  const [confirmPull, setConfirmPull] = useState<QueueTaskResponse | null>(null)
  const [myTasks, setMyTasks] = useState<Task[]>([])

  useEffect(() => {
    let cancelled = false
    api
      .get<User[]>('/api/users')
      .then((list) => {
        if (!cancelled) {
          setUsers(list)
          if (list.length && !currentUserId) setCurrentUserId(list[0].id)
        }
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!currentUserId) return
    let cancelled = false
    api
      .get<QueueTaskResponse[]>(`/api/queue?user_id=${currentUserId}`)
      .then((list) => !cancelled && setTasks(list))
      .catch(() => !cancelled && setTasks([]))
    return () => { cancelled = true }
  }, [currentUserId])

  useEffect(() => {
    if (!currentUserId) return
    api
      .get<Task[]>(`/api/tasks?assignee_id=${currentUserId}`)
      .then(setMyTasks)
      .catch(() => setMyTasks([]))
  }, [currentUserId])

  const doPull = async () => {
    if (!confirmPull || !currentUserId) return
    setPullingId(confirmPull.id)
    try {
      await api.post('/api/queue/pull', {
        user_id: currentUserId,
        task_id: confirmPull.id,
      })
      toast.success('Задача взята!')
      setConfirmPull(null)
      setTasks((prev) => prev.filter((t) => t.id !== confirmPull.id))
      navigate('/my-tasks')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось взять задачу')
      setConfirmPull(null)
      api.get<QueueTaskResponse[]>(`/api/queue?user_id=${currentUserId}`).then(setTasks)
    } finally {
      setPullingId(null)
    }
  }

  const currentUser = users.find((u) => u.id === currentUserId)
  const wipCount = myTasks.filter((t) => t.status === 'in_progress').length

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Глобальная очередь</h1>
        <div className="flex items-center gap-4">
          {currentUser && (
            <div className="text-sm text-slate-600">
              Лига {currentUser.league} · WIP: {wipCount} из {currentUser.wip_limit} ·{' '}
              {currentUser.wallet_main}/{currentUser.mpw} Q
            </div>
          )}
          {users.length > 0 && (
            <select
              value={currentUserId}
              onChange={(e) => setCurrentUserId(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              <option value="">— Выберите —</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} (Лига {u.league})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-500">
          Все задачи разобраны 🎉
        </div>
      ) : (
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
              {tasks.map((t) => (
                <tr
                  key={t.id}
                  className={t.locked ? 'bg-slate-50 opacity-75' : ''}
                >
                  <td className="px-4 py-3 text-sm text-slate-900">{t.title}</td>
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
                  <td className="px-4 py-3">
                    <QBadge q={t.estimated_q} />
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
    </div>
  )
}
