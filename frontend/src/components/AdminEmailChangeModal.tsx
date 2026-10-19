import { useEffect, useState } from 'react'
import { Mail, ShieldCheck } from 'lucide-react'
import { api } from '@/api/client'
import type { AdminUser, EmailChangeRequest } from '@/api/types'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

interface AdminEmailChangeModalProps {
  user: AdminUser | null
  open: boolean
  onClose: () => void
  onRequested: (request: EmailChangeRequest) => void
}

export function AdminEmailChangeModal({ user, open, onClose, onRequested }: AdminEmailChangeModalProps) {
  const [newEmail, setNewEmail] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useProtectedModal<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    setNewEmail('')
    setReason('')
    setBusy(false)
    setError(null)
  }, [open, user?.id])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!user) return
    if (!newEmail.trim() || reason.trim().length < 3) {
      setError('Укажите новый email и причину изменения')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const request = await api.post<EmailChangeRequest>(`/api/users/${user.id}/email-change-request`, {
        new_email: newEmail.trim().toLowerCase(),
        reason: reason.trim(),
      })
      onRequested(request)
      onClose()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Не удалось создать запрос')
    } finally {
      setBusy(false)
    }
  }

  if (!open || !user) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-email-change-title"
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-start gap-3">
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Mail className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 id="admin-email-change-title" className="font-semibold text-slate-900 dark:text-slate-100">
              Смена email сотрудника
            </h2>
            <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">
              {user.full_name} · {user.email}
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
            Новый email
            <input
              autoFocus
              type="email"
              value={newEmail}
              onChange={(event) => setNewEmail(event.target.value)}
              className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
            Причина изменения
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              placeholder="Например: корпоративный адрес будет отключен после увольнения"
              className="mt-1.5 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>
          <p className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2.5 text-sm text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-100">
            Администратор только запускает процедуру. Сотрудник подтверждает новый адрес самостоятельно.
          </p>
          {error && <p className="text-sm text-red-600 dark:text-red-300">{error}</p>}
          <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              {busy ? 'Отправляем...' : 'Запустить подтверждение'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
