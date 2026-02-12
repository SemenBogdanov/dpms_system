import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User, UserProgress } from '@/api/types'

const FALLBACK_USER_ID = ''

export function ProfilePage() {
  const [user, setUser] = useState<User | null>(null)
  const [progress, setProgress] = useState<UserProgress | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [currentId, setCurrentId] = useState(FALLBACK_USER_ID)
  const [loading, setLoading] = useState(true)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)

  useEffect(() => {
    api.get<User[]>('/api/users').then((list) => {
      setUsers(list)
      if (list.length && !currentId) setCurrentId(list[0].id)
    }).catch(() => setUsers([])).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!currentId) {
      setUser(null)
      setProgress(null)
      setProfileError(null)
      setProfileLoading(false)
      return
    }
    setProfileError(null)
    setProfileLoading(true)
    Promise.all([
      api.get<User>(`/api/users/${currentId}`),
      api.get<UserProgress>(`/api/users/${currentId}/progress`),
    ]).then(([u, p]) => {
      setUser(u)
      setProgress(p)
    }).catch((e) => {
      setUser(null)
      setProgress(null)
      setProfileError(e instanceof Error ? e.message : 'Ошибка загрузки профиля')
    }).finally(() => setProfileLoading(false))
  }, [currentId])

  if (loading) return <div className="text-slate-500">Загрузка...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Профиль</h1>
        {users.length > 0 && (
          <select
            value={currentId}
            onChange={(e) => setCurrentId(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </select>
        )}
      </div>
      {profileError && <div className="text-red-600">{profileError}</div>}
      {user && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="font-medium text-slate-800">{user.full_name}</p>
          <p className="text-sm text-slate-500">{user.email}</p>
          <p className="mt-2 text-sm">Лига: {user.league} · Роль: {user.role}</p>
          <p className="mt-2 text-sm">План на месяц: {user.mpw} Q · WIP-лимит: {user.wip_limit}</p>
          {progress != null && (
            <div className="mt-4 pt-4 border-t border-slate-200">
              <p className="text-sm font-medium text-slate-700">Баланс</p>
              <p className="text-lg font-semibold text-slate-900">
                {(Number(progress.earned) ?? 0).toFixed(1)} / {(Number(progress.target) ?? 0).toFixed(0)} Q ({(Number(progress.percent) ?? 0).toFixed(0)}%)
              </p>
              <p className="text-sm text-slate-500">Карма: {(Number(progress.karma) ?? 0).toFixed(1)} Q</p>
            </div>
          )}
        </div>
      )}
      {profileLoading && <p className="text-slate-500">Загрузка профиля...</p>}
      {!user && !profileError && !loading && !profileLoading && <p className="text-slate-500">Выберите сотрудника в списке выше.</p>}
    </div>
  )
}
