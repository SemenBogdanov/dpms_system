import type { Task } from '@/api/types'
import { QBadge } from './QBadge'
import { cn } from '@/lib/utils'

interface TaskCardProps {
  task: Task
  onPull?: (taskId: string) => void
  onSubmitReview?: (taskId: string) => void
  onValidate?: (taskId: string, approved: boolean) => void
  showActions?: boolean
  pullingTaskId?: string | null
  busyTaskId?: string | null
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

export function TaskCard({
  task,
  onPull,
  onSubmitReview,
  onValidate,
  showActions,
  pullingTaskId,
  busyTaskId,
  className,
}: TaskCardProps) {
  const inQueue = task.status === 'in_queue'
  const inProgress = task.status === 'in_progress'
  const inReview = task.status === 'review'
  const canPull = showActions && inQueue && onPull
  const canSubmit = showActions && inProgress && onSubmitReview
  const canValidate = showActions && inReview && onValidate
  const isPulling = pullingTaskId === task.id
  const isBusy = busyTaskId === task.id

  return (
    <div
      className={cn(
        'rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition-shadow hover:shadow',
        className
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium text-slate-900 truncate">{task.title}</h3>
          {task.description && (
            <p className="mt-1 text-sm text-slate-500 line-clamp-2">{task.description}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <QBadge q={task.estimated_q} />
            <span className="text-xs text-slate-400">
              {statusLabels[task.status] ?? task.status}
            </span>
            <span className="text-xs text-slate-400">· {task.priority}</span>
            <span className="text-xs text-slate-400">Лига {task.min_league}</span>
          </div>
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
              {isBusy ? '...' : 'Сдать на проверку'}
            </button>
          )}
          {canValidate && onValidate && (
            <>
              <button
                type="button"
                onClick={() => onValidate(task.id, true)}
                disabled={isBusy}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {isBusy ? '...' : 'Принять'}
              </button>
              <button
                type="button"
                onClick={() => onValidate(task.id, false)}
                disabled={isBusy}
                className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Вернуть
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
