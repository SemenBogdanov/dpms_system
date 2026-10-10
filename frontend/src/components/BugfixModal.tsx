import { useCallback, useRef, type FC, type FormEvent } from 'react'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { useFormNavigationProtection } from './PersonalTaskForm'
import type { Task, User } from '@/api/types'

const TASK_TITLE_MAX_LENGTH = 120

// eslint-disable-next-line react-refresh/only-export-components
export function useTaskDialogProtection(open: boolean, busy: boolean, dirty: boolean, onClose: () => void) {
  const panelRef = useProtectedModal<HTMLDivElement>(open)
  const busyRef = useRef(busy)
  busyRef.current = busy
  const requestDiscard = useCallback((leave: () => void) => {
    if (!busyRef.current && window.confirm('Закрыть без сохранения изменений?')) leave()
  }, [])
  useFormNavigationProtection(open && (dirty || busy), busyRef, requestDiscard)
  const requestClose = () => {
    if (busyRef.current) return
    if (dirty) requestDiscard(onClose)
    else onClose()
  }
  return { panelRef, requestClose }
}

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
  const { panelRef, requestClose } = useTaskDialogProtection(open && Boolean(parentTask), Boolean(busy), Boolean(title.trim() || description.trim()), onClose)
  if (!open || !parentTask) return null

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (busy || !title.trim()) return
    onSubmit()
  }

  const isAuthorActive = author?.is_active ?? false

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-label="Гарантийный баг-фикс"
      onPointerDown={preventBackdropDismiss}
      onKeyDown={(e) => e.key === 'Escape' && requestClose()}
    >
      <div ref={panelRef} tabIndex={-1} className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto pb-[env(safe-area-inset-bottom)]">
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full rounded-xl bg-white p-6 shadow-xl [overflow-wrap:anywhere]"
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
            <label htmlFor="bugfix-title" className="block text-sm font-medium text-slate-700">
              Название бага
            </label>
            <input
              id="bugfix-title"
              disabled={busy}
              type="text"
              value={title}
              onChange={(e) => onTitleChange(e.target.value)}
              maxLength={TASK_TITLE_MAX_LENGTH}
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-slate-400">
              {title.trim().length}/{TASK_TITLE_MAX_LENGTH} символов
            </p>
          </div>
          <div>
            <label htmlFor="bugfix-description" className="block text-sm font-medium text-slate-700">
              Описание
            </label>
            <textarea
              id="bugfix-description"
              disabled={busy}
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
            disabled={busy}
            onClick={requestClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={busy || !title.trim() || title.trim().length > TASK_TITLE_MAX_LENGTH}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {busy ? '...' : 'Создать баг-фикс'}
          </button>
        </div>
      </form>
      </div>
    </div>
  )
}
