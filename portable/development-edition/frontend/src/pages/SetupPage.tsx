import { useState } from 'react'
import { Eye, EyeOff, ShieldCheck } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'

export function SetupPage() {
  const { bootstrap, setup } = useAuth()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await bootstrap({ full_name: fullName.trim(), email: email.trim().toLowerCase(), password })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось завершить настройку')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <section className="w-full max-w-lg rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-blue-50 text-blue-700">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Первичная настройка</h1>
            <p className="text-sm text-slate-500">
              Каталог: {setup?.catalog_competencies ?? 0} компетенций, {setup?.catalog_questions ?? 0} вопросов
            </p>
          </div>
        </div>
        <form onSubmit={submit} className="mt-7 grid gap-4">
          <label className="text-sm font-medium text-slate-700">
            ФИО администратора
            <input required minLength={2} value={fullName} onChange={(event) => setFullName(event.target.value)} className="mt-1.5 w-full rounded-md border border-slate-200 px-3 py-2.5 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <label className="text-sm font-medium text-slate-700">
            Электронная почта
            <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1.5 w-full rounded-md border border-slate-200 px-3 py-2.5 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
          </label>
          <div className="text-sm font-medium text-slate-700">
            <label htmlFor="setup-password">Пароль</label>
            <span className="relative mt-1.5 block">
              <input id="setup-password" required minLength={10} type={revealed ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2.5 pr-11 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
              <button type="button" aria-label="Показать пароль при удержании" onPointerDown={() => setRevealed(true)} onPointerUp={() => setRevealed(false)} onPointerLeave={() => setRevealed(false)} className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-slate-400 hover:text-slate-700">
                {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </span>
            <span className="mt-1 block text-xs font-normal text-slate-500">Не менее 10 символов: заглавная, строчная буква и цифра.</span>
          </div>
          {error && <p className="whitespace-pre-line text-sm text-rose-600">{error}</p>}
          <button disabled={submitting} className="mt-2 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {submitting ? 'Создание...' : 'Создать администратора'}
          </button>
        </form>
      </section>
    </main>
  )
}
