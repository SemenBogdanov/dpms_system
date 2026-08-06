import { useEffect, useState } from 'react'
import type { User } from '@/api/types'
import { validatePassword } from '@/lib/passwordValidation'
import { cn } from '@/lib/utils'
import { PasswordRevealButton } from '@/components/PasswordRevealButton'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

export type UserFormPayload = {
  full_name: string
  email: string
  role: User['role']
  league: User['league']
  mpw: number
  is_new_employee: boolean
  task_workspace_enabled: boolean
  can_link_queue_tasks_to_projects: boolean
  feedback_enabled: boolean
  competency_development_enabled: boolean
  competency_constructor_enabled: boolean
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

/*
const roleBadgeClass: Record<string, string> = {
  admin: 'bg-red-100 text-red-800',
  teamlead: 'bg-blue-100 text-blue-800',
  executor: 'bg-slate-100 text-slate-700',
}*/

export function UserModal({ mode, initial, open, onClose, onSubmit }: UserModalProps) {
  const [full_name, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<User['role']>('executor')
  const [league, setLeague] = useState<User['league']>('C')
  const [mpw, setMpw] = useState(60)
  const [isNewEmployee, setIsNewEmployee] = useState(false)
  const [taskWorkspaceEnabled, setTaskWorkspaceEnabled] = useState(false)
  const [canLinkQueueTasksToProjects, setCanLinkQueueTasksToProjects] = useState(false)
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  const [competencyDevelopmentEnabled, setCompetencyDevelopmentEnabled] = useState(true)
  const [competencyConstructorEnabled, setCompetencyConstructorEnabled] = useState(false)
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const panelRef = useProtectedModal<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    setValidationError(null)
    if (mode === 'edit' && initial) {
      setFullName(initial.full_name)
      setEmail(initial.email)
      setRole(initial.role)
      setLeague(initial.league)
      setMpw(initial.mpw)
      setIsNewEmployee(Boolean(initial.is_new_employee))
      setTaskWorkspaceEnabled(Boolean(initial.task_workspace_enabled))
      setCanLinkQueueTasksToProjects(Boolean(initial.can_link_queue_tasks_to_projects))
      setFeedbackEnabled(Boolean(initial.feedback_enabled))
      setCompetencyDevelopmentEnabled(Boolean(initial.competency_development_enabled))
      setCompetencyConstructorEnabled(Boolean(initial.competency_constructor_enabled))
      setPassword('')
      setShowPassword(false)
    } else {
      setFullName('')
      setEmail('')
      setRole('executor')
      setLeague('C')
      setMpw(0)
      setIsNewEmployee(false)
      setTaskWorkspaceEnabled(false)
      setCanLinkQueueTasksToProjects(false)
      setFeedbackEnabled(false)
      setCompetencyDevelopmentEnabled(true)
      setCompetencyConstructorEnabled(false)
      setPassword('')
      setShowPassword(false)
    }
  }, [open, mode, initial])

  const handleDevelopmentChange = (checked: boolean) => {
    setCompetencyDevelopmentEnabled(checked)
    if (!checked) setCompetencyConstructorEnabled(false)
  }

  const handleConstructorChange = (checked: boolean) => {
    setCompetencyConstructorEnabled(checked)
    if (checked) setCompetencyDevelopmentEnabled(true)
  }

  const handleTaskWorkspaceChange = (checked: boolean) => {
    setTaskWorkspaceEnabled(checked)
    if (!checked) setCanLinkQueueTasksToProjects(false)
  }

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
    if (mode === 'create') {
      const passwordErrors = validatePassword(password)
      if (passwordErrors.length > 0) {
        setValidationError(passwordErrors.join('. '))
        return
      }
    }
    if (mpw < 0) {
      setValidationError('План (MPW) не может быть меньше 0')
      return
    }
    setValidationError(null)
    setBusy(true)
    try {
      await onSubmit({
        full_name: full_name.trim(),
        email: email.trim().toLowerCase(),
        role,
        league,
        mpw,
        is_new_employee: isNewEmployee,
        task_workspace_enabled: taskWorkspaceEnabled,
        can_link_queue_tasks_to_projects: canLinkQueueTasksToProjects,
        feedback_enabled: feedbackEnabled,
        competency_development_enabled: competencyDevelopmentEnabled,
        competency_constructor_enabled: competencyConstructorEnabled,
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
      aria-labelledby="user-modal-title"
      onPointerDown={preventBackdropDismiss}
    >
      <div ref={panelRef} tabIndex={-1} className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
        <h3 id="user-modal-title" className="text-lg font-semibold text-slate-900">
          {mode === 'create' ? 'Добавить сотрудника' : 'Редактировать сотрудника'}
        </h3>
        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <label htmlFor="user-full-name" className="block text-sm font-medium text-slate-700">ФИО *</label>
          <input
            id="user-full-name"
            type="text"
            value={full_name}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            maxLength={255}
          />
          <label htmlFor="user-email" className="block text-sm font-medium text-slate-700">Email *</label>
          <input
            id="user-email"
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
            min={0}
            value={mpw}
            onChange={(e) => setMpw(Number(e.target.value) || 0)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={isNewEmployee}
              onChange={(e) => setIsNewEmployee(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-slate-300"
            />
            <span>
              <span className="block font-medium text-slate-800">Новый сотрудник</span>
              <span className="block text-xs text-slate-500">План считается с адаптацией: 50% на первые 3 месяца и пропорционально оставшимся рабочим дням месяца.</span>
            </span>
          </label>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-semibold text-slate-800">Доступ к разделам</p>
            <p className="mt-1 text-xs text-slate-500">
              Роль определяет действия внутри раздела. Галочка ниже открывает сам раздел в оболочке DPMS.
            </p>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={taskWorkspaceEnabled}
                  onChange={(e) => handleTaskWorkspaceChange(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <span>
                  <span className="block font-medium text-slate-800">Работа с задачами</span>
                  <span className="block text-xs text-slate-500">Очередь, мои задачи, профиль, магазин, база знаний, отчеты и каталог.</span>
                </span>
              </label>
              <label className={cn(
                'flex items-start gap-3 rounded-md border px-3 py-2 text-sm',
                taskWorkspaceEnabled
                  ? 'border-slate-200 bg-white text-slate-700'
                  : 'border-slate-200 bg-slate-100 text-slate-400',
              )}>
                <input
                  type="checkbox"
                  checked={canLinkQueueTasksToProjects}
                  disabled={!taskWorkspaceEnabled}
                  onChange={(e) => setCanLinkQueueTasksToProjects(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <span>
                  <span className="block font-medium">Q-задачи в проектах</span>
                  <span className="block text-xs">
                    Разрешает владельцу или редактору проекта публиковать операции в глобальную очередь и связывать существующие Q-задачи.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={competencyDevelopmentEnabled}
                  onChange={(e) => handleDevelopmentChange(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <span>
                  <span className="block font-medium text-slate-800">Развитие</span>
                  <span className="block text-xs text-slate-500">Оценка компетенций, ИПР, отчеты по развитию.</span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={competencyConstructorEnabled}
                  onChange={(e) => handleConstructorChange(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <span>
                  <span className="block font-medium text-slate-800">Конструктор компетенций</span>
                  <span className="block text-xs text-slate-500">Создание custom-опросов и назначение сотрудникам DPMS.</span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={feedbackEnabled}
                  onChange={(e) => setFeedbackEnabled(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300"
                />
                <span>
                  <span className="block font-medium text-slate-800">Обратная связь</span>
                  <span className="block text-xs text-slate-500">Создание и рассмотрение обращений по системе.</span>
                </span>
              </label>
            </div>
          </div>
          {mode === 'create' && (
            <>
              <label htmlFor="temporary_password" className="block text-sm font-medium text-slate-700">
                Временный пароль *
              </label>
              <div className="relative">
                <input
                  id="temporary_password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 pr-11 text-sm"
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                />
                <PasswordRevealButton
                  revealed={showPassword}
                  onRevealChange={setShowPassword}
                />
              </div>
              <p className="text-xs text-slate-500">
                Действует 7 дней. При первом входе сотрудник обязан заменить его собственным паролем.
              </p>
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
