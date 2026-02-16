import { useEffect, useState } from 'react'
import type { User } from '@/api/types'
import { cn } from '@/lib/utils'

export type UserFormPayload = {
  full_name: string
  email: string
  role: User['role']
  league: User['league']
  mpw: number
  password?: string
}

interface UserModalProps {
  mode: 'create' | 'edit'
  initial?: User | null
  open: boolean
  onClose: () => void
  onSubmit: (payload: UserFormPayload) => Promise<void>
}

const ROLES: User['role'][] = ['executor', 'teamlead', 'admin']
const LEAGUES: User['league'][] = ['C', 'B', 'A']

const roleBadgeClass: Record<string, string> = {
  admin: 'bg-red-100 text-red-800',
  teamlead: 'bg-blue-100 text-blue-800',
  executor: 'bg-slate-100 text-slate-700',
}

export function UserModal({ mode, initial, open, onClose, onSubmit }: UserModalProps) {
  const [full_name, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<User['role']>('executor')
  const [league, setLeague] = useState<User['league']>('C')
  const [mpw, setMpw] = useState(60)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setValidationError(null)
    if (mode === 'edit' && initial) {
      setFullName(initial.full_name)
      setEmail(initial.email)
      setRole(initial.role)
      setLeague(initial.league)
      setMpw(initial.mpw)
      setPassword('')
    } else {
      setFullName('')
      setEmail('')
      setRole('executor')
      setLeague('C')
      setMpw(60)
      setPassword('')
    }
  }, [open, mode, initial])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!full_name.trim()) {
      setValidationError('ФИО обязательно')
      return
    }
    if (!email.trim()) {
      setValidationError('Email обязателен')
      return
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(email)) {
      setValidationError('Некорректный формат email')
      return
    }
    if (mode === 'create' && password.length < 6) {
      setValidationError('Пароль не менее 6 символов')
      return
    }
    if (mpw <= 0) {
      setValidationError('План (MPW) должен быть больше 0')
      return
    }
    setValidationError(null)
    setBusy(true)
    try {
      await onSubmit({
        full_name: full_name.trim(),
        email: email.trim(),
        role,
        league,
        mpw,
        ...(mode === 'create' ? { password } : undefined),
      })
      onClose()
    } catch (err) {
      setValidationError(err instanceof Error ? err.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">
          {mode === 'create' ? 'Добавить сотрудника' : 'Редактировать сотрудника'}
        </h3>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <label className="block text-sm font-medium text-slate-700">ФИО *</label>
          <input
            type="text"
            value={full_name}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            maxLength={255}
          />
          <label className="block text-sm font-medium text-slate-700">Email *</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <label className="block text-sm font-medium text-slate-700">Роль</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as User['role'])}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <label className="block text-sm font-medium text-slate-700">Лига</label>
          <select
            value={league}
            onChange={(e) => setLeague(e.target.value as User['league'])}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            {LEAGUES.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
          <label className="block text-sm font-medium text-slate-700">План (MPW)</label>
          <input
            type="number"
            min={1}
            value={mpw}
            onChange={(e) => setMpw(Number(e.target.value) || 0)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          {mode === 'create' && (
            <>
              <label className="block text-sm font-medium text-slate-700">Пароль * (мин. 6 символов)</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                minLength={6}
              />
            </>
          )}
          {validationError && (
            <p className="text-sm text-red-600">{validationError}</p>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy}
              className={cn(
                'rounded-md px-4 py-2 text-sm font-medium text-white',
                mode === 'create' ? 'bg-primary hover:opacity-90' : 'bg-slate-700 hover:bg-slate-800',
                'disabled:opacity-50'
              )}
            >
              {busy ? '...' : mode === 'create' ? 'Создать' : 'Сохранить'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
