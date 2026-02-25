import type { FC } from 'react'
import type { Task, User, CatalogItem } from '@/api/types'
import { DeadlineBadge } from './DeadlineBadge'
import { PriorityBadge } from './PriorityBadge'
import { X } from 'lucide-react'

interface TaskDetailModalProps {
  task: Task | null
  onClose: () => void
  users: User[]
  catalogItems?: CatalogItem[]
  isTeamleadOrAdmin?: boolean
  onOpenBugfix?: (task: Task) => void
  onOpenDeadline?: (task: Task) => void
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

const statusEmoji: Record<string, string> = {
  new: '⚪',
  estimated: '🔵',
  in_queue: '🔵',
  in_progress: '🟢',
  review: '🟡',
  done: '🟢',
  cancelled: '⚫',
}

const priorityEmoji: Record<string, string> = {
  critical: '🔴',
  high: '🟠',
  medium: '🟡',
  low: '🟢',
}

function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  const date = new Date(d)
  return `${date.toLocaleDateString('ru')} ${date.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })}`
}

export const TaskDetailModal: FC<TaskDetailModalProps> = ({
  task,
  onClose,
  users,
  catalogItems = [],
  isTeamleadOrAdmin,
  onOpenBugfix,
  onOpenDeadline,
}) => {
  if (!task) return null

  const resolveName = (id: string | null | undefined) => {
    if (!id) return '—'
    return users.find((u) => u.id === id)?.full_name ?? '—'
  }

  const resolveCatalogName = (catalogId: string | undefined) => {
    if (!catalogId) return '—'
    return catalogItems.find((c) => c.id === catalogId)?.name ?? catalogId
  }

  const breakdown = task.estimation_details && typeof task.estimation_details === 'object' && 'breakdown' in task.estimation_details
    ? (task.estimation_details as { breakdown?: Array<{ catalog_id?: string; name?: string; subtotal_q: number }> }).breakdown
    : undefined

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="task-detail-title"
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      onClick={handleOverlayClick}
    >
      <div
        className="relative w-full max-w-lg rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-slate-200 p-4">
          <h2 id="task-detail-title" className="text-lg font-semibold text-slate-900 pr-8">
            📋 {task.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="absolute right-4 top-4 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(100vh-12rem)] overflow-y-auto p-4 space-y-4">
          {/* Статус, приоритет, тип, сложность, дедлайн */}
          <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3 text-sm">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span>
                Статус: {statusEmoji[task.status] ?? '•'} {statusLabels[task.status] ?? task.status}
              </span>
              <span>
                Приоритет: {priorityEmoji[task.priority] ?? '•'}{' '}
                <PriorityBadge priority={task.priority} />
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
              <span>Тип: {task.task_type}</span>
              <span>Сложность: {task.complexity}</span>
            </div>
            {task.due_date && (
              <div className="mt-2">
                Дедлайн: <DeadlineBadge dueDate={task.due_date} zone={task.deadline_zone ?? null} />
              </div>
            )}
            {task.rejection_count > 0 && (
              <div className="mt-2 flex items-center gap-2 text-sm">
                <span className="text-slate-500">Возвраты:</span>
                <span
                  className={`font-semibold ${
                    task.rejection_count >= 3
                      ? 'text-red-600'
                      : task.rejection_count >= 2
                        ? 'text-orange-600'
                        : 'text-amber-600'
                  }`}
                >
                  {task.rejection_count}{' '}
                  {task.rejection_count === 1
                    ? 'раз'
                    : task.rejection_count < 5
                      ? 'раза'
                      : 'раз'}
                </span>
              </div>
            )}
          </div>

          {/* Оценка */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Оценка</p>
            <p className="mt-1 text-slate-700">
              <span className="whitespace-nowrap font-semibold">{Number(task.estimated_q).toFixed(1)} Q</span>
              {!breakdown?.length && ' (без декомпозиции)'}
            </p>
            {breakdown && breakdown.length > 0 && (
              <div className="mt-2 rounded-lg border border-slate-200 p-3">
                <table className="w-full text-sm">
                  <tbody>
                    {breakdown.map((row, i) => (
                      <tr key={i} className="border-b border-slate-100 last:border-0">
                        <td className="py-1 pr-2 text-slate-700">
                          {row.name ?? resolveCatalogName(row.catalog_id)}
                        </td>
                        <td className="py-1 text-right whitespace-nowrap font-medium">
                          {Number(row.subtotal_q).toFixed(1)} Q
                        </td>
                      </tr>
                    ))}
                    <tr className="border-t border-slate-200 font-medium">
                      <td className="py-2 text-slate-700">Итого</td>
                      <td className="py-2 text-right whitespace-nowrap">
                        {Number(task.estimated_q).toFixed(1)} Q
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Описание */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Описание</p>
            <p className="mt-1 text-sm text-slate-700 whitespace-pre-wrap">
              {task.description || '—'}
            </p>
          </div>

          {/* Участники */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Участники</p>
            <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
              <li>Оценил: {resolveName(task.estimator_id)}</li>
              <li>Исполнитель: {resolveName(task.assignee_id)}</li>
              <li>Валидатор: {resolveName(task.validator_id)}</li>
            </ul>
          </div>

          {/* Результат */}
          {task.result_url && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Результат</p>
              <a
                href={task.result_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 block text-sm text-primary hover:underline"
              >
                🔗 {task.result_url}
              </a>
            </div>
          )}

          {/* Даты */}
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Даты</p>
            <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
              <li>Создана: {formatDate(task.created_at)}</li>
              <li>Начата: {formatDate(task.started_at)}</li>
              <li>Завершена: {formatDate(task.completed_at)}</li>
              <li>Валидирована: {formatDate(task.validated_at)}</li>
            </ul>
          </div>

          {/* Баг-фикс к задаче */}
          {task.parent_task_id && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-sm text-amber-800">
              🐛 Это баг-фикс к задаче (ID: {task.parent_task_id})
            </div>
          )}

          {/* Кнопки */}
          <div className="flex flex-wrap gap-2 border-t border-slate-200 pt-4">
            {isTeamleadOrAdmin && onOpenDeadline && (
              <button
                type="button"
                onClick={() => onOpenDeadline(task)}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                📅 Дедлайн
              </button>
            )}
            {isTeamleadOrAdmin && task.status === 'done' && onOpenBugfix && (
              <button
                type="button"
                onClick={() => onOpenBugfix(task)}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                🐛 Создать баг-фикс
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-300"
            >
              Закрыть
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
