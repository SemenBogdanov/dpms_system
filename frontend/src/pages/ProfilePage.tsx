import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { User, UserProgress, Task, QTransactionRead, LeagueEvaluation } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'
import { SkeletonCard } from '@/components/Skeleton'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 20

export function ProfilePage() {
  const [searchParams] = useSearchParams()
  const urlUserId = searchParams.get('user_id') ?? ''
  const { user: currentUser } = useAuth()
  const currentId = urlUserId || currentUser?.id || ''

  const [user, setUser] = useState<User | null>(null)
  const [progress, setProgress] = useState<UserProgress | null>(null)
  const [loading, setLoading] = useState(true)
  const [profileError, setProfileError] = useState<string | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [doneTasks, setDoneTasks] = useState<Task[]>([])
  const [transactions, setTransactions] = useState<QTransactionRead[]>([])
  const [transLimit, setTransLimit] = useState(PAGE_SIZE)
  const [walletFilter, setWalletFilter] = useState<'all' | 'main' | 'karma'>('all')
  const [directionFilter, setDirectionFilter] = useState<'all' | 'credit' | 'debit'>('all')
  const [leagueEval, setLeagueEval] = useState<LeagueEvaluation | null>(null)

  const loadProfile = useCallback(async () => {
    if (!currentId) {
      setUser(null)
      setProgress(null)
      setDoneTasks([])
      setTransactions([])
      setProfileError(null)
      return
    }
    setProfileError(null)
    setProfileLoading(true)
    try {
      const promises: [Promise<User>, Promise<UserProgress>, Promise<Task[]>, Promise<QTransactionRead[]>] = [
        api.get<User>(`/api/users/${currentId}`),
        api.get<UserProgress>(`/api/users/${currentId}/progress`),
        api.get<Task[]>(`/api/tasks?assignee_id=${currentId}&status=done`),
        api.get<QTransactionRead[]>(`/api/users/${currentId}/transactions`, {
          ...(walletFilter !== 'all' && { wallet_type: walletFilter }),
          ...(directionFilter !== 'all' && { direction: directionFilter }),
        }),
      ]
      const [u, p, tasks, trans] = await Promise.all(promises)
      setUser(u)
      setProgress(p)
      setDoneTasks(tasks)
      setTransactions(trans)
      if (currentUser?.role === 'admin' || currentUser?.role === 'teamlead') {
        api.get<LeagueEvaluation[]>('/api/admin/league-evaluation', { user_id: currentId })
          .then((r) => setLeagueEval(r[0] ?? null))
          .catch(() => setLeagueEval(null))
      } else {
        setLeagueEval(null)
      }
    } catch (e) {
      setUser(null)
      setProgress(null)
      setDoneTasks([])
      setTransactions([])
      setLeagueEval(null)
      setProfileError(e instanceof Error ? e.message : 'Ошибка загрузки профиля')
    } finally {
      setProfileLoading(false)
    }
  }, [currentId, walletFilter, directionFilter, currentUser?.role])

  useEffect(() => {
    loadProfile()
  }, [loadProfile])

  if (!currentId) return <SkeletonCard />
  if (loading && !user) return <SkeletonCard />

  const progressPercent = progress ? progress.percent : 0
  const progressColor =
    progressPercent < 50 ? 'bg-red-500' : progressPercent < 80 ? 'bg-amber-500' : 'bg-emerald-500'
  const shownTransactions = transactions.slice(0, transLimit)
  const hasMoreTransactions = transactions.length > transLimit

  const avgCompletionHours =
    doneTasks.length > 0
      ? doneTasks.reduce((sum, t) => {
          if (!t.started_at || !t.completed_at) return sum
          const s = new Date(t.started_at).getTime()
          const c = new Date(t.completed_at).getTime()
          return sum + (c - s) / (1000 * 60 * 60)
        }, 0) / doneTasks.length
      : null

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Профиль</h1>
      </div>

      {profileError && <div className="text-red-600">{profileError}</div>}
      {profileLoading && <p className="text-slate-500">Загрузка профиля...</p>}

      {user && !profileLoading && (
        <>
          {/* Карточка героя */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-center gap-4">
              <LeagueBadge league={user.league} className="text-lg px-4 py-2" />
              <div>
                <h2 className="text-xl font-semibold text-slate-900">{user.full_name}</h2>
                <p className="text-sm text-slate-500">{user.role}</p>
                {leagueEval && (
                  <div className="mt-2 text-sm text-slate-600">
                    <p>
                      {user.league === 'A'
                        ? 'Максимальная лига'
                        : `Следующая лига: ${leagueEval.suggested_league}`}
                    </p>
                    {leagueEval.history.length > 0 && (
                      <p>
                        Выполнение{' '}
                        {user.league === 'B' ? '95%+' : '90%+'} —{' '}
                        {leagueEval.history.filter((h) => h.percent >= (user.league === 'B' ? 95 : 90)).length} из 3 месяцев
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-4 min-w-[240px]">
              <div>
                <p className="text-sm font-medium text-slate-700">Main Wallet</p>
                <p className="text-sm text-slate-600">
                  {Number(user.wallet_main).toFixed(1)} / {user.mpw} Q
                </p>
                <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    className={cn('h-full transition-all', progressColor)}
                    style={{
                      width: `${Math.min(100, (user.mpw > 0 ? (user.wallet_main / user.mpw) * 100 : 0))}%`,
                    }}
                  />
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-700">Karma Wallet</p>
                <p className="text-lg font-semibold text-slate-900">⭐ {Number(user.wallet_karma).toFixed(1)} Q</p>
                <p className="text-xs text-slate-500">Свободные средства</p>
              </div>
            </div>
          </div>

          {/* Статистика — 4 карточки */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Задач завершено</p>
              <p className="text-2xl font-semibold text-slate-900">{doneTasks.length}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Среднее время</p>
              <p className="text-2xl font-semibold text-slate-900">
                {avgCompletionHours != null ? `${Number(avgCompletionHours / 24).toFixed(1)} д.` : '—'}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Текущий месяц (%)</p>
              <p className="text-2xl font-semibold text-slate-900">{progress?.percent != null ? `${Number(progress.percent).toFixed(0)}%` : '—'}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-medium text-slate-600">Лучший месяц</p>
              <p className="text-2xl font-semibold text-slate-900">—</p>
            </div>
          </div>

          {/* История операций */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="p-4 border-b border-slate-200 flex flex-wrap gap-4 items-center">
              <h2 className="font-medium text-slate-800">История операций</h2>
              <select
                value={walletFilter}
                onChange={(e) => setWalletFilter(e.target.value as 'all' | 'main' | 'karma')}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
              >
                <option value="all">Все кошельки</option>
                <option value="main">Main</option>
                <option value="karma">Karma</option>
              </select>
              <select
                value={directionFilter}
                onChange={(e) => setDirectionFilter(e.target.value as 'all' | 'credit' | 'debit')}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
              >
                <option value="all">Все</option>
                <option value="credit">Приход</option>
                <option value="debit">Расход</option>
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <th className="px-4 py-2 text-left font-medium text-slate-700">Дата</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-700">Сумма (Q)</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-700">Кошелёк</th>
                    <th className="px-4 py-2 text-left font-medium text-slate-700">Причина</th>
                  </tr>
                </thead>
                <tbody>
                  {shownTransactions.map((tx) => (
                    <tr key={tx.id} className="border-b border-slate-100">
                      <td className="px-4 py-2 text-slate-600">
                        {new Date(tx.created_at).toLocaleString('ru')}
                      </td>
                      <td
                        className={cn(
                          'px-4 py-2 font-medium',
                          tx.amount >= 0 ? 'text-emerald-600' : 'text-red-600'
                        )}
                      >
                        {tx.amount >= 0 ? '+' : ''}{Number(tx.amount).toFixed(1)}
                      </td>
                      <td className="px-4 py-2 text-slate-600">{tx.wallet_type}</td>
                      <td className="px-4 py-2 text-slate-600">{tx.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {transactions.length === 0 && !profileLoading && (
              <p className="p-4 text-slate-500 text-center">Нет операций</p>
            )}
            {hasMoreTransactions && (
              <div className="p-4 border-t border-slate-200 text-center">
                <button
                  type="button"
                  onClick={() => setTransLimit((n) => n + PAGE_SIZE)}
                  className="text-sm font-medium text-primary hover:underline"
                >
                  Показать ещё
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {!user && !profileError && !loading && !profileLoading && (
        <p className="text-slate-500">Выберите сотрудника в списке выше.</p>
      )}
    </div>
  )
}
