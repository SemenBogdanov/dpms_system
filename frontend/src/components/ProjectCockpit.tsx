import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  FileCheck2,
  Gauge,
  GitBranch,
  Loader2,
  Milestone,
  RefreshCw,
  Rocket,
  Target,
  Users,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  ProjectCharterChangePreview,
  ProjectDeadlineChangePreview,
  WorkEntity,
  WorkEntityMilestone,
  WorkEntityMilestoneReschedulePreview,
  WorkEntityReadiness,
  WorkEntityTask,
  WorkEntityWorkspace,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

type ProjectCockpitProps = {
  entity: WorkEntity
  readiness: WorkEntityReadiness | null
  onChanged: () => Promise<void>
  onEditProject: () => void
  onOpenAdvanced: (tab: 'work' | 'map' | 'access' | 'events') => void
}

export type ProjectCockpitHandle = {
  openCharter: () => void
  openTask: () => void
  openMilestone: () => void
  openDecision: () => void
  openDeadline: () => void
}

type DialogName =
  | 'task'
  | 'milestone'
  | 'decision'
  | 'charter'
  | 'deadline'
  | 'reschedule'
  | null

type TaskForm = {
  title: string
  acceptanceCriteria: string
  startsAt: string
  dueAt: string
  assigneeId: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  targetMilestoneId: string
}

type MilestoneForm = {
  title: string
  acceptanceCriteria: string
  at: string
  decisionOwnerId: string
  criticality: 'control' | 'key' | 'critical'
  criticalityReason: string
}

const taskStatusLabels: Record<string, string> = {
  planned: 'Запланирована',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  blocked: 'Блокирована',
  review: 'На проверке',
  done: 'Готово',
  cancelled: 'Отменена',
}

const milestoneStatusLabels: Record<string, string> = {
  planned: 'Запланирована',
  rescheduled: 'Перенесена',
  overdue: 'Просрочена',
  achieved: 'Пройдена',
  cancelled: 'Отменена',
}

const projectStatusLabels: Record<WorkEntity['status'], string> = {
  draft: 'Черновик',
  active: 'Активный проект',
  paused: 'Проект на паузе',
  done: 'Проект завершен',
  archived: 'Проект в архиве',
}

const charterFieldLabels = {
  outcome_statement: 'Ожидаемый результат',
  success_criteria: 'Критерии успеха',
  constraints: 'Ограничения',
}

function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return 'не задана'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  })
}

function inputDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function isoDate(value: string) {
  return new Date(value).toISOString()
}

function daysBetween(left: string | null | undefined, right: string | null | undefined) {
  if (!left || !right) return null
  return Math.round(
    (new Date(right).getTime() - new Date(left).getTime()) / 86_400_000,
  )
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const panelRef = useProtectedModal<HTMLDivElement>()

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/55 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="max-h-[100dvh] w-full overflow-y-auto rounded-t-lg bg-white pb-[env(safe-area-inset-bottom)] shadow-2xl sm:max-h-[92vh] sm:max-w-2xl sm:rounded-lg sm:pb-0"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-800">{label}</span>
      {hint && <span className="mb-1.5 block text-xs leading-5 text-slate-500">{hint}</span>}
      {children}
    </label>
  )
}

function statusTone(status: string) {
  if (status === 'done' || status === 'achieved') return 'bg-emerald-100 text-emerald-700'
  if (status === 'blocked' || status === 'overdue') return 'bg-red-100 text-red-700'
  if (status === 'waiting' || status === 'rescheduled') return 'bg-amber-100 text-amber-700'
  if (status === 'in_progress' || status === 'review') return 'bg-sky-100 text-sky-700'
  return 'bg-slate-100 text-slate-600'
}

function progressPercent(taskList: WorkEntityTask[], milestone: WorkEntityMilestone) {
  const doneTasks = taskList.filter((task) => task.status === 'done').length
  const total = taskList.length + 1
  const done = doneTasks + (milestone.status === 'achieved' ? 1 : 0)
  return Math.round((done / total) * 100)
}

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

export const ProjectCockpit = forwardRef<ProjectCockpitHandle, ProjectCockpitProps>(
function ProjectCockpit(
  {
    entity,
    readiness,
    onChanged,
    onEditProject,
    onOpenAdvanced,
  },
  ref,
) {
  const [workspace, setWorkspace] = useState<WorkEntityWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<DialogName>(null)
  const [rescheduleMilestone, setRescheduleMilestone] = useState<WorkEntityMilestone | null>(null)
  const [deadlineTarget, setDeadlineTarget] = useState('')
  const [deadlineReason, setDeadlineReason] = useState('')
  const [deadlinePreview, setDeadlinePreview] = useState<ProjectDeadlineChangePreview | null>(null)
  const [charterOutcome, setCharterOutcome] = useState('')
  const [charterSuccess, setCharterSuccess] = useState('')
  const [charterConstraints, setCharterConstraints] = useState('')
  const [charterReason, setCharterReason] = useState('')
  const [charterPreview, setCharterPreview] =
    useState<ProjectCharterChangePreview | null>(null)
  const [rescheduleAt, setRescheduleAt] = useState('')
  const [rescheduleReason, setRescheduleReason] = useState('')
  const [reschedulePreview, setReschedulePreview] =
    useState<WorkEntityMilestoneReschedulePreview | null>(null)
  const [decisionTitle, setDecisionTitle] = useState('')
  const [decisionText, setDecisionText] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [decisionParticipants, setDecisionParticipants] = useState('')
  const [decisionFollowUp, setDecisionFollowUp] = useState('')
  const [decisionOwnerId, setDecisionOwnerId] = useState('')
  const [decisionDueAt, setDecisionDueAt] = useState('')
  const [taskForm, setTaskForm] = useState<TaskForm>({
    title: '',
    acceptanceCriteria: '',
    startsAt: inputDate(entity.starts_at),
    dueAt: inputDate(entity.target_due_at || entity.due_at),
    assigneeId: '',
    priority: 'medium',
    targetMilestoneId: '',
  })
  const [milestoneForm, setMilestoneForm] = useState<MilestoneForm>({
    title: '',
    acceptanceCriteria: '',
    at: inputDate(entity.target_due_at || entity.due_at),
    decisionOwnerId: '',
    criticality: 'control',
    criticalityReason: '',
  })

  const loadWorkspace = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<WorkEntityWorkspace>(
        `/api/work-entities/${entity.id}/workspace`,
      )
      setWorkspace(data)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить план')
    } finally {
      setLoading(false)
    }
  }, [entity.id])

  useEffect(() => {
    void loadWorkspace()
  }, [loadWorkspace])

  const milestones = useMemo(
    () =>
      [...(workspace?.milestones || [])]
        .filter((item) => item.status !== 'cancelled')
        .sort(
          (left, right) =>
            new Date(left.forecast_at).getTime() - new Date(right.forecast_at).getTime(),
        ),
    [workspace],
  )
  const activeTasks = useMemo(
    () => (workspace?.tasks || []).filter((item) => item.status !== 'cancelled'),
    [workspace],
  )
  const plannedMilestones = useMemo(
    () => milestones.filter((item) => item.status === 'planned'),
    [milestones],
  )
  const taskMilestoneTargets = useMemo(() => {
    const targets = new Map<string, string>()
    for (const dependency of workspace?.dependencies || []) {
      if (
        dependency.status === 'active' &&
        dependency.predecessor_type === 'task' &&
        dependency.successor_type === 'milestone'
      ) {
        targets.set(dependency.predecessor_id, dependency.successor_id)
      }
    }
    return targets
  }, [workspace?.dependencies])
  const taskByMilestone = useMemo(() => {
    const groups = new Map<string, WorkEntityTask[]>()
    for (const milestone of milestones) groups.set(milestone.id, [])
    for (const task of activeTasks) {
      const targetId = taskMilestoneTargets.get(task.id)
      if (targetId && groups.has(targetId)) groups.get(targetId)?.push(task)
    }
    for (const items of groups.values()) {
      items.sort(
        (left, right) =>
          new Date(left.forecast_due_at || left.baseline_due_at || 0).getTime() -
          new Date(right.forecast_due_at || right.baseline_due_at || 0).getTime(),
      )
    }
    return groups
  }, [activeTasks, milestones, taskMilestoneTargets])
  const unlinkedTasks = useMemo(
    () => activeTasks.filter((task) => !taskMilestoneTargets.has(task.id)),
    [activeTasks, taskMilestoneTargets],
  )
  const nextMilestone = plannedMilestones[0]
  const overdueTasks = activeTasks.filter(
    (task) =>
      !['done', 'cancelled'].includes(task.status) &&
      Boolean(task.forecast_due_at) &&
      new Date(task.forecast_due_at || 0) < new Date(),
  )
  const targetVariance = daysBetween(entity.due_at, entity.target_due_at || entity.due_at)
  const forecastVariance = daysBetween(
    entity.target_due_at || entity.due_at,
    entity.forecast_due_at,
  )
  const canEdit = entity.access_role === 'owner' || entity.access_role === 'editor'
  const canManage =
    canEdit && !['done', 'archived'].includes(entity.status)
  const assignableParticipants =
    workspace?.participants.filter((participant) => participant.can_be_assigned) ?? []
  const participants = workspace?.participants ?? []
  const ownerParticipant =
    participants.find((participant) => participant.role === 'owner') ?? participants[0] ?? null
  const otherParticipants = participants
    .filter((participant) => participant.user_id !== ownerParticipant?.user_id)
    .slice(0, 4)
  const nearestMilestones = milestones.slice(0, 3)
  const projectHealth = (() => {
    if (entity.status === 'done') {
      return {
        label: 'Проект завершен',
        detail: 'Финальный результат зафиксирован.',
        tone: 'text-emerald-700',
      }
    }
    if (entity.status === 'archived') {
      return {
        label: 'Проект в архиве',
        detail: 'Изменения заблокированы.',
        tone: 'text-slate-600',
      }
    }
    if (entity.status === 'paused') {
      return {
        label: 'Проект на паузе',
        detail: 'График сохранен, работа приостановлена.',
        tone: 'text-amber-700',
      }
    }
    if (entity.status === 'draft') {
      return readiness?.can_activate
        ? {
            label: 'Готов к запуску',
            detail: 'Обязательные параметры заполнены.',
            tone: 'text-emerald-700',
          }
        : {
            label: 'Черновик: есть замечания',
            detail: `Блокеров: ${readiness?.blocking_count ?? 0}; предупреждений: ${readiness?.warning_count ?? 0}.`,
            tone: 'text-amber-700',
          }
    }
    if (overdueTasks.length > 0 || (forecastVariance || 0) > 0) {
      return {
        label: 'Требует внимания',
        detail: `Просрочено работ: ${overdueTasks.length}; отклонение: ${Math.max(0, forecastVariance || 0)} дн.`,
        tone: 'text-red-700',
      }
    }
    return {
      label: 'Идет по плану',
      detail: 'Прогноз находится в пределах целевой даты.',
      tone: 'text-emerald-700',
    }
  })()

  const refreshAll = async () => {
    await Promise.all([loadWorkspace(), onChanged()])
  }

  const openTaskDialog = () => {
    const target = nextMilestone
    setTaskForm({
      title: '',
      acceptanceCriteria: '',
      startsAt: inputDate(entity.forecast_starts_at || entity.starts_at),
      dueAt: inputDate(target?.forecast_at || entity.target_due_at || entity.due_at),
      assigneeId: '',
      priority: 'medium',
      targetMilestoneId: target?.id || '',
    })
    setDialog('task')
  }

  const openMilestoneDialog = () => {
    setMilestoneForm({
      title: '',
      acceptanceCriteria: '',
      at: inputDate(entity.target_due_at || entity.due_at),
      decisionOwnerId: '',
      criticality: 'control',
      criticalityReason: '',
    })
    setDialog('milestone')
  }

  const createTask = async (event: FormEvent) => {
    event.preventDefault()
    if (!taskForm.title.trim() || !taskForm.acceptanceCriteria.trim()) return
    if (!taskForm.targetMilestoneId) {
      toast.error('Выберите контрольную точку, которую подготавливает работа')
      return
    }
    setBusy(true)
    try {
      await api.post(
        `/api/project-cockpit/${entity.id}/work`,
        {
          title: taskForm.title.trim(),
          acceptance_criteria: taskForm.acceptanceCriteria.trim(),
          baseline_starts_at: isoDate(taskForm.startsAt),
          baseline_due_at: isoDate(taskForm.dueAt),
          assignee_id: taskForm.assigneeId || null,
          priority: taskForm.priority,
          target_milestone_id: taskForm.targetMilestoneId,
        },
      )
      setDialog(null)
      await refreshAll()
      toast.success('Работа добавлена в маршрут')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить работу')
      await refreshAll()
    } finally {
      setBusy(false)
    }
  }

  const createMilestone = async (event: FormEvent) => {
    event.preventDefault()
    if (!milestoneForm.title.trim() || !milestoneForm.acceptanceCriteria.trim()) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${entity.id}/milestones`, {
        title: milestoneForm.title.trim(),
        acceptance_criteria: milestoneForm.acceptanceCriteria.trim(),
        baseline_at: isoDate(milestoneForm.at),
        decision_owner_id: milestoneForm.decisionOwnerId || null,
        criticality: milestoneForm.criticality,
        criticality_reason: milestoneForm.criticalityReason.trim() || null,
      })
      setDialog(null)
      await refreshAll()
      toast.success('Контрольная точка добавлена')
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Не удалось добавить контрольную точку',
      )
    } finally {
      setBusy(false)
    }
  }

  const openDecisionDialog = () => {
    setDecisionTitle('')
    setDecisionText('')
    setDecisionReason('')
    setDecisionParticipants('')
    setDecisionFollowUp('')
    setDecisionOwnerId('')
    setDecisionDueAt('')
    setDialog('decision')
  }

  const saveDecision = async (event: FormEvent) => {
    event.preventDefault()
    if (!decisionTitle.trim() || !decisionText.trim()) return
    setBusy(true)
    try {
      await api.post(`/api/project-cockpit/${entity.id}/decisions`, {
        decided_at: new Date().toISOString(),
        title: decisionTitle.trim(),
        decision: decisionText.trim(),
        reason: decisionReason.trim() || null,
        participants: decisionParticipants.trim() || null,
        follow_up: decisionFollowUp.trim() || null,
        owner_id: decisionOwnerId || null,
        due_at: decisionDueAt ? isoDate(decisionDueAt) : null,
      })
      setDialog(null)
      await refreshAll()
      toast.success('Решение зафиксировано в журнале проекта')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить решение')
    } finally {
      setBusy(false)
    }
  }

  const openCharterDialog = () => {
    if (entity.status === 'draft') {
      onEditProject()
      return
    }
    setCharterOutcome(entity.outcome_statement || '')
    setCharterSuccess(entity.success_criteria || '')
    setCharterConstraints(entity.constraints || '')
    setCharterReason('')
    setCharterPreview(null)
    setDialog('charter')
  }

  const charterPayload = () => ({
    outcome_statement: charterOutcome.trim(),
    success_criteria: charterSuccess.trim(),
    constraints: charterConstraints.trim() || null,
    reason: charterReason.trim(),
    expected_revision: entity.schedule_revision,
  })

  const previewCharter = async () => {
    if (
      !charterOutcome.trim() ||
      !charterSuccess.trim() ||
      charterReason.trim().length < 5
    ) {
      toast.error('Заполните результат, критерии успеха и причину')
      return
    }
    setBusy(true)
    try {
      const preview = await api.post<ProjectCharterChangePreview>(
        `/api/project-cockpit/${entity.id}/charter-change/preview`,
        charterPayload(),
      )
      setCharterPreview(preview)
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Не удалось проверить поправку',
      )
    } finally {
      setBusy(false)
    }
  }

  const applyCharter = async () => {
    if (!charterPreview) return
    setBusy(true)
    try {
      await api.post(
        `/api/project-cockpit/${entity.id}/charter-change/apply`,
        charterPayload(),
      )
      setDialog(null)
      await refreshAll()
      toast.success('Поправка к паспорту сохранена в новой ревизии')
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Не удалось применить поправку',
      )
    } finally {
      setBusy(false)
    }
  }

  const openDeadlineDialog = () => {
    if (entity.status === 'draft') {
      onEditProject()
      return
    }
    setDeadlineTarget(inputDate(entity.target_due_at || entity.due_at))
    setDeadlineReason('')
    setDeadlinePreview(null)
    setDialog('deadline')
  }

  const previewDeadline = async () => {
    if (!deadlineTarget || deadlineReason.trim().length < 5) {
      toast.error('Укажите новую дату и причину')
      return
    }
    setBusy(true)
    try {
      const preview = await api.post<ProjectDeadlineChangePreview>(
        `/api/project-cockpit/${entity.id}/deadline-change/preview`,
        {
          target_due_at: isoDate(deadlineTarget),
          reason: deadlineReason.trim(),
          expected_revision: entity.schedule_revision,
        },
      )
      setDeadlinePreview(preview)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось проверить срок')
    } finally {
      setBusy(false)
    }
  }

  const applyDeadline = async () => {
    if (!deadlinePreview) return
    setBusy(true)
    try {
      await api.post(`/api/project-cockpit/${entity.id}/deadline-change/apply`, {
        target_due_at: isoDate(deadlineTarget),
        reason: deadlineReason.trim(),
        expected_revision: entity.schedule_revision,
      })
      setDialog(null)
      await refreshAll()
      toast.success('Новая целевая дата зафиксирована; базовый план сохранен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить срок')
    } finally {
      setBusy(false)
    }
  }

  const openReschedule = (milestone: WorkEntityMilestone) => {
    setRescheduleMilestone(milestone)
    setRescheduleAt(inputDate(milestone.forecast_at))
    setRescheduleReason('')
    setReschedulePreview(null)
    setDialog('reschedule')
  }

  const previewReschedule = async () => {
    if (!rescheduleMilestone || !rescheduleAt || rescheduleReason.trim().length < 5) {
      toast.error('Укажите новую дату и причину')
      return
    }
    setBusy(true)
    try {
      const preview = await api.post<WorkEntityMilestoneReschedulePreview>(
        `/api/work-entities/${entity.id}/milestones/${rescheduleMilestone.id}/reschedule/preview`,
        {
          forecast_at: isoDate(rescheduleAt),
          reason: rescheduleReason.trim(),
          cascade: true,
          expected_revision: entity.schedule_revision,
        },
      )
      setReschedulePreview(preview)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось проверить перенос')
    } finally {
      setBusy(false)
    }
  }

  const applyReschedule = async () => {
    if (!rescheduleMilestone || !reschedulePreview) return
    setBusy(true)
    try {
      await api.post(
        `/api/work-entities/${entity.id}/milestones/${rescheduleMilestone.id}/reschedule/apply`,
        {
          forecast_at: isoDate(rescheduleAt),
          reason: rescheduleReason.trim(),
          cascade: true,
          expected_revision: entity.schedule_revision,
        },
      )
      setDialog(null)
      await refreshAll()
      toast.success('Перенос применен и записан в журнал')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось применить перенос')
    } finally {
      setBusy(false)
    }
  }

  useImperativeHandle(ref, () => ({
    openCharter: openCharterDialog,
    openTask: openTaskDialog,
    openMilestone: openMilestoneDialog,
    openDecision: openDecisionDialog,
    openDeadline: openDeadlineDialog,
  }))

  if (loading && !workspace) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загружаем план
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <section className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1fr)_480px] 2xl:grid-cols-[minmax(0,1.2fr)_640px]">
        <div className="grid min-w-0 grid-rows-[auto_1fr] gap-4">
          <article className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="text-xs font-semibold uppercase text-primary">Описание проекта</h3>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
              <span>{projectStatusLabels[entity.status]}</span>
              <span>Владелец: {entity.owner_name}</span>
              <span>Начало: {formatDate(entity.starts_at)}</span>
              <span>Цель: {formatDate(entity.target_due_at || entity.due_at)}</span>
              <span>{entity.visibility === 'private' ? 'Приватный доступ' : 'Общий доступ'}</span>
            </div>
            <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">
              {entity.description || 'Описание проекта еще не заполнено.'}
            </p>
          </article>

          <article className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-primary">
              <Target className="h-4 w-4" />
              Результат проекта
            </div>
            <p className="mt-2 whitespace-pre-wrap break-words text-lg font-semibold leading-7 text-slate-900">
              {entity.outcome_statement || 'Результат еще не сформулирован'}
            </p>
            {entity.success_criteria && (
              <div className="mt-3 flex items-start gap-2 text-sm leading-6 text-slate-600">
                <FileCheck2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />
                <span>
                  <strong className="font-medium text-slate-800">Успех:</strong>{' '}
                  {entity.success_criteria}
                </span>
              </div>
            )}
            {entity.constraints && (
              <div className="mt-3 border-l-2 border-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <strong className="font-medium">Ограничения:</strong> {entity.constraints}
              </div>
            )}
          </article>
        </div>

        <div className="grid min-w-0 gap-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(200px,1fr)] 2xl:grid-cols-2">
            <article className="overflow-hidden rounded-lg border border-slate-200 bg-white">
              <h3 className="px-3 pt-3 text-xs font-semibold uppercase text-primary">
                Сроки проекта
              </h3>
              <div className="mt-2 grid grid-cols-3 divide-x divide-slate-200 border-y border-slate-200">
                <div className="min-w-0 px-2 py-2.5">
                  <span className="block text-[11px] text-slate-500">Базовый срок</span>
                  <strong className="mt-1 block whitespace-nowrap text-sm font-semibold tabular-nums text-slate-900">
                    {formatDate(entity.due_at)}
                  </strong>
                </div>
                <div className="min-w-0 px-2 py-2.5">
                  <span className="block text-[11px] text-slate-500">Текущая цель</span>
                  <strong className="mt-1 block whitespace-nowrap text-sm font-semibold tabular-nums text-slate-900">
                    {formatDate(entity.target_due_at || entity.due_at)}
                  </strong>
                  {targetVariance !== null && targetVariance !== 0 && (
                    <span
                      className={cn(
                        'mt-0.5 block text-[10px]',
                        targetVariance < 0 ? 'text-emerald-700' : 'text-amber-700',
                      )}
                    >
                      {targetVariance > 0 ? '+' : ''}
                      {targetVariance} дн.
                    </span>
                  )}
                </div>
                <div className="min-w-0 px-2 py-2.5">
                  <span className="block text-[11px] text-slate-500">Прогноз</span>
                  <strong
                    className={cn(
                      'mt-1 block whitespace-nowrap text-sm font-semibold tabular-nums',
                      forecastVariance && forecastVariance > 0
                        ? 'text-red-700'
                        : 'text-emerald-700',
                    )}
                  >
                    {formatDate(entity.forecast_due_at)}
                  </strong>
                  {forecastVariance !== null && forecastVariance > 0 && (
                    <span className="mt-0.5 block text-[10px] text-red-700">
                      +{forecastVariance} дн.
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-start gap-2.5 px-3 py-3">
                {projectHealth.tone === 'text-emerald-700' ? (
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
                ) : (
                  <AlertTriangle className={cn('mt-0.5 h-5 w-5 shrink-0', projectHealth.tone)} />
                )}
                <div className="min-w-0">
                  <h4 className={cn('text-sm font-semibold', projectHealth.tone)}>
                    {projectHealth.label}
                  </h4>
                  <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
                    {projectHealth.detail}
                  </p>
                </div>
              </div>
            </article>

            <button
              type="button"
              onClick={() => onOpenAdvanced('access')}
              className="rounded-lg border border-slate-200 bg-white p-3 text-left hover:border-primary/35"
              aria-label="Открыть команду проекта"
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold uppercase text-primary">Команда</h3>
                <span className="text-xs text-slate-500">{participants.length}</span>
              </div>
              <div className="mt-2 flex flex-col items-center">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary">
                  {initials(ownerParticipant?.user_name || entity.owner_name)}
                </span>
                <span className="mt-1 max-w-full truncate text-[11px] font-medium text-slate-700">
                  {ownerParticipant?.user_name || entity.owner_name}
                </span>
                {otherParticipants.length > 0 ? (
                  <>
                    <span className="h-2 w-px bg-slate-300" />
                    <span className="h-px w-4/5 bg-slate-300" />
                    <div className="flex w-full flex-wrap justify-center gap-x-3 gap-y-1 pt-1.5">
                      {otherParticipants.map((participant) => (
                        <span
                          key={participant.user_id}
                          className="flex w-12 min-w-0 flex-col items-center"
                          title={participant.user_name}
                        >
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-[9px] font-semibold text-slate-600">
                            {initials(participant.user_name)}
                          </span>
                          <span className="mt-0.5 w-full truncate text-center text-[9px] text-slate-500">
                            {participant.user_name}
                          </span>
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <span className="mt-3 inline-flex items-center gap-1.5 text-xs text-slate-500">
                    <Users className="h-3.5 w-3.5" />
                    Участники еще не добавлены
                  </span>
                )}
              </div>
            </button>
          </div>

          <article className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <h3 className="px-3 py-2 text-xs font-semibold uppercase text-primary">
              Ближайшие контрольные точки
            </h3>
            {nearestMilestones.length === 0 ? (
              <p className="border-t border-slate-200 px-3 py-6 text-center text-xs text-slate-500">
                Контрольные точки еще не запланированы.
              </p>
            ) : (
              <div className="divide-y divide-slate-200 border-t border-slate-200">
                {nearestMilestones.map((milestone) => (
                  <button
                    key={milestone.id}
                    type="button"
                    onClick={() => onOpenAdvanced('work')}
                    className="flex w-full items-start gap-2 px-3 py-1.5 text-left hover:bg-slate-50"
                  >
                    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-700">
                      <ClipboardCheck className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] font-semibold text-slate-500">
                          КТ-{milestone.milestone_number}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-800">
                          {milestone.title}
                        </span>
                        <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', statusTone(milestone.display_status))}>
                          {milestoneStatusLabels[milestone.display_status]}
                        </span>
                      </span>
                      <span className="mt-0.5 flex flex-wrap gap-x-3 text-[10px] text-slate-500">
                        <span>{milestone.decision_owner_name || 'Ответственный не назначен'}</span>
                        <span>прогноз до {formatDate(milestone.forecast_at)}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-[10px] text-slate-600">
                        Критерий: {milestone.acceptance_criteria}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </article>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900">Маршрут к результату</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Работы подготавливают проверку; проверка подтверждает переход дальше.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenAdvanced('map')}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary"
          >
            <GitBranch className="h-4 w-4" />
            Детальный график
          </button>
        </div>

        {milestones.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 px-5 py-10 text-center">
            <Milestone className="mx-auto h-7 w-7 text-slate-300" />
            <p className="mt-2 text-sm font-medium text-slate-700">
              Добавьте первую контрольную точку
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Это дата, когда нужно подтвердить результат или принять решение.
            </p>
          </div>
        ) : (
          <div className="mt-4 hidden overflow-x-auto md:block">
            <div
              className="relative min-h-28 px-4"
              style={{ minWidth: `${Math.max(760, (milestones.length + 2) * 150)}px` }}
            >
              <div className="absolute left-6 right-6 top-8 h-1.5 rounded-full bg-primary/20" />
              <div
                className="relative grid h-full items-start"
                style={{ gridTemplateColumns: `repeat(${milestones.length + 2}, minmax(0, 1fr))` }}
              >
                <div className="text-center">
                  <span className="mx-auto inline-flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-slate-700 text-white shadow">
                    <Rocket className="h-3.5 w-3.5" />
                  </span>
                  <p className="mt-2 text-xs font-medium text-slate-700">Старт</p>
                  <p className="text-[11px] text-slate-500">{formatDate(entity.starts_at)}</p>
                </div>
                {milestones.map((milestone, index) => (
                  <div key={milestone.id} className="min-w-0 text-center">
                    <span
                      className={cn(
                        'mx-auto inline-flex h-8 w-8 items-center justify-center rounded-full border-2 border-white text-xs font-semibold shadow',
                        statusTone(milestone.display_status),
                      )}
                    >
                      {index + 1}
                    </span>
                    <p className="mx-auto mt-2 line-clamp-2 max-w-36 text-xs font-medium text-slate-700">
                      {milestone.title}
                    </p>
                    <p className="text-[11px] text-slate-500">{formatDate(milestone.forecast_at)}</p>
                  </div>
                ))}
                <div className="text-center">
                  <span className="mx-auto inline-flex h-8 w-8 items-center justify-center rounded-full border-2 border-white bg-emerald-600 text-white shadow">
                    <Target className="h-4 w-4" />
                  </span>
                  <p className="mt-2 text-xs font-medium text-slate-700">Результат</p>
                  <p className="text-[11px] text-slate-500">
                    {formatDate(entity.target_due_at || entity.due_at)}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      {milestones.length > 0 && (
        <section
          className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,24rem),1fr))] items-stretch gap-3"
          aria-label="Контрольные точки проекта"
        >
          {milestones.map((milestone, index) => {
            const tasks = taskByMilestone.get(milestone.id) || []
            const percent = progressPercent(tasks, milestone)
            return (
              <article
                key={milestone.id}
                className="flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white"
              >
                <header className="flex items-start gap-2 border-b border-slate-100 p-3">
                  <span
                    className={cn(
                      'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                      statusTone(milestone.display_status),
                    )}
                  >
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h4 className="line-clamp-2 text-sm font-semibold leading-5 text-slate-900">
                      {milestone.title}
                    </h4>
                    <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
                      <span>{formatDate(milestone.forecast_at)}</span>
                      <span className="truncate">
                        {milestone.decision_owner_name || 'ответственный не назначен'}
                      </span>
                    </div>
                  </div>
                  {canManage && milestone.status === 'planned' && entity.status !== 'draft' && (
                    <button
                      type="button"
                      onClick={() => openReschedule(milestone)}
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-primary"
                      title="Изменить дату контрольной точки"
                      aria-label={`Изменить дату ${milestone.title}`}
                    >
                      <CalendarClock className="h-4 w-4" />
                    </button>
                  )}
                </header>
                <div className="flex flex-1 flex-col p-3">
                  <div className="flex items-start gap-2 text-xs leading-5 text-slate-600">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    <span className="line-clamp-3">{milestone.acceptance_criteria}</span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full rounded-full bg-emerald-500 transition-all"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className={cn('rounded px-2 py-0.5 text-[10px] font-medium', statusTone(milestone.display_status))}>
                      {milestoneStatusLabels[milestone.display_status]}
                    </span>
                    {milestone.introduced_after_baseline && (
                      <span className="text-[10px] font-medium text-violet-700">Добавлено после запуска</span>
                    )}
                  </div>
                  <div className="mt-3 border-t border-slate-100">
                    {tasks.length === 0 ? (
                      <p className="py-2 text-xs text-amber-800">
                        До этой проверки не привязана работа.
                      </p>
                    ) : (
                      tasks.map((task) => (
                        <div key={task.id} className="border-b border-slate-100 py-2 last:border-b-0">
                          <div className="flex min-w-0 items-center gap-2">
                            <ClipboardCheck className="h-4 w-4 shrink-0 text-sky-600" />
                            <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-700">
                              {task.title}
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between gap-2 pl-6 text-[10px]">
                            <span className="text-slate-500">
                              {formatDate(task.forecast_due_at || task.baseline_due_at)}
                            </span>
                            <span className={cn('rounded px-1.5 py-0.5 font-medium', statusTone(task.status))}>
                              {taskStatusLabels[task.status]}
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </article>
            )
          })}
        </section>
      )}

      {unlinkedTasks.length > 0 && (
        <div className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 sm:flex-row sm:items-center">
          <AlertTriangle className="h-5 w-5 shrink-0 text-amber-700" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-amber-900">
              Есть работы без контрольной точки: {unlinkedTasks.length}
            </p>
            <p className="mt-0.5 text-xs leading-5 text-amber-800">
              {unlinkedTasks.slice(0, 3).map((task) => task.title).join(', ')}
              {unlinkedTasks.length > 3 ? ' и другие' : ''}. Их нельзя считать частью
              управляемого маршрута, пока связь не задана явно.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenAdvanced('work')}
            className="h-10 shrink-0 rounded-lg border border-amber-400 bg-white px-3 text-sm font-medium text-amber-900 hover:bg-amber-100"
          >
            Связать работы
          </button>
        </div>
      )}

      {entity.status === 'draft' && readiness?.issues.length ? (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            <h3 className="text-base font-semibold text-slate-900">Что нужно до запуска</h3>
          </div>
          <div className="mt-3 grid gap-2 xl:grid-cols-2">
            {readiness.issues.slice(0, 6).map((issue) => (
              <div
                key={`${issue.code}-${issue.scope_id}`}
                className="flex items-start gap-3 border-t border-slate-100 py-2 first:border-t-0"
              >
                <span
                  className={cn(
                    'mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    issue.severity === 'blocking'
                      ? 'bg-red-100 text-red-700'
                      : 'bg-amber-100 text-amber-700',
                  )}
                >
                  !
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800">{issue.message}</p>
                  <p className="mt-0.5 text-xs leading-5 text-slate-500">{issue.guidance}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {dialog === 'task' && (
        <Modal title="Добавить работу" onClose={() => setDialog(null)}>
          <form onSubmit={(event) => void createTask(event)} className="space-y-4 p-4">
            <Field
              label="Что нужно сделать"
              hint="Работа занимает время и выполняется конкретным человеком."
            >
              <input
                value={taskForm.title}
                onChange={(event) => setTaskForm((current) => ({ ...current, title: event.target.value }))}
                autoFocus
                required
                className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field label="Какой результат работы будет принят">
              <textarea
                value={taskForm.acceptanceCriteria}
                onChange={(event) => setTaskForm((current) => ({ ...current, acceptanceCriteria: event.target.value }))}
                rows={3}
                required
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Начало">
                <input
                  type="datetime-local"
                  value={taskForm.startsAt}
                  onChange={(event) => setTaskForm((current) => ({ ...current, startsAt: event.target.value }))}
                  required
                  className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary"
                />
              </Field>
              <Field label="Завершить до">
                <input
                  type="datetime-local"
                  value={taskForm.dueAt}
                  min={taskForm.startsAt}
                  onChange={(event) => setTaskForm((current) => ({ ...current, dueAt: event.target.value }))}
                  required
                  className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary"
                />
              </Field>
              <Field label="Исполнитель">
                <select
                  value={taskForm.assigneeId}
                  onChange={(event) => setTaskForm((current) => ({ ...current, assigneeId: event.target.value }))}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  <option value="">Назначить позднее</option>
                  {workspace?.participants.filter((person) => person.can_be_assigned).map((person) => (
                    <option key={person.user_id} value={person.user_id}>{person.user_name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Приоритет исполнения">
                <select
                  value={taskForm.priority}
                  onChange={(event) => setTaskForm((current) => ({ ...current, priority: event.target.value as TaskForm['priority'] }))}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  <option value="low">Низкий</option>
                  <option value="medium">Средний</option>
                  <option value="high">Высокий</option>
                  <option value="critical">Критический</option>
                </select>
              </Field>
            </div>
            <Field
              label="К какой проверке готовит"
              hint="Работа должна завершиться до выбранной контрольной точки."
            >
              <select
                value={taskForm.targetMilestoneId}
                onChange={(event) => setTaskForm((current) => ({ ...current, targetMilestoneId: event.target.value }))}
                required
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
              >
                <option value="">Выберите контрольную точку</option>
                {plannedMilestones.map((milestone) => (
                  <option key={milestone.id} value={milestone.id}>
                    {milestone.title} · {formatDate(milestone.forecast_at)}
                  </option>
                ))}
              </select>
              {plannedMilestones.length === 0 && (
                <p className="mt-1 text-xs leading-5 text-amber-700">
                  Сначала добавьте контрольную точку: работа должна готовить проверяемый
                  результат.
                </p>
              )}
            </Field>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setDialog(null)} className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700">Отмена</button>
              <button type="submit" disabled={busy || !taskForm.targetMilestoneId} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Добавить
              </button>
            </div>
          </form>
        </Modal>
      )}

      {dialog === 'milestone' && (
        <Modal title="Добавить контрольную точку" onClose={() => setDialog(null)}>
          <form onSubmit={(event) => void createMilestone(event)} className="space-y-4 p-4">
            <Field
              label="Что должно быть подтверждено"
              hint="Событие или решение на одну дату, без длительности."
            >
              <input
                value={milestoneForm.title}
                onChange={(event) => setMilestoneForm((current) => ({ ...current, title: event.target.value }))}
                autoFocus
                required
                className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field label="Критерий прохождения">
              <textarea
                value={milestoneForm.acceptanceCriteria}
                onChange={(event) => setMilestoneForm((current) => ({ ...current, acceptanceCriteria: event.target.value }))}
                rows={3}
                required
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Дата решения">
                <input
                  type="datetime-local"
                  value={milestoneForm.at}
                  onChange={(event) => setMilestoneForm((current) => ({ ...current, at: event.target.value }))}
                  required
                  className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary"
                />
              </Field>
              <Field label="Ответственный за решение">
                <select
                  value={milestoneForm.decisionOwnerId}
                  onChange={(event) => setMilestoneForm((current) => ({ ...current, decisionOwnerId: event.target.value }))}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  <option value="">Назначить позднее</option>
                  {workspace?.participants.filter((person) => person.can_be_assigned).map((person) => (
                    <option key={person.user_id} value={person.user_id}>{person.user_name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Влияние на проект">
                <select
                  value={milestoneForm.criticality}
                  onChange={(event) => setMilestoneForm((current) => ({ ...current, criticality: event.target.value as MilestoneForm['criticality'] }))}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  <option value="control">Контроль хода работы</option>
                  <option value="key">Открывает следующий шаг</option>
                  <option value="critical">Определяет успех проекта</option>
                </select>
              </Field>
              {milestoneForm.criticality !== 'control' && (
                <Field label="Почему это важно">
                  <input
                    value={milestoneForm.criticalityReason}
                    onChange={(event) => setMilestoneForm((current) => ({ ...current, criticalityReason: event.target.value }))}
                    required
                    className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary"
                  />
                </Field>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setDialog(null)} className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700">Отмена</button>
              <button type="submit" disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Добавить
              </button>
            </div>
          </form>
        </Modal>
      )}

      {dialog === 'decision' && (
        <Modal title="Зафиксировать решение" onClose={() => setDialog(null)}>
          <form onSubmit={(event) => void saveDecision(event)} className="space-y-4 p-4">
            <Field label="Короткое название решения">
              <input value={decisionTitle} onChange={(event) => setDecisionTitle(event.target.value)} autoFocus required className="h-11 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-primary" />
            </Field>
            <Field label="Что решили">
              <textarea value={decisionText} onChange={(event) => setDecisionText(event.target.value)} rows={4} required className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Почему принято решение">
                <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} rows={3} className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
              </Field>
              <Field label="Участники обсуждения">
                <textarea value={decisionParticipants} onChange={(event) => setDecisionParticipants(event.target.value)} rows={3} className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
              </Field>
            </div>
            <Field label="Следующее действие">
              <textarea value={decisionFollowUp} onChange={(event) => setDecisionFollowUp(event.target.value)} rows={2} className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Ответственный">
                <select value={decisionOwnerId} onChange={(event) => setDecisionOwnerId(event.target.value)} className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary">
                  <option value="">Не назначен</option>
                  {assignableParticipants.map((person) => (
                    <option key={person.user_id} value={person.user_id}>
                      {person.user_name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Срок следующего действия">
                <input type="datetime-local" value={decisionDueAt} onChange={(event) => setDecisionDueAt(event.target.value)} className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary" />
              </Field>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setDialog(null)} className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700">Отмена</button>
              <button type="submit" disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Сохранить решение
              </button>
            </div>
          </form>
        </Modal>
      )}

      {dialog === 'charter' && (
        <Modal title="Поправка к паспорту проекта" onClose={() => setDialog(null)}>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void previewCharter()
            }}
            className="space-y-4 p-4"
          >
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-5 text-amber-900">
              Исходный результат, критерии и ограничения останутся в baseline.
              Поправка создаст новую ревизию и запись с причиной в журнале.
            </div>
            <Field
              label="Ожидаемый результат"
              hint="Какое наблюдаемое состояние теперь должно быть достигнуто."
            >
              <textarea
                value={charterOutcome}
                onChange={(event) => {
                  setCharterOutcome(event.target.value)
                  setCharterPreview(null)
                }}
                rows={4}
                required
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field
              label="Критерии успеха"
              hint="Какие факты или подтверждения докажут достижение результата."
            >
              <textarea
                value={charterSuccess}
                onChange={(event) => {
                  setCharterSuccess(event.target.value)
                  setCharterPreview(null)
                }}
                rows={4}
                required
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field label="Ограничения">
              <textarea
                value={charterConstraints}
                onChange={(event) => {
                  setCharterConstraints(event.target.value)
                  setCharterPreview(null)
                }}
                rows={3}
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            <Field
              label="Причина поправки"
              hint="Например: решение проектного комитета от 29.07.2026."
            >
              <textarea
                value={charterReason}
                onChange={(event) => {
                  setCharterReason(event.target.value)
                  setCharterPreview(null)
                }}
                rows={3}
                required
                className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </Field>
            {charterPreview && (
              <section className="rounded-lg border border-sky-200 bg-sky-50 p-3">
                <p className="text-sm font-semibold text-sky-900">
                  Будет создана ревизия {charterPreview.schedule_revision + 1}
                </p>
                <ul className="mt-2 space-y-1 text-xs leading-5 text-sky-900">
                  {charterPreview.changes.map((change) => (
                    <li key={change.field}>
                      {charterFieldLabels[change.field]}: изменение будет
                      зафиксировано с сохранением исходного значения.
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
              <button
                type="button"
                onClick={() => setDialog(null)}
                className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700"
              >
                Отмена
              </button>
              {!charterPreview ? (
                <button
                  type="submit"
                  disabled={busy}
                  className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Проверить изменение
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void applyCharter()}
                  disabled={busy}
                  className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Применить поправку
                </button>
              )}
            </div>
          </form>
        </Modal>
      )}

      {dialog === 'deadline' && (
        <Modal title="Изменить целевой срок" onClose={() => setDialog(null)}>
          <div className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg bg-slate-50 p-3">
                <span className="text-xs text-slate-500">Baseline</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(entity.due_at)}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <span className="text-xs text-slate-500">Текущая цель</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(entity.target_due_at || entity.due_at)}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <span className="text-xs text-slate-500">Прогноз</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(entity.forecast_due_at)}</p>
              </div>
            </div>
            <Field label="Новая целевая дата">
              <input type="datetime-local" value={deadlineTarget} min={inputDate(entity.starts_at)} onChange={(event) => { setDeadlineTarget(event.target.value); setDeadlinePreview(null) }} className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary" />
            </Field>
            <Field label="Причина управленческого изменения">
              <textarea value={deadlineReason} onChange={(event) => { setDeadlineReason(event.target.value); setDeadlinePreview(null) }} rows={3} className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
            </Field>
            {deadlinePreview && (
              <section className={cn('rounded-lg border p-3', deadlinePreview.conflicts.length ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50')}>
                <h4 className="text-sm font-semibold text-slate-900">
                  Влияние: {deadlinePreview.shift_days > 0 ? '+' : ''}{deadlinePreview.shift_days} дн.
                </h4>
                {deadlinePreview.conflicts.length ? (
                  <>
                    <p className="mt-1 text-xs leading-5 text-amber-900">
                      Новая цель не меняет работы автоматически. После фиксации перепланируйте элементы:
                    </p>
                    <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
                      {deadlinePreview.conflicts.map((conflict) => (
                        <div key={`${conflict.node_type}-${conflict.node_id}`} className="rounded bg-white/80 px-2 py-1.5 text-xs text-slate-700">
                          <strong>{conflict.node_ref}</strong> {conflict.title} · {formatDate(conflict.forecast_due_at)}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="mt-1 text-xs text-emerald-800">Открытые элементы помещаются в новую целевую дату.</p>
                )}
              </section>
            )}
            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setDialog(null)} className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700">Отмена</button>
              {!deadlinePreview ? (
                <button type="button" onClick={() => void previewDeadline()} disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Проверить влияние
                </button>
              ) : (
                <button type="button" onClick={() => void applyDeadline()} disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Зафиксировать цель
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}

      {dialog === 'reschedule' && rescheduleMilestone && (
        <Modal title={`Изменить дату: ${rescheduleMilestone.title}`} onClose={() => setDialog(null)}>
          <div className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-slate-50 p-3">
                <span className="text-xs text-slate-500">Базовая дата</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(rescheduleMilestone.baseline_at, true)}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <span className="text-xs text-slate-500">Текущий прогноз</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(rescheduleMilestone.forecast_at, true)}</p>
              </div>
            </div>
            <Field label="Новая дата">
              <input type="datetime-local" value={rescheduleAt} min={inputDate(entity.starts_at)} onChange={(event) => { setRescheduleAt(event.target.value); setReschedulePreview(null) }} className="h-11 w-full rounded-lg border border-slate-200 px-2 text-sm outline-none focus:border-primary" />
            </Field>
            <Field label="Причина переноса">
              <textarea value={rescheduleReason} onChange={(event) => { setRescheduleReason(event.target.value); setReschedulePreview(null) }} rows={3} className="w-full resize-y rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-primary" />
            </Field>
            {reschedulePreview && (
              <section className={cn('rounded-lg border p-3', reschedulePreview.conflicts.length ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50')}>
                <h4 className="text-sm font-semibold text-slate-900">
                  Сдвиг: {reschedulePreview.shift_days > 0 ? '+' : ''}{reschedulePreview.shift_days} дн.; затронуто элементов: {reschedulePreview.changes.length}
                </h4>
                {reschedulePreview.conflicts.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {reschedulePreview.conflicts.map((conflict) => (
                      <p key={`${conflict.node_type}-${conflict.node_id}`} className="text-xs text-red-800">
                        <strong>{conflict.node_ref}</strong> {conflict.node_title}: {conflict.message}
                      </p>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        setDialog(null)
                        onOpenAdvanced('work')
                      }}
                      className="mt-2 inline-flex h-10 items-center gap-2 rounded-lg border border-red-200 bg-white px-3 text-sm font-medium text-red-700 hover:border-red-300"
                    >
                      <Gauge className="h-4 w-4" />
                      Перепланировать работы
                    </button>
                  </div>
                )}
              </section>
            )}
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setDialog(null)} className="h-11 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700">Отмена</button>
              {!reschedulePreview ? (
                <button type="button" onClick={() => void previewReschedule()} disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Проверить влияние
                </button>
              ) : (
                <button type="button" onClick={() => void applyReschedule()} disabled={busy || reschedulePreview.conflicts.length > 0} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-40">
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Применить изменение
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
})
