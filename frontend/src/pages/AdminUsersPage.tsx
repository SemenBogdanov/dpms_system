import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User, PeriodHistoryItem, LeagueEvaluation, LeagueChange } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'
import { UserModal, type UserFormPayload } from '@/components/UserModal'
import toast from 'react-hot-toast'
import { cn } from '@/lib/utils'

const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

export function AdminUsersPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [periodHistory, setPeriodHistory] = useState<PeriodHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rolloverConfirm, setRolloverConfirm] = useState(false)
  const [rolloverInput, setRolloverInput] = useState('')
  const [rolloverBusy, setRolloverBusy] = useState(false)
  const [leagueEvaluations, setLeagueEvaluations] = useState<LeagueEvaluation[]>([])
  const [leagueEvalLoading, setLeagueEvalLoading] = useState(false)
  const [applyLeagueBusy, setApplyLeagueBusy] = useState(false)
  const [userModalOpen, setUserModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  const loadUsers = useCallback(() => {
    api.get<User[]>('/api/users')
      .then(setUsers)
      .catch((e) => setError(e instanceof Error ? e.message : 'Ошибка'))
      .finally(() => setLoading(false))
  }, [])

  const loadHistory = useCallback(() => {
    api.get<PeriodHistoryItem[]>('/api/admin/period-history').then(setPeriodHistory).catch(() => setPeriodHistory([]))
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const now = new Date()
  const currentPeriodLabel = `${MONTHS[now.getMonth()]} ${now.getFullYear()}`
  const selectedAdminId = currentUser?.id ?? ''

  const handleRolloverClick = () => {
    if (!window.confirm('Вы уверены? Это обнулит wallet_main всех сотрудников и спишет 50% кармы. Действие необратимо.')) return
    setRolloverConfirm(true)
    setRolloverInput('')
  }

  const loadLeagueEvaluation = useCallback(() => {
    setLeagueEvalLoading(true)
    api
      .get<LeagueEvaluation[]>('/api/admin/league-evaluation')
      .then(setLeagueEvaluations)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : 'Ошибка оценки лиг')
        setLeagueEvaluations([])
      })
      .finally(() => setLeagueEvalLoading(false))
  }, [])

  const handleApplyLeagueChanges = () => {
    const eligibleCount = leagueEvaluations.filter((e) => e.eligible && e.suggested_league !== e.current_league).length
    if (eligibleCount === 0) return
    if (!window.confirm(`Будут изменены лиги ${eligibleCount} сотрудников. Подтвердить?`)) return
    if (!selectedAdminId) {
      toast.error('Требуется авторизация')
      return
    }
    setApplyLeagueBusy(true)
    api
      .post<LeagueChange[]>('/api/admin/apply-league-changes', { admin_id: selectedAdminId })
      .then((changes) => {
        toast.success(`Изменено лиг: ${changes.length}. ${changes.map((c) => `${c.full_name}: ${c.old_league} → ${c.new_league}`).join('; ')}`)
        loadUsers()
        loadLeagueEvaluation()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка применения'))
      .finally(() => setApplyLeagueBusy(false))
  }

  const handleRolloverSubmit = () => {
    if (rolloverInput.trim() !== 'ROLLOVER') {
      toast.error('Введите ROLLOVER для подтверждения')
      return
    }
    if (!selectedAdminId) {
      toast.error('Требуется авторизация')
      return
    }
    setRolloverBusy(true)
    api
      .post<{ period: string; users_processed: number; total_main_reset: number; total_karma_burned: number }>(
        '/api/admin/rollover-period',
        { admin_id: selectedAdminId }
      )
      .then((res) => {
        toast.success(
          `Период ${res.period} закрыт. Обработано: ${res.users_processed}, Main обнулено: ${res.total_main_reset}, Karma списано: ${res.total_karma_burned}`
        )
        setRolloverConfirm(false)
        setRolloverInput('')
        loadHistory()
        loadUsers()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка rollover'))
      .finally(() => setRolloverBusy(false))
  }

  const handleUserSubmit = async (payload: UserFormPayload) => {
    if (editingUser) {
      await api.patch(`/api/users/${editingUser.id}`, {
        full_name: payload.full_name,
        email: payload.email,
        role: payload.role,
        league: payload.league,
        mpw: payload.mpw,
      })
      toast.success('Изменения сохранены')
    } else {
      await api.post<User>('/api/users', {
        full_name: payload.full_name,
        email: payload.email,
        role: payload.role,
        league: payload.league,
        mpw: payload.mpw,
        password: payload.password,
      })
      toast.success('Сотрудник добавлен')
    }
    loadUsers()
  }

  const handleDeactivate = (u: User) => {
    if (!window.confirm(`Деактивировать ${u.full_name}?`)) return
    api.patch(`/api/users/${u.id}`, { is_active: false }).then(() => {
      toast.success('Сотрудник деактивирован')
      loadUsers()
    }).catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  const handleRestore = (u: User) => {
    api.patch(`/api/users/${u.id}`, { is_active: true }).then(() => {
      toast.success('Сотрудник восстановлен')
      loadUsers()
    }).catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка'))
  }

  const roleBadgeClass: Record<string, string> = {
    admin: 'bg-red-100 text-red-800',
    teamlead: 'bg-blue-100 text-blue-800',
    executor: 'bg-slate-100 text-slate-700',
  }

  if (loading) return <div className="text-slate-500">Загрузка...</div>
  if (error) return <div className="text-red-600">{error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-900">Сотрудники</h1>

      {/* Управление сотрудниками */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="font-medium text-slate-800">Управление сотрудниками</h2>
          {currentUser?.role === 'admin' && (
            <button
              type="button"
              onClick={() => { setEditingUser(null); setUserModalOpen(true) }}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              + Добавить сотрудника
            </button>
          )}
        </div>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">ФИО</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Email</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Роль</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Лига</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">MPW</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Статус</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {users.map((u) => (
                <tr
                  key={u.id}
                  className={cn(
                    'bg-white',
                    !u.is_active && 'bg-slate-50 opacity-75'
                  )}
                >
                  <td className="px-4 py-3 text-slate-900">{u.full_name}</td>
                  <td className="px-4 py-3 text-slate-600">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className={cn('rounded px-2 py-0.5 text-xs font-medium', roleBadgeClass[u.role] ?? 'bg-slate-100')}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3"><LeagueBadge league={u.league} /></td>
                  <td className="px-4 py-3">{u.mpw}</td>
                  <td className="px-4 py-3">{u.is_active ? 'Активен' : 'Неактивен'}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => { setEditingUser(u); setUserModalOpen(true) }}
                        className="text-slate-500 hover:text-slate-700"
                        title="Редактировать"
                      >
                        ✏️
                      </button>
                      {u.is_active ? (
                        <button
                          type="button"
                          onClick={() => handleDeactivate(u)}
                          className="text-slate-500 hover:text-red-600"
                          title="Деактивировать"
                        >
                          🗑️
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleRestore(u)}
                          className="text-slate-500 hover:text-emerald-600"
                          title="Восстановить"
                        >
                          ♻️ Восстановить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
        <h2 className="font-medium text-amber-800">Управление периодом</h2>
        <p className="mt-1 text-sm text-slate-600">Текущий период: {currentPeriodLabel}</p>
        {currentUser?.role === 'admin' && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleRolloverClick}
              className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
            >
              ⚠️ Закрыть период
            </button>
          </div>
        )}
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <h3 className="border-b border-slate-200 px-4 py-2 text-sm font-medium text-slate-700">История периодов</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-4 py-2 text-left font-medium text-slate-600">Период</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Дата закрытия</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Сотрудников</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Main обнулено</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Karma списано</th>
              </tr>
            </thead>
            <tbody>
              {periodHistory.map((h) => (
                <tr key={h.period} className="border-b border-slate-100">
                  <td className="px-4 py-2">{h.period}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {h.closed_at ? new Date(h.closed_at).toLocaleString('ru') : '—'}
                  </td>
                  <td className="px-4 py-2">{h.users_count}</td>
                  <td className="px-4 py-2">{Number(h.total_main_reset).toFixed(1)}</td>
                  <td className="px-4 py-2">{Number(h.total_karma_burned).toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {periodHistory.length === 0 && <p className="p-4 text-slate-500 text-center">Нет закрытых периодов</p>}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="font-medium text-slate-800">Оценка лиг</h2>
        <p className="mt-1 text-sm text-slate-600">Повышение/понижение лиг по снимкам периодов</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={loadLeagueEvaluation}
            disabled={leagueEvalLoading}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {leagueEvalLoading ? '...' : 'Рассчитать изменения лиг'}
          </button>
          {leagueEvaluations.some((e) => e.eligible && e.suggested_league !== e.current_league) && (
            <button
              type="button"
              onClick={handleApplyLeagueChanges}
              disabled={applyLeagueBusy}
              className="rounded-lg border border-amber-400 bg-amber-100 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-200 disabled:opacity-50"
            >
              {applyLeagueBusy ? '...' : 'Применить изменения'}
            </button>
          )}
        </div>
        {leagueEvaluations.length > 0 && (
          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  <th className="px-4 py-2 text-left font-medium text-slate-600">ФИО</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Текущая</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Предложена</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Причина</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-600">Статус</th>
                </tr>
              </thead>
              <tbody>
                {leagueEvaluations.map((ev) => {
                  const hasChange = ev.eligible && ev.suggested_league !== ev.current_league
                  return (
                    <tr
                      key={ev.user_id}
                      className={hasChange ? 'bg-amber-50' : 'bg-white'}
                    >
                      <td className="px-4 py-2 text-slate-900">{ev.full_name}</td>
                      <td className="px-4 py-2">{ev.current_league}</td>
                      <td className="px-4 py-2">{ev.suggested_league}</td>
                      <td className="px-4 py-2 text-slate-600">{ev.reason}</td>
                      <td className="px-4 py-2">{hasChange ? 'Рекомендовано' : 'Без изменений'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <UserModal
        mode={editingUser ? 'edit' : 'create'}
        initial={editingUser}
        open={userModalOpen}
        onClose={() => { setUserModalOpen(false); setEditingUser(null) }}
        onSubmit={handleUserSubmit}
      />

      {rolloverConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setRolloverConfirm(false)}
        >
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-900">Подтверждение закрытия периода</h3>
            <p className="mt-2 text-sm text-slate-600">Введите "ROLLOVER" для подтверждения</p>
            <input
              type="text"
              value={rolloverInput}
              onChange={(e) => setRolloverInput(e.target.value)}
              className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="ROLLOVER"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRolloverConfirm(false)}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleRolloverSubmit}
                disabled={rolloverBusy || rolloverInput.trim() !== 'ROLLOVER'}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {rolloverBusy ? '...' : 'Закрыть период'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
