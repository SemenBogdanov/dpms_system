import type { Task } from '@/api/types'
import { Check } from 'lucide-react'
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

  return (
    <div
      className={cn(
        'rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {onOpenDetail ? (
            <button
              type="button"
              onClick={() => onOpenDetail(task)}
              className="text-left font-medium text-slate-900 truncate block w-full cursor-pointer text-primary hover:underline"
            >
              {task.title}
            </button>
          ) : (
            <h3 className="font-medium text-slate-900 truncate">{task.title}</h3>
          )}
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
            <DeadlineBadge dueDate={task.due_date} zone={task.deadline_zone} />
          </div>
          {inReview && task.rejection_comment && (
            <p className="mt-2 text-sm text-red-600">{task.rejection_comment}</p>
          )}
          {inReview && !task.rejection_comment && (
            <p className="mt-2 text-sm text-slate-500">⏳ Ожидает проверки</p>
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
