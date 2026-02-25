import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import type { Task, User } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { TaskCard } from '@/components/TaskCard'
import { TaskDetailModal } from '@/components/TaskDetailModal'
import toast from 'react-hot-toast'
import { BugfixModal } from '@/components/BugfixModal'

export function MyTasksPage() {
  const { user: currentUser } = useAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [reviewTasks, setReviewTasks] = useState<Task[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error] = useState<string | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)

  const [submitTaskId, setSubmitTaskId] = useState<string | null>(null)
  const [submitResultUrl, setSubmitResultUrl] = useState('')
  const [submitComment, setSubmitComment] = useState('')

  const [rejectTask, setRejectTask] = useState<Task | null>(null)
  const [rejectComment, setRejectComment] = useState('')

  const [bugfixParent, setBugfixParent] = useState<Task | null>(null)
  const [bugfixTitle, setBugfixTitle] = useState('')
  const [bugfixDescription, setBugfixDescription] = useState('')
  const [bugfixBusy, setBugfixBusy] = useState(false)

  const [deadlineTask, setDeadlineTask] = useState<Task | null>(null)
  const [deadlineValue, setDeadlineValue] = useState('')
  const [deadlineBusy, setDeadlineBusy] = useState(false)
  const [detailTask, setDetailTask] = useState<Task | null>(null)

  const [focusBusyId, setFocusBusyId] = useState<string | null>(null)

  useEffect(() => {
    api.get<User[]>('/api/users').then(setUsers).catch(() => setUsers([])).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!currentUser) return
    let cancelled = false
    api.get<Task[]>(`/api/tasks?assignee_id=${currentUser.id}`).then((list) => !cancelled && setTasks(list)).catch(() => !cancelled && setTasks([]))
    return () => { cancelled = true }
  }, [currentUser])

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
    if (!currentUser) return
    api.get<Task[]>(`/api/tasks?assignee_id=${currentUser.id}`).then(setTasks)
    loadReviewTasks()
    api.get<User[]>('/api/users').then(setUsers)
  }, [currentUser, loadReviewTasks])

  const formatDuration = (totalSeconds: number): string => {
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    if (hours > 0) {
      return `${hours}ч ${minutes}мин`
    }
    return `${minutes}мин`
  }

  const [now, setNow] = useState<number>(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const tasksWithComputedTime = useMemo(() => {
    return tasks.map((t) => {
      let elapsedSeconds = t.active_seconds ?? 0
      if (t.is_focused && t.focus_started_at) {
        const started = new Date(t.focus_started_at).getTime()
        elapsedSeconds += Math.max(0, Math.floor((now - started) / 1000))
      }
      return { ...t, _elapsedSeconds: elapsedSeconds }
    })
  }, [tasks, now])

  const handleSubmitReview = (taskId: string) => {
    setSubmitTaskId(taskId)
    setSubmitResultUrl('')
    setSubmitComment('')
  }

  const handleSubmitModalOk = async () => {
    if (!currentUser || !submitTaskId) return
    setBusyTaskId(submitTaskId)
    try {
      await api.post('/api/queue/submit', {
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
    if (!currentUser) return
    setBusyTaskId(taskId)
    try {
      await api.post('/api/queue/validate', {
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

  const handleOpenBugfix = (task: Task) => {
    setBugfixParent(task)
    setBugfixTitle(`Баг: ${task.title}`)
    setBugfixDescription('')
  }

  const handleOpenDeadline = (task: Task) => {
    setDeadlineTask(task)
    if (task.due_date) {
      const d = new Date(task.due_date)
      const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      setDeadlineValue(local.toISOString().slice(0, 16))
    } else {
      setDeadlineValue('')
    }
  }

  const handleSaveDeadline = async () => {
    if (!deadlineTask || !deadlineValue) {
      setDeadlineTask(null)
      setDeadlineValue('')
      return
    }
    setDeadlineBusy(true)
    try {
      const local = new Date(deadlineValue)
      const iso = local.toISOString()
      await api.patch(`/api/tasks/${deadlineTask.id}/due-date`, {
        due_date: iso,
      })
      toast.success('Дедлайн установлен')
      setDeadlineTask(null)
      setDeadlineValue('')
      refreshTasks()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось установить дедлайн')
    } finally {
      setDeadlineBusy(false)
    }
  }

  const handleCreateBugfix = async () => {
    if (!currentUser || !bugfixParent || !bugfixTitle.trim()) return
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
      refreshTasks()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Не удалось создать баг-фикс')
    } finally {
      setBugfixBusy(false)
    }
  }

  const isTeamleadOrAdmin =
    currentUser?.role === 'teamlead' || currentUser?.role === 'admin'
  const validatorNames: Record<string, string> = {}
  users.forEach((u) => {
    validatorNames[u.id] = u.full_name
  })

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  const inProgress = tasksWithComputedTime.filter((t) => t.status === 'in_progress')
  const review = tasksWithComputedTime.filter((t) => t.status === 'review')
  const done = tasksWithComputedTime.filter((t) => t.status === 'done')

  const progressPercent = currentUser
    ? (currentUser.mpw > 0 ? (Number(currentUser.wallet_main) / currentUser.mpw) * 100 : 0)
    : 0
  const progressColor =
    progressPercent < 50 ? 'bg-red-500' : progressPercent < 80 ? 'bg-yellow-500' : 'bg-emerald-500'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Мои задачи</h1>
      </div>

      {currentUser && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-slate-600">Кошелёк / MPW</span>
            <span className="whitespace-nowrap font-medium text-slate-900">
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
              <span className="whitespace-nowrap">⭐ Karma: {currentUser.wallet_karma} Q</span>
            </p>
          )}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-3">
        <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
          <h2 className="mb-3 font-medium text-slate-700">В работе</h2>
          <div className="space-y-2">
            {inProgress.map((t) => {
              const elapsedLabel = formatDuration((t as any)._elapsedSeconds ?? 0)
              const isFocused = t.is_focused
              const hasActive = !t.is_focused && (t.active_seconds ?? 0) > 0
              const isNewAssigned = !t.is_focused && (t.active_seconds ?? 0) === 0

              return (
                <div key={t.id} className="space-y-1 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="mb-1 flex items-center justify-between text-xs font-medium">
                    {isFocused && (
                      <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-700">
                        🟢 В ФОКУСЕ&nbsp;
                        <span className="font-semibold">⏱ {elapsedLabel}</span>
                      </span>
                    )}
                    {!isFocused && hasActive && (
                      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-slate-700">
                        ⏸ НА ПАУЗЕ&nbsp;
                        <span className="font-semibold">⏱ {elapsedLabel} накоплено</span>
                      </span>
                    )}
                    {!isFocused && isNewAssigned && (
                      <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">
                        🆕 НАЗНАЧЕНА (ожидает фокуса)
                      </span>
                    )}
                  </div>

                  <TaskCard
                    task={t}
                    showActions
                    onSubmitReview={handleSubmitReview}
                    busyTaskId={busyTaskId}
                  />

                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {isFocused ? (
                      <button
                        type="button"
                        disabled={focusBusyId === t.id}
                        onClick={async () => {
                          setFocusBusyId(t.id)
                          try {
                            await api.post(`/api/tasks/${t.id}/pause`, {})
                            refreshTasks()
                          } finally {
                            setFocusBusyId(null)
                          }
                        }}
                        className="inline-flex items-center rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200"
                      >
                        ⏸ Пауза
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={focusBusyId === t.id}
                        onClick={async () => {
                          setFocusBusyId(t.id)
                          try {
                            await api.post(`/api/tasks/${t.id}/focus`, {})
                            refreshTasks()
                          } finally {
                            setFocusBusyId(null)
                          }
                        }}
                        className="inline-flex items-center rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700"
                      >
                        ▶ {isNewAssigned ? 'Начать работу' : 'В фокус'}
                      </button>
                    )}

                    {isTeamleadOrAdmin && (
                      <button
                        type="button"
                        onClick={() => handleOpenDeadline(t)}
                        className="text-xs text-slate-500 hover:text-slate-800"
                      >
                        📅 Дедлайн
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
            {inProgress.length === 0 && (
              <p className="text-sm text-slate-400">Нет задач в работе</p>
            )}
          </div>
        </section>
        <section className="rounded-xl border border-slate-200 bg-slate-50/50 p-4">
          <h2 className="mb-3 font-medium text-slate-700">На проверке</h2>
          <div className="space-y-2">
            {review.map((t) => (
              <div key={t.id} className="space-y-1">
                <TaskCard
                  task={t}
                  currentUserId={currentUser?.id ?? ''}
                  validatorName={validatorNames[t.validator_id ?? '']}
                  onOpenDetail={setDetailTask}
                />
                {isTeamleadOrAdmin && (
                  <button
                    type="button"
                    onClick={() => handleOpenDeadline(t)}
                    className="text-xs text-slate-500 hover:text-slate-800"
                  >
                    📅 Дедлайн
                  </button>
                )}
              </div>
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
              <div key={t.id} className="space-y-1">
                <TaskCard
                  task={t}
                  validatorName={validatorNames[t.validator_id ?? '']}
                  onOpenDetail={setDetailTask}
                />
                {isTeamleadOrAdmin && (
                  <button
                    type="button"
                    onClick={() => handleOpenBugfix(t)}
                    className="text-xs text-slate-500 hover:text-slate-800"
                  >
                    🐛 Баг
                  </button>
                )}
              </div>
            ))}
            {done.length === 0 && (
              <p className="text-sm text-slate-400">Нет завершённых задач</p>
            )}
          </div>
        </section>
      </div>

      <TaskDetailModal
        task={detailTask}
        onClose={() => setDetailTask(null)}
        users={users}
        isTeamleadOrAdmin={isTeamleadOrAdmin}
        onOpenBugfix={(t) => {
          setDetailTask(null)
          setBugfixParent(t)
          setBugfixTitle('')
          setBugfixDescription('')
        }}
        onOpenDeadline={(t) => {
          setDetailTask(null)
          setDeadlineTask(t)
          setDeadlineValue(t.due_date ? new Date(t.due_date).toISOString().slice(0, 16) : '')
        }}
      />

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
                currentUserId={currentUser?.id ?? ''}
                validatorName={validatorNames[t.validator_id ?? '']}
                onOpenDetail={setDetailTask}
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

      {/* Модалка: Установить дедлайн */}
      {deadlineTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onClick={() => setDeadlineTask(null)}
          onKeyDown={(e) => e.key === 'Escape' && setDeadlineTask(null)}
        >
          <div
            className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-slate-900">📅 Установить дедлайн</h3>
            <p className="mt-1 text-sm text-slate-500">{deadlineTask.title}</p>
            <div className="mt-4">
              <label className="block text-sm font-medium text-slate-700">Дата и время</label>
              <input
                type="datetime-local"
                value={deadlineValue}
                onChange={(e) => setDeadlineValue(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeadlineTask(null)}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleSaveDeadline}
                disabled={deadlineBusy || !deadlineValue}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {deadlineBusy ? '...' : 'Сохранить'}
              </button>
            </div>
          </div>
        </div>
      )}

      <BugfixModal
        open={Boolean(bugfixParent)}
        parentTask={bugfixParent}
        author={
          bugfixParent
            ? users.find((u) => u.id === bugfixParent.assignee_id) ?? null
            : null
        }
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
    </div>
  )
}
