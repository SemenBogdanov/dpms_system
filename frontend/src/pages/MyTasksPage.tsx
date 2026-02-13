import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { Task, User } from '@/api/types'
import { TaskCard } from '@/components/TaskCard'
import toast from 'react-hot-toast'

const FALLBACK_USER_ID = ''

export function MyTasksPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [reviewTasks, setReviewTasks] = useState<Task[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [currentUserId, setCurrentUserId] = useState(FALLBACK_USER_ID)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)

  // Модалка «Сдать на проверку»
  const [submitTaskId, setSubmitTaskId] = useState<string | null>(null)
  const [submitResultUrl, setSubmitResultUrl] = useState('')
  const [submitComment, setSubmitComment] = useState('')

  // Модалка «Вернуть» (причина обязательна)
  const [rejectTask, setRejectTask] = useState<Task | null>(null)
  const [rejectComment, setRejectComment] = useState('')

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

  const loadReviewTasks = useCallback(async () => {
    try {
      const list = await api.get<Task[]>('/api/tasks?status=review')
      setReviewTasks(list)
    } catch {
      setReviewTasks([])
    }
  }, [])

  useEffect(() => {
    loadReviewTasks()
  }, [loadReviewTasks])

  const refreshTasks = useCallback(() => {
    if (!currentUserId) return
    api.get<Task[]>(`/api/tasks?assignee_id=${currentUserId}`).then(setTasks)
    loadReviewTasks()
    api.get<User[]>('/api/users').then(setUsers)
  }, [currentUserId, loadReviewTasks])

  const handleSubmitReview = (taskId: string) => {
    setSubmitTaskId(taskId)
    setSubmitResultUrl('')
    setSubmitComment('')
  }

  const handleSubmitModalOk = async () => {
    if (!currentUserId || !submitTaskId) return
    setBusyTaskId(submitTaskId)
    try {
      await api.post('/api/queue/submit', {
        user_id: currentUserId,
        task_id: submitTaskId,
        result_url: submitResultUrl || undefined,
        comment: submitComment || undefined,
      })
      toast.success('Отправлено на проверку')
      setSubmitTaskId(null)
      refreshTasks()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось сдать на проверку')
    } finally {
      setBusyTaskId(null)
    }
  }

  const handleValidate = async (taskId: string, approved: boolean, comment?: string) => {
    if (!currentUserId) return
    setBusyTaskId(taskId)
    try {
      await api.post('/api/queue/validate', {
        validator_id: currentUserId,
        task_id: taskId,
        approved,
        comment: comment || undefined,
      })
      toast.success(approved ? 'Задача принята' : 'Задача возвращена')
      setRejectTask(null)
      setRejectComment('')
      refreshTasks()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setBusyTaskId(null)
    }
  }

  const handleRejectClick = (task: Task) => {
    setRejectTask(task)
    setRejectComment('')
  }

  const handleRejectModalOk = () => {
    if (!rejectTask) return
    if (!rejectComment.trim()) {
      toast.error('Укажите причину возврата')
      return
    }
    handleValidate(rejectTask.id, false, rejectComment.trim())
  }

  const currentUser = users.find((u) => u.id === currentUserId)
  const isTeamleadOrAdmin =
    currentUser?.role === 'teamlead' || currentUser?.role === 'admin'
  const validatorNames: Record<string, string> = {}
  users.forEach((u) => {
    validatorNames[u.id] = u.full_name
  })

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  const inProgress = tasks.filter((t) => t.status === 'in_progress')
  const review = tasks.filter((t) => t.status === 'review')
  const done = tasks.filter((t) => t.status === 'done')

  const progressPercent = currentUser
    ? (currentUser.mpw > 0 ? (currentUser.wallet_main / currentUser.mpw) * 100 : 0)
    : 0
  const progressColor =
    progressPercent < 50 ? 'bg-red-500' : progressPercent < 80 ? 'bg-yellow-500' : 'bg-emerald-500'

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

      {currentUser && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-slate-600">Кошелёк / MPW</span>
            <span className="font-medium text-slate-900">
              {currentUser.wallet_main} / {currentUser.mpw} Q
            </span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full transition-all ${progressColor}`}
              style={{ width: `${Math.min(100, progressPercent)}%` }}
            />
          </div>
          {currentUser.wallet_karma > 0 && (
            <p className="mt-2 text-sm text-slate-600">
              ⭐ Karma: {currentUser.wallet_karma} Q
            </p>
          )}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-3">
        <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
          <h2 className="mb-3 font-medium text-slate-700">В работе</h2>
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
        <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
          <h2 className="mb-3 font-medium text-slate-700">На проверке</h2>
          <div className="space-y-2">
            {review.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                currentUserId={currentUserId}
                validatorName={validatorNames[t.validator_id ?? '']}
              />
            ))}
            {review.length === 0 && (
              <p className="text-sm text-slate-400">Нет задач на проверке</p>
            )}
          </div>
        </section>
        <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
          <h2 className="mb-3 font-medium text-slate-700">Завершено</h2>
          <div className="space-y-2">
            {done.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                validatorName={validatorNames[t.validator_id ?? '']}
              />
            ))}
            {done.length === 0 && (
              <p className="text-sm text-slate-400">Нет завершённых задач</p>
            )}
          </div>
        </section>
      </div>

      {isTeamleadOrAdmin && reviewTasks.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
          <h2 className="mb-3 font-medium text-amber-800">На валидацию</h2>
          <div className="space-y-2">
            {reviewTasks.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                showActions
                onValidate={handleValidate}
                onRejectClick={handleRejectClick}
                busyTaskId={busyTaskId}
                currentUserId={currentUserId}
                validatorName={validatorNames[t.validator_id ?? '']}
              />
            ))}
          </div>
        </section>
      )}

      {/* Модалка: Сдать на проверку */}
      {submitTaskId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setSubmitTaskId(null)}
        >
          <div
            className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-slate-900">Сдать на проверку</h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Ссылка на результат
                </label>
                <input
                  type="text"
                  value={submitResultUrl}
                  onChange={(e) => setSubmitResultUrl(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="Необязательно"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Комментарий
                </label>
                <textarea
                  value={submitComment}
                  onChange={(e) => setSubmitComment(e.target.value)}
                  rows={2}
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="Необязательно"
                />
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSubmitTaskId(null)}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleSubmitModalOk}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                Сдать
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Модалка: Вернуть (причина обязательна) */}
      {rejectTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setRejectTask(null)}
        >
          <div
            className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-slate-900">Вернуть задачу</h3>
            <p className="mt-1 text-sm text-slate-500">{rejectTask.title}</p>
            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-700">
                Причина возврата <span className="text-red-600">*</span>
              </label>
              <textarea
                value={rejectComment}
                onChange={(e) => setRejectComment(e.target.value)}
                rows={3}
                required
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                placeholder="Обязательно укажите причину"
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRejectTask(null)}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleRejectModalOk}
                disabled={!rejectComment.trim()}
                className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Вернуть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
