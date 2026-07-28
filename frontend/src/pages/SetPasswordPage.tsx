import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { api } from '@/api/client'
import { PasswordRevealButton } from '@/components/PasswordRevealButton'
import { useAuth } from '@/contexts/AuthContext'
import { validatePassword } from '@/lib/passwordValidation'

export function SetPasswordPage() {
  const { user, loading, logout } = useAuth()
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [serverError, setServerError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setServerError(null)

    const validationErrors = validatePassword(newPassword)
    if (confirmPassword !== newPassword) {
      validationErrors.push('Пароли не совпадают')
    }
    setErrors(validationErrors)
    if (validationErrors.length > 0) return

    setSubmitting(true)
    try {
      await api.post('/api/auth/set-password', { new_password: newPassword })
      setSuccess(true)
      window.setTimeout(logout, 1200)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка сохранения пароля'
      setServerError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100">
        <p className="text-sm text-slate-500">Проверяем сессию...</p>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  if (!user.needs_password_change) return <Navigate to="/" replace />

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-lg">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold text-slate-900">Заменить временный пароль</h1>
          <p className="mt-1 text-sm text-slate-500">Придумайте собственный пароль для дальнейшего входа</p>
        </div>
        {success ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
            Пароль установлен. Все старые сессии завершены, сейчас откроется повторный вход.
          </div>
        ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
           <div>
             <label htmlFor="new_password" className="block text-sm font-medium text-slate-700">
               Новый пароль
             </label>
             <div className="relative">
               <input
                 id="new_password"
                 name="new_password"
                 type={showNewPassword ? 'text' : 'password'}
                 value={newPassword}
                 onChange={(e) => {
                   setNewPassword(e.target.value)
                   setErrors([])
                 }}
                 className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm"
                 placeholder="Минимум 8 символов"
                 autoComplete="new-password"
                 maxLength={128}
               />
               <PasswordRevealButton
                 revealed={showNewPassword}
                 onRevealChange={setShowNewPassword}
               />
             </div>
           </div>
           <div>
             <label htmlFor="confirm_password" className="block text-sm font-medium text-slate-700">
               Подтвердите пароль
             </label>
             <div className="relative">
               <input
                 id="confirm_password"
                 name="confirm_password"
                 type={showConfirmPassword ? 'text' : 'password'}
                 value={confirmPassword}
                 onChange={(e) => {
                   setConfirmPassword(e.target.value)
                   setErrors([])
                 }}
                 className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm"
                 placeholder="••••••••"
                 autoComplete="new-password"
                 maxLength={128}
               />
               <PasswordRevealButton
                 revealed={showConfirmPassword}
                 onRevealChange={setShowConfirmPassword}
               />
             </div>
           </div>
          {errors.length > 0 && (
            <ul className="space-y-1">
              {errors.map((err, i) => (
                <li key={i} className="text-sm text-red-600">{err}</li>
              ))}
            </ul>
          )}
          {serverError && <p className="text-sm text-red-600">{serverError}</p>}
          <div className="rounded-md bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600 space-y-1">
            <p>Требования к паролю:</p>
            <ul className="ml-4 list-disc space-y-0.5">
              <li>Минимум 8 символов</li>
              <li>Хотя бы одна заглавная буква (A-Z)</li>
              <li>Хотя бы одна строчная буква (a-z)</li>
              <li>Хотя бы одна цифра (0-9)</li>
            </ul>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? 'Сохранение...' : 'Установить пароль'}
          </button>
        </form>
        )}
      </div>
    </div>
  )
}
