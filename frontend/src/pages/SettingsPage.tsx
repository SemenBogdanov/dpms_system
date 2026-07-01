import { useState } from 'react'
import { KeyRound, ShieldCheck, UserRound } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { ChangePasswordModal } from '@/components/ChangePasswordModal'
import { LeagueBadge } from '@/components/LeagueBadge'

export function SettingsPage() {
  const { user } = useAuth()
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Настройки</h1>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
              <UserRound className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <h2 className="truncate font-medium text-slate-900">{user?.full_name ?? 'Пользователь'}</h2>
              <p className="mt-1 truncate text-sm text-slate-500">{user?.email}</p>
              {user && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <LeagueBadge league={user.league} />
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">{user.role}</span>
                </div>
              )}
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            <ShieldCheck className="h-3.5 w-3.5" />
            Активен
          </span>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
              <KeyRound className="h-5 w-5" />
            </span>
            <div>
              <h2 className="font-medium text-slate-900">Пароль</h2>
              <p className="mt-1 text-sm text-slate-500">Обновление пароля учетной записи</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setChangePasswordOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            <KeyRound className="h-4 w-4" />
            Сменить пароль
          </button>
        </div>
      </section>

      <ChangePasswordModal
        open={changePasswordOpen}
        onClose={() => setChangePasswordOpen(false)}
      />
    </div>
  )
}
