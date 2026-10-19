import { useLayoutEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Mail, XCircle } from 'lucide-react'
import { api } from '@/api/client'
import type { EmailChangeActionResult } from '@/api/types'
import { clearToken } from '@/lib/auth'

type EmailChangeAction = 'confirm' | 'cancel'

function readLinkFromFragment(): { action: EmailChangeAction | null; token: string } {
  if (typeof window === 'undefined') return { action: null, token: '' }
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const rawAction = params.get('action')
  return {
    action: rawAction === 'confirm' || rawAction === 'cancel' ? rawAction : null,
    token: params.get('token') || '',
  }
}

export function EmailChangeActionPage() {
  const [link] = useState(readLinkFromFragment)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EmailChangeActionResult | null>(null)

  useLayoutEffect(() => {
    if (!window.location.hash) return
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`)
  }, [])

  const valid = Boolean(link.action && link.token)
  const confirm = link.action === 'confirm'

  const runAction = async () => {
    if (!link.action || !link.token) return
    setBusy(true)
    setError(null)
    try {
      const endpoint = link.action === 'confirm'
        ? '/api/auth/email-change/confirm'
        : '/api/auth/email-change/cancel-link'
      const response = await api.post<EmailChangeActionResult>(endpoint, { token: link.token })
      if (response.reauth_required) clearToken()
      setResult(response)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Не удалось обработать ссылку')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <section className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900">
        <span className="inline-flex h-11 w-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Mail className="h-5 w-5" aria-hidden="true" />
        </span>

        {result ? (
          <div className="mt-5">
            <CheckCircle2 className="h-7 w-7 text-emerald-600" aria-hidden="true" />
            <h1 className="mt-3 text-xl font-semibold text-slate-900 dark:text-slate-100">Готово</h1>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{result.message}</p>
            <Link
              to="/login"
              className="mt-5 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              Перейти ко входу
            </Link>
          </div>
        ) : !valid ? (
          <div className="mt-5">
            <XCircle className="h-7 w-7 text-red-500" aria-hidden="true" />
            <h1 className="mt-3 text-xl font-semibold text-slate-900 dark:text-slate-100">Ссылка не распознана</h1>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              Откройте полную ссылку из письма или создайте новый запрос в настройках.
            </p>
          </div>
        ) : (
          <div className="mt-5">
            <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
              {confirm ? 'Подтвердить новый email?' : 'Отменить смену email?'}
            </h1>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {confirm
                ? 'После подтверждения все ранее открытые сессии завершатся. Пароль останется прежним, а логином станет новый адрес.'
                : 'Запрос будет отменен, текущий email-логин останется без изменений.'}
            </p>
            <div className="mt-4 flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <p>Действие выполняется только после нажатия кнопки ниже.</p>
            </div>
            {error && <p className="mt-4 text-sm text-red-600 dark:text-red-300">{error}</p>}
            <button
              type="button"
              onClick={runAction}
              disabled={busy}
              className="mt-5 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {busy ? 'Обрабатываем...' : confirm ? 'Подтвердить email' : 'Отменить запрос'}
            </button>
          </div>
        )}
      </section>
    </main>
  )
}
