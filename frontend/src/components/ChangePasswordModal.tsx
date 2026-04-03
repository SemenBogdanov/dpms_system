import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { api } from '@/api/client'
import { validatePassword } from '@/lib/passwordValidation'

interface ChangePasswordModalProps {
  open: boolean
  onClose: () => void
}

export function ChangePasswordModal({ open, onClose }: ChangePasswordModalProps) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [serverError, setServerError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [success, setSuccess] = useState(false)

  const resetForm = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setShowCurrentPassword(false)
    setShowNewPassword(false)
    setShowConfirmPassword(false)
    setErrors([])
    setServerError(null)
    setSuccess(false)
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setServerError(null)

    const validationErrors = validatePassword(newPassword)
    if (newPassword !== confirmPassword) {
      validationErrors.push('Пароли не совпадают')
    }
    setErrors(validationErrors)
    if (validationErrors.length > 0) return

    setBusy(true)
    try {
      await api.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      setSuccess(true)
      setTimeout(() => {
        handleClose()
      }, 1500)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Ошибка при смене пароля'
      setServerError(msg)
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
      onClick={(e) => e.target === e.currentTarget && handleClose()}
      onKeyDown={(e) => e.key === 'Escape' && handleClose()}
    >
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Сменить пароль</h3>
        {success ? (
          <p className="mt-4 text-sm text-emerald-600">Пароль успешно изменён!</p>
        ) : (
          <form onSubmit={handleSubmit} className="mt-4 space-y-3">
             <div>
               <label className="block text-sm font-medium text-slate-700">Текущий пароль</label>
               <div className="relative">
                 <input
                   type={showCurrentPassword ? 'text' : 'password'}
                   name="current_password"
                   value={currentPassword}
                   onChange={(e) => {
                     setCurrentPassword(e.target.value)
                     setServerError(null)
                   }}
                   className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm"
                   autoComplete="current-password"
                 />
                 <button
                   type="button"
                   onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                   className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                   tabIndex={-1}
                 >
                   {showCurrentPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                 </button>
               </div>
             </div>
             <div>
               <label className="block text-sm font-medium text-slate-700">Новый пароль</label>
               <div className="relative">
                 <input
                   type={showNewPassword ? 'text' : 'password'}
                   name="new_password"
                   value={newPassword}
                   onChange={(e) => {
                     setNewPassword(e.target.value)
                     setErrors([])
                   }}
                   className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm"
                   autoComplete="new-password"
                 />
                 <button
                   type="button"
                   onClick={() => setShowNewPassword(!showNewPassword)}
                   className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                   tabIndex={-1}
                 >
                   {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                 </button>
               </div>
             </div>
             <div>
               <label className="block text-sm font-medium text-slate-700">Подтвердите новый пароль</label>
               <div className="relative">
                 <input
                   type={showConfirmPassword ? 'text' : 'password'}
                   name="confirm_password"
                   value={confirmPassword}
                   onChange={(e) => {
                     setConfirmPassword(e.target.value)
                     setErrors([])
                   }}
                   className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 pr-10 text-sm"
                   autoComplete="new-password"
                 />
                 <button
                   type="button"
                   onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                   className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                   tabIndex={-1}
                 >
                   {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                 </button>
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
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {busy ? '...' : 'Сменить'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
