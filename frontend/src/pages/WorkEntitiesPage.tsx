import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  FileText,
  Gauge,
  Link2,
  ListChecks,
  Loader2,
  Milestone,
  Map,
  Network,
  Pencil,
  Plus,
  Play,
  RefreshCw,
  Search,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import { GuidedProjectWizard } from '@/components/GuidedProjectWizard'
import {
  ProjectCockpit,
  type ProjectCockpitHandle,
} from '@/components/ProjectCockpit'
import { WorkEntityProjectMap } from '@/components/WorkEntityProjectMap'
import { WorkEntityWorkspacePanel } from '@/components/WorkEntityWorkspacePanel'
import type {
  Contact,
  WorkEntity,
  WorkEntityCreate,
  WorkEntityEvent,
  WorkEntityLink,
  WorkEntityLinkOption,
  WorkEntityMember,
  WorkEntityMemberRole,
  WorkEntityRelationType,
  WorkEntityReadiness,
  WorkEntityStatus,
  WorkEntitySummary,
  WorkEntityTargetType,
  WorkEntityType,
  WorkEntityUpdate,
} from '@/api/types'
import { cn } from '@/lib/utils'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

type DetailTab = 'control' | 'work' | 'map' | 'links' | 'access' | 'events'

const entityTypeLabels: Record<WorkEntityType, string> = {
  project: 'Проект',
  initiative: 'Инициатива',
  goal: 'Цель',
  system: 'Система',
  kpi: 'KPI-контекст',
  other: 'Другое',
}

const statusLabels: Record<WorkEntityStatus, string> = {
  draft: 'Черновик',
  active: 'Активно',
  paused: 'Пауза',
  done: 'Завершено',
  archived: 'Архив',
}

const statusOrder: Record<WorkEntityStatus, number> = {
  active: 0,
  draft: 1,
  paused: 2,
  done: 3,
  archived: 4,
}

const editableStatusOptions: Record<WorkEntityStatus, WorkEntityStatus[]> = {
  draft: ['draft'],
  active: ['active', 'paused', 'done'],
  paused: ['paused', 'active', 'done'],
  done: ['done'],
  archived: ['archived'],
}

const detailNavigation = [
  ['control', 'Пульт', Gauge],
  ['work', 'План', ListChecks],
  ['map', 'График', Map],
  ['links', 'Связи', Link2],
  ['access', 'Команда', Users],
  ['events', 'История', ClipboardList],
] as const

const relationLabels: Record<WorkEntityRelationType, string> = {
  contains: 'В составе',
  contributes_to: 'Вносит вклад',
  depends_on: 'Зависит от',
  measures: 'Измеряет',
  related: 'Связано',
}

const targetTypeLabels: Record<WorkEntityTargetType, string> = {
  entity: 'Проект или цель',
  task: 'DPMS-задача',
  personal_task: 'Личная задача',
  quick_note: 'Заметка',
  deadline_tracker: 'Контроль срока',
}

type JournalEvent = WorkEntityEvent & {
  object_type?: string | null
  object_id?: string | null
  object_ref?: string | null
  object_title?: string | null
  action?: string | null
  reason?: string | null
  correlation_id?: string | null
}

type JournalChange = {
  field: string
  from: unknown
  to: unknown
}

type JournalImpact = {
  label: string
  value: string
}

type JournalEventView = {
  event: WorkEntityEvent
  actor: string
  objectType: string
  objectRef: string | null
  objectTitle: string | null
  action: string
  headline: string
  changes: JournalChange[]
  reason: string | null
  impact: JournalImpact[]
  entryType: string | null
  body: string | null
  correlationId: string | null
}

type JournalEventGroup = {
  id: string
  correlationId: string | null
  events: JournalEventView[]
  operationSize: number
}

const legacyEventActions: Record<string, string> = {
  entity_created: 'created',
  guided_project_created: 'created',
  entity_updated: 'updated',
  entity_archived: 'archived',
  link_added: 'created',
  link_updated: 'updated',
  link_removed: 'removed',
  member_added: 'created',
  member_updated: 'updated',
  member_removed: 'removed',
  project_stage_created: 'created',
  project_stage_updated: 'updated',
  project_task_created: 'created',
  project_task_updated: 'updated',
  project_task_journal: 'journal_entry_added',
  project_milestone_created: 'created',
  project_milestone_updated: 'updated',
  project_milestone_journal: 'journal_entry_added',
  project_dependency_added: 'created',
  project_dependency_removed: 'removed',
  project_schedule_item_shifted: 'forecast_shifted',
  project_schedule_rescheduled: 'schedule_rescheduled',
  project_target_deadline_changed: 'target_deadline_changed',
  project_charter_changed: 'charter_changed',
  project_decision_recorded: 'decision_recorded',
  project_artifact_created: 'created',
  project_artifact_updated: 'updated',
}

const objectTypeLabels: Record<string, string> = {
  entity: 'Проект или цель',
  stage: 'Этап',
  task: 'Задача',
  milestone: 'Контрольная точка',
  dependency: 'Зависимость',
  artifact: 'Артефакт',
  member: 'Участник',
  link: 'Связь',
  methodology: 'Методология',
}

const objectTypeGenitiveLabels: Record<string, string> = {
  entity: 'проекта или цели',
  stage: 'этапа',
  task: 'задачи',
  milestone: 'контрольной точки',
  dependency: 'зависимости',
  artifact: 'артефакта',
  member: 'участника',
  link: 'связи',
  methodology: 'методологии',
}

const actionFilterLabels: Record<string, string> = {
  created: 'Создание',
  updated: 'Изменение',
  removed: 'Удаление',
  archived: 'Перенос в архив',
  journal_entry_added: 'Запись в журнал',
  forecast_shifted: 'Сдвиг прогноза',
  schedule_rescheduled: 'Перенос графика',
  target_deadline_changed: 'Изменение целевого срока',
  charter_changed: 'Поправка к паспорту',
  decision_recorded: 'Управленческое решение',
}

const projectTaskStatusLabels: Record<string, string> = {
  planned: 'Запланировано',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  blocked: 'Заблокировано',
  review: 'На проверке',
  done: 'Готово',
  cancelled: 'Отменено',
}

const priorityLabels: Record<string, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  critical: 'Критический',
}

const milestoneStatusLabels: Record<string, string> = {
  planned: 'Запланирована',
  achieved: 'Пройдена',
  rescheduled: 'Перенесена',
  overdue: 'Просрочена',
  cancelled: 'Отменена',
}

const criticalityLabels: Record<string, string> = {
  informational: 'Информационная',
  standard: 'Обычная',
  control: 'Контрольная',
  key: 'Ключевая',
  blocking: 'Блокирующая',
  critical: 'Критическая',
}

const journalTypeLabels: Record<string, string> = {
  progress: 'Ход работы',
  meeting: 'Встреча',
  decision: 'Решение',
  blocker: 'Блокер',
  comment: 'Комментарий',
}

const auditFieldLabels: Record<string, string> = {
  title: 'Название',
  description: 'Описание',
  outcome_statement: 'Ожидаемый результат',
  success_criteria: 'Критерии успеха',
  constraints: 'Ограничения',
  entity_type: 'Тип проекта',
  status: 'Статус',
  visibility: 'Видимость',
  tags: 'Теги',
  details_json: 'Дополнительные данные',
  planning_mode: 'Режим планирования',
  methodology_title: 'Методология',
  methodology_version: 'Версия методологии',
  guidance: 'Подсказка этапа',
  source_type: 'Источник',
  acceptance_criteria: 'Критерии завершения',
  next_step: 'Следующий шаг',
  waiting_for: 'Что ожидаем',
  priority: 'Приоритет',
  criticality: 'Критичность',
  criticality_reason: 'Обоснование критичности',
  assignee: 'Исполнитель',
  assignee_id: 'Исполнитель',
  decision_owner: 'Ответственный за решение',
  decision_owner_id: 'Ответственный за решение',
  stage_id: 'Этап',
  item_type: 'Тип элемента',
  artifact_type: 'Тип артефакта',
  body: 'Содержание',
  url: 'Ссылка',
  task_id: 'Привязка к задаче',
  role: 'Роль участника',
  relation_type: 'Тип связи',
  starts_at: 'Начало',
  due_at: 'Срок',
  target_due_at: 'Текущий целевой срок',
  baseline_starts_at: 'Базовое начало',
  baseline_due_at: 'Базовый срок',
  forecast_starts_at: 'Прогноз начала',
  forecast_due_at: 'Прогноз завершения',
  actual_starts_at: 'Фактическое начало',
  actual_due_at: 'Фактическое завершение',
  baseline_at: 'Базовая дата',
  forecast_at: 'Прогнозная дата',
  actual_at: 'Фактическая дата',
  introduced_after_baseline: 'Добавлено после запуска',
  introduced_at_revision: 'Ревизия добавления',
  position: 'Позиция',
}

const impactFieldLabels: Record<string, string> = {
  shift_days: 'Сдвиг',
  affected_count: 'Затронуто элементов',
  cascade: 'Каскадный перенос',
  project_forecast_due_before: 'Прежний прогноз проекта',
  project_forecast_due_after: 'Новый прогноз проекта',
  source_milestone_id: 'Источник сдвига (ID)',
  conflicts: 'Элементов вне целевой даты',
  baseline_due_at: 'Базовый срок проекта',
  forecast_due_at: 'Прогноз проекта',
  members: 'Участников',
  milestones: 'Контрольных точек',
  tasks: 'Работ',
  schedule_revision: 'Ревизия графика',
  baseline_preserved: 'Исходный baseline сохранен',
}

const EVENT_PAGE_SIZE = 100

const emptyForm = {
  entityType: 'project' as WorkEntityType,
  title: '',
  description: '',
  outcomeStatement: '',
  successCriteria: '',
  constraints: '',
  status: 'draft' as WorkEntityStatus,
  startsAt: '',
  dueAt: '',
  tags: '',
}

function targetIcon(type: WorkEntityTargetType) {
  const Icon = {
    entity: Network,
    task: ClipboardList,
    personal_task: CheckCircle2,
    quick_note: FileText,
    deadline_tracker: CalendarClock,
  }[type]
  return <Icon className="h-4 w-4" />
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

function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean)
    .slice(0, 20)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function readString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

function inferObjectType(eventType: string): string {
  if (eventType.includes('milestone') || eventType === 'project_schedule_rescheduled') {
    return 'milestone'
  }
  if (eventType.includes('stage')) return 'stage'
  if (eventType.includes('task') || eventType === 'project_schedule_item_shifted') {
    return 'task'
  }
  if (eventType.includes('dependency')) return 'dependency'
  if (eventType.includes('artifact')) return 'artifact'
  if (eventType.includes('member')) return 'member'
  if (eventType.includes('link')) return 'link'
  return 'entity'
}

function legacyValue(
  payload: Record<string, unknown>,
  field: string,
  direction: 'from' | 'to',
): unknown {
  const directKey = `${direction}_${field}`
  if (directKey in payload) return payload[directKey]
  if (field === 'assignee_id') return payload[`${direction}_assignee_name`]
  if (field === 'role' && direction === 'to') return payload.to_role ?? payload.role
  return undefined
}

function eventChanges(payload: Record<string, unknown>): JournalChange[] {
  const changes: JournalChange[] = []
  const seen = new Set<string>()
  const append = (field: string, from: unknown, to: unknown) => {
    if (!field || seen.has(field)) return
    if (from === undefined && to === undefined) return
    seen.add(field)
    changes.push({ field, from, to })
  }

  if (Array.isArray(payload.changes)) {
    for (const value of payload.changes) {
      const change = asRecord(value)
      const field = readString(change?.field)
      if (change && field) append(field, change.from, change.to)
    }
  }

  const legacyFields = Array.isArray(payload.fields)
    ? payload.fields.filter((field): field is string => typeof field === 'string')
    : []
  for (const field of legacyFields) {
    append(field, legacyValue(payload, field, 'from'), legacyValue(payload, field, 'to'))
  }

  for (const field of ['status', 'role', 'priority', 'starts_at', 'due_at']) {
    append(field, legacyValue(payload, field, 'from'), legacyValue(payload, field, 'to'))
  }
  return changes
}

function formatAuditValue(field: string, value: unknown, objectType: string): string {
  if (value === null || value === undefined || value === '') return 'не задано'
  if (typeof value === 'boolean') return value ? 'да' : 'нет'
  if (field === 'status' && typeof value === 'string') {
    if (objectType === 'milestone') return milestoneStatusLabels[value] || value
    if (objectType === 'entity') {
      return statusLabels[value as WorkEntityStatus] || projectTaskStatusLabels[value] || value
    }
    return projectTaskStatusLabels[value] || value
  }
  if (field === 'priority' && typeof value === 'string') {
    return priorityLabels[value] || value
  }
  if (field === 'criticality' && typeof value === 'string') {
    return criticalityLabels[value] || value
  }
  if (field === 'role' && typeof value === 'string') {
    return memberRoleLabel(value as WorkEntityMemberRole)
  }
  if (field === 'entity_type' && typeof value === 'string') {
    return entityTypeLabels[value as WorkEntityType] || value
  }
  if (field === 'planning_mode' && typeof value === 'string') {
    return value === 'methodology' ? 'По методологии' : 'Свободное планирование'
  }
  if (field === 'visibility' && typeof value === 'string') {
    return value === 'private' ? 'Приватная' : value === 'shared' ? 'Общая' : value
  }
  if (field === 'relation_type' && typeof value === 'string') {
    return relationLabels[value as WorkEntityRelationType] || value
  }
  if (
    typeof value === 'string' &&
    /(^|_)(at|date|starts|start|due|finish|finished)(_|$)/.test(field)
  ) {
    const timestamp = Date.parse(value)
    if (!Number.isNaN(timestamp)) return formatDate(value, true)
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return 'нет'
    if (value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))) {
      return value.join(', ')
    }
  }
  if (typeof value === 'object') {
    const serialized = JSON.stringify(value)
    return serialized.length > 240 ? `${serialized.slice(0, 237)}...` : serialized
  }
  return String(value)
}

function eventImpact(
  payload: Record<string, unknown>,
  objectType: string,
): JournalImpact[] {
  const impact = asRecord(payload.impact)
  if (!impact) return []
  const values: JournalImpact[] = []
  const forecastBefore = impact.project_forecast_due_before
  const forecastAfter = impact.project_forecast_due_after
  if (forecastBefore !== undefined || forecastAfter !== undefined) {
    values.push({
      label: 'Прогноз завершения проекта',
      value: `${formatAuditValue('forecast_due_at', forecastBefore, 'entity')} → ${formatAuditValue('forecast_due_at', forecastAfter, 'entity')}`,
    })
  }
  for (const [field, value] of Object.entries(impact)) {
    if (field === 'project_forecast_due_before' || field === 'project_forecast_due_after') {
      continue
    }
    const formatted =
      field === 'shift_days' && typeof value === 'number'
        ? `${value > 0 ? '+' : ''}${value} дн.`
        : formatAuditValue(field, value, objectType)
    values.push({
      label: impactFieldLabels[field] || auditFieldLabels[field] || field,
      value: formatted,
    })
  }
  return values
}

function objectIdentity(ref: string | null, title: string | null): string {
  if (ref && title && ref !== title) return `${ref} «${title}»`
  if (title) return `«${title}»`
  return ref || ''
}

function eventHeadline(
  actor: string,
  action: string,
  objectType: string,
  ref: string | null,
  title: string | null,
  eventType: string,
): string {
  const objectLabel =
    objectTypeGenitiveLabels[objectType] || objectTypeLabels[objectType]?.toLowerCase() || objectType
  const identity = objectIdentity(ref, title)
  const actionText: Record<string, string> = {
    created: `создание ${objectLabel}`,
    updated: `изменение ${objectLabel}`,
    removed: `удаление ${objectLabel}`,
    archived: `перенос ${objectLabel} в архив`,
    journal_entry_added: `запись в журнал ${objectLabel}`,
    forecast_shifted: `сдвиг прогноза ${objectLabel}`,
    schedule_rescheduled: `перенос графика от ${objectLabel}`,
  }
  const concreteAction =
    actionText[action] || `событие «${eventType}» для ${objectLabel}`
  return `${actor}: ${concreteAction}${identity ? ` ${identity}` : ''}`
}

function normalizeJournalEvent(
  event: WorkEntityEvent,
  entityTitle: string | null,
): JournalEventView {
  const extended = event as JournalEvent
  const payload = event.payload || {}
  const payloadObject = asRecord(payload.object)
  const objectType =
    readString(extended.object_type, payloadObject?.type) || inferObjectType(event.event_type)
  const objectRef = readString(
    extended.object_ref,
    payloadObject?.ref,
    payload.task_ref,
    payload.milestone_ref,
    payload.object_ref,
  )
  const objectTitle = readString(
    extended.object_title,
    payloadObject?.title,
    payload.task_title,
    payload.milestone_title,
    payload.stage_title,
    payload.artifact_title,
    payload.user_name,
    payload.target_title,
    payload.title,
    objectType === 'entity' ? entityTitle : null,
  )
  const action =
    readString(extended.action, payload.action) ||
    legacyEventActions[event.event_type] ||
    event.event_type
  const actor = event.actor_name || 'Система'
  return {
    event,
    actor,
    objectType,
    objectRef,
    objectTitle,
    action,
    headline: eventHeadline(
      actor,
      action,
      objectType,
      objectRef,
      objectTitle,
      event.event_type,
    ),
    changes: eventChanges(payload),
    reason: readString(extended.reason, payload.reason),
    impact: eventImpact(payload, objectType),
    entryType: readString(payload.entry_type),
    body: readString(payload.body),
    correlationId: readString(extended.correlation_id),
  }
}

function journalDotClass(action: string): string {
  if (action === 'created') return 'bg-emerald-500'
  if (action === 'removed' || action === 'archived') return 'bg-rose-500'
  if (action === 'journal_entry_added') return 'bg-sky-500'
  if (action === 'forecast_shifted' || action === 'schedule_rescheduled') {
    return 'bg-amber-500'
  }
  return 'bg-primary'
}

function memberRoleLabel(role: WorkEntityMemberRole): string {
  if (role === 'editor') return 'Редактор'
  if (role === 'participant') return 'Участник'
  return 'Наблюдатель'
}

function contactUser(contact: Contact) {
  return contact.direction === 'outgoing'
    ? {
        id: contact.recipient_id,
        name: contact.recipient_name,
        email: contact.recipient_email,
      }
    : {
        id: contact.requester_id,
        name: contact.requester_name,
        email: contact.requester_email,
      }
}

function targetPath(link: WorkEntityLink): string | null {
  if (!link.target_id) return null
  if (link.target_type === 'entity') return `/work-entities?entity=${link.target_id}`
  if (link.target_type === 'task') return `/queue?task=${link.target_id}`
  if (link.target_type === 'personal_task') return `/personal-tasks?task=${link.target_id}`
  if (link.target_type === 'quick_note') return `/quick-notes/${link.target_id}`
  if (link.target_type === 'deadline_tracker') {
    return `/deadline-trackers?tracker=${link.target_id}`
  }
  return null
}

function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const panelRef = useProtectedModal<HTMLDivElement>()

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={cn(
          'max-h-[92vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-2xl sm:rounded-lg',
          wide ? 'sm:max-w-2xl' : 'sm:max-w-lg',
        )}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

function JournalEventItem({ view }: { view: JournalEventView }) {
  return (
    <li className="relative pb-5 pl-5 last:pb-0">
      <span
        className={cn(
          'absolute -left-1.5 top-1 h-3 w-3 rounded-full border-2 border-white',
          journalDotClass(view.action),
        )}
      />
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <p className="min-w-0 flex-1 break-words text-sm font-medium leading-5 text-slate-900">
            {view.headline}
          </p>
          <time
            className="shrink-0 text-[11px] text-slate-500"
            dateTime={view.event.created_at}
          >
            {formatDate(view.event.created_at, true)}
          </time>
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
            {objectTypeLabels[view.objectType] || view.objectType}
          </span>
          <span
            className="rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary"
            title={view.event.event_type}
          >
            {actionFilterLabels[view.action] || view.action}
          </span>
          {view.entryType && (
            <span className="rounded bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
              {journalTypeLabels[view.entryType] || view.entryType}
            </span>
          )}
        </div>

        {view.changes.length > 0 && (
          <dl className="mt-3 border-y border-slate-200 bg-slate-50/70 px-3">
            {view.changes.map((change) => (
              <div
                key={change.field}
                className="grid min-w-0 gap-1 border-t border-slate-200/80 py-2 first:border-t-0 sm:grid-cols-[minmax(120px,0.5fr)_minmax(0,1fr)] sm:items-start sm:gap-3"
              >
                <dt className="text-xs font-medium text-slate-600">
                  {auditFieldLabels[change.field] || change.field}
                </dt>
                <dd className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px_minmax(0,1fr)] items-start gap-1 text-xs leading-5 text-slate-700">
                  <span className="min-w-0 break-words">
                    {formatAuditValue(change.field, change.from, view.objectType)}
                  </span>
                  <ChevronRight className="mt-0.5 h-4 w-4 text-slate-400" aria-hidden="true" />
                  <span className="min-w-0 break-words font-medium text-slate-900">
                    {formatAuditValue(change.field, change.to, view.objectType)}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        )}

        {view.body && (
          <div className="mt-3 border-l-2 border-sky-400 pl-3">
            <div className="text-[11px] font-medium uppercase text-sky-700">
              Запись в журнале
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-5 text-slate-700">
              {view.body}
            </p>
          </div>
        )}

        {view.reason && (
          <div className="mt-3 border-l-2 border-amber-400 pl-3 text-xs leading-5 text-slate-700">
            <span className="font-medium text-slate-900">Причина: </span>
            <span className="whitespace-pre-wrap break-words">{view.reason}</span>
          </div>
        )}

        {view.impact.length > 0 && (
          <div className="mt-3">
            <div className="text-[11px] font-medium uppercase text-slate-500">
              Влияние на график
            </div>
            <dl className="mt-1 grid min-w-0 gap-x-4 gap-y-1 sm:grid-cols-2">
              {view.impact.map((item) => (
                <div
                  key={`${item.label}-${item.value}`}
                  className="flex min-w-0 items-baseline justify-between gap-3 border-b border-slate-100 py-1 text-xs"
                >
                  <dt className="text-slate-500">{item.label}</dt>
                  <dd className="min-w-0 break-words text-right font-medium text-slate-800">
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </li>
  )
}

export function WorkEntitiesPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedEntityId = searchParams.get('entity')
  const [entities, setEntities] = useState<WorkEntity[]>([])
  const [selectedId, setSelectedId] = useState(requestedEntityId || '')
  const [links, setLinks] = useState<WorkEntityLink[]>([])
  const [summary, setSummary] = useState<WorkEntitySummary | null>(null)
  const [readiness, setReadiness] = useState<WorkEntityReadiness | null>(null)
  const [members, setMembers] = useState<WorkEntityMember[]>([])
  const [events, setEvents] = useState<WorkEntityEvent[]>([])
  const [eventsHasMore, setEventsHasMore] = useState(false)
  const [eventsLoadingMore, setEventsLoadingMore] = useState(false)
  const [eventObjectFilter, setEventObjectFilter] = useState('all')
  const [eventActionFilter, setEventActionFilter] = useState('all')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [tab, setTab] = useState<DetailTab>('control')
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [guidedCreateOpen, setGuidedCreateOpen] = useState(false)
  const [entityFormOpen, setEntityFormOpen] = useState(false)
  const [linkFormOpen, setLinkFormOpen] = useState(false)
  const [editingEntity, setEditingEntity] = useState<WorkEntity | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [linkTargetType, setLinkTargetType] = useState<WorkEntityTargetType>('task')
  const [linkRelation, setLinkRelation] = useState<WorkEntityRelationType>('contains')
  const [linkNotes, setLinkNotes] = useState('')
  const [linkSearch, setLinkSearch] = useState('')
  const [linkOptions, setLinkOptions] = useState<WorkEntityLinkOption[]>([])
  const [selectedTargetId, setSelectedTargetId] = useState('')
  const [optionsLoading, setOptionsLoading] = useState(false)
  const [memberUserId, setMemberUserId] = useState('')
  const [memberRole, setMemberRole] = useState<WorkEntityMemberRole>('participant')
  const detailRequestRef = useRef(0)
  const detailSectionRef = useRef<HTMLElement | null>(null)
  const cockpitRef = useRef<ProjectCockpitHandle | null>(null)

  const selected = useMemo(
    () => entities.find((entity) => entity.id === selectedId) ?? null,
    [entities, selectedId],
  )
  const canEdit = selected?.access_role === 'owner' || selected?.access_role === 'editor'
  const isOwner = selected?.access_role === 'owner'
  const normalizedEvents = useMemo(
    () => events.map((event) => normalizeJournalEvent(event, selected?.title || null)),
    [events, selected?.title],
  )
  const eventObjectOptions = useMemo(
    () =>
      [...new Set(normalizedEvents.map((event) => event.objectType))].sort((left, right) =>
        (objectTypeLabels[left] || left).localeCompare(objectTypeLabels[right] || right, 'ru'),
      ),
    [normalizedEvents],
  )
  const eventActionOptions = useMemo(
    () =>
      [...new Set(normalizedEvents.map((event) => event.action))].sort((left, right) =>
        (actionFilterLabels[left] || left).localeCompare(actionFilterLabels[right] || right, 'ru'),
      ),
    [normalizedEvents],
  )
  const filteredJournalEvents = useMemo(
    () =>
      normalizedEvents.filter(
        (event) =>
          (eventObjectFilter === 'all' || event.objectType === eventObjectFilter) &&
          (eventActionFilter === 'all' || event.action === eventActionFilter),
      ),
    [eventActionFilter, eventObjectFilter, normalizedEvents],
  )
  const journalEventGroups = useMemo(() => {
    const operationSizes = new globalThis.Map<string, number>()
    for (const event of normalizedEvents) {
      if (!event.correlationId) continue
      operationSizes.set(
        event.correlationId,
        (operationSizes.get(event.correlationId) || 0) + 1,
      )
    }

    const groups: JournalEventGroup[] = []
    const grouped = new globalThis.Map<string, JournalEventGroup>()
    for (const event of filteredJournalEvents) {
      const operationSize = event.correlationId
        ? operationSizes.get(event.correlationId) || 1
        : 1
      const shouldGroup = Boolean(event.correlationId && operationSize > 1)
      const groupId = shouldGroup ? `operation-${event.correlationId}` : `event-${event.event.id}`
      const existing = grouped.get(groupId)
      if (existing) {
        existing.events.push(event)
        continue
      }
      const group = {
        id: groupId,
        correlationId: shouldGroup ? event.correlationId : null,
        events: [event],
        operationSize,
      }
      grouped.set(groupId, group)
      groups.push(group)
    }
    return groups
  }, [filteredJournalEvents, normalizedEvents])

  const loadEntities = useCallback(async () => {
    const data = await api.get<WorkEntity[]>('/api/work-entities?include_archived=true')
    setEntities(data)
    setSelectedId((current) => {
      if (requestedEntityId && data.some((entity) => entity.id === requestedEntityId)) {
        return requestedEntityId
      }
      if (current && data.some((entity) => entity.id === current)) return current
      return data.find((entity) => !['done', 'archived'].includes(entity.status))?.id ?? data[0]?.id ?? ''
    })
    return data
  }, [requestedEntityId])

  const loadDetail = useCallback(async (entityId: string) => {
    const requestId = ++detailRequestRef.current
    setDetailLoading(true)
    setEventsLoadingMore(false)
    setReadiness(null)
    try {
      const [linkList, entitySummary, readinessResult, memberList, eventList] = await Promise.all([
        api.get<WorkEntityLink[]>(`/api/work-entities/${entityId}/links`),
        api.get<WorkEntitySummary>(`/api/work-entities/${entityId}/summary`),
        api.get<WorkEntityReadiness>(`/api/work-entities/${entityId}/readiness`),
        api.get<WorkEntityMember[]>(`/api/work-entities/${entityId}/members`),
        api.get<WorkEntityEvent[]>(
          `/api/work-entities/${entityId}/events?limit=${EVENT_PAGE_SIZE}`,
        ),
      ])
      if (requestId !== detailRequestRef.current) return
      setLinks(linkList)
      setSummary(entitySummary)
      setReadiness(readinessResult)
      setMembers(memberList)
      setEvents(eventList)
      setEventsHasMore(eventList.length === EVENT_PAGE_SIZE)
    } catch (error) {
      if (requestId !== detailRequestRef.current) return
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить сущность')
    } finally {
      if (requestId === detailRequestRef.current) setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void Promise.all([
      loadEntities(),
      api
        .get<Contact[]>('/api/contacts')
        .then(setContacts)
        .catch((error) => {
          setContacts([])
          toast.error(
            error instanceof Error
              ? error.message
              : 'Не удалось загрузить контакты для доступа к проекту',
          )
        }),
    ])
      .catch((error) =>
        toast.error(error instanceof Error ? error.message : 'Не удалось загрузить проекты и цели'),
      )
      .finally(() => setLoading(false))
  }, [loadEntities])

  useEffect(() => {
    if (!selectedId) {
      setLinks([])
      setSummary(null)
      setReadiness(null)
      setMembers([])
      setEvents([])
      setEventsHasMore(false)
      return
    }
    void loadDetail(selectedId)
  }, [loadDetail, selectedId])

  useEffect(() => {
    setEventObjectFilter('all')
    setEventActionFilter('all')
  }, [selectedId])

  const loadMoreEvents = async () => {
    if (!selectedId || eventsLoadingMore || !eventsHasMore || events.length === 0) return
    const requestId = detailRequestRef.current
    const cursor = events[events.length - 1]
    const params = new URLSearchParams({
      limit: String(EVENT_PAGE_SIZE),
      before_created_at: cursor.created_at,
      before_id: cursor.id,
    })
    setEventsLoadingMore(true)
    try {
      const olderEvents = await api.get<WorkEntityEvent[]>(
        `/api/work-entities/${selectedId}/events?${params.toString()}`,
      )
      if (requestId !== detailRequestRef.current) return
      setEvents((current) => {
        const knownIds = new Set(current.map((event) => event.id))
        return [
          ...current,
          ...olderEvents.filter((event) => !knownIds.has(event.id)),
        ]
      })
      setEventsHasMore(olderEvents.length === EVENT_PAGE_SIZE)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить историю')
    } finally {
      if (requestId === detailRequestRef.current) setEventsLoadingMore(false)
    }
  }

  useEffect(() => {
    if (!linkFormOpen || !selected) return
    let active = true
    const timer = window.setTimeout(async () => {
      setOptionsLoading(true)
      try {
        const params = new URLSearchParams({
          target_type: linkTargetType,
          limit: '60',
          exclude_entity_id: selected.id,
        })
        if (linkSearch.trim()) params.set('search', linkSearch.trim())
        const data = await api.get<WorkEntityLinkOption[]>(
          `/api/work-entities/link-options?${params.toString()}`,
        )
        if (active) setLinkOptions(data)
      } catch (error) {
        if (!active) return
        setLinkOptions([])
        toast.error(error instanceof Error ? error.message : 'Не удалось найти объекты')
      } finally {
        if (active) setOptionsLoading(false)
      }
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [linkFormOpen, linkSearch, linkTargetType, selected])

  const orderedEntities = useMemo(
    () =>
      [...entities].sort(
        (left, right) =>
          statusOrder[left.status] - statusOrder[right.status] ||
          left.title.localeCompare(right.title, 'ru'),
      ),
    [entities],
  )

  const groupedLinks = useMemo(() => {
    return Object.entries(
      links.reduce<Record<string, WorkEntityLink[]>>((groups, link) => {
        ;(groups[link.target_type] ||= []).push(link)
        return groups
      }, {}),
    ) as Array<[WorkEntityTargetType, WorkEntityLink[]]>
  }, [links])

  const acceptedContacts = useMemo(
    () => contacts.filter((contact) => contact.status === 'accepted').map(contactUser),
    [contacts],
  )
  const availableContacts = useMemo(() => {
    const memberIds = new Set(members.map((member) => member.user_id))
    return acceptedContacts.filter((contact) => !memberIds.has(contact.id))
  }, [acceptedContacts, members])

  const selectEntity = (entityId: string) => {
    if (entityId !== selectedId) {
      setLinks([])
      setSummary(null)
      setReadiness(null)
      setMembers([])
      setEvents([])
      setEventsHasMore(false)
    }
    setSelectedId(entityId)
    setTab('control')
    setMobileActionsOpen(false)
    navigate(`/work-entities?entity=${entityId}`, { replace: true })
    if (window.matchMedia('(max-width: 1023px)').matches) {
      window.requestAnimationFrame(() =>
        detailSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      )
    }
  }

  const openCreate = () => {
    setGuidedCreateOpen(true)
  }

  const openEdit = (entity: WorkEntity) => {
    setEditingEntity(entity)
    setForm({
      entityType: entity.entity_type,
      title: entity.title,
      description: entity.description || '',
      outcomeStatement: entity.outcome_statement || '',
      successCriteria: entity.success_criteria || '',
      constraints: entity.constraints || '',
      status: entity.status,
      startsAt: toInputDate(entity.starts_at),
      dueAt: toInputDate(entity.due_at),
      tags: entity.tags.join(', '),
    })
    setEntityFormOpen(true)
  }

  const saveEntity = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.title.trim()) return
    const payload: WorkEntityUpdate = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      outcome_statement: form.outcomeStatement.trim() || null,
      success_criteria: form.successCriteria.trim() || null,
      constraints: form.constraints.trim() || null,
      status: editingEntity ? form.status : 'draft',
      starts_at: toPayloadDate(form.startsAt),
      due_at: toPayloadDate(form.dueAt),
      tags: splitTags(form.tags),
    }
    if (!editingEntity || editingEntity.status === 'draft') {
      payload.entity_type = form.entityType
    }
    setBusy(true)
    try {
      const saved = editingEntity
        ? await api.patch<WorkEntity>(`/api/work-entities/${editingEntity.id}`, payload)
        : await api.post<WorkEntity>(
            '/api/work-entities',
            payload as WorkEntityCreate,
          )
      await Promise.all([loadEntities(), loadDetail(saved.id)])
      setEntityFormOpen(false)
      selectEntity(saved.id)
      toast.success(editingEntity ? 'Изменения сохранены' : 'Проект создан')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  const activateEntity = async () => {
    if (!selected || !canEdit || !readiness?.can_activate) return
    setBusy(true)
    try {
      await api.patch<WorkEntity>(`/api/work-entities/${selected.id}`, {
        status: 'active',
      })
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      toast.success('Проект активирован, базовый план зафиксирован')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось активировать проект')
    } finally {
      setBusy(false)
    }
  }

  const archiveEntity = async () => {
    if (!selected || !window.confirm(`Перенести «${selected.title}» в архив?`)) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${selected.id}/archive`, {})
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      toast.success('Сущность перенесена в архив')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось архивировать')
    } finally {
      setBusy(false)
    }
  }

  const openLinkForm = () => {
    setLinkTargetType('task')
    setLinkRelation('contains')
    setLinkNotes('')
    setLinkSearch('')
    setSelectedTargetId('')
    setLinkOptions([])
    setLinkFormOpen(true)
  }

  const addLink = async (event: FormEvent) => {
    event.preventDefault()
    if (!selected || !selectedTargetId) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${selected.id}/links`, {
        target_type: linkTargetType,
        target_id: selectedTargetId,
        relation_type: linkRelation,
        notes: linkNotes.trim() || null,
      })
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      setLinkFormOpen(false)
      toast.success('Связь добавлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить связь')
    } finally {
      setBusy(false)
    }
  }

  const updateLinkRelation = async (
    link: WorkEntityLink,
    relationType: WorkEntityRelationType,
  ) => {
    if (!selected) return
    try {
      await api.patch(`/api/work-entities/${selected.id}/links/${link.id}`, {
        relation_type: relationType,
      })
      await loadDetail(selected.id)
      toast.success('Тип связи изменен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить связь')
    }
  }

  const removeLink = async (link: WorkEntityLink) => {
    if (!selected || !window.confirm('Убрать эту связь?')) return
    setBusy(true)
    try {
      await api.delete(`/api/work-entities/${selected.id}/links/${link.id}`)
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      toast.success('Связь удалена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить связь')
    } finally {
      setBusy(false)
    }
  }

  const addMember = async () => {
    if (!selected || !memberUserId) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${selected.id}/members`, {
        user_id: memberUserId,
        role: memberRole,
      })
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      setMemberUserId('')
      toast.success('Доступ открыт')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось открыть доступ')
    } finally {
      setBusy(false)
    }
  }

  const updateMember = async (member: WorkEntityMember, role: WorkEntityMemberRole) => {
    if (!selected) return
    try {
      await api.patch(`/api/work-entities/${selected.id}/members/${member.id}`, { role })
      await loadDetail(selected.id)
      toast.success('Роль изменена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить роль')
    }
  }

  const removeMember = async (member: WorkEntityMember) => {
    if (!selected || !window.confirm(`Закрыть доступ для ${member.user_name}?`)) return
    setBusy(true)
    try {
      await api.delete(`/api/work-entities/${selected.id}/members/${member.id}`)
      await Promise.all([loadEntities(), loadDetail(selected.id)])
      toast.success('Доступ закрыт')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось закрыть доступ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="w-full space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div className="relative min-w-0 flex-1 cursor-pointer">
          <h1 className="inline-flex max-w-full items-center gap-2">
            <span className="line-clamp-2 min-w-0 break-words text-xl font-semibold leading-7 text-slate-900 sm:text-2xl">
              {selected?.title || 'Проекты и цели'}
            </span>
            <ChevronDown className="h-5 w-5 shrink-0 text-slate-500" />
          </h1>
          <select
            value={selectedId}
            onChange={(event) => selectEntity(event.target.value)}
            disabled={loading || orderedEntities.length === 0}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            aria-label="Выбрать проект или цель"
          >
            {orderedEntities.length === 0 && <option value="">Нет проектов</option>}
            {orderedEntities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.title} · {statusLabels[entity.status]}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-primary text-sm font-medium text-primary-foreground transition hover:opacity-90 sm:w-auto sm:px-4"
          aria-label="Новый проект"
        >
          <Plus className="h-4 w-4" />
          <span className="hidden sm:inline">Новый проект</span>
        </button>
      </header>

      <div className="grid min-h-[620px] min-w-0 items-start gap-4 lg:grid-cols-[232px_minmax(0,1fr)] xl:grid-cols-[248px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-6 lg:sticky lg:top-[73px]">
          <section>
            <h2 className="mb-2 px-1 text-base font-semibold text-slate-900">Навигация</h2>
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
              <nav
                className="grid grid-cols-3 gap-1 p-2 lg:grid-cols-1"
                aria-label="Разделы выбранного проекта"
              >
                {selected ? (
                  detailNavigation.map(([value, label, Icon]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => {
                        setTab(value)
                        setMobileActionsOpen(false)
                      }}
                      className={cn(
                        'flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium transition lg:justify-start lg:px-3 lg:text-sm',
                        tab === value
                          ? 'bg-primary text-primary-foreground'
                          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                      )}
                      aria-current={tab === value ? 'page' : undefined}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="min-w-0 truncate">{label}</span>
                    </button>
                  ))
                ) : (
                  <span className="col-span-3 px-3 py-5 text-center text-sm text-slate-500 lg:col-span-1">
                    {loading ? 'Загрузка' : 'Создайте первый проект'}
                  </span>
                )}
              </nav>
              {selected && (canEdit || (isOwner && selected.status !== 'archived')) && (
                <div className="grid grid-cols-2 gap-1 border-t border-slate-200 p-2 lg:grid-cols-1">
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => openEdit(selected)}
                      className="flex min-h-10 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-primary lg:justify-start lg:px-3"
                    >
                      <Pencil className="h-4 w-4" />
                      Параметры
                    </button>
                  )}
                  {isOwner && selected.status !== 'archived' && (
                    <button
                      type="button"
                      onClick={() => void archiveEntity()}
                      disabled={busy}
                      className="flex min-h-10 items-center justify-center gap-2 rounded-lg px-2 text-xs font-medium text-slate-600 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 lg:justify-start lg:px-3"
                    >
                      <Archive className="h-4 w-4" />
                      В архив
                    </button>
                  )}
                </div>
              )}
            </div>
          </section>

          {selected &&
            tab === 'control' &&
            canEdit &&
            !['done', 'archived'].includes(selected.status) && (
              <section>
                <div className="mb-2 flex items-center justify-between gap-2 px-1">
                  <h2 className="text-base font-semibold text-slate-900">Параметры</h2>
                  <button
                    type="button"
                    onClick={() => setMobileActionsOpen((current) => !current)}
                    className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 lg:hidden"
                    aria-expanded={mobileActionsOpen}
                    aria-label={mobileActionsOpen ? 'Скрыть параметры' : 'Показать параметры'}
                  >
                    <ChevronDown
                      className={cn('h-4 w-4 transition-transform', mobileActionsOpen && 'rotate-180')}
                    />
                  </button>
                </div>
                <div
                  className={cn(
                    'gap-2 sm:grid-cols-2 lg:grid lg:grid-cols-1',
                    mobileActionsOpen ? 'grid' : 'hidden',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => cockpitRef.current?.openCharter()}
                    disabled={detailLoading}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary disabled:opacity-40"
                  >
                    <Pencil className="h-4 w-4" />
                    {selected.status === 'draft' ? 'Изменить паспорт' : 'Поправка к паспорту'}
                  </button>
                  <button
                    type="button"
                    onClick={() => cockpitRef.current?.openTask()}
                    disabled={detailLoading}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" />
                    Добавить работу
                  </button>
                  <button
                    type="button"
                    onClick={() => cockpitRef.current?.openMilestone()}
                    disabled={detailLoading}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 text-sm font-medium text-primary hover:bg-primary/15 disabled:opacity-40"
                  >
                    <Milestone className="h-4 w-4" />
                    Добавить проверку
                  </button>
                  <button
                    type="button"
                    onClick={() => cockpitRef.current?.openDecision()}
                    disabled={detailLoading}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary disabled:opacity-40"
                  >
                    <FileText className="h-4 w-4" />
                    Зафиксировать решение
                  </button>
                  <button
                    type="button"
                    onClick={() => cockpitRef.current?.openDeadline()}
                    disabled={detailLoading}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:border-primary/40 hover:text-primary disabled:opacity-40"
                  >
                    <CalendarClock className="h-4 w-4" />
                    {selected.status === 'draft' ? 'Изменить сроки' : 'Изменить целевой срок'}
                  </button>
                  {selected.status === 'draft' && (
                    <button
                      type="button"
                      onClick={() => void activateEntity()}
                      disabled={busy || !readiness?.can_activate}
                      className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
                      title={
                        readiness?.can_activate
                          ? 'Зафиксировать базовый план и запустить проект'
                          : 'Сначала устраните блокирующие замечания'
                      }
                    >
                      <Play className="h-4 w-4" />
                      Активировать проект
                    </button>
                  )}
                </div>
              </section>
            )}
        </aside>

        <section
          ref={detailSectionRef}
          className="min-w-0 scroll-mt-4"
          aria-label="Выбранный проект или цель"
        >
          {!selected ? (
            <div className="flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center">
              <Network className="h-8 w-8 text-slate-300" />
              <p className="mt-3 text-sm font-medium text-slate-700">Создайте первый проект</p>
            </div>
          ) : (
            <div className="min-w-0">
              <div
                className={cn(
                  'min-w-0',
                  tab !== 'control' && 'rounded-lg border border-slate-200 bg-white',
                )}
              >

              {selected.status === 'draft' && tab !== 'control' && (
                <section
                  className={cn(
                    'border-b px-4 py-3',
                    readiness?.can_activate
                      ? 'border-emerald-200 bg-emerald-50/60'
                      : 'border-amber-200 bg-amber-50/60',
                  )}
                  aria-label="Проверка готовности проекта"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        {readiness === null ? (
                          <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
                        ) : readiness.can_activate ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-700" />
                        ) : (
                          <AlertTriangle className="h-4 w-4 text-amber-700" />
                        )}
                        <h3 className="text-sm font-semibold text-slate-900">
                          Готовность к запуску
                        </h3>
                      </div>
                      <p className="mt-1 text-xs text-slate-600">
                        {readiness === null
                          ? 'Проверяем границы проекта, scope, роли и критерии завершения.'
                          : readiness.can_activate
                          ? 'Обязательные поля заполнены. При активации исходный план и версия методологии будут зафиксированы.'
                          : `Блокирующих замечаний: ${readiness.blocking_count}; предупреждений: ${readiness.warning_count}.`}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void loadDetail(selected.id)}
                        disabled={detailLoading}
                        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-600 hover:border-primary/40 hover:text-primary disabled:opacity-50"
                        title="Повторить проверку"
                        aria-label="Повторить проверку готовности"
                      >
                        <RefreshCw className={cn('h-4 w-4', detailLoading && 'animate-spin')} />
                      </button>
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => void activateEntity()}
                          disabled={busy || !readiness?.can_activate}
                          className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
                          title={
                            readiness?.can_activate
                              ? 'Зафиксировать базовый план и запустить проект'
                              : 'Сначала устраните блокирующие замечания'
                          }
                        >
                          <Play className="h-4 w-4" />
                          Активировать
                        </button>
                      )}
                    </div>
                  </div>
                  {readiness && readiness.issues.length > 0 && (
                    <div className="mt-3 grid gap-2 lg:grid-cols-2">
                      {readiness.issues.map((issue) => (
                        <div
                          key={`${issue.code}-${issue.scope_id}`}
                          className="min-w-0 rounded-lg border border-white/80 bg-white/80 px-3 py-2"
                        >
                          <div className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-slate-800">
                            <span
                              className={cn(
                                'rounded px-1.5 py-0.5 text-[10px] uppercase',
                                issue.severity === 'blocking'
                                  ? 'bg-red-50 text-red-700'
                                  : 'bg-amber-50 text-amber-700',
                              )}
                            >
                              {issue.severity === 'blocking' ? 'Нужно исправить' : 'Проверить'}
                            </span>
                            <span>{issue.scope_ref || issue.scope_title}</span>
                            {issue.scope_ref && (
                              <span className="min-w-0 truncate font-medium text-slate-500">
                                {issue.scope_title}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-xs text-slate-700">{issue.message}</p>
                          <p className="mt-0.5 text-xs text-slate-500">{issue.guidance}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}

              <div className={cn('min-h-72', tab !== 'control' && 'p-4')}>
                {detailLoading ? (
                  <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Загрузка
                  </div>
                ) : tab === 'control' ? (
                  <ProjectCockpit
                    ref={cockpitRef}
                    entity={selected}
                    readiness={readiness}
                    onChanged={async () => {
                      await Promise.all([loadEntities(), loadDetail(selected.id)])
                    }}
                    onEditProject={() => openEdit(selected)}
                    onOpenAdvanced={(nextTab) => {
                      setTab(nextTab)
                      setMobileActionsOpen(false)
                    }}
                  />
                ) : tab === 'work' ? (
                  <WorkEntityWorkspacePanel
                    entity={selected}
                    onChanged={async () => {
                      await Promise.all([loadEntities(), loadDetail(selected.id)])
                    }}
                  />
                ) : tab === 'map' ? (
                  <WorkEntityProjectMap entity={selected} />
                ) : tab === 'links' ? (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900">Связанные объекты</h3>
                        {summary?.restricted_links ? (
                          <p className="mt-0.5 text-xs text-slate-500">
                            Без доступа к содержимому: {summary.restricted_links}
                          </p>
                        ) : null}
                      </div>
                      {canEdit && (
                        <button
                          type="button"
                          onClick={openLinkForm}
                          className="inline-flex h-10 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90"
                        >
                          <Plus className="h-4 w-4" />
                          Добавить
                        </button>
                      )}
                    </div>

                    {groupedLinks.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
                        Связей пока нет.
                      </div>
                    ) : (
                      groupedLinks.map(([targetType, group]) => (
                        <section key={targetType}>
                          <h4 className="mb-2 text-xs font-semibold uppercase text-slate-500">
                            {targetTypeLabels[targetType]} · {group.length}
                          </h4>
                          <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                            {group.map((link) => {
                              const path = targetPath(link)
                              const content = (
                                <>
                                  <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                                    {targetIcon(link.target_type)}
                                  </span>
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-medium text-slate-800">
                                      {link.target_accessible
                                        ? link.target_title
                                        : 'Содержимое недоступно'}
                                    </span>
                                    <span className="mt-0.5 flex flex-wrap gap-2 text-xs text-slate-500">
                                      <span>{relationLabels[link.relation_type]}</span>
                                      {link.target_subtitle && <span>{link.target_subtitle}</span>}
                                      {link.target_due_at && (
                                        <span>до {formatDate(link.target_due_at)}</span>
                                      )}
                                    </span>
                                    {link.notes && (
                                      <span className="mt-1 block text-xs text-slate-500">
                                        {link.notes}
                                      </span>
                                    )}
                                  </span>
                                </>
                              )
                              return (
                                <div
                                  key={link.id}
                                  className="flex min-h-16 items-center gap-3 px-3 py-2"
                                >
                                  {path && link.target_accessible ? (
                                    <Link
                                      to={path}
                                      className="flex min-w-0 flex-1 items-center gap-3 hover:text-primary"
                                    >
                                      {content}
                                    </Link>
                                  ) : (
                                    <div className="flex min-w-0 flex-1 items-center gap-3">
                                      {content}
                                    </div>
                                  )}
                                  {canEdit && (
                                    <div className="flex shrink-0 items-center gap-1">
                                      <select
                                        value={link.relation_type}
                                        onChange={(event) =>
                                          void updateLinkRelation(
                                            link,
                                            event.target.value as WorkEntityRelationType,
                                          )
                                        }
                                        className="hidden h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-primary sm:block"
                                        aria-label="Тип связи"
                                      >
                                        {Object.entries(relationLabels).map(([value, label]) => (
                                          <option key={value} value={value}>
                                            {label}
                                          </option>
                                        ))}
                                      </select>
                                      <button
                                        type="button"
                                        onClick={() => void removeLink(link)}
                                        disabled={busy}
                                        className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                                        title="Убрать связь"
                                        aria-label="Убрать связь"
                                      >
                                        <Trash2 className="h-4 w-4" />
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </section>
                      ))
                    )}
                  </div>
                ) : tab === 'access' ? (
                  <div className="space-y-4">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">Участники</h3>
                      <p className="mt-1 text-xs text-slate-500">
                        {selected.visibility === 'private'
                          ? 'Сущность видна только владельцу.'
                          : 'Работа и проектные артефакты доступны участникам по их ролям.'}
                      </p>
                    </div>
                    <div className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
                      {[
                        ['Владелец', 'Управляет проектом, работой и доступом'],
                        ['Редактор', 'Планирует задачи, зависимости и артефакты'],
                        ['Участник', 'Выполняет назначенную работу и ведет журнал'],
                        ['Наблюдатель', 'Просматривает проект без изменений'],
                      ].map(([role, description]) => (
                        <div key={role} className="rounded-lg border border-slate-200 p-2.5">
                          <div className="font-semibold text-slate-700">{role}</div>
                          <div className="mt-1 leading-4 text-slate-500">{description}</div>
                        </div>
                      ))}
                    </div>
                    {isOwner && (
                      <div className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-[minmax(0,1fr)_140px_auto]">
                        <label>
                          <span className="mb-1 block text-xs font-medium text-slate-600">
                            Контакт
                          </span>
                          <select
                            value={memberUserId}
                            onChange={(event) => setMemberUserId(event.target.value)}
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                          >
                            <option value="">Выберите контакт</option>
                            {availableContacts.map((contact) => (
                              <option key={contact.id} value={contact.id}>
                                {contact.name} · {contact.email}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span className="mb-1 block text-xs font-medium text-slate-600">
                            Роль
                          </span>
                          <select
                            value={memberRole}
                            onChange={(event) =>
                              setMemberRole(event.target.value as WorkEntityMemberRole)
                            }
                            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                          >
                            <option value="participant">Участник</option>
                            <option value="editor">Редактор</option>
                            <option value="viewer">Наблюдатель</option>
                          </select>
                        </label>
                        <button
                          type="button"
                          onClick={() => void addMember()}
                          disabled={!memberUserId || busy}
                          className="mt-auto inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                        >
                          <UserPlus className="h-4 w-4" />
                          Открыть
                        </button>
                        {availableContacts.length === 0 && (
                          <p className="text-xs text-slate-500 sm:col-span-3">
                            Добавьте или примите контакт в разделе «Контакты».
                          </p>
                        )}
                      </div>
                    )}
                    {members.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
                        Доступ другим пользователям не открыт.
                      </div>
                    ) : (
                      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                        {members.map((member) => (
                          <div
                            key={member.id}
                            className="flex min-h-16 flex-wrap items-center gap-3 px-3 py-2"
                          >
                            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600">
                              {member.user_name.slice(0, 1).toUpperCase()}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium text-slate-800">
                                {member.user_name}
                              </span>
                              {member.user_email && (
                                <span className="block truncate text-xs text-slate-500">
                                  {member.user_email}
                                </span>
                              )}
                            </span>
                            {isOwner ? (
                              <div className="flex items-center gap-1">
                                <select
                                  value={member.role}
                                  onChange={(event) =>
                                    void updateMember(
                                      member,
                                      event.target.value as WorkEntityMemberRole,
                                    )
                                  }
                                  className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-primary"
                                >
                                  <option value="participant">Участник</option>
                                  <option value="editor">Редактор</option>
                                  <option value="viewer">Наблюдатель</option>
                                </select>
                                <button
                                  type="button"
                                  onClick={() => void removeMember(member)}
                                  disabled={busy}
                                  className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                                  title="Закрыть доступ"
                                  aria-label={`Закрыть доступ для ${member.user_name}`}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              </div>
                            ) : (
                              <span className="text-xs text-slate-500">
                                {memberRoleLabel(member.role)}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900">
                          История проекта
                        </h3>
                        <p className="mt-0.5 text-xs text-slate-500">
                          Показано {filteredJournalEvents.length} из {events.length} событий
                        </p>
                      </div>
                      {events.length > 0 && (
                        <div className="grid w-full min-w-0 grid-cols-2 gap-2 sm:w-auto">
                          <label className="min-w-0">
                            <span className="sr-only">Фильтр журнала по объекту</span>
                            <select
                              value={eventObjectFilter}
                              onChange={(event) => setEventObjectFilter(event.target.value)}
                              className="h-9 min-w-0 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-primary"
                              aria-label="Фильтр журнала по объекту"
                            >
                              <option value="all">Все объекты</option>
                              {eventObjectOptions.map((objectType) => (
                                <option key={objectType} value={objectType}>
                                  {objectTypeLabels[objectType] || objectType}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="min-w-0">
                            <span className="sr-only">Фильтр журнала по действию</span>
                            <select
                              value={eventActionFilter}
                              onChange={(event) => setEventActionFilter(event.target.value)}
                              className="h-9 min-w-0 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus:border-primary"
                              aria-label="Фильтр журнала по действию"
                            >
                              <option value="all">Все действия</option>
                              {eventActionOptions.map((action) => (
                                <option key={action} value={action}>
                                  {actionFilterLabels[action] || action}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                      )}
                    </div>
                    {events.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
                        Событий пока нет.
                      </div>
                    ) : journalEventGroups.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center">
                        <p className="text-sm text-slate-500">
                          По выбранным фильтрам событий нет.
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setEventObjectFilter('all')
                            setEventActionFilter('all')
                          }}
                          className="mt-3 text-sm font-medium text-primary hover:underline"
                        >
                          Сбросить фильтры
                        </button>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {journalEventGroups.map((group) => {
                          const isScheduleOperation = group.events.some(
                            (event) =>
                              event.action === 'forecast_shifted' ||
                              event.action === 'schedule_rescheduled',
                          )
                          if (!group.correlationId) {
                            return (
                              <ol
                                key={group.id}
                                className="relative ml-2 border-l border-slate-200"
                              >
                                <JournalEventItem view={group.events[0]} />
                              </ol>
                            )
                          }
                          return (
                            <section
                              key={group.id}
                              className={cn(
                                'border-l-2 px-3 py-3',
                                isScheduleOperation
                                  ? 'border-amber-400 bg-amber-50/40'
                                  : 'border-primary/40 bg-primary/[0.03]',
                              )}
                              aria-label={
                                isScheduleOperation
                                  ? 'Операция изменения графика'
                                  : 'Связанная операция'
                              }
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-slate-800">
                                  <CalendarClock
                                    className={cn(
                                      'h-4 w-4',
                                      isScheduleOperation ? 'text-amber-600' : 'text-primary',
                                    )}
                                  />
                                  {isScheduleOperation
                                    ? 'Операция изменения графика'
                                    : 'Связанная операция'}
                                </div>
                                <span className="text-[11px] text-slate-500">
                                  Показано {group.events.length} из {group.operationSize} событий
                                </span>
                              </div>
                              <ol
                                className={cn(
                                  'relative ml-2 mt-3 border-l',
                                  isScheduleOperation
                                    ? 'border-amber-300'
                                    : 'border-primary/30',
                                )}
                              >
                                {group.events.map((event) => (
                                  <JournalEventItem key={event.event.id} view={event} />
                                ))}
                              </ol>
                            </section>
                          )
                        })}
                        {eventsHasMore && (
                          <button
                            type="button"
                            onClick={() => void loadMoreEvents()}
                            disabled={eventsLoadingMore}
                            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                          >
                            {eventsLoadingMore && <Loader2 className="h-4 w-4 animate-spin" />}
                            Показать более ранние
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            </div>
          )}
        </section>
      </div>

      {guidedCreateOpen && (
        <GuidedProjectWizard
          contacts={contacts}
          onClose={() => setGuidedCreateOpen(false)}
          onCreated={async (entityId) => {
            await loadEntities()
            selectEntity(entityId)
            await loadDetail(entityId)
          }}
        />
      )}

      {entityFormOpen && editingEntity && (
        <Modal
          title="Параметры проекта"
          onClose={() => setEntityFormOpen(false)}
          wide
        >
          <form onSubmit={(event) => void saveEntity(event)} className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Тип</span>
                <select
                  value={form.entityType}
                  disabled={editingEntity.status !== 'draft'}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      entityType: event.target.value as WorkEntityType,
                    }))
                  }
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
                >
                  {Object.entries(entityTypeLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                {editingEntity.status !== 'draft' && (
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    Тип фиксируется при запуске проекта.
                  </p>
                )}
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Статус</span>
                {editingEntity && editingEntity.status !== 'draft' ? (
                  <select
                    value={form.status}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        status: event.target.value as WorkEntityStatus,
                      }))
                    }
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  >
                    {Object.entries(statusLabels)
                      .filter(([value]) =>
                        editableStatusOptions[editingEntity.status].includes(
                          value as WorkEntityStatus,
                        ),
                      )
                      .map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                  </select>
                ) : (
                  <div className="flex h-11 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-700">
                    Черновик
                  </div>
                )}
                {!editingEntity && (
                  <span className="mt-1 block text-xs text-slate-500">
                    После заполнения scope проект проходит проверку готовности.
                  </span>
                )}
              </label>
            </div>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Название</span>
              <input
                value={form.title}
                onChange={(event) =>
                  setForm((current) => ({ ...current, title: event.target.value }))
                }
                maxLength={240}
                required
                autoFocus
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Описание</span>
              <textarea
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                rows={4}
                className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">
                Ожидаемый результат
              </span>
              <span className="mb-1.5 block text-xs text-slate-500">
                Наблюдаемое состояние, которое должно быть достигнуто к конечному сроку.
              </span>
              <textarea
                value={form.outcomeStatement}
                disabled={Boolean(editingEntity?.baseline_locked_at)}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    outcomeStatement: event.target.value,
                  }))
                }
                rows={3}
                className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100"
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">
                Критерии успеха
              </span>
              <span className="mb-1.5 block text-xs text-slate-500">
                Факты, документы или решение, подтверждающие достижение результата.
              </span>
              <textarea
                value={form.successCriteria}
                disabled={Boolean(editingEntity?.baseline_locked_at)}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    successCriteria: event.target.value,
                  }))
                }
                rows={3}
                className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100"
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">
                Ограничения
              </span>
              <textarea
                value={form.constraints}
                disabled={Boolean(editingEntity?.baseline_locked_at)}
                onChange={(event) =>
                  setForm((current) => ({ ...current, constraints: event.target.value }))
                }
                rows={2}
                className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Начало</span>
                <input
                  type="datetime-local"
                  value={form.startsAt}
                  disabled={Boolean(editingEntity?.baseline_locked_at)}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, startsAt: event.target.value }))
                  }
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">Срок</span>
                <input
                  type="datetime-local"
                  value={form.dueAt}
                  min={form.startsAt || undefined}
                  disabled={Boolean(editingEntity?.baseline_locked_at)}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, dueAt: event.target.value }))
                  }
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </label>
            </div>
            {editingEntity.baseline_locked_at && (
              <p className="text-xs leading-5 text-slate-500">
                Исходный паспорт и базовые даты зафиксированы при запуске.
                Результат изменяйте через поправку к паспорту, а текущую
                целевую дату через соответствующую команду на пульте.
              </p>
            )}
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Теги</span>
              <input
                value={form.tags}
                onChange={(event) =>
                  setForm((current) => ({ ...current, tags: event.target.value }))
                }
                placeholder="через запятую"
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </label>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button
                type="button"
                onClick={() => setEntityFormOpen(false)}
                className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={busy || !form.title.trim()}
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      )}

      {linkFormOpen && selected && (
        <Modal title="Добавить связь" onClose={() => setLinkFormOpen(false)} wide>
          <form onSubmit={(event) => void addLink(event)} className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">
                  Тип объекта
                </span>
                <select
                  value={linkTargetType}
                  onChange={(event) => {
                    setLinkTargetType(event.target.value as WorkEntityTargetType)
                    setSelectedTargetId('')
                  }}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  {Object.entries(targetTypeLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-sm font-medium text-slate-700">
                  Тип связи
                </span>
                <select
                  value={linkRelation}
                  onChange={(event) =>
                    setLinkRelation(event.target.value as WorkEntityRelationType)
                  }
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary"
                >
                  {Object.entries(relationLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Поиск</span>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={linkSearch}
                  onChange={(event) => setLinkSearch(event.target.value)}
                  className="h-11 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                  placeholder="Название объекта"
                />
              </div>
            </label>
            <div className="max-h-64 overflow-y-auto rounded-lg border border-slate-200">
              {optionsLoading ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Поиск
                </div>
              ) : linkOptions.length === 0 ? (
                <div className="py-10 text-center text-sm text-slate-500">
                  Доступные объекты не найдены.
                </div>
              ) : (
                <div className="divide-y divide-slate-100">
                  {linkOptions.map((option) => (
                    <label
                      key={option.target_id}
                      className={cn(
                        'flex min-h-14 cursor-pointer items-center gap-3 px-3 py-2 hover:bg-slate-50',
                        selectedTargetId === option.target_id && 'bg-primary/10',
                      )}
                    >
                      <input
                        type="radio"
                        name="link-target"
                        value={option.target_id}
                        checked={selectedTargetId === option.target_id}
                        onChange={() => setSelectedTargetId(option.target_id)}
                      />
                      <span className="text-slate-500">{targetIcon(option.target_type)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-800">
                          {option.title}
                        </span>
                        <span className="block truncate text-xs text-slate-500">
                          {[option.subtitle, option.status, formatDate(option.due_at)]
                            .filter((value) => value && value !== 'не задано')
                            .join(' · ')}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">
                Примечание к связи
              </span>
              <textarea
                value={linkNotes}
                onChange={(event) => setLinkNotes(event.target.value)}
                rows={3}
                maxLength={2000}
                className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </label>
            <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
              <button
                type="button"
                onClick={() => setLinkFormOpen(false)}
                className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={!selectedTargetId || busy}
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Добавить
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
