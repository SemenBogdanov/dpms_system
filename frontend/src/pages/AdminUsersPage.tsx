import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { User, PeriodHistoryItem, LeagueEvaluation, LeagueChange, RolloverResponse } from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { LeagueBadge } from '@/components/LeagueBadge'
import { UserModal, type UserFormPayload } from '@/components/UserModal'
import toast from 'react-hot-toast'
import { cn } from '@/lib/utils'
import { Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'

const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

const ROLLOVER_CONFIRM_TEXT = 'ROLLOVER'
const CANCEL_CONFIRM_TEXT = 'CANCEL'

function monthInputValue(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function previousMonthValue(date = new Date()) {
  return monthInputValue(new Date(date.getFullYear(), date.getMonth() - 1, 1))
}

export function AdminUsersPage() {
  const { user: currentUser } = useAuth()
  const [users, setUsers] = useState<User[]>([])
  const [periodHistory, setPeriodHistory] = useState<PeriodHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rolloverConfirm, setRolloverConfirm] = useState(false)
  const [rolloverInput, setRolloverInput] = useState('')
  const [rolloverBusy, setRolloverBusy] = useState(false)
  const [rolloverMode, setRolloverMode] = useState<'manual' | 'auto'>('manual')
  const [periodToClose, setPeriodToClose] = useState(() => previousMonthValue())
  const [cancelPeriod, setCancelPeriod] = useState<PeriodHistoryItem | null>(null)
  const [cancelInput, setCancelInput] = useState('')
  const [cancelBusy, setCancelBusy] = useState(false)
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

  const handleRolloverClick = (mode: 'manual' | 'auto') => {
    if (mode === 'auto') {
      setPeriodToClose(previousMonthValue())
    }
    setRolloverMode(mode)
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
    if (rolloverInput.trim() !== ROLLOVER_CONFIRM_TEXT) {
      toast.error(`Введите ${ROLLOVER_CONFIRM_TEXT} для подтверждения`)
      return
    }
    if (rolloverMode === 'manual' && !periodToClose) {
      toast.error('Выберите период')
      return
    }
    if (!selectedAdminId) {
      toast.error('Требуется авторизация')
      return
    }
    setRolloverBusy(true)
    const request = rolloverMode === 'auto'
      ? api.post<RolloverResponse>('/api/admin/period-close/auto', { admin_id: selectedAdminId })
      : api.post<RolloverResponse>('/api/admin/rollover-period', {
        admin_id: selectedAdminId,
        period: periodToClose,
        mode: 'manual',
      })

    request
      .then((res) => {
        toast.success(
          `Период ${res.period} закрыт. Обработано: ${res.users_processed}, закрыто Main: ${res.total_main_reset}, сверхплан сохранён`
        )
        setRolloverConfirm(false)
        setRolloverInput('')
        loadHistory()
        loadUsers()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка rollover'))
      .finally(() => setRolloverBusy(false))
  }

  const handleCancelSubmit = () => {
    if (!cancelPeriod) return
    if (cancelInput.trim() !== CANCEL_CONFIRM_TEXT) {
      toast.error(`Введите ${CANCEL_CONFIRM_TEXT} для подтверждения`)
      return
    }
    if (!selectedAdminId) {
      toast.error('Требуется авторизация')
      return
    }
    setCancelBusy(true)
    api
      .post<RolloverResponse>(`/api/admin/period-history/${cancelPeriod.period}/cancel`, { admin_id: selectedAdminId })
      .then((res) => {
        toast.success(`Закрытие периода ${res.period} отменено. Восстановлено Main: ${res.total_main_reset}`)
        setCancelPeriod(null)
        setCancelInput('')
        loadHistory()
        loadUsers()
      })
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка отмены закрытия'))
      .finally(() => setCancelBusy(false))
  }

  const handleUserSubmit = async (payload: UserFormPayload) => {
    if (editingUser) {
      await api.patch(`/api/users/${editingUser.id}`, {
        full_name: payload.full_name,
        email: payload.email,
        role: payload.role,
        league: payload.league,
        mpw: payload.mpw,
        is_new_employee: payload.is_new_employee,
        task_workspace_enabled: payload.task_workspace_enabled,
        feedback_enabled: payload.feedback_enabled,
        competency_development_enabled: payload.competency_development_enabled,
        competency_constructor_enabled: payload.competency_constructor_enabled,
      })
      toast.success('Изменения сохранены')
    } else {
      await api.post<User>('/api/users', {
        full_name: payload.full_name,
        email: payload.email,
        role: payload.role,
        league: payload.league,
        mpw: payload.mpw,
        is_new_employee: payload.is_new_employee,
        task_workspace_enabled: payload.task_workspace_enabled,
        feedback_enabled: payload.feedback_enabled,
        competency_development_enabled: payload.competency_development_enabled,
        competency_constructor_enabled: payload.competency_constructor_enabled,
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

  const formatDate = (value: string | null) => (value ? new Date(value).toLocaleDateString('ru') : '')
  const periodActionLabel = rolloverMode === 'auto' ? 'автоматически закрыть прошлый месяц' : `закрыть период ${periodToClose}`
  const isOnboardingActive = (u: User) =>
    u.is_new_employee && (!u.onboarding_until || new Date(u.onboarding_until).getTime() > Date.now())

  const roleBadgeClass: Record<string, string> = {
    admin: 'bg-red-100 text-red-800',
    teamlead: 'bg-blue-100 text-blue-800',
    executor: 'bg-slate-100 text-slate-700',
  }

  const accessBadgeClass = (enabled: boolean, enabledClass: string) =>
    cn(
      'rounded px-2 py-0.5 text-xs font-medium',
      enabled ? enabledClass : 'bg-slate-100 text-slate-500'
    )

  const renderAccessBadges = (u: User) => (
    <div className="flex flex-wrap gap-1.5">
      <span className={accessBadgeClass(u.task_workspace_enabled, 'bg-sky-50 text-sky-700')}>
        Задачи: {u.task_workspace_enabled ? 'вкл' : 'выкл'}
      </span>
      <span className={accessBadgeClass(u.feedback_enabled, 'bg-emerald-50 text-emerald-700')}>
        ОС: {u.feedback_enabled ? 'вкл' : 'выкл'}
      </span>
      <span className={accessBadgeClass(u.competency_development_enabled, 'bg-blue-50 text-blue-700')}>
        Развитие: {u.competency_development_enabled ? 'вкл' : 'выкл'}
      </span>
      {u.competency_constructor_enabled && (
        <span className="rounded bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">Конструктор</span>
      )}
    </div>
  )

  const renderUserActions = (u: User, mobile = false) => (
    <div className={cn('flex items-center gap-2', mobile && 'justify-end')}>
      <button
        type="button"
        onClick={() => { setEditingUser(u); setUserModalOpen(true) }}
        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
        title="Редактировать"
        aria-label={`Редактировать ${u.full_name}`}
      >
        <Pencil className="h-4 w-4" />
      </button>
      {u.is_active ? (
        <button
          type="button"
          onClick={() => handleDeactivate(u)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
          title="Деактивировать"
          aria-label={`Деактивировать ${u.full_name}`}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => handleRestore(u)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-600"
          title="Восстановить"
          aria-label={`Восстановить ${u.full_name}`}
        >
          <RotateCcw className="h-4 w-4" />
        </button>
      )}
    </div>
  )

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
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              <Plus className="h-4 w-4" />
              Добавить сотрудника
            </button>
          )}
        </div>
        <div className="mt-4 grid gap-3 lg:hidden">
          {users.map((u) => (
            <article
              key={u.id}
              className={cn(
                'rounded-lg border border-slate-200 bg-white p-3 shadow-sm',
                !u.is_active && 'bg-slate-50 opacity-75'
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-medium text-slate-900">{u.full_name}</h3>
                  <p className="mt-1 truncate text-xs text-slate-500">{u.email}</p>
                </div>
                {renderUserActions(u, true)}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className={cn('rounded px-2 py-0.5 text-xs font-medium', roleBadgeClass[u.role] ?? 'bg-slate-100')}>
                  {u.role}
                </span>
                <LeagueBadge league={u.league} />
                <span
                  className={cn(
                    'rounded px-2 py-0.5 text-xs font-medium',
                    u.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'
                  )}
                >
                  {u.is_active ? 'Активен' : 'Неактивен'}
                </span>
                {isOnboardingActive(u) && (
                  <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Новый</span>
                )}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
                <div className="rounded-md bg-slate-50 px-2 py-1.5">MPW: {u.mpw} Q</div>
                <div className="rounded-md bg-slate-50 px-2 py-1.5">QS: {Number(u.quality_score).toFixed(0)}%</div>
              </div>
              <div className="mt-3">{renderAccessBadges(u)}</div>
            </article>
          ))}
        </div>
        <div className="mt-4 hidden overflow-x-auto rounded-lg border border-slate-200 lg:block">
          <table className="min-w-[1120px] text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-slate-600">ФИО</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Email</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Роль</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Лига</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">MPW</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">QS</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Статус</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Задачи</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">ОС</th>
                <th className="px-4 py-3 text-left font-medium text-slate-600">Развитие</th>
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
                  <td className="px-4 py-3">
                    <div className="flex flex-col">
                      <span>{u.mpw} Q</span>
                      {isOnboardingActive(u) && (
                        <span className="text-xs text-slate-500">адаптация до {formatDate(u.onboarding_until)}</span>
                      )}
                      {u.is_new_employee && !isOnboardingActive(u) && (
                        <span className="text-xs text-slate-500">адаптация завершена</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        'inline-flex rounded-full px-2 py-0.5 text-xs font-medium',
                        u.quality_score >= 90
                          ? 'bg-emerald-50 text-emerald-700'
                          : u.quality_score >= 70
                          ? 'bg-amber-50 text-amber-700'
                          : u.quality_score >= 50
                          ? 'bg-orange-50 text-orange-700'
                          : 'bg-red-50 text-red-700'
                      )}
                    >
                      {Number(u.quality_score).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      <span>{u.is_active ? 'Активен' : 'Неактивен'}</span>
                      {isOnboardingActive(u) && (
                        <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Новый</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={accessBadgeClass(u.task_workspace_enabled, 'bg-sky-50 text-sky-700')}>
                      {u.task_workspace_enabled ? 'Вкл' : 'Выкл'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={accessBadgeClass(u.feedback_enabled, 'bg-emerald-50 text-emerald-700')}>
                      {u.feedback_enabled ? 'Вкл' : 'Выкл'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {u.competency_development_enabled ? (
                        <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Доступ</span>
                      ) : (
                        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Нет</span>
                      )}
                      {u.competency_constructor_enabled && (
                        <span className="rounded bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700">Конструктор</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {renderUserActions(u)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="font-medium text-amber-800">Управление периодом</h2>
            <p className="mt-1 text-sm text-slate-600">
              Текущий период: {currentPeriodLabel}. При закрытии списывается только базовый план, сверхплан сохраняется.
            </p>
          </div>
          <span className="w-fit rounded-full border border-amber-200 bg-white/80 px-3 py-1 text-xs font-medium text-amber-700">
            ID 47
          </span>
        </div>
        {currentUser?.role === 'admin' && (
          <div className="mt-4 grid gap-3 rounded-lg border border-amber-200 bg-white/80 p-3 md:grid-cols-[minmax(180px,240px)_1fr]">
            <label className="text-sm font-medium text-slate-700">
              Выбранный период
              <input
                type="month"
                value={periodToClose}
                onChange={(e) => setPeriodToClose(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-200"
              />
            </label>
            <div className="flex flex-wrap items-end gap-2">
              <button
                type="button"
                onClick={() => handleRolloverClick('manual')}
                className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
              >
                Закрыть выбранный период
              </button>
              <button
                type="button"
                onClick={() => handleRolloverClick('auto')}
                className="rounded-lg border border-amber-300 bg-amber-100 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-200"
              >
                Автозакрыть прошлый месяц
              </button>
            </div>
          </div>
        )}
        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <h3 className="border-b border-slate-200 px-4 py-2 text-sm font-medium text-slate-700">История периодов</h3>
          <table className="min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50">
                <th className="px-4 py-2 text-left font-medium text-slate-600">Период</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Статус</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Режим</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Дата закрытия</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Дата отмены</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Сотрудников</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Main закрыто</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Karma списано</th>
                <th className="px-4 py-2 text-right font-medium text-slate-600">Действие</th>
              </tr>
            </thead>
            <tbody>
              {periodHistory.map((h) => (
                <tr key={h.period} className="border-b border-slate-100">
                  <td className="px-4 py-2 font-medium text-slate-900">{h.period}</td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        'rounded-full px-2 py-1 text-xs font-medium',
                        h.status === 'cancelled'
                          ? 'bg-slate-100 text-slate-600'
                          : 'bg-emerald-50 text-emerald-700'
                      )}
                    >
                      {h.status === 'cancelled' ? 'Отменён' : 'Закрыт'}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {h.mode === 'auto' ? 'Авто' : h.mode === 'legacy' ? 'Legacy' : 'Вручную'}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {h.closed_at ? new Date(h.closed_at).toLocaleString('ru') : '—'}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {h.cancelled_at ? new Date(h.cancelled_at).toLocaleString('ru') : '—'}
                  </td>
                  <td className="px-4 py-2">{h.users_count}</td>
                  <td className="px-4 py-2">{Number(h.total_main_reset).toFixed(1)}</td>
                  <td className="px-4 py-2">{Number(h.total_karma_burned).toFixed(1)}</td>
                  <td className="px-4 py-2 text-right">
                    {h.status === 'closed' ? (
                      <button
                        type="button"
                        onClick={() => { setCancelPeriod(h); setCancelInput('') }}
                        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      >
                        Отменить
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
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
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-[820px] text-sm">
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
            <p className="mt-2 text-sm text-slate-600">
              Будет выполнено действие: {periodActionLabel}. Списывается только базовый план; баллы сверх плана сохраняются.
            </p>
            <p className="mt-2 text-sm text-slate-600">
              Введите "{ROLLOVER_CONFIRM_TEXT}" для подтверждения.
            </p>
            <input
              type="text"
              value={rolloverInput}
              onChange={(e) => setRolloverInput(e.target.value)}
              className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder={ROLLOVER_CONFIRM_TEXT}
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
                disabled={rolloverBusy || rolloverInput.trim() !== ROLLOVER_CONFIRM_TEXT}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {rolloverBusy ? '...' : 'Закрыть период'}
              </button>
            </div>
          </div>
        </div>
      )}

      {cancelPeriod && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => e.key === 'Escape' && setCancelPeriod(null)}
        >
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-slate-900">Отмена закрытия периода</h3>
            <p className="mt-2 text-sm text-slate-600">
              Период {cancelPeriod.period} будет открыт обратно: снимки удалятся, а списанные по базовому плану Main будут восстановлены обратными транзакциями.
            </p>
            <p className="mt-2 text-sm text-slate-600">
              Введите "{CANCEL_CONFIRM_TEXT}" для подтверждения.
            </p>
            <input
              type="text"
              value={cancelInput}
              onChange={(e) => setCancelInput(e.target.value)}
              className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder={CANCEL_CONFIRM_TEXT}
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCancelPeriod(null)}
                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={handleCancelSubmit}
                disabled={cancelBusy || cancelInput.trim() !== CANCEL_CONFIRM_TEXT}
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {cancelBusy ? '...' : 'Отменить закрытие'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
