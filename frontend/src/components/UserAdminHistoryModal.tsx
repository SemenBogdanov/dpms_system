import { useEffect, useRef, useState } from 'react'
import { History, KeyRound, RefreshCw, UserPlus, X } from 'lucide-react'
import { api } from '@/api/client'
import type {
  AdminUser,
  AdminUserAuditAction,
  AdminUserAuditHistory,
} from '@/api/types'

type UserAdminHistoryModalProps = {
  user: AdminUser | null
  open: boolean
  onClose: () => void
}

const FIELD_LABELS: Record<string, string> = {
  full_name: 'ФИО',
  email: 'Email',
  role: 'Роль',
  league: 'Лига',
  mpw: 'Базовый план',
  is_active: 'Учетная запись',
  is_new_employee: 'Новый сотрудник',
  task_workspace_enabled: 'Работа с задачами',
  feedback_enabled: 'Обратная связь',
  competency_development_enabled: 'Развитие',
  competency_constructor_enabled: 'Конструктор компетенций',
  plan_started_at: 'Начало плана',
  onboarding_started_at: 'Начало адаптации',
  onboarding_until: 'Окончание адаптации',
}

const ACTION_LABELS: Record<AdminUserAuditAction, string> = {
  created: 'Сотрудник создан',
  updated: 'Данные изменены',
  temporary_password_issued: 'Выдан временный пароль',
}

const ROLE_LABELS: Record<string, string> = {
  executor: 'Исполнитель',
  teamlead: 'Руководитель',
  admin: 'Администратор',
}

const DATE_FIELDS = new Set([
  'plan_started_at',
  'onboarding_started_at',
  'onboarding_until',
])

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function formatValue(field: string, value: unknown) {
  if (value === null || value === undefined || value === '') return 'не задано'
  if (typeof value === 'boolean') return value ? 'включено' : 'выключено'
  if (field === 'role' && typeof value === 'string') return ROLE_LABELS[value] || value
  if (field === 'mpw') return `${String(value)} Q`
  if (DATE_FIELDS.has(field) && typeof value === 'string') {
    const date = new Date(value)
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
    }
  }
  return String(value)
}

function actionIcon(action: AdminUserAuditAction) {
  if (action === 'created') return <UserPlus className="h-4 w-4" aria-hidden="true" />
  if (action === 'temporary_password_issued') return <KeyRound className="h-4 w-4" aria-hidden="true" />
  return <History className="h-4 w-4" aria-hidden="true" />
}

export function UserAdminHistoryModal({ user, open, onClose }: UserAdminHistoryModalProps) {
  const [history, setHistory] = useState<AdminUserAuditHistory | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open || !user) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .get<AdminUserAuditHistory>(`/api/users/${user.id}/admin-history`, { limit: '100' })
      .then((response) => {
        if (!cancelled) setHistory(response)
      })
      .catch((requestError) => {
        if (!cancelled) {
          setHistory(null)
          setError(requestError instanceof Error ? requestError.message : 'Не удалось загрузить историю')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, reloadKey, user])

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow

    document.body.style.overflow = 'hidden'
    const focusFrame = window.requestAnimationFrame(() => {
      const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ;(first || panelRef.current)?.focus()
    })

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !panelRef.current) return

      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((element) => element.offsetParent !== null)

      if (focusable.length === 0) {
        event.preventDefault()
        panelRef.current.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!panelRef.current.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus()
    }
  }, [open])

  if (!open || !user) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-user-history-title"
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-primary">
              <History className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="text-xs font-semibold uppercase">Административный аудит</span>
            </div>
            <h2 id="admin-user-history-title" className="mt-1 truncate text-lg font-semibold text-slate-900">
              {user.full_name}
            </h2>
            <p className="truncate text-sm text-slate-500">{user.email}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:bg-slate-50 hover:text-slate-800"
            aria-label="Закрыть историю изменений"
            title="Закрыть"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div
          className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5"
          tabIndex={0}
          role="region"
          aria-label="События административного аудита"
        >
          {loading && (
            <div className="flex min-h-40 items-center justify-center text-sm text-slate-500" aria-live="polite">
              Загрузка истории...
            </div>
          )}

          {!loading && error && (
            <div className="flex min-h-40 flex-col items-center justify-center text-center">
              <p className="text-sm text-red-600">{error}</p>
              <button
                type="button"
                onClick={() => setReloadKey((value) => value + 1)}
                className="mt-3 inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                Повторить
              </button>
            </div>
          )}

          {!loading && !error && history?.items.length === 0 && (
            <div className="flex min-h-40 items-center justify-center text-center text-sm text-slate-500">
              Изменений пока нет.
            </div>
          )}

          {!loading && !error && history && history.items.length > 0 && (
            <ol className="divide-y divide-slate-200">
              {history.items.map((event) => (
                <li key={event.id} className="py-4 first:pt-0 last:pb-0">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        {actionIcon(event.action)}
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-900">{ACTION_LABELS[event.action]}</p>
                        <p className="truncate text-xs text-slate-500">Администратор: {event.actor_name}</p>
                      </div>
                    </div>
                    <time className="text-xs text-slate-500" dateTime={event.occurred_at}>
                      {new Date(event.occurred_at).toLocaleString('ru-RU', {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      })}
                    </time>
                  </div>

                  {event.sessions_revoked && (
                    <p className="mt-2 text-xs font-medium text-amber-700">Активные сессии сотрудника завершены</p>
                  )}

                  {event.changes.length > 0 && (
                    <dl className="mt-3 overflow-hidden rounded-md border border-slate-200">
                      {event.changes.map((change) => (
                        <div
                          key={change.field}
                          className="grid gap-1 border-b border-slate-200 px-3 py-2.5 last:border-b-0 sm:grid-cols-[minmax(150px,0.7fr)_1fr_auto_1fr] sm:items-center sm:gap-3"
                        >
                          <dt className="text-xs font-medium text-slate-600">
                            {FIELD_LABELS[change.field] || change.field}
                          </dt>
                          <dd className="min-w-0 break-words text-sm text-slate-500">
                            <span className="mr-1 text-xs font-medium text-slate-500 sm:hidden">Было:</span>
                            {formatValue(change.field, change.before)}
                          </dd>
                          <span className="hidden text-slate-400 sm:inline" aria-hidden="true">→</span>
                          <dd className="min-w-0 break-words text-sm font-medium text-slate-900">
                            <span className="mr-1 text-xs font-medium text-slate-500 sm:hidden">Стало:</span>
                            {formatValue(change.field, change.after)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>

        {history && history.total > history.items.length && (
          <footer className="border-t border-slate-200 px-4 py-3 text-xs text-slate-500 sm:px-5">
            Показаны последние {history.items.length} из {history.total} событий.
          </footer>
        )}
      </div>
    </div>
  )
}
