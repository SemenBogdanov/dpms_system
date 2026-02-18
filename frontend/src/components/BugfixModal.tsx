import type { FC, FormEvent } from 'react'
import type { Task, User } from '@/api/types'

interface BugfixModalProps {
  open: boolean
  parentTask: Task | null
  author: User | null
  title: string
  description: string
  onTitleChange: (value: string) => void
  onDescriptionChange: (value: string) => void
  onClose: () => void
  onSubmit: () => void
  busy?: boolean
}

export const BugfixModal: FC<BugfixModalProps> = ({
  open,
  parentTask,
  author,
  title,
  description,
  onTitleChange,
  onDescriptionChange,
  onClose,
  onSubmit,
  busy,
}) => {
  if (!open || !parentTask) return null

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    onSubmit()
  }

  const isAuthorActive = author?.is_active ?? false

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl"
      >
        <h3 className="text-lg font-semibold text-slate-900">🐛 Гарантийный баг-фикс</h3>
        <p className="mt-2 text-sm text-slate-600">
          Оригинал: «{parentTask.title}»
        </p>
        <p className="mt-1 text-sm text-slate-600">
          Автор:{' '}
          {author ? (
            <>
              {author.full_name}{' '}
              {author.is_active ? (
                <span className="text-emerald-600">(активен ✅)</span>
              ) : (
                <span className="text-red-600">(уволен ❌)</span>
              )}
            </>
          ) : (
            '—'
          )}
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Название бага
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => onTitleChange(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Описание
            </label>
            <textarea
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="mt-4 space-y-1 text-sm text-slate-600">
          <p>⚠️ Стоимость: {isAuthorActive ? '0Q' : '50% от оценки оригинала (karma-бонус)'}</p>
          <p>📌 Приоритет: critical</p>
          <p>
            👤 Назначение:{' '}
            {isAuthorActive ? author?.full_name ?? 'Автор' : 'общая очередь'}
          </p>
          {!isAuthorActive && (
            <p className="text-xs text-slate-500">
              Автор недоступен. Задача уйдёт в общую очередь с karma-бонусом.
            </p>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={busy || !title.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {busy ? '...' : 'Создать баг-фикс'}
          </button>
        </div>
      </form>
    </div>
  )
}

