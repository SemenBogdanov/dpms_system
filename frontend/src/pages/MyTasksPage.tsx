import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { Task, User } from '@/api/types'
import { TaskCard } from '@/components/TaskCard'

const FALLBACK_USER_ID = ''

export function MyTasksPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState(FALLBACK_USER_ID)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const list = await api.get<User[]>('/api/users')
        if (!cancelled) {
          setUsers(list)
          if (list.length && !currentUserId) setCurrentUserId(list[0].id)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!currentUserId) return
    let cancelled = false
    async function loadTasks() {
      try {
        const list = await api.get<Task[]>(`/api/tasks?assignee_id=${currentUserId}`)
        if (!cancelled) setTasks(list)
      } catch {
        if (!cancelled) setTasks([])
      }
    }
    loadTasks()
    return () => { cancelled = true }
  }, [currentUserId])

  const refreshTasks = () => {
    if (!currentUserId) return
    api.get<Task[]>(`/api/tasks?assignee_id=${currentUserId}`).then(setTasks)
  }

  const handleSubmitReview = async (taskId: string) => {
    if (!currentUserId) return
    setBusyTaskId(taskId)
    try {
      await api.post('/api/queue/submit', { user_id: currentUserId, task_id: taskId })
      refreshTasks()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Не удалось сдать на проверку')
    } finally {
      setBusyTaskId(null)
    }
  }

  const handleValidate = async (taskId: string, approved: boolean) => {
    if (!currentUserId) return
    setBusyTaskId(taskId)
    try {
      await api.post('/api/queue/validate', {
        validator_id: currentUserId,
        task_id: taskId,
        approved,
      })
      refreshTasks()
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setBusyTaskId(null)
    }
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  const inProgress = tasks.filter((t) => t.status === 'in_progress')
  const review = tasks.filter((t) => t.status === 'review')
  const done = tasks.filter((t) => t.status === 'done')

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Мои задачи</h1>
        {users.length > 0 && (
          <select
            value={currentUserId}
            onChange={(e) => setCurrentUserId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="grid gap-6 md:grid-cols-3">
        <section>
          <h2 className="mb-2 font-medium text-slate-700">В работе</h2>
          <div className="space-y-2">
            {inProgress.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                showActions
                onSubmitReview={handleSubmitReview}
                busyTaskId={busyTaskId}
              />
            ))}
            {inProgress.length === 0 && (
              <p className="text-sm text-slate-400">Нет задач в работе</p>
            )}
          </div>
        </section>
        <section>
          <h2 className="mb-2 font-medium text-slate-700">На проверке</h2>
          <div className="space-y-2">
            {review.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                showActions
                onValidate={handleValidate}
                busyTaskId={busyTaskId}
              />
            ))}
            {review.length === 0 && (
              <p className="text-sm text-slate-400">Нет задач на проверке</p>
            )}
          </div>
        </section>
        <section>
          <h2 className="mb-2 font-medium text-slate-700">Готово</h2>
          <div className="space-y-2">
            {done.map((t) => (
              <TaskCard key={t.id} task={t} />
            ))}
            {done.length === 0 && (
              <p className="text-sm text-slate-400">Нет завершённых задач</p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
