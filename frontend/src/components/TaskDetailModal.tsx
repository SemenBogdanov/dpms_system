import { useEffect, useState, type FC } from 'react'
import { api } from '@/api/client'
import type { Task, User, CatalogItem, TaskAttachment } from '@/api/types'
import { DeadlineBadge } from './DeadlineBadge'
import { PriorityBadge } from './PriorityBadge'
import { Copy, FileText, X } from 'lucide-react'
import toast from 'react-hot-toast'

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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`
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
  const taskId = task?.id
  const [attachments, setAttachments] = useState<TaskAttachment[]>([])
  const [attachmentUrls, setAttachmentUrls] = useState<Record<string, string>>({})
  const [attachmentsLoading, setAttachmentsLoading] = useState(false)

  useEffect(() => {
    if (!taskId) {
      setAttachments([])
      setAttachmentUrls({})
      return
    }

    let active = true
    const createdUrls: string[] = []

    async function loadAttachments() {
      setAttachmentsLoading(true)
      setAttachments([])
      setAttachmentUrls({})
      try {
        const list = await api.get<TaskAttachment[]>(`/api/tasks/${taskId}/attachments`)
        if (!active) return
        setAttachments(list)
        const entries: Array<[string, string]> = []
        for (const attachment of list) {
          try {
            const blob = await api.blob(
              `/api/tasks/${taskId}/attachments/${attachment.id}/content`
            )
            if (!active) return
            const url = URL.createObjectURL(blob)
            createdUrls.push(url)
            entries.push([attachment.id, url])
          } catch {
            if (!active) return
          }
        }
        if (active) setAttachmentUrls(Object.fromEntries(entries))
      } catch {
        if (active) setAttachments([])
      } finally {
        if (active) setAttachmentsLoading(false)
      }
    }

    void loadAttachments()

    return () => {
      active = false
      createdUrls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [taskId])

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
  const taskLabel = `#${task.task_number} ${task.title}`
  const briefStars = task.brief_rating
    ? '★'.repeat(task.brief_rating) + '☆'.repeat(5 - task.brief_rating)
    : null

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }

  const handleCopyTaskLabel = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(taskLabel)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = taskLabel
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      toast.success('Номер и название скопированы')
    } catch {
      toast.error('Не удалось скопировать')
    }
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
            <button
              type="button"
              onClick={handleCopyTaskLabel}
              className="group flex min-w-0 items-start gap-2 text-left hover:text-primary"
              title="Скопировать номер и название"
            >
              <span className="shrink-0 font-mono text-sm text-slate-400">#{task.task_number}</span>
              <span className="min-w-0">{task.title}</span>
              <Copy className="mt-1 h-4 w-4 shrink-0 text-slate-300 group-hover:text-primary" />
            </button>
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
                Дедлайн: <DeadlineBadge dueDate={task.due_date} zone={task.deadline_zone ?? null} status={task.status} />
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

          {(attachmentsLoading || attachments.length > 0) && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Вложения</p>
              {attachmentsLoading && (
                <p className="mt-1 text-sm text-slate-500">Загрузка...</p>
              )}
              {!attachmentsLoading && attachments.length > 0 && (
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {attachments.map((attachment) => {
                    const url = attachmentUrls[attachment.id]
                    const isImage = attachment.content_type.startsWith('image/')
                    return (
                      <a
                        key={attachment.id}
                        href={url}
                        target="_blank"
                        download={attachment.original_filename}
                        rel="noopener noreferrer"
                        className={`overflow-hidden rounded-lg border border-slate-200 bg-white text-left shadow-sm transition ${
                          url ? 'hover:border-primary hover:shadow' : 'pointer-events-none opacity-70'
                        }`}
                      >
                        <div className="flex h-28 items-center justify-center bg-slate-100">
                          {url && isImage ? (
                            <img
                              src={url}
                              alt={attachment.original_filename}
                              className="h-full w-full object-cover"
                            />
                          ) : url ? (
                            <div className="flex flex-col items-center gap-2 px-3 text-center text-slate-500">
                              <FileText className="h-8 w-8" />
                              <span className="text-xs font-medium uppercase">
                                {attachment.original_filename.split('.').pop() || 'файл'}
                              </span>
                            </div>
                          ) : (
                            <span className="px-3 text-center text-xs text-slate-400">
                              Не удалось открыть файл
                            </span>
                          )}
                        </div>
                        <div className="space-y-0.5 p-2">
                          <p className="truncate text-sm font-medium text-slate-700">
                            {attachment.original_filename}
                          </p>
                          <p className="text-xs text-slate-400">
                            {formatBytes(attachment.size_bytes)}
                          </p>
                        </div>
                      </a>
                    )
                  })}
                </div>
              )}
            </div>
          )}

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
          {(task.result_url || task.result_comment) && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Результат</p>
              {task.result_comment && (
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                  {task.result_comment}
                </p>
              )}
              {task.result_url && (
                <a
                  href={task.result_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 block text-sm text-primary hover:underline"
                >
                  🔗 {task.result_url}
                </a>
              )}
            </div>
          )}

          {briefStars && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Оценка постановки</p>
              <p className="mt-1 text-sm font-medium text-slate-700">
                {briefStars} <span className="text-slate-400">({task.brief_rating}/5)</span>
              </p>
              {task.brief_feedback && (
                <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
                  {task.brief_feedback}
                </p>
              )}
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
              🐛 Это баг-фикс к связанной задаче
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
