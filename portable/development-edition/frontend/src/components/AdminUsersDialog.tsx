import { useEffect, useState } from 'react'
import { Eye, EyeOff, Plus, Users, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { User, UserRole } from '@/api/types'

export function AdminUsersDialog({ open, currentUserId, onClose }: { open: boolean; currentUserId: string; onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([])
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<UserRole>('executor')
  const [constructorEnabled, setConstructorEnabled] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = async () => setUsers(await api.get<User[]>('/api/users'))

  useEffect(() => {
    if (open) void load().catch((error) => toast.error(error instanceof Error ? error.message : 'Не удалось загрузить сотрудников'))
  }, [open])

  if (!open) return null

  const createUser = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    try {
      await api.post<User>('/api/users', {
        full_name: fullName.trim(),
        email: email.trim().toLowerCase(),
        password,
        role,
        competency_constructor_enabled: constructorEnabled,
      })
      setFullName('')
      setEmail('')
      setPassword('')
      setRole('executor')
      setConstructorEnabled(false)
      await load()
      toast.success('Сотрудник добавлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить сотрудника')
    } finally {
      setSaving(false)
    }
  }

  const updateUser = async (user: User, patch: Record<string, unknown>) => {
    try {
      await api.patch<User>(`/api/users/${user.id}`, patch)
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить сотрудника')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm" role="presentation">
      <section role="dialog" aria-modal="true" aria-labelledby="users-title" className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-2xl">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <div className="flex items-center gap-3">
            <Users className="h-5 w-5 text-blue-600" />
            <h2 id="users-title" className="font-semibold text-slate-900">Сотрудники</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Закрыть" className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="grid gap-6 p-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <form onSubmit={createUser} className="space-y-4 border-b border-slate-200 pb-6 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-6">
            <h3 className="text-sm font-semibold text-slate-900">Новый сотрудник</h3>
            <input required minLength={2} placeholder="ФИО" value={fullName} onChange={(event) => setFullName(event.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            <input required type="email" placeholder="Электронная почта" value={email} onChange={(event) => setEmail(event.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
            <div className="relative">
              <input required minLength={10} type={revealed ? 'text' : 'password'} placeholder="Первичный пароль" value={password} onChange={(event) => setPassword(event.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2 pr-10 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
              <button type="button" aria-label="Показать пароль при удержании" onPointerDown={() => setRevealed(true)} onPointerUp={() => setRevealed(false)} onPointerLeave={() => setRevealed(false)} className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400">
                {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <select value={role} onChange={(event) => setRole(event.target.value as UserRole)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm">
              <option value="executor">Сотрудник</option>
              <option value="teamlead">Руководитель</option>
              <option value="admin">Администратор</option>
            </select>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={constructorEnabled} onChange={(event) => setConstructorEnabled(event.target.checked)} />
              Доступ к конструктору
            </label>
            <button disabled={saving} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              <Plus className="h-4 w-4" />
              Добавить
            </button>
          </form>

          <div className="min-w-0">
            <h3 className="mb-3 text-sm font-semibold text-slate-900">Учетные записи</h3>
            <div className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {users.map((user) => (
                <div key={user.id} className="grid gap-3 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900">{user.full_name}</div>
                    <div className="truncate text-xs text-slate-500">{user.email}</div>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input type="checkbox" checked={user.competency_constructor_enabled || user.role === 'admin'} disabled={user.role === 'admin'} onChange={(event) => void updateUser(user, { competency_constructor_enabled: event.target.checked })} />
                    Конструктор
                  </label>
                  <label className="flex items-center gap-2 text-xs text-slate-600">
                    <input type="checkbox" checked={user.is_active} disabled={user.id === currentUserId} onChange={(event) => void updateUser(user, { is_active: event.target.checked })} />
                    Активен
                  </label>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
