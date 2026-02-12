import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User } from '@/api/types'

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<User[]>('/api/users')
      .then(setUsers)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Сотрудники</h1>
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">ФИО</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Email</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Лига</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Роль</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">План (Q)</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-600">Баланс</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {users.map((u) => (
              <tr key={u.id} className="bg-white">
                <td className="px-4 py-3 text-sm text-slate-900">{u.full_name}</td>
                <td className="px-4 py-3 text-sm text-slate-600">{u.email}</td>
                <td className="px-4 py-3 text-sm">{u.league}</td>
                <td className="px-4 py-3 text-sm">{u.role}</td>
                <td className="px-4 py-3 text-sm">{u.mpw}</td>
                <td className="px-4 py-3 text-sm">{u.wallet_main} / {u.wallet_karma} karma</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
