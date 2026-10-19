import { useEffect, useState } from 'react'
import { AlertTriangle, Mail, ShieldCheck } from 'lucide-react'
import { api } from '@/api/client'
import type { EmailChangeRequest } from '@/api/types'
import { PasswordRevealButton } from '@/components/PasswordRevealButton'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

interface EmailChangeModalProps {
  currentEmail: string
  open: boolean
  onClose: () => void
  onRequested: (request: EmailChangeRequest) => void
}

export function EmailChangeModal({ currentEmail, open, onClose, onRequested }: EmailChangeModalProps) {
  const [newEmail, setNewEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useProtectedModal<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    setNewEmail('')
    setCurrentPassword('')
    setShowPassword(false)
    setBusy(false)
    setError(null)
  }, [open])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const normalized = newEmail.trim().toLowerCase()
    if (!normalized || !currentPassword) {
      setError('Укажите новый email и текущий пароль')
      return
    }
    if (normalized === currentEmail.trim().toLowerCase()) {
      setError('Новый email должен отличаться от текущего')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const request = await api.post<EmailChangeRequest>('/api/auth/email-change/request', {
        new_email: normalized,
        current_password: currentPassword,
      })
      onRequested(request)
      onClose()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Не удалось создать запрос')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-change-title"
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
          <div>
            <h2 id="email-change-title" className="font-semibold text-slate-900 dark:text-slate-100">
              Изменить email-логин
            </h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Сейчас: {currentEmail}
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
              autoComplete="email"
              className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>

          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
            Текущий пароль
            <div className="relative mt-1.5">
              <input
                type={showPassword ? 'text' : 'password'}
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                autoComplete="current-password"
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 pr-11 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
              />
              <PasswordRevealButton revealed={showPassword} onRevealChange={setShowPassword} />
            </div>
          </label>

          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>Изменение вступит в силу только после подтверждения из нового почтового ящика.</p>
            </div>
          </div>

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
              {busy ? 'Отправляем...' : 'Отправить подтверждение'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
