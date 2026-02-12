import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { Task, User } from '@/api/types'
import { TaskCard } from '@/components/TaskCard'

/** MVP: выбираем первого пользователя как текущего (без авторизации). */
const FALLBACK_USER_ID = ''

export function QueuePage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState(FALLBACK_USER_ID)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pulling, setPulling] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadUsers() {
      try {
        const list = await api.get<User[]>('/api/users')
        if (!cancelled) {
          setUsers(list)
          if (list.length && !currentUserId) setCurrentUserId(list[0].id)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadUsers()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!currentUserId) return
    let cancelled = false
    async function loadQueue() {
      try {
        const list = await api.get<Task[]>(`/api/queue?user_id=${currentUserId}`)
        if (!cancelled) setTasks(list)
      } catch {
        if (!cancelled) setTasks([])
      }
    }
    loadQueue()
    return () => { cancelled = true }
  }, [currentUserId])

  const handlePull = async (taskId: string) => {
    if (!currentUserId) return
    setPulling(taskId)
    try {
      await api.post('/api/queue/pull', { user_id: currentUserId, task_id: taskId })
      setTasks((prev) => prev.filter((t) => t.id !== taskId))
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Не удалось взять задачу')
    } finally {
      setPulling(null)
    }
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Глобальная очередь</h1>
        {users.length > 0 && (
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} (Лига {u.league})
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onPull={handlePull}
            showActions
            pullingTaskId={pulling}
          />
        ))}
      </div>
      {tasks.length === 0 && (
        <p className="text-slate-500">Нет доступных задач в очереди для выбранного пользователя.</p>
      )}
    </div>
  )
}
