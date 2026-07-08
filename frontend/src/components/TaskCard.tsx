import type { Task } from '@/api/types'
import { CalendarClock, Check } from 'lucide-react'
import { QBadge } from './QBadge'
import { PriorityBadge } from './PriorityBadge'
import { cn } from '@/lib/utils'
import { DeadlineBadge } from './DeadlineBadge'

interface TaskCardProps {
  task: Task
  onPull?: (taskId: string) => void
  onSubmitReview?: (taskId: string) => void
  onValidate?: (taskId: string, approved: boolean, comment?: string) => void
  /** Открыть модалку «Вернуть» с полем «Причина возврата»; сабмит вызовет onValidate(taskId, false, comment) */
  onRejectClick?: (task: Task) => void
  /** Клик по названию задачи — открыть детальную модалку */
  onOpenDetail?: (task: Task) => void
  showActions?: boolean
  pullingTaskId?: string | null
  busyTaskId?: string | null
  /** Для блокировки самовалидации: кнопки Принять/Вернуть disabled если task.assignee_id === currentUserId */
  currentUserId?: string | null
  /** Имя валидатора для карточки DONE */
  validatorName?: string
  onToggleTracker?: (task: Task) => void
  isInTracker?: boolean
  trackerBusy?: boolean
  className?: string
}

const statusLabels: Record<string, string> = {
  new: 'Новая',
  estimated: 'Оценена',
  in_queue: 'В очереди',
  in_progress: 'В работе',
  review: 'На проверке',
  done: 'Готово',
  cancelled: 'Отменена',
}

function daysSince(dateStr: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (24 * 60 * 60 * 1000))
}

function wasCompletedLate(task: Task): boolean {
  if (task.status !== 'done' || !task.completed_at || !task.due_date) return false
  return new Date(task.completed_at).getTime() > new Date(task.due_date).getTime()
}

export function TaskCard({
  task,
  onPull,
  onSubmitReview,
  onValidate,
  onRejectClick,
  onOpenDetail,
  showActions,
  pullingTaskId,
  busyTaskId,
  currentUserId,
  validatorName,
  onToggleTracker,
  isInTracker,
  trackerBusy,
  className,
}: TaskCardProps) {
  const inQueue = task.status === 'in_queue'
  const inProgress = task.status === 'in_progress'
  const inReview = task.status === 'review'
  const isDone = task.status === 'done'
  const canPull = showActions && inQueue && onPull
  const canSubmit = showActions && inProgress && onSubmitReview
  const canValidate = showActions && inReview && onValidate
  const isSelfTask = currentUserId && task.assignee_id === currentUserId
  const isPulling = pullingTaskId === task.id
  const isBusy = busyTaskId === task.id
  const validateDisabled = Boolean(isBusy || isSelfTask)
  const days = daysSince(task.started_at)
  const completedLate = wasCompletedLate(task)
  const briefStars = task.brief_rating
    ? '★'.repeat(task.brief_rating) + '☆'.repeat(5 - task.brief_rating)
    : null

  return (
    <div
      className={cn(
        'rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 font-mono text-xs font-semibold text-slate-400">
              #{task.task_number}
            </span>
            {completedLate && (
              <span
                className="h-2 w-2 shrink-0 rounded-full bg-red-500 ring-2 ring-red-100"
                title="Завершена с просрочкой"
                aria-label="Завершена с просрочкой"
              />
            )}
            {onOpenDetail ? (
              <button
                type="button"
                onClick={() => onOpenDetail(task)}
                className="block min-w-0 flex-1 cursor-pointer truncate text-left font-medium text-primary hover:underline"
              >
                {task.title}
              </button>
            ) : (
              <h3 className="min-w-0 flex-1 truncate font-medium text-slate-900">{task.title}</h3>
            )}
          </div>
          {task.description && (
            <p className="mt-1 text-sm text-slate-500 line-clamp-2">{task.description}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="whitespace-nowrap"><QBadge q={task.estimated_q} /></span>
            <PriorityBadge priority={task.priority} />
            <span className="text-xs text-slate-400">
              {statusLabels[task.status] ?? task.status}
            </span>
            <span className="text-xs text-slate-400">· {task.complexity}</span>
            {days != null && (
              <span className="text-xs text-slate-400">· {days} д. в работе</span>
            )}
            <DeadlineBadge dueDate={task.due_date} zone={task.deadline_zone} status={task.status} />
            {task.rejection_count > 0 && (
              <span
                className={cn(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                  task.rejection_count === 1
                    ? 'bg-amber-50 text-amber-700'
                    : task.rejection_count === 2
                      ? 'bg-orange-100 text-orange-800'
                      : 'bg-red-100 text-red-800'
                )}
                title={`Возвращена на доработку ${task.rejection_count} раз`}
              >
                🔄 {task.rejection_count}
              </span>
            )}
          </div>
          {task.rejection_comment && task.rejection_count > 0 && (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Последний возврат</p>
              <p className="mt-1 whitespace-pre-wrap">{task.rejection_comment}</p>
            </div>
          )}
          {inReview && !task.rejection_comment && (
            <p className="mt-2 text-sm text-slate-500">⏳ Ожидает проверки</p>
          )}
          {(inReview || isDone) && (task.result_url || task.result_comment || task.brief_rating) && (
            <div className="mt-2 rounded-md border border-slate-100 bg-slate-50 p-2 text-sm text-slate-600">
              {briefStars && (
                <p className="mb-1 text-xs font-medium text-slate-500">Постановка: {briefStars}</p>
              )}
              {task.result_comment && (
                <p className="line-clamp-2 whitespace-pre-wrap">{task.result_comment}</p>
              )}
              {task.result_url && (
                <a
                  href={task.result_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 block truncate text-primary hover:underline"
                >
                  {task.result_url}
                </a>
              )}
            </div>
          )}
          {isDone && (
            <p className="mt-2 flex items-center gap-1 text-sm text-emerald-700">
              <Check className="h-4 w-4" />
              <span className="whitespace-nowrap">+{task.estimated_q} Q</span>
              {validatorName && ` · ${validatorName}`}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {onToggleTracker && (
            <button
              type="button"
              onClick={() => onToggleTracker(task)}
              disabled={trackerBusy}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm font-medium disabled:opacity-50',
                isInTracker
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                  : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
              )}
            >
              <CalendarClock className="h-3.5 w-3.5" />
              {trackerBusy ? '...' : isInTracker ? 'В трекере' : 'В трекер'}
            </button>
          )}
          {canPull && (
            <button
              type="button"
              onClick={() => onPull?.(task.id)}
              disabled={isPulling}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {isPulling ? '...' : 'Взять'}
            </button>
          )}
          {canSubmit && (
            <button
              type="button"
              onClick={() => onSubmitReview?.(task.id)}
              disabled={isBusy}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {isBusy ? '...' : 'Сдать'}
            </button>
          )}
          {canValidate && onValidate && (
            <>
              <button
                type="button"
                onClick={() => onValidate(task.id, true)}
                disabled={validateDisabled}
                title={isSelfTask ? 'Нельзя валидировать свою задачу' : undefined}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {isBusy ? '...' : '✓ Принять'}
              </button>
              <button
                type="button"
                onClick={() => (onRejectClick ? onRejectClick(task) : onValidate(task.id, false))}
                disabled={validateDisabled}
                title={isSelfTask ? 'Нельзя валидировать свою задачу' : undefined}
                className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                ✗ Вернуть
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
