import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  HelpCircle,
  FilePlus2,
  FileText,
  Flag,
  GitBranch,
  Layers3,
  ListTodo,
  Loader2,
  MessageSquarePlus,
  Milestone as MilestoneIcon,
  Pencil,
  Plus,
  Route,
  Unlink,
  UserRound,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  WorkEntity,
  WorkEntityArtifact,
  WorkEntityArtifactType,
  WorkEntityJournalEntryType,
  WorkEntityMilestone,
  WorkEntityMilestoneCriticality,
  WorkEntityMilestoneLifecycleStatus,
  WorkEntityMilestoneReschedulePreview,
  WorkEntityMilestoneRescheduleRequest,
  WorkEntityMilestoneUpdate,
  WorkEntityScheduleDependency,
  WorkEntityScheduleNodeType,
  WorkEntityStage,
  WorkEntityStageStatus,
  WorkEntityTask,
  WorkEntityTaskCreate,
  WorkEntityTaskPriority,
  WorkEntityTaskStatus,
  WorkEntityTaskUpdate,
  WorkEntityWorkspace,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import {
  OperationExecutionContractButton,
  OperationExecutionContractModal,
} from '@/components/OperationExecutionContract'

const inputClass =
  'h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/15'
const textareaClass =
  'w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/15'
const iconButtonClass =
  'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-primary/10 hover:text-primary disabled:opacity-40'

const taskStatusLabels: Record<WorkEntityTaskStatus, string> = {
  planned: 'Запланирована',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  blocked: 'Заблокирована',
  review: 'На проверке',
  done: 'Выполнена',
  cancelled: 'Отменена',
}

const taskStatusClasses: Record<WorkEntityTaskStatus, string> = {
  planned: 'bg-slate-100 text-slate-700',
  in_progress: 'bg-sky-50 text-sky-700',
  waiting: 'bg-amber-50 text-amber-800',
  blocked: 'bg-red-50 text-red-700',
  review: 'bg-violet-50 text-violet-700',
  done: 'bg-emerald-50 text-emerald-700',
  cancelled: 'bg-slate-100 text-slate-500',
}

const participantTaskStatuses: WorkEntityTaskStatus[] = [
  'in_progress',
  'waiting',
  'blocked',
  'review',
  'done',
]

const taskPriorityLabels: Record<WorkEntityTaskPriority, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  critical: 'Критичный',
}

const milestoneLifecycleLabels: Record<WorkEntityMilestoneLifecycleStatus, string> = {
  planned: 'Запланирована',
  achieved: 'Пройдена',
  cancelled: 'Отменена',
}

const milestoneDisplayLabels: Record<WorkEntityMilestone['display_status'], string> = {
  planned: 'Запланирована',
  rescheduled: 'Перенесена',
  overdue: 'Просрочена',
  achieved: 'Пройдена',
  cancelled: 'Отменена',
}

const milestoneDisplayClasses: Record<WorkEntityMilestone['display_status'], string> = {
  planned: 'bg-sky-50 text-sky-700',
  rescheduled: 'bg-amber-50 text-amber-800',
  overdue: 'bg-red-50 text-red-700',
  achieved: 'bg-emerald-50 text-emerald-700',
  cancelled: 'bg-slate-100 text-slate-500',
}

const criticalityLabels: Record<WorkEntityMilestoneCriticality, string> = {
  control: 'Контрольная',
  key: 'Ключевая',
  critical: 'Критическая',
}

const criticalityHelp: Record<WorkEntityMilestoneCriticality, string> = {
  control: 'Внутренняя проверка хода исполнения. Не является обязательным внешним обязательством.',
  key: 'Открывает следующий этап, результат или операцию другой команды. Требуется обоснование.',
  critical: 'Связана с внешним обязательством, решением руководящего органа или сроком проекта. Требуется обоснование.',
}

const criticalityClasses: Record<WorkEntityMilestoneCriticality, string> = {
  control: 'border-slate-200 text-slate-600',
  key: 'border-amber-300 text-amber-800',
  critical: 'border-red-300 text-red-700',
}

const stageStatusLabels: Record<WorkEntityStageStatus, string> = {
  planned: 'Запланирован',
  active: 'Активен',
  done: 'Завершен',
  cancelled: 'Отменен',
}

const artifactLabels: Record<WorkEntityArtifactType, string> = {
  note: 'Заметка',
  decision: 'Решение',
  evidence: 'Подтверждение',
  document: 'Документ',
  reference: 'Ссылка',
  other: 'Другое',
}

const journalLabels: Record<WorkEntityJournalEntryType, string> = {
  progress: 'Ход работы',
  meeting: 'Встреча',
  decision: 'Решение',
  blocker: 'Блокер',
  comment: 'Комментарий',
}

function toInputDate(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function toPayloadDate(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function formatDate(value: string | null, includeTime = false): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  })
}

function formatShift(days: number): string {
  if (days === 0) return 'без отклонения'
  return `${days > 0 ? '+' : ''}${days} дн.`
}

function Dialog({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const panelRef = useProtectedModal<HTMLDivElement>()

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          'max-h-[94vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-2xl sm:rounded-lg',
          wide ? 'sm:max-w-4xl' : 'sm:max-w-xl',
        )}
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-slate-900">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className={iconButtonClass} aria-label="Закрыть">
            <X className="h-5 w-5" />
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

function FieldHelp({ children }: { children: ReactNode }) {
  return (
    <span className="mt-1 flex items-start gap-1.5 text-xs leading-5 text-slate-500">
      <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </span>
  )
}

type TaskFormState = {
  title: string
  description: string
  status: WorkEntityTaskStatus
  priority: WorkEntityTaskPriority
  assigneeId: string
  stageId: string
  targetMilestoneId: string
  acceptanceCriteria: string
  nextStep: string
  waitingFor: string
  baselineStartsAt: string
  baselineDueAt: string
  forecastStartsAt: string
  forecastDueAt: string
  changeReason: string
}

const emptyTaskForm: TaskFormState = {
  title: '',
  description: '',
  status: 'planned',
  priority: 'medium',
  assigneeId: '',
  stageId: '',
  targetMilestoneId: '',
  acceptanceCriteria: '',
  nextStep: '',
  waitingFor: '',
  baselineStartsAt: '',
  baselineDueAt: '',
  forecastStartsAt: '',
  forecastDueAt: '',
  changeReason: '',
}

type MilestoneFormState = {
  title: string
  description: string
  status: WorkEntityMilestoneLifecycleStatus
  criticality: WorkEntityMilestoneCriticality
  criticalityReason: string
  acceptanceCriteria: string
  decisionOwnerId: string
  stageId: string
  baselineAt: string
  changeReason: string
}

const emptyMilestoneForm: MilestoneFormState = {
  title: '',
  description: '',
  status: 'planned',
  criticality: 'control',
  criticalityReason: '',
  acceptanceCriteria: '',
  decisionOwnerId: '',
  stageId: '',
  baselineAt: '',
  changeReason: '',
}

type StageFormState = {
  title: string
  description: string
  completionCriteria: string
  guidance: string
  status: WorkEntityStageStatus
}

const emptyStageForm: StageFormState = {
  title: '',
  description: '',
  completionCriteria: '',
  guidance: '',
  status: 'planned',
}

type JournalTarget = {
  type: WorkEntityScheduleNodeType
  id: string
  ref: string
  title: string
} | null

function parseNodeValue(value: string): { type: WorkEntityScheduleNodeType; id: string } | null {
  const separator = value.indexOf(':')
  if (separator < 0) return null
  const type = value.slice(0, separator)
  const id = value.slice(separator + 1)
  if ((type !== 'task' && type !== 'milestone') || !id) return null
  return { type, id }
}

export function WorkEntityWorkspacePanel({
  entity,
  onChanged,
}: {
  entity: WorkEntity
  onChanged: () => void | Promise<void>
}) {
  const [workspace, setWorkspace] = useState<WorkEntityWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const [expandedTaskId, setExpandedTaskId] = useState('')
  const [executionContractTask, setExecutionContractTask] =
    useState<WorkEntityTask | null>(null)
  const [expandedMilestoneId, setExpandedMilestoneId] = useState('')

  const [taskDialogOpen, setTaskDialogOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<WorkEntityTask | null>(null)
  const [taskForm, setTaskForm] = useState<TaskFormState>(emptyTaskForm)

  const [milestoneDialogOpen, setMilestoneDialogOpen] = useState(false)
  const [editingMilestone, setEditingMilestone] = useState<WorkEntityMilestone | null>(null)
  const [milestoneForm, setMilestoneForm] = useState<MilestoneFormState>(emptyMilestoneForm)

  const [stageDialogOpen, setStageDialogOpen] = useState(false)
  const [editingStage, setEditingStage] = useState<WorkEntityStage | null>(null)
  const [stageForm, setStageForm] = useState<StageFormState>(emptyStageForm)

  const [rescheduleMilestone, setRescheduleMilestone] = useState<WorkEntityMilestone | null>(null)
  const [rescheduleForecastAt, setRescheduleForecastAt] = useState('')
  const [rescheduleReason, setRescheduleReason] = useState('')
  const [rescheduleCascade, setRescheduleCascade] = useState(true)
  const [reschedulePreview, setReschedulePreview] =
    useState<WorkEntityMilestoneReschedulePreview | null>(null)

  const [journalTarget, setJournalTarget] = useState<JournalTarget>(null)
  const [journalType, setJournalType] = useState<WorkEntityJournalEntryType>('progress')
  const [journalBody, setJournalBody] = useState('')

  const [artifactDialogOpen, setArtifactDialogOpen] = useState(false)
  const [editingArtifact, setEditingArtifact] = useState<WorkEntityArtifact | null>(null)
  const [artifactType, setArtifactType] = useState<WorkEntityArtifactType>('note')
  const [artifactTitle, setArtifactTitle] = useState('')
  const [artifactBody, setArtifactBody] = useState('')
  const [artifactUrl, setArtifactUrl] = useState('')
  const [artifactParent, setArtifactParent] = useState('')

  const [dependencyPredecessor, setDependencyPredecessor] = useState('')
  const [dependencySuccessor, setDependencySuccessor] = useState('')
  const [dependencyLagDays, setDependencyLagDays] = useState(0)
  const [dependencyCascade, setDependencyCascade] = useState(true)
  const [waivingDependencyId, setWaivingDependencyId] = useState<string | null>(null)
  const [dependencyWaiverReason, setDependencyWaiverReason] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setWorkspace(
        await api.get<WorkEntityWorkspace>(`/api/work-entities/${entity.id}/workspace`),
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить рабочее пространство')
    } finally {
      setLoading(false)
    }
  }, [entity.id])

  useEffect(() => {
    setWorkspace(null)
    void load()
  }, [load])

  useEffect(() => {
    if (!['done', 'archived'].includes(entity.status)) return
    setTaskDialogOpen(false)
    setMilestoneDialogOpen(false)
    setStageDialogOpen(false)
    setRescheduleMilestone(null)
    setReschedulePreview(null)
    setJournalTarget(null)
    setArtifactDialogOpen(false)
    setWaivingDependencyId(null)
    setExecutionContractTask(null)
  }, [entity.status])

  const refresh = async () => {
    await Promise.all([load(), Promise.resolve(onChanged())])
  }

  const workspaceMutable = !['done', 'archived'].includes(entity.status)
  const canManage =
    workspaceMutable &&
    (workspace?.current_access_role === 'owner' || workspace?.current_access_role === 'editor')
  const canContribute =
    workspaceMutable && Boolean(workspace?.current_access_role && workspace.current_access_role !== 'viewer')
  const activeTasks = useMemo(
    () => workspace?.tasks.filter((task) => task.status !== 'cancelled') ?? [],
    [workspace],
  )
  const activeMilestones = useMemo(
    () => workspace?.milestones.filter((milestone) => milestone.status !== 'cancelled') ?? [],
    [workspace],
  )
  const plannedMilestones = useMemo(
    () => workspace?.milestones.filter((milestone) => milestone.status === 'planned') ?? [],
    [workspace],
  )
  const targetMilestoneOptions = useMemo(() => {
    if (!editingTask?.target_milestone_id) return plannedMilestones
    const currentTarget = workspace?.milestones.find(
      (milestone) => milestone.id === editingTask.target_milestone_id,
    )
    if (
      !currentTarget ||
      plannedMilestones.some((milestone) => milestone.id === currentTarget.id)
    ) {
      return plannedMilestones
    }
    return [currentTarget, ...plannedMilestones]
  }, [editingTask, plannedMilestones, workspace?.milestones])
  const assignableParticipants = useMemo(
    () => workspace?.participants.filter((participant) => participant.can_be_assigned) ?? [],
    [workspace],
  )
  const scheduleNodes = useMemo(
    () => [
      ...(workspace?.tasks.map((task) => ({
        value: `task:${task.id}`,
        label: `PRJ-${task.task_number} ${task.title}`,
      })) ?? []),
      ...(workspace?.milestones.map((milestone) => ({
        value: `milestone:${milestone.id}`,
        label: `КТ-${milestone.milestone_number} ${milestone.title}`,
      })) ?? []),
    ],
    [workspace],
  )

  const openNewTask = () => {
    setEditingTask(null)
    setTaskForm({
      ...emptyTaskForm,
      targetMilestoneId: plannedMilestones[0]?.id ?? '',
      baselineStartsAt: toInputDate(entity.forecast_starts_at || entity.starts_at),
      baselineDueAt: toInputDate(entity.target_due_at || entity.due_at),
    })
    setTaskDialogOpen(true)
  }

  const openEditTask = (task: WorkEntityTask) => {
    setEditingTask(task)
    setTaskForm({
      title: task.title,
      description: task.description ?? '',
      status: task.status,
      priority: task.priority,
      assigneeId: task.assignee_id ?? '',
      stageId: task.stage_id ?? '',
      targetMilestoneId: task.target_milestone_id ?? '',
      acceptanceCriteria: task.acceptance_criteria ?? '',
      nextStep: task.next_step ?? '',
      waitingFor: task.waiting_for ?? '',
      baselineStartsAt: toInputDate(task.baseline_starts_at),
      baselineDueAt: toInputDate(task.baseline_due_at),
      forecastStartsAt: toInputDate(task.forecast_starts_at),
      forecastDueAt: toInputDate(task.forecast_due_at),
      changeReason: '',
    })
    setTaskDialogOpen(true)
  }

  const saveTask = async (event: FormEvent) => {
    event.preventDefault()
    if (!taskForm.title.trim()) return
    if (
      !editingTask &&
      entity.entity_type === 'project' &&
      !taskForm.targetMilestoneId
    ) {
      toast.error('Выберите контрольную точку, которую подготавливает операция')
      return
    }
    setBusy(true)
    try {
      if (editingTask) {
        const payload: WorkEntityTaskUpdate = {
          title: taskForm.title.trim(),
          description: taskForm.description.trim() || null,
          status: taskForm.status,
          priority: taskForm.priority,
          assignee_id: taskForm.assigneeId || null,
          stage_id: taskForm.stageId || null,
          target_milestone_id: taskForm.targetMilestoneId || null,
          acceptance_criteria: taskForm.acceptanceCriteria.trim() || null,
          next_step: taskForm.nextStep.trim() || null,
          waiting_for: taskForm.waitingFor.trim() || null,
          forecast_starts_at: toPayloadDate(taskForm.forecastStartsAt),
          forecast_due_at: toPayloadDate(taskForm.forecastDueAt),
          change_reason: taskForm.changeReason.trim() || null,
        }
        await api.patch(`/api/work-entities/${entity.id}/tasks/${editingTask.id}`, payload)
      } else {
        const payload: WorkEntityTaskCreate = {
          title: taskForm.title.trim(),
          description: taskForm.description.trim() || null,
          status: taskForm.status,
          priority: taskForm.priority,
          assignee_id: taskForm.assigneeId || null,
          stage_id: taskForm.stageId || null,
          acceptance_criteria: taskForm.acceptanceCriteria.trim() || null,
          next_step: taskForm.nextStep.trim() || null,
          waiting_for: taskForm.waitingFor.trim() || null,
          baseline_starts_at: toPayloadDate(taskForm.baselineStartsAt),
          baseline_due_at: toPayloadDate(taskForm.baselineDueAt),
          target_milestone_id: taskForm.targetMilestoneId || null,
        }
        await api.post(`/api/work-entities/${entity.id}/tasks`, payload)
      }
      setTaskDialogOpen(false)
      await refresh()
      toast.success(editingTask ? 'Операция обновлена' : 'Операция добавлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить операцию')
    } finally {
      setBusy(false)
    }
  }

  const changeTaskStatus = async (task: WorkEntityTask, status: WorkEntityTaskStatus) => {
    setBusy(true)
    try {
      await api.patch(`/api/work-entities/${entity.id}/tasks/${task.id}`, { status })
      await refresh()
      toast.success('Статус операции обновлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить статус')
    } finally {
      setBusy(false)
    }
  }

  const openNewMilestone = () => {
    setEditingMilestone(null)
    setMilestoneForm({
      ...emptyMilestoneForm,
      baselineAt: toInputDate(entity.due_at),
    })
    setMilestoneDialogOpen(true)
  }

  const openEditMilestone = (milestone: WorkEntityMilestone) => {
    setEditingMilestone(milestone)
    setMilestoneForm({
      title: milestone.title,
      description: milestone.description ?? '',
      status: milestone.status,
      criticality: milestone.criticality,
      criticalityReason: milestone.criticality_reason ?? '',
      acceptanceCriteria: milestone.acceptance_criteria,
      decisionOwnerId: milestone.decision_owner_id ?? '',
      stageId: milestone.stage_id ?? '',
      baselineAt: toInputDate(milestone.baseline_at),
      changeReason: '',
    })
    setMilestoneDialogOpen(true)
  }

  const saveMilestone = async (event: FormEvent) => {
    event.preventDefault()
    const needsCriticalityReason =
      milestoneForm.criticality === 'key' || milestoneForm.criticality === 'critical'
    if (
      !milestoneForm.title.trim() ||
      !milestoneForm.acceptanceCriteria.trim() ||
      !milestoneForm.baselineAt ||
      (needsCriticalityReason && !milestoneForm.criticalityReason.trim()) ||
      (editingMilestone &&
        editingMilestone.status !== milestoneForm.status &&
        !milestoneForm.changeReason.trim())
    ) {
      return
    }
    setBusy(true)
    try {
      if (editingMilestone) {
        const payload: WorkEntityMilestoneUpdate = {
          title: milestoneForm.title.trim(),
          description: milestoneForm.description.trim() || null,
          status: milestoneForm.status,
          criticality: milestoneForm.criticality,
          criticality_reason: milestoneForm.criticalityReason.trim() || null,
          acceptance_criteria: milestoneForm.acceptanceCriteria.trim(),
          decision_owner_id: milestoneForm.decisionOwnerId || null,
          stage_id: milestoneForm.stageId || null,
          change_reason: milestoneForm.changeReason.trim() || null,
        }
        await api.patch(
          `/api/work-entities/${entity.id}/milestones/${editingMilestone.id}`,
          payload,
        )
      } else {
        await api.post(`/api/work-entities/${entity.id}/milestones`, {
          title: milestoneForm.title.trim(),
          description: milestoneForm.description.trim() || null,
          status: milestoneForm.status,
          criticality: milestoneForm.criticality,
          criticality_reason: milestoneForm.criticalityReason.trim() || null,
          acceptance_criteria: milestoneForm.acceptanceCriteria.trim(),
          decision_owner_id: milestoneForm.decisionOwnerId || null,
          stage_id: milestoneForm.stageId || null,
          baseline_at: toPayloadDate(milestoneForm.baselineAt),
        })
      }
      setMilestoneDialogOpen(false)
      await refresh()
      toast.success(editingMilestone ? 'Контрольная точка обновлена' : 'Контрольная точка добавлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить контрольную точку')
    } finally {
      setBusy(false)
    }
  }

  const openReschedule = (milestone: WorkEntityMilestone) => {
    setRescheduleMilestone(milestone)
    setRescheduleForecastAt(toInputDate(milestone.forecast_at))
    setRescheduleReason('')
    setRescheduleCascade(true)
    setReschedulePreview(null)
  }

  const closeReschedule = () => {
    setRescheduleMilestone(null)
    setReschedulePreview(null)
  }

  const previewReschedule = async (event: FormEvent) => {
    event.preventDefault()
    if (!rescheduleMilestone || !rescheduleForecastAt || rescheduleReason.trim().length < 3) return
    setBusy(true)
    setReschedulePreview(null)
    try {
      const payload: WorkEntityMilestoneRescheduleRequest = {
        forecast_at: new Date(rescheduleForecastAt).toISOString(),
        reason: rescheduleReason.trim(),
        cascade: rescheduleCascade,
        expected_revision: entity.schedule_revision,
      }
      setReschedulePreview(
        await api.post<WorkEntityMilestoneReschedulePreview>(
          `/api/work-entities/${entity.id}/milestones/${rescheduleMilestone.id}/reschedule/preview`,
          payload,
        ),
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось рассчитать перенос')
    } finally {
      setBusy(false)
    }
  }

  const applyReschedule = async () => {
    if (!rescheduleMilestone || !reschedulePreview || reschedulePreview.conflicts.length > 0) return
    setBusy(true)
    try {
      const payload: WorkEntityMilestoneRescheduleRequest = {
        forecast_at: new Date(rescheduleForecastAt).toISOString(),
        reason: rescheduleReason.trim(),
        cascade: rescheduleCascade,
        expected_revision: reschedulePreview.schedule_revision,
      }
      await api.post(
        `/api/work-entities/${entity.id}/milestones/${rescheduleMilestone.id}/reschedule/apply`,
        payload,
      )
      closeReschedule()
      await refresh()
      toast.success('Новый прогноз графика применен')
    } catch (error) {
      setReschedulePreview(null)
      toast.error(error instanceof Error ? error.message : 'Не удалось применить перенос')
    } finally {
      setBusy(false)
    }
  }

  const openNewStage = () => {
    setEditingStage(null)
    setStageForm(emptyStageForm)
    setStageDialogOpen(true)
  }

  const openEditStage = (stage: WorkEntityStage) => {
    setEditingStage(stage)
    setStageForm({
      title: stage.title,
      description: stage.description ?? '',
      completionCriteria: stage.completion_criteria ?? '',
      guidance: stage.guidance ?? '',
      status: stage.status,
    })
    setStageDialogOpen(true)
  }

  const saveStage = async (event: FormEvent) => {
    event.preventDefault()
    if (!stageForm.title.trim()) return
    setBusy(true)
    const payload = {
      title: stageForm.title.trim(),
      description: stageForm.description.trim() || null,
      completion_criteria: stageForm.completionCriteria.trim() || null,
      guidance: stageForm.guidance.trim() || null,
      status: stageForm.status,
    }
    try {
      if (editingStage) {
        await api.patch(`/api/work-entities/${entity.id}/stages/${editingStage.id}`, payload)
      } else {
        await api.post(`/api/work-entities/${entity.id}/stages`, {
          ...payload,
          source_type: 'manual',
        })
      }
      setStageDialogOpen(false)
      await refresh()
      toast.success(editingStage ? 'Этап обновлен' : 'Этап добавлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить этап')
    } finally {
      setBusy(false)
    }
  }

  const saveJournal = async (event: FormEvent) => {
    event.preventDefault()
    if (!journalTarget || !journalBody.trim()) return
    setBusy(true)
    try {
      const path =
        journalTarget.type === 'task'
          ? `/api/work-entities/${entity.id}/tasks/${journalTarget.id}/journal`
          : `/api/work-entities/${entity.id}/milestones/${journalTarget.id}/journal`
      await api.post(path, {
        entry_type: journalType,
        body: journalBody.trim(),
      })
      setJournalTarget(null)
      setJournalBody('')
      await refresh()
      toast.success('Запись добавлена в журнал проекта')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить запись')
    } finally {
      setBusy(false)
    }
  }

  const addDependency = async () => {
    const predecessor = parseNodeValue(dependencyPredecessor)
    const successor = parseNodeValue(dependencySuccessor)
    if (!predecessor || !successor) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${entity.id}/dependencies`, {
        predecessor_type: predecessor.type,
        predecessor_id: predecessor.id,
        successor_type: successor.type,
        successor_id: successor.id,
        dependency_type: 'finish_to_start',
        lag_days: dependencyLagDays,
        cascade_on_shift: dependencyCascade,
      })
      setDependencyPredecessor('')
      setDependencySuccessor('')
      setDependencyLagDays(0)
      await refresh()
      toast.success('Зависимость добавлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить зависимость')
    } finally {
      setBusy(false)
    }
  }

  const removeDependency = async (dependency: WorkEntityScheduleDependency) => {
    setBusy(true)
    try {
      await api.delete(`/api/work-entities/${entity.id}/dependencies/${dependency.id}`)
      await refresh()
      toast.success('Зависимость удалена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить зависимость')
    } finally {
      setBusy(false)
    }
  }

  const waiveDependency = async (dependency: WorkEntityScheduleDependency) => {
    if (!dependencyWaiverReason.trim()) return
    setBusy(true)
    try {
      await api.post(
        `/api/work-entities/${entity.id}/dependencies/${dependency.id}/waive`,
        { reason: dependencyWaiverReason.trim() },
      )
      setWaivingDependencyId(null)
      setDependencyWaiverReason('')
      await refresh()
      toast.success('Исключение зафиксировано, следующий шаг разблокирован')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось снять блокировку')
    } finally {
      setBusy(false)
    }
  }

  const resetArtifactForm = () => {
    setEditingArtifact(null)
    setArtifactType('note')
    setArtifactTitle('')
    setArtifactBody('')
    setArtifactUrl('')
    setArtifactParent('')
  }

  const openNewArtifact = () => {
    resetArtifactForm()
    setArtifactDialogOpen(true)
  }

  const openEditArtifact = (artifact: WorkEntityArtifact) => {
    setEditingArtifact(artifact)
    setArtifactType(artifact.artifact_type)
    setArtifactTitle(artifact.title)
    setArtifactBody(artifact.body ?? '')
    setArtifactUrl(artifact.url ?? '')
    setArtifactParent(
      artifact.task_id
        ? `task:${artifact.task_id}`
        : artifact.milestone_id
          ? `milestone:${artifact.milestone_id}`
          : '',
    )
    setArtifactDialogOpen(true)
  }

  const closeArtifactDialog = () => {
    setArtifactDialogOpen(false)
    resetArtifactForm()
  }

  const saveArtifact = async (event: FormEvent) => {
    event.preventDefault()
    if (!artifactTitle.trim() || (!artifactBody.trim() && !artifactUrl.trim())) return
    const parent = parseNodeValue(artifactParent)
    if (artifactType === 'evidence' && parent?.type !== 'milestone') {
      toast.error('Подтверждение результата нужно связать с контрольной точкой')
      return
    }
    setBusy(true)
    try {
      const payload = {
        artifact_type: artifactType,
        title: artifactTitle.trim(),
        body: artifactBody.trim() || null,
        url: artifactUrl.trim() || null,
        task_id: parent?.type === 'task' ? parent.id : null,
        milestone_id: parent?.type === 'milestone' ? parent.id : null,
      }
      if (editingArtifact) {
        await api.patch(
          `/api/work-entities/${entity.id}/artifacts/${editingArtifact.id}`,
          payload,
        )
      } else {
        await api.post(`/api/work-entities/${entity.id}/artifacts`, payload)
      }
      closeArtifactDialog()
      await refresh()
      toast.success(editingArtifact ? 'Артефакт обновлен' : 'Артефакт добавлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить артефакт')
    } finally {
      setBusy(false)
    }
  }

  const archiveArtifact = async (artifact: WorkEntityArtifact) => {
    setBusy(true)
    try {
      await api.patch(`/api/work-entities/${entity.id}/artifacts/${artifact.id}`, {
        status: artifact.status === 'archived' ? 'active' : 'archived',
      })
      await refresh()
      toast.success(artifact.status === 'archived' ? 'Артефакт восстановлен' : 'Артефакт архивирован')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить артефакт')
    } finally {
      setBusy(false)
    }
  }

  if ((loading && !workspace) || (workspace && workspace.entity_id !== entity.id)) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Загрузка рабочего пространства
      </div>
    )
  }

  if (!workspace) return null

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Операции проекта</h3>
          <p className="mt-1 text-xs text-slate-500">
            Операции описывают исполняемые действия, контрольные точки фиксируют проверяемое событие на одну дату.
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {canManage && (
            <>
              <button
                type="button"
                onClick={openNewStage}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary"
              >
                <Layers3 className="h-4 w-4" />
                Этап
              </button>
              <button
                type="button"
                onClick={openNewMilestone}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 text-sm font-medium text-primary hover:bg-primary/10"
              >
                <MilestoneIcon className="h-4 w-4" />
                Контрольная точка
              </button>
              <button
                type="button"
                onClick={openNewTask}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                <Plus className="h-4 w-4" />
                Операция
              </button>
            </>
          )}
          {canContribute && (
            <button
              type="button"
              onClick={openNewArtifact}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary"
            >
              <FilePlus2 className="h-4 w-4" />
              Артефакт
            </button>
          )}
        </div>
      </header>

      <section className="border-y border-slate-200 py-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase text-slate-500">
            Этапы · {workspace.stages.length}
          </h4>
          <span className="text-xs text-slate-500">
            {entity.planning_mode === 'methodology' ? 'По методологии' : 'Свободное планирование'}
          </span>
        </div>
        {workspace.stages.length === 0 ? (
          <p className="text-sm text-slate-500">Этапы не заданы. Операции и точки можно планировать без них.</p>
        ) : (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {workspace.stages.map((stage, index) => (
              <article key={stage.id} className="flex min-w-0 items-start gap-3 rounded-lg border border-slate-200 px-3 py-2.5">
                <span className="inline-flex h-7 min-w-7 items-center justify-center rounded bg-slate-100 px-1.5 text-xs font-semibold text-slate-600">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h5 className="min-w-0 truncate text-sm font-semibold text-slate-900" title={stage.title}>
                      {stage.title}
                    </h5>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                      {stageStatusLabels[stage.status]}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {stage.tasks_count} операций · {stage.milestones_count} точек
                  </p>
                  {stage.completion_criteria && (
                    <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                      Результат: {stage.completion_criteria}
                    </p>
                  )}
                </div>
                {stage.can_manage && (
                  <button
                    type="button"
                    onClick={() => openEditStage(stage)}
                    className={iconButtonClass}
                    title="Редактировать этап"
                    aria-label={`Редактировать этап ${stage.title}`}
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.75fr)]">
        <div className="min-w-0 space-y-5">
          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase text-slate-500">
                Операции · {activeTasks.length}
              </h4>
              <span className="text-xs text-slate-500">{assignableParticipants.length} исполнителей</span>
            </div>
            {activeTasks.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center">
                <ListTodo className="mx-auto h-7 w-7 text-slate-300" />
                <p className="mt-2 text-sm font-medium text-slate-700">Исполняемые операции не добавлены</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                {activeTasks.map((task) => {
                  const expanded = expandedTaskId === task.id
                  return (
                    <article key={task.id} className={cn(task.status === 'done' && 'bg-emerald-50/20')}>
                      <div className="flex min-h-20 items-start gap-3 px-3 py-3">
                        <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-700">
                          <ListTodo className="h-4 w-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 flex-wrap items-center gap-2">
                            <span className="text-[11px] font-semibold text-slate-600">
                              PRJ-{task.task_number}
                            </span>
                            <h5 className="min-w-0 break-words text-sm font-semibold text-slate-900">
                              {task.title}
                            </h5>
                            <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', taskStatusClasses[task.status])}>
                              {taskStatusLabels[task.status]}
                            </span>
                          </div>
                          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                            <span className="inline-flex items-center gap-1">
                              <UserRound className="h-3.5 w-3.5" />
                              {task.assignee_name || 'Не назначено'}
                            </span>
                            <span className="inline-flex items-center gap-1">
                              <CalendarDays className="h-3.5 w-3.5" />
                              прогноз до {formatDate(task.forecast_due_at)}
                            </span>
                            {task.stage_title && (
                              <span className="inline-flex items-center gap-1">
                                <Layers3 className="h-3.5 w-3.5" />
                                {task.stage_title}
                              </span>
                            )}
                            {task.predecessor_ids.length > 0 && (
                              <span className="inline-flex items-center gap-1">
                                <GitBranch className="h-3.5 w-3.5" />
                                предшественников: {task.predecessor_ids.length}
                              </span>
                            )}
                          </div>
                          {task.next_step && (
                            <p className="mt-1.5 line-clamp-2 text-xs text-slate-600">
                              Следующий шаг: {task.next_step}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <OperationExecutionContractButton
                            operation={task}
                            projectStatus={entity.status}
                            compact
                            onClick={() => setExecutionContractTask(task)}
                          />
                          {task.can_execute && (
                            <button
                              type="button"
                              onClick={() =>
                                setJournalTarget({
                                  type: 'task',
                                  id: task.id,
                                  ref: `PRJ-${task.task_number}`,
                                  title: task.title,
                                })
                              }
                              className={iconButtonClass}
                              title="Добавить запись в журнал"
                              aria-label={`Добавить запись в журнал операции ${task.title}`}
                            >
                              <MessageSquarePlus className="h-4 w-4" />
                            </button>
                          )}
                          {task.can_manage && (
                            <button
                              type="button"
                              onClick={() => openEditTask(task)}
                              className={iconButtonClass}
                              title="Редактировать операцию"
                              aria-label={`Редактировать операцию ${task.title}`}
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setExpandedTaskId(expanded ? '' : task.id)}
                            className={iconButtonClass}
                            aria-label={expanded ? 'Свернуть детали операции' : 'Раскрыть детали операции'}
                          >
                            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>
                      {expanded && (
                        <div className="border-t border-slate-100 bg-slate-50/50 px-3 py-3">
                          <div className="grid gap-3 text-xs text-slate-600 sm:grid-cols-2">
                            <div>
                              <span className="font-semibold text-slate-700">Описание операции</span>
                              <p className="mt-1 whitespace-pre-wrap">{task.description || 'Не заполнено'}</p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Критерии приемки</span>
                              <p className="mt-1 whitespace-pre-wrap">{task.acceptance_criteria || 'Не заполнены'}</p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Базовый план</span>
                              <p className="mt-1">
                                {formatDate(task.baseline_starts_at)} → {formatDate(task.baseline_due_at)}
                              </p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Текущий прогноз</span>
                              <p className="mt-1">
                                {formatDate(task.forecast_starts_at)} → {formatDate(task.forecast_due_at)}
                                {task.variance_days !== null && task.variance_days !== 0 && (
                                  <span className="ml-2 font-medium text-amber-700">{formatShift(task.variance_days)}</span>
                                )}
                              </p>
                            </div>
                            {task.waiting_for && (
                              <div>
                                <span className="font-semibold text-slate-700">Что ожидаем</span>
                                <p className="mt-1">{task.waiting_for}</p>
                              </div>
                            )}
                            <div>
                              <span className="font-semibold text-slate-700">Приоритет операции</span>
                              <p className="mt-1">{taskPriorityLabels[task.priority]}</p>
                            </div>
                          </div>
                          {task.can_execute && (
                            <label className="mt-3 block max-w-xs">
                              <span className="mb-1 block text-xs font-semibold text-slate-700">Статус исполнения</span>
                              <select
                                value={task.status}
                                disabled={busy}
                                onChange={(event) => void changeTaskStatus(task, event.target.value as WorkEntityTaskStatus)}
                                className={inputClass}
                              >
                                {(task.can_manage
                                  ? Object.keys(taskStatusLabels)
                                  : participantTaskStatuses
                                ).map((status) => (
                                  <option key={status} value={status}>
                                    {taskStatusLabels[status as WorkEntityTaskStatus]}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase text-slate-500">
                Контрольные точки · {activeMilestones.length}
              </h4>
              <span className="text-xs text-slate-500">Одна точка = одна проверяемая дата</span>
            </div>
            {activeMilestones.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center">
                <MilestoneIcon className="mx-auto h-7 w-7 text-slate-300" />
                <p className="mt-2 text-sm font-medium text-slate-700">Контрольные события не заданы</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                {activeMilestones.map((milestone) => {
                  const expanded = expandedMilestoneId === milestone.id
                  return (
                    <article key={milestone.id}>
                      <div className="flex min-h-20 items-start gap-3 px-3 py-3">
                        <span
                          className={cn(
                            'mt-0.5 inline-flex shrink-0 items-center justify-center rotate-45 border bg-white',
                            milestone.criticality === 'control' && 'h-8 w-8 border-slate-400',
                            milestone.criticality === 'key' && 'h-9 w-9 border-2 border-amber-500',
                            milestone.criticality === 'critical' && 'h-10 w-10 border-[3px] border-red-500',
                          )}
                          title={`Критичность: ${criticalityLabels[milestone.criticality]}`}
                        >
                          {milestone.status === 'achieved' && (
                            <CheckCircle2 className="-rotate-45 h-4 w-4 text-emerald-600" />
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 flex-wrap items-center gap-2">
                            <span className="text-[11px] font-semibold text-slate-600">
                              КТ-{milestone.milestone_number}
                            </span>
                            <h5 className="min-w-0 break-words text-sm font-semibold text-slate-900">
                              {milestone.title}
                            </h5>
                            <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', milestoneDisplayClasses[milestone.display_status])}>
                              {milestoneDisplayLabels[milestone.display_status]}
                            </span>
                            <span className={cn('rounded border px-1.5 py-0.5 text-[11px] font-medium', criticalityClasses[milestone.criticality])}>
                              {criticalityLabels[milestone.criticality]}
                            </span>
                          </div>
                          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                            <span className="inline-flex items-center gap-1">
                              <Flag className="h-3.5 w-3.5" />
                              прогноз {formatDate(milestone.forecast_at)}
                            </span>
                            <span className="inline-flex items-center gap-1">
                              <UserRound className="h-3.5 w-3.5" />
                              {milestone.decision_owner_name || 'Ответственный за решение не назначен'}
                            </span>
                            {milestone.stage_title && (
                              <span className="inline-flex items-center gap-1">
                                <Layers3 className="h-3.5 w-3.5" />
                                {milestone.stage_title}
                              </span>
                            )}
                          </div>
                          {milestone.variance_days !== 0 && (
                            <p className="mt-1.5 text-xs font-medium text-amber-700">
                              Базовая дата {formatDate(milestone.baseline_at)} · отклонение {formatShift(milestone.variance_days)}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          {canContribute && (
                            <button
                              type="button"
                              onClick={() =>
                                setJournalTarget({
                                  type: 'milestone',
                                  id: milestone.id,
                                  ref: `КТ-${milestone.milestone_number}`,
                                  title: milestone.title,
                                })
                              }
                              className={iconButtonClass}
                              title="Добавить запись в журнал"
                              aria-label={`Добавить запись в журнал контрольной точки ${milestone.title}`}
                            >
                              <MessageSquarePlus className="h-4 w-4" />
                            </button>
                          )}
                          {milestone.can_manage && milestone.status === 'planned' && (
                            <button
                              type="button"
                              onClick={() => openReschedule(milestone)}
                              className={iconButtonClass}
                              title="Пересчитать перенос"
                              aria-label={`Перенести контрольную точку ${milestone.title}`}
                            >
                              <CalendarClock className="h-4 w-4" />
                            </button>
                          )}
                          {milestone.can_manage && (
                            <button
                              type="button"
                              onClick={() => openEditMilestone(milestone)}
                              className={iconButtonClass}
                              title="Редактировать контрольную точку"
                              aria-label={`Редактировать контрольную точку ${milestone.title}`}
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setExpandedMilestoneId(expanded ? '' : milestone.id)}
                            className={iconButtonClass}
                            aria-label={expanded ? 'Свернуть детали точки' : 'Раскрыть детали точки'}
                          >
                            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>
                      {expanded && (
                        <div className="border-t border-slate-100 bg-slate-50/50 px-3 py-3">
                          <div className="grid gap-3 text-xs text-slate-600 sm:grid-cols-2">
                            <div>
                              <span className="font-semibold text-slate-700">Что должно быть подтверждено</span>
                              <p className="mt-1 whitespace-pre-wrap">{milestone.acceptance_criteria}</p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Почему эта точка важна</span>
                              <p className="mt-1 whitespace-pre-wrap">
                                {milestone.criticality_reason || criticalityHelp[milestone.criticality]}
                              </p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Календарь</span>
                              <p className="mt-1">
                                база {formatDate(milestone.baseline_at)} · прогноз {formatDate(milestone.forecast_at)}
                                {milestone.actual_at && ` · факт ${formatDate(milestone.actual_at)}`}
                              </p>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Контекст</span>
                              <p className="mt-1 whitespace-pre-wrap">{milestone.description || 'Не заполнен'}</p>
                            </div>
                            {milestone.reschedule_reason && (
                              <div className="sm:col-span-2">
                                <span className="font-semibold text-slate-700">Последняя причина переноса</span>
                                <p className="mt-1 whitespace-pre-wrap">{milestone.reschedule_reason}</p>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
          </section>
        </div>

        <aside className="min-w-0 space-y-5">
          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase text-slate-500">
                Зависимости · {workspace.dependencies.length}
              </h4>
              <Route className="h-4 w-4 text-slate-400" />
            </div>
            {canManage && (
              <div className="space-y-2 rounded-lg border border-slate-200 p-3">
                <label>
                  <span className="mb-1 block text-xs font-medium text-slate-700">Предшественник</span>
                  <select
                    value={dependencyPredecessor}
                    onChange={(event) => setDependencyPredecessor(event.target.value)}
                    className={inputClass}
                  >
                    <option value="">Выберите операцию или точку</option>
                    {scheduleNodes.map((node) => (
                      <option key={node.value} value={node.value}>{node.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="mb-1 block text-xs font-medium text-slate-700">Последователь</span>
                  <select
                    value={dependencySuccessor}
                    onChange={(event) => setDependencySuccessor(event.target.value)}
                    className={inputClass}
                  >
                    <option value="">Что начинается после</option>
                    {scheduleNodes.map((node) => (
                      <option key={node.value} value={node.value}>{node.label}</option>
                    ))}
                  </select>
                </label>
                <div className="grid gap-2 sm:grid-cols-[100px_1fr] xl:grid-cols-1 2xl:grid-cols-[100px_1fr]">
                  <label>
                    <span className="mb-1 block text-xs font-medium text-slate-700">Лаг, дней</span>
                    <input
                      type="number"
                      min={0}
                      max={3650}
                      value={dependencyLagDays}
                      onChange={(event) => setDependencyLagDays(Number(event.target.value))}
                      className={inputClass}
                    />
                  </label>
                  <label className="flex min-h-11 items-center gap-2 self-end rounded-lg border border-slate-200 px-3 text-xs text-slate-700">
                    <input
                      type="checkbox"
                      checked={dependencyCascade}
                      onChange={(event) => setDependencyCascade(event.target.checked)}
                    />
                    Учитывать при переносе графика
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => void addDependency()}
                  disabled={
                    busy ||
                    !dependencyPredecessor ||
                    !dependencySuccessor ||
                    dependencyPredecessor === dependencySuccessor
                  }
                  className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  <GitBranch className="h-4 w-4" />
                  Добавить связь
                </button>
              </div>
            )}
            <div className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
              {workspace.dependencies.length === 0 ? (
                <p className="px-3 py-5 text-center text-xs text-slate-500">Зависимости не заданы</p>
              ) : (
                workspace.dependencies.map((dependency) => {
                  const predecessor = dependency.predecessor_type === 'task'
                    ? workspace.tasks.find((item) => item.id === dependency.predecessor_id)
                    : workspace.milestones.find((item) => item.id === dependency.predecessor_id)
                  const canWaive = dependency.status === 'active' && predecessor?.status === 'cancelled'
                  return (
                    <div key={dependency.id} className="px-3 py-2.5 text-xs">
                      <div className="flex items-start gap-2">
                        <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <p className="font-medium text-slate-700">
                              {dependency.predecessor_ref} → {dependency.successor_ref}
                            </p>
                            {dependency.status === 'waived' && (
                              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
                                Блокировка снята
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 break-words text-slate-500">
                            {dependency.predecessor_title} → {dependency.successor_title}
                          </p>
                          <p className="mt-0.5 text-slate-500">
                            лаг {dependency.lag_days} дн. · перенос {dependency.cascade_on_shift ? 'автоматический' : 'ручной'}
                          </p>
                          {dependency.waiver_reason && (
                            <p className="mt-1 break-words text-amber-800">
                              Исключение: {dependency.waiver_reason}
                              {dependency.waived_by_name ? ` · ${dependency.waived_by_name}` : ''}
                            </p>
                          )}
                        </div>
                        {canManage && canWaive && (
                          <button
                            type="button"
                            onClick={() => {
                              setWaivingDependencyId(
                                waivingDependencyId === dependency.id ? null : dependency.id,
                              )
                              setDependencyWaiverReason('')
                            }}
                            disabled={busy}
                            className={iconButtonClass}
                            title="Снять блокировку после отмены предшественника"
                            aria-label={`Снять блокировку ${dependency.predecessor_ref} — ${dependency.successor_ref}`}
                          >
                            <Unlink className="h-4 w-4" />
                          </button>
                        )}
                        {canManage && (
                          <button
                            type="button"
                            onClick={() => void removeDependency(dependency)}
                            disabled={busy}
                            className={iconButtonClass}
                            title="Удалить зависимость"
                            aria-label={`Удалить зависимость ${dependency.predecessor_ref} — ${dependency.successor_ref}`}
                          >
                            <X className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                      {waivingDependencyId === dependency.id && (
                        <div className="mt-2 space-y-2 rounded-lg bg-amber-50 p-2.5">
                          <p className="text-amber-900">
                            Отменённый предшественник не считается выполненным.
                            Обоснуйте исключение, чтобы сохранить историю и разблокировать следующий шаг.
                          </p>
                          <textarea
                            value={dependencyWaiverReason}
                            onChange={(event) => setDependencyWaiverReason(event.target.value)}
                            rows={2}
                            maxLength={2000}
                            className={textareaClass}
                            placeholder="Почему зависимость больше не должна блокировать работу"
                          />
                          <button
                            type="button"
                            onClick={() => void waiveDependency(dependency)}
                            disabled={busy || dependencyWaiverReason.trim().length < 3}
                            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
                          >
                            <Unlink className="h-4 w-4" />
                            Зафиксировать исключение
                          </button>
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase text-slate-500">
                Артефакты · {workspace.artifacts.filter((item) => item.status === 'active').length}
              </h4>
              <FileText className="h-4 w-4 text-slate-400" />
            </div>
            <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {workspace.artifacts.length === 0 ? (
                <p className="px-3 py-6 text-center text-xs text-slate-500">
                  Решения, документы и заметки еще не добавлены
                </p>
              ) : (
                workspace.artifacts.map((artifact) => (
                  <article key={artifact.id} className={cn('px-3 py-3', artifact.status === 'archived' && 'opacity-55')}>
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-sm font-medium text-slate-800">{artifact.title}</p>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          {artifactLabels[artifact.artifact_type]}
                          {artifact.task_title && ` · операция: ${artifact.task_title}`}
                          {artifact.milestone_title && ` · точка: ${artifact.milestone_title}`}
                        </p>
                        {artifact.body && <p className="mt-1 line-clamp-3 text-xs text-slate-600">{artifact.body}</p>}
                        {artifact.url && (
                          <a
                            href={artifact.url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-primary hover:underline"
                          >
                            Открыть ссылку
                          </a>
                        )}
                      </div>
                      {artifact.can_edit && (
                        <div className="flex shrink-0">
                          <button
                            type="button"
                            onClick={() => openEditArtifact(artifact)}
                            className={iconButtonClass}
                            title="Редактировать артефакт"
                            aria-label={`Редактировать артефакт ${artifact.title}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => void archiveArtifact(artifact)}
                            className={iconButtonClass}
                            title={artifact.status === 'archived' ? 'Восстановить' : 'Архивировать'}
                            aria-label={`${artifact.status === 'archived' ? 'Восстановить' : 'Архивировать'} артефакт ${artifact.title}`}
                          >
                            {artifact.status === 'archived' ? <CheckCircle2 className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
                          </button>
                        </div>
                      )}
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>
        </aside>
      </div>

      {taskDialogOpen && (
        <Dialog
          title={editingTask ? `Редактировать PRJ-${editingTask.task_number}` : 'Новая операция'}
          subtitle="Операция имеет исполнителя, длительность и результат, который можно принять."
          onClose={() => setTaskDialogOpen(false)}
          wide
        >
          <form onSubmit={(event) => void saveTask(event)} className="space-y-4 p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Название операции</span>
                <input
                  autoFocus
                  required
                  maxLength={240}
                  value={taskForm.title}
                  onChange={(event) => setTaskForm((value) => ({ ...value, title: event.target.value }))}
                  className={inputClass}
                />
              </label>
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Описание операции</span>
                <textarea
                  rows={4}
                  value={taskForm.description}
                  onChange={(event) => setTaskForm((value) => ({ ...value, description: event.target.value }))}
                  className={textareaClass}
                />
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Исполнитель</span>
                <select
                  value={taskForm.assigneeId}
                  onChange={(event) => setTaskForm((value) => ({ ...value, assigneeId: event.target.value }))}
                  className={inputClass}
                >
                  <option value="">Не назначен</option>
                  {assignableParticipants.map((participant) => (
                    <option key={participant.user_id} value={participant.user_id}>
                      {participant.user_name} · {participant.open_tasks} открытых
                    </option>
                  ))}
                </select>
                <FieldHelp>Назначить можно владельца, редактора или участника проекта.</FieldHelp>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Этап</span>
                <select
                  value={taskForm.stageId}
                  onChange={(event) => setTaskForm((value) => ({ ...value, stageId: event.target.value }))}
                  className={inputClass}
                >
                  <option value="">Без этапа</option>
                  {workspace.stages.filter((stage) => stage.status !== 'cancelled').map((stage) => (
                    <option key={stage.id} value={stage.id}>{stage.title}</option>
                  ))}
                </select>
              </label>
              {entity.entity_type === 'project' && (
                <label className="sm:col-span-2">
                  <span className="mb-1 block text-sm font-medium text-slate-700">
                    Какую контрольную точку подготавливает
                  </span>
                  <select
                    required
                    value={taskForm.targetMilestoneId}
                    onChange={(event) =>
                      setTaskForm((value) => ({
                        ...value,
                        targetMilestoneId: event.target.value,
                      }))
                    }
                    className={inputClass}
                  >
                    <option value="">Выберите контрольную точку</option>
                    {targetMilestoneOptions.map((milestone) => (
                      <option key={milestone.id} value={milestone.id}>
                        КТ-{milestone.milestone_number} {milestone.title}
                        {milestone.status === 'achieved' ? ' · пройдена' : ''}
                      </option>
                    ))}
                  </select>
                  <FieldHelp>
                    Операция должна готовить конкретную проверку результата.
                    {editingTask
                      ? ' Переназначение требует причины и сохраняется в журнале.'
                      : ' Без этой связи маршрут проекта неполон.'}
                  </FieldHelp>
                </label>
              )}
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Статус</span>
                <select
                  value={taskForm.status}
                  onChange={(event) => setTaskForm((value) => ({ ...value, status: event.target.value as WorkEntityTaskStatus }))}
                  className={inputClass}
                >
                  {Object.entries(taskStatusLabels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Приоритет</span>
                <select
                  value={taskForm.priority}
                  onChange={(event) => setTaskForm((value) => ({ ...value, priority: event.target.value as WorkEntityTaskPriority }))}
                  className={inputClass}
                >
                  {Object.entries(taskPriorityLabels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <FieldHelp>Приоритет определяет очередность исполнения операции, а не важность контрольной точки.</FieldHelp>
              </label>
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Критерии приемки</span>
                <textarea
                  rows={3}
                  value={taskForm.acceptanceCriteria}
                  onChange={(event) => setTaskForm((value) => ({ ...value, acceptanceCriteria: event.target.value }))}
                  className={textareaClass}
                />
                <FieldHelp>Наблюдаемый результат, по которому операция считается выполненной.</FieldHelp>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Следующий шаг</span>
                <input
                  maxLength={500}
                  value={taskForm.nextStep}
                  onChange={(event) => setTaskForm((value) => ({ ...value, nextStep: event.target.value }))}
                  className={inputClass}
                />
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Что или кого ожидаем</span>
                <input
                  maxLength={240}
                  value={taskForm.waitingFor}
                  onChange={(event) => setTaskForm((value) => ({ ...value, waitingFor: event.target.value }))}
                  className={inputClass}
                />
              </label>
            </div>

            <fieldset className="border-t border-slate-200 pt-4">
              <legend className="px-1 text-sm font-semibold text-slate-800">
                {editingTask ? 'Текущий прогноз' : 'Базовый план'}
              </legend>
              <div className="mt-2 grid gap-4 sm:grid-cols-2">
                <label>
                  <span className="mb-1 block text-sm font-medium text-slate-700">Начало</span>
                  <input
                    type="datetime-local"
                    value={editingTask ? taskForm.forecastStartsAt : taskForm.baselineStartsAt}
                    onChange={(event) =>
                      setTaskForm((value) =>
                        editingTask
                          ? { ...value, forecastStartsAt: event.target.value }
                          : { ...value, baselineStartsAt: event.target.value },
                      )
                    }
                    className={inputClass}
                  />
                </label>
                <label>
                  <span className="mb-1 block text-sm font-medium text-slate-700">Окончание</span>
                  <input
                    type="datetime-local"
                    value={editingTask ? taskForm.forecastDueAt : taskForm.baselineDueAt}
                    onChange={(event) =>
                      setTaskForm((value) =>
                        editingTask
                          ? { ...value, forecastDueAt: event.target.value }
                          : { ...value, baselineDueAt: event.target.value },
                      )
                    }
                    className={inputClass}
                  />
                </label>
              </div>
              {editingTask && (
                <>
                  <p className="mt-2 text-xs text-slate-500">
                    База остается неизменной: {formatDate(editingTask.baseline_starts_at)} → {formatDate(editingTask.baseline_due_at)}.
                  </p>
                  <label className="mt-3 block">
                    <span className="mb-1 block text-sm font-medium text-slate-700">Причина изменения прогноза</span>
                    <textarea
                      rows={2}
                      maxLength={2000}
                      value={taskForm.changeReason}
                      onChange={(event) => setTaskForm((value) => ({ ...value, changeReason: event.target.value }))}
                      className={textareaClass}
                    />
                    <FieldHelp>Обязательна, если прогнозные даты отличаются от сохраненных.</FieldHelp>
                  </label>
                </>
              )}
            </fieldset>

            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setTaskDialogOpen(false)} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                Отмена
              </button>
              <button
                type="submit"
                disabled={
                  busy ||
                  !taskForm.title.trim() ||
                  (entity.entity_type === 'project' &&
                    !taskForm.targetMilestoneId) ||
                  (Boolean(editingTask) &&
                    taskForm.targetMilestoneId !==
                      editingTask?.target_milestone_id &&
                    !taskForm.changeReason.trim())
                }
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ListTodo className="h-4 w-4" />}
                Сохранить операцию
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {milestoneDialogOpen && (
        <Dialog
          title={editingMilestone ? `Редактировать КТ-${editingMilestone.milestone_number}` : 'Новая контрольная точка'}
          subtitle="Контрольная точка не имеет длительности и исполнителя: она подтверждает событие на одну дату."
          onClose={() => setMilestoneDialogOpen(false)}
          wide
        >
          <form onSubmit={(event) => void saveMilestone(event)} className="space-y-4 p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Название события</span>
                <input
                  autoFocus
                  required
                  maxLength={240}
                  value={milestoneForm.title}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, title: event.target.value }))}
                  className={inputClass}
                />
              </label>
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Контекст</span>
                <textarea
                  rows={3}
                  value={milestoneForm.description}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, description: event.target.value }))}
                  className={textareaClass}
                />
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Базовая дата</span>
                <input
                  type="datetime-local"
                  required
                  disabled={Boolean(editingMilestone)}
                  value={milestoneForm.baselineAt}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, baselineAt: event.target.value }))}
                  className={inputClass}
                />
                <FieldHelp>
                  Это утвержденная дата. После создания она не переписывается; новый прогноз оформляется переносом.
                </FieldHelp>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Ответственный за решение</span>
                <select
                  value={milestoneForm.decisionOwnerId}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, decisionOwnerId: event.target.value }))}
                  className={inputClass}
                >
                  <option value="">Не назначен</option>
                  {assignableParticipants.map((participant) => (
                    <option key={participant.user_id} value={participant.user_id}>{participant.user_name}</option>
                  ))}
                </select>
                <FieldHelp>Подтверждает, что критерий выполнен. Это не исполнитель операции.</FieldHelp>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Этап</span>
                <select
                  value={milestoneForm.stageId}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, stageId: event.target.value }))}
                  className={inputClass}
                >
                  <option value="">Без этапа</option>
                  {workspace.stages.filter((stage) => stage.status !== 'cancelled').map((stage) => (
                    <option key={stage.id} value={stage.id}>{stage.title}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Состояние</span>
                {editingMilestone ? (
                  <select
                    value={milestoneForm.status}
                    onChange={(event) => setMilestoneForm((value) => ({ ...value, status: event.target.value as WorkEntityMilestoneLifecycleStatus }))}
                    className={inputClass}
                  >
                    {Object.entries(milestoneLifecycleLabels).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                ) : (
                  <div className="flex h-11 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
                    Запланирована
                  </div>
                )}
                <FieldHelp>«Перенесена» и «Просрочена» вычисляются системой из базовой и прогнозной дат.</FieldHelp>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Критичность</span>
                <select
                  value={milestoneForm.criticality}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, criticality: event.target.value as WorkEntityMilestoneCriticality }))}
                  className={inputClass}
                >
                  {Object.entries(criticalityLabels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <FieldHelp>{criticalityHelp[milestoneForm.criticality]}</FieldHelp>
              </label>
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">
                  Критерий прохождения
                </span>
                <textarea
                  required
                  rows={3}
                  maxLength={4000}
                  value={milestoneForm.acceptanceCriteria}
                  onChange={(event) => setMilestoneForm((value) => ({ ...value, acceptanceCriteria: event.target.value }))}
                  className={textareaClass}
                />
                <FieldHelp>Проверяемый факт, решение или артефакт, после которого точку можно отметить пройденной.</FieldHelp>
              </label>
              {(milestoneForm.criticality === 'key' || milestoneForm.criticality === 'critical') && (
                <label className="sm:col-span-2">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Обоснование критичности</span>
                  <textarea
                    required
                    rows={3}
                    maxLength={2000}
                    value={milestoneForm.criticalityReason}
                    onChange={(event) => setMilestoneForm((value) => ({ ...value, criticalityReason: event.target.value }))}
                    className={textareaClass}
                  />
                </label>
              )}
              {editingMilestone && editingMilestone.status !== milestoneForm.status && (
                <label className="sm:col-span-2">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Причина изменения состояния</span>
                  <textarea
                    required
                    rows={2}
                    maxLength={2000}
                    value={milestoneForm.changeReason}
                    onChange={(event) => setMilestoneForm((value) => ({ ...value, changeReason: event.target.value }))}
                    className={textareaClass}
                  />
                  <FieldHelp>Причина попадет в журнал вместе с автором и изменением статуса.</FieldHelp>
                </label>
              )}
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setMilestoneDialogOpen(false)} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                Отмена
              </button>
              <button
                type="submit"
                disabled={
                  busy ||
                  !milestoneForm.title.trim() ||
                  !milestoneForm.acceptanceCriteria.trim() ||
                  !milestoneForm.baselineAt ||
                  ((milestoneForm.criticality === 'key' || milestoneForm.criticality === 'critical') &&
                    !milestoneForm.criticalityReason.trim()) ||
                  Boolean(
                    editingMilestone &&
                    editingMilestone.status !== milestoneForm.status &&
                    !milestoneForm.changeReason.trim(),
                  )
                }
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MilestoneIcon className="h-4 w-4" />}
                Сохранить точку
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {stageDialogOpen && (
        <Dialog
          title={editingStage ? 'Редактировать этап' : 'Новый этап'}
          subtitle="Этап объединяет операции и контрольные точки общим результатом."
          onClose={() => setStageDialogOpen(false)}
        >
          <form onSubmit={(event) => void saveStage(event)} className="space-y-4 p-4">
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Название этапа</span>
              <input
                autoFocus
                required
                maxLength={240}
                value={stageForm.title}
                onChange={(event) => setStageForm((value) => ({ ...value, title: event.target.value }))}
                className={inputClass}
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Назначение этапа</span>
              <textarea
                rows={3}
                value={stageForm.description}
                onChange={(event) => setStageForm((value) => ({ ...value, description: event.target.value }))}
                className={textareaClass}
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Критерий завершения</span>
              <textarea
                rows={3}
                value={stageForm.completionCriteria}
                onChange={(event) => setStageForm((value) => ({ ...value, completionCriteria: event.target.value }))}
                className={textareaClass}
              />
              <FieldHelp>Что должно быть истинно, чтобы этап можно было закрыть.</FieldHelp>
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Подсказка участникам</span>
              <textarea
                rows={3}
                value={stageForm.guidance}
                onChange={(event) => setStageForm((value) => ({ ...value, guidance: event.target.value }))}
                className={textareaClass}
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Статус</span>
              <select
                value={stageForm.status}
                onChange={(event) => setStageForm((value) => ({ ...value, status: event.target.value as WorkEntityStageStatus }))}
                className={inputClass}
              >
                {Object.entries(stageStatusLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setStageDialogOpen(false)} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                Отмена
              </button>
              <button type="submit" disabled={busy || !stageForm.title.trim()} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Layers3 className="h-4 w-4" />}
                Сохранить этап
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {rescheduleMilestone && (
        <Dialog
          title={`Перенос КТ-${rescheduleMilestone.milestone_number}`}
          subtitle="Сначала система покажет последствия. Базовая дата останется неизменной."
          onClose={closeReschedule}
          wide
        >
          <form onSubmit={(event) => void previewReschedule(event)} className="space-y-4 p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 px-3 py-2">
                <span className="text-xs font-medium text-slate-500">Базовая дата</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(rescheduleMilestone.baseline_at, true)}</p>
              </div>
              <div className="rounded-lg border border-slate-200 px-3 py-2">
                <span className="text-xs font-medium text-slate-500">Текущий прогноз</span>
                <p className="mt-1 text-sm font-semibold text-slate-800">{formatDate(rescheduleMilestone.forecast_at, true)}</p>
              </div>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Новый прогноз</span>
                <input
                  type="datetime-local"
                  required
                  min={toInputDate(rescheduleMilestone.forecast_at)}
                  value={rescheduleForecastAt}
                  onChange={(event) => {
                    setRescheduleForecastAt(event.target.value)
                    setReschedulePreview(null)
                  }}
                  className={inputClass}
                />
              </label>
              <label className="flex min-h-11 items-center gap-2 self-end rounded-lg border border-slate-200 px-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={rescheduleCascade}
                  onChange={(event) => {
                    setRescheduleCascade(event.target.checked)
                    setReschedulePreview(null)
                  }}
                />
                Сдвинуть зависимые элементы вправо
              </label>
              <label className="sm:col-span-2">
                <span className="mb-1 block text-sm font-medium text-slate-700">Причина переноса</span>
                <textarea
                  required
                  rows={3}
                  minLength={3}
                  maxLength={2000}
                  value={rescheduleReason}
                  onChange={(event) => {
                    setRescheduleReason(event.target.value)
                    setReschedulePreview(null)
                  }}
                  className={textareaClass}
                />
                <FieldHelp>Причина будет записана в журнал для точки и каждого измененного элемента.</FieldHelp>
              </label>
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={
                  busy ||
                  !rescheduleForecastAt ||
                  rescheduleReason.trim().length < 3 ||
                  new Date(rescheduleForecastAt).getTime() <= new Date(rescheduleMilestone.forecast_at).getTime()
                }
                className="inline-flex h-11 items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-4 text-sm font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
                Рассчитать последствия
              </button>
            </div>
          </form>

          {reschedulePreview && (
            <section className="border-t border-slate-200 px-4 py-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="text-sm font-semibold text-slate-900">
                    Изменения графика · {reschedulePreview.changes.length}
                  </h4>
                  <p className="mt-1 text-xs text-slate-500">
                    Срок проекта: {formatDate(reschedulePreview.project_forecast_due_before)} → {formatDate(reschedulePreview.project_forecast_due_after)}
                  </p>
                </div>
                <span className="rounded bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
                  {formatShift(reschedulePreview.shift_days)}
                </span>
              </div>

              <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-[720px] w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Элемент</th>
                      <th className="px-3 py-2 font-semibold">До</th>
                      <th className="px-3 py-2 font-semibold">После</th>
                      <th className="px-3 py-2 text-right font-semibold">Сдвиг</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {reschedulePreview.changes.map((change) => (
                      <tr key={`${change.node_type}:${change.node_id}`}>
                        <td className="px-3 py-2">
                          <span className="font-semibold text-slate-700">{change.node_ref}</span>
                          <span className="ml-1 text-slate-600">{change.node_title}</span>
                          {change.criticality && (
                            <span className="ml-2 rounded border border-slate-200 px-1 py-0.5 text-[10px] text-slate-500">
                              {criticalityLabels[change.criticality as WorkEntityMilestoneCriticality] ?? change.criticality}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-600">
                          {formatDate(change.forecast_due_before, true)}
                        </td>
                        <td className="px-3 py-2 font-medium text-slate-800">
                          {formatDate(change.forecast_due_after, true)}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold text-amber-700">
                          {formatShift(change.shift_days)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {reschedulePreview.conflicts.length > 0 && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
                  <p className="flex items-center gap-2 text-sm font-semibold text-red-800">
                    <AlertTriangle className="h-4 w-4" />
                    Автоматическое применение остановлено
                  </p>
                  <ul className="mt-2 space-y-1 text-xs text-red-700">
                    {reschedulePreview.conflicts.map((conflict) => (
                      <li key={`${conflict.node_type}:${conflict.node_id}:${conflict.code}`}>
                        <span className="font-semibold">{conflict.node_ref} {conflict.node_title}:</span>{' '}
                        {conflict.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <button type="button" onClick={closeReschedule} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={() => void applyReschedule()}
                  disabled={busy || reschedulePreview.conflicts.length > 0}
                  className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Подтвердить и применить
                </button>
              </div>
            </section>
          )}
        </Dialog>
      )}

      {journalTarget && (
        <Dialog
          title={`Запись в журнал · ${journalTarget.ref}`}
          subtitle={journalTarget.title}
          onClose={() => setJournalTarget(null)}
        >
          <form onSubmit={(event) => void saveJournal(event)} className="space-y-4 p-4">
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Тип события</span>
              <select
                value={journalType}
                onChange={(event) => setJournalType(event.target.value as WorkEntityJournalEntryType)}
                className={inputClass}
              >
                {Object.entries(journalLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Что произошло</span>
              <textarea
                autoFocus
                required
                rows={7}
                maxLength={4000}
                value={journalBody}
                onChange={(event) => setJournalBody(event.target.value)}
                className={textareaClass}
              />
              <FieldHelp>Запись будет сохранена с автором, временем и ссылкой на конкретный элемент.</FieldHelp>
            </label>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={() => setJournalTarget(null)} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                Отмена
              </button>
              <button type="submit" disabled={busy || !journalBody.trim()} className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquarePlus className="h-4 w-4" />}
                Добавить запись
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {artifactDialogOpen && (
        <Dialog
          title={editingArtifact ? 'Редактировать артефакт' : 'Новый артефакт проекта'}
          onClose={closeArtifactDialog}
        >
          <form onSubmit={(event) => void saveArtifact(event)} className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Тип</span>
                <select
                  value={artifactType}
                  onChange={(event) => {
                    const nextType = event.target.value as WorkEntityArtifactType
                    setArtifactType(nextType)
                    if (
                      nextType === 'evidence' &&
                      parseNodeValue(artifactParent)?.type !== 'milestone'
                    ) {
                      setArtifactParent(
                        activeMilestones[0]
                          ? `milestone:${activeMilestones[0].id}`
                          : '',
                      )
                    }
                  }}
                  className={inputClass}
                >
                  {Object.entries(artifactLabels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">
                  {artifactType === 'evidence'
                    ? 'Какую контрольную точку подтверждает'
                    : 'Связать с элементом'}
                </span>
                <select
                  value={artifactParent}
                  onChange={(event) => setArtifactParent(event.target.value)}
                  required={artifactType === 'evidence'}
                  className={inputClass}
                >
                  {artifactType === 'evidence' ? (
                    <>
                      <option value="">Выберите контрольную точку</option>
                      {activeMilestones.map((milestone) => (
                        <option
                          key={milestone.id}
                          value={`milestone:${milestone.id}`}
                        >
                          КТ-{milestone.milestone_number} {milestone.title}
                        </option>
                      ))}
                    </>
                  ) : (
                    <>
                      <option value="">Со всем проектом</option>
                      {scheduleNodes.map((node) => (
                        <option key={node.value} value={node.value}>{node.label}</option>
                      ))}
                    </>
                  )}
                </select>
                {artifactType === 'evidence' && (
                  <FieldHelp>
                    Это подтверждение прохождения выбранной контрольной точки, а не
                    произвольный файл проекта.
                  </FieldHelp>
                )}
              </label>
            </div>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Название</span>
              <input
                autoFocus
                required
                maxLength={240}
                value={artifactTitle}
                onChange={(event) => setArtifactTitle(event.target.value)}
                className={inputClass}
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Текст</span>
              <textarea rows={6} value={artifactBody} onChange={(event) => setArtifactBody(event.target.value)} className={textareaClass} />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Ссылка</span>
              <input
                type="url"
                placeholder="https://"
                maxLength={1000}
                value={artifactUrl}
                onChange={(event) => setArtifactUrl(event.target.value)}
                className={inputClass}
              />
            </label>
            {!artifactBody.trim() && !artifactUrl.trim() && (
              <p className="flex items-center gap-2 text-xs text-amber-700">
                <AlertTriangle className="h-4 w-4" />
                Добавьте текст или ссылку.
              </p>
            )}
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button type="button" onClick={closeArtifactDialog} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600">
                Отмена
              </button>
              <button
                type="submit"
                disabled={
                  busy ||
                  !artifactTitle.trim() ||
                  (!artifactBody.trim() && !artifactUrl.trim()) ||
                  (artifactType === 'evidence' &&
                    parseNodeValue(artifactParent)?.type !== 'milestone')
                }
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePlus2 className="h-4 w-4" />}
                {editingArtifact ? 'Сохранить' : 'Добавить'}
              </button>
            </div>
          </form>
        </Dialog>
      )}

      {executionContractTask && (
        <OperationExecutionContractModal
          entityId={entity.id}
          operation={executionContractTask}
          onClose={() => setExecutionContractTask(null)}
          onChanged={refresh}
        />
      )}
    </div>
  )
}
