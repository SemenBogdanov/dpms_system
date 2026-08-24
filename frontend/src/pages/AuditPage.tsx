import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Boxes,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Download,
  ExternalLink,
  EyeOff,
  FileDown,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  Filter,
  FolderOpen,
  History,
  Loader2,
  Lock,
  Paperclip,
  Pencil,
  Plus,
  RefreshCcw,
  Save,
  Search,
  Shield,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { api, ApiError } from '@/api/client'
import type {
  AuditAtom,
  AuditAtomCreate,
  AuditAtomUpdate,
  AuditAIAtomDraft,
  AuditAIAtomizationAttempt,
  AuditAIAtomizationCommitResult,
  AuditAIModelComparison,
  AuditAIModelComparisonCommitResult,
  AuditAIModelComparisonDraft,
  AuditAIModelRegistry,
  AuditAIModelRegistryList,
  AuditAIProviderOption,
  AuditAIProviderOptionList,
  AuditAIPrivacyPreview,
  AuditAssignment,
  AuditAssignmentList,
  AuditAtomizationSkillList,
  AuditAtomizationSkillVersion,
  AuditCaseCreate,
  AuditCaseDeleteResponse,
  AuditCaseDetail,
  AuditCaseSummary,
  AuditCaseUpdate,
  AuditDocument,
  AuditDocumentBatchResponse,
  AuditDocumentKind,
  AuditEvent,
  AuditImportPreview,
  AuditTeamCandidate,
  AuditTeamMember,
  AuditTeamRole,
  AuditTZAtomizationPreview,
  AuditTZRun,
  AuditWorkflowStage,
} from '@/api/types'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'

type UnknownRecord = Record<string, unknown>
type DetailTab = 'materials' | 'atoms' | 'history'
type WorkspaceView = 'dashboard' | 'registry' | 'assignments' | 'case' | 'team'
type CaseDialogMode = 'create' | 'edit'
type AtomDialogMode = 'create' | 'edit'

type AuditCaseSummaryLike = Partial<AuditCaseSummary> & UnknownRecord
type AuditCaseDetailLike = Partial<AuditCaseDetail> & UnknownRecord
type AuditAtomLike = Partial<AuditAtom> & UnknownRecord
type AuditEventLike = Partial<AuditEvent> & UnknownRecord
type AuditImportPreviewLike = Partial<AuditImportPreview> & UnknownRecord
type AuditCaseCreatePayload = Partial<AuditCaseCreate> & UnknownRecord
type AuditCaseUpdatePayload = Partial<AuditCaseUpdate> & UnknownRecord
type AuditAtomCreatePayload = Partial<AuditAtomCreate> & UnknownRecord
type AuditAtomUpdatePayload = Partial<AuditAtomUpdate> & UnknownRecord

interface NormalizedAuditCaseSummary {
  id: string
  code: string
  title: string
  productMasked: string
  contractMasked: string
  contractDate: string | null
  status: string
  workflowStage: string
  atomsTotal: number
  atomsReady: number
  atomsDraft: number
  atomsExcluded: number
  updatedAt: string | null
  createdAt: string | null
  ownerName: string | null
  responsibleUserId: string | null
  responsibleName: string | null
  responsibleEmail: string | null
  alphaPassed: number
  commissionPassed: number
  documentsCount: number
}

interface NormalizedAuditAtom {
  id: string
  itemCode: string
  title: string
  digitalProduct: string
  objectType: string
  workType: string
  sourceClause: string
  sourceEvidenceText: string | null
  sourceRefs: Array<{ source_unit_id: string; locator: string; excerpt: string }>
  status: string
  legacyAlphaRef: string | null
  commissionRef: string | null
  systemUrl: string | null
  notes: string | null
  createdAt: string | null
  updatedAt: string | null
}

interface NormalizedAuditCaseDetail extends NormalizedAuditCaseSummary {
  summary: string | null
  notes: string | null
  atoms: NormalizedAuditAtom[]
}

interface NormalizedAuditEvent {
  id: string
  type: string
  title: string
  body: string | null
  actorName: string | null
  createdAt: string | null
}

interface NormalizedImportGroup {
  id: string
  name: string
  rowCount: number
  validCount: number
  errorCount: number
  warningCount: number
}

interface NormalizedImportIssue {
  text: string
  severity: 'error' | 'warning'
}

interface NormalizedImportRow {
  groupId: string
  rowNumber: number
  groupName: string
  itemCode: string
  title: string
  issues: NormalizedImportIssue[]
  ready: boolean
}

interface NormalizedImportPreview {
  totalRows: number
  validRows: number
  errorRows: number
  warningRows: number
  hasErrors: boolean
  expectedSha256: string | null
  groups: NormalizedImportGroup[]
  rows: NormalizedImportRow[]
}

interface EditableAIAtomDraft extends AuditAIAtomDraft {
  included: boolean
}

interface EditableAIModelComparisonDraft extends AuditAIModelComparisonDraft {
  included: boolean
}

interface CaseFormState {
  title: string
  productName: string
  status: string
  workflowStage: AuditWorkflowStage
  summary: string
  contractReference: string
  contractDate: string
}

interface AtomFormState {
  itemCode: string
  title: string
  digitalProduct: string
  objectType: string
  workType: string
  sourceClause: string
  status: string
  legacyAlphaRef: string
  commissionRef: string
  systemUrl: string
  notes: string
}

interface DialogShellProps {
  open: boolean
  title: string
  description?: string
  sizeClassName?: string
  busy?: boolean
  initialFocusRef?: React.RefObject<HTMLElement>
  onRequestClose: (reason: 'escape' | 'backdrop' | 'close-button') => void
  footer?: ReactNode
  children: ReactNode
}

const CASE_STATUS_LABELS: Record<string, string> = {
  draft: 'Черновик',
  atomization: 'Атомизация',
  ready: 'Готово',
  archived: 'Архив',
}

const AUDIT_WORKFLOW_LABELS: Record<AuditWorkflowStage, string> = {
  unassigned: 'Договор не назначен',
  atomization: 'Выполняется атомизация',
  alpha_review: 'Выполняется альфа-проверка',
  commission_pending: 'Ожидает комиссии',
  fixes_required: 'Ожидает исправлений',
  fixing: 'Выполняются исправления',
  recommission_pending: 'Ожидает повторной комиссии',
  ready: 'Готов',
}

const AUDIT_WORKFLOW_ORDER = Object.keys(AUDIT_WORKFLOW_LABELS) as AuditWorkflowStage[]

const ATOM_STATUS_LABELS: Record<string, string> = {
  draft: 'Черновик',
  ready: 'Готов',
  excluded: 'Исключен',
}

const AUDIT_EVENT_LABELS: Record<string, string> = {
  case_created: 'Договор создан',
  case_updated: 'Договор изменен',
  case_imported: 'Договор импортирован',
  responsible_changed: 'Ответственный изменен',
  document_uploaded: 'Материал загружен',
  atom_created: 'Атом создан',
  atom_updated: 'Атом изменен',
  atom_imported: 'Атом импортирован',
  import_committed: 'Импорт подтвержден',
  ai_atomization_started: 'ИИ-атомизация запущена',
  ai_atomization_privacy_previewed: 'Проверено обезличивание запроса к ИИ',
  ai_atomization_ready: 'ИИ-черновик сформирован',
  ai_atomization_failed: 'ИИ-атомизация завершилась ошибкой',
  ai_atomization_committed: 'ИИ-черновик подтвержден',
  audit_tz_preflight_queued: 'Документ поставлен в очередь обработки',
  audit_tz_preflight_pass: 'Документ подготовлен',
  audit_tz_preflight_blocked: 'Подготовка документа остановлена',
  audit_tz_preflight_failed: 'Подготовка документа завершилась ошибкой',
  audit_tz_atomization_queued: 'ИИ-атомизация поставлена в очередь',
  audit_tz_atomization_ready: 'Черновик атомов сформирован',
  audit_tz_atomization_failed: 'ИИ-атомизация завершилась ошибкой',
  assignment_created: 'Договор назначен',
  assignment_transferred: 'Договор передан',
  assignment_removed: 'Назначение снято',
  assignment_consolidated: 'Назначения объединены',
  workflow_stage_changed: 'Этап аудита изменен',
}

const AUDIT_DOCUMENT_KIND_LABELS: Record<AuditDocumentKind, string> = {
  technical_spec: 'Техническое задание',
  atom_register: 'Реестр атомов',
  audit_result: 'Результат аудита',
  protocol: 'Протокол',
  other: 'Другой материал',
}

const CASE_STATUS_ORDER = ['all', ...AUDIT_WORKFLOW_ORDER, 'archived']
const ATOM_STATUS_ORDER = ['all', 'draft', 'ready', 'excluded']

const EMPTY_CASE_FORM: CaseFormState = {
  title: '',
  productName: '',
  status: 'draft',
  workflowStage: 'unassigned',
  summary: '',
  contractReference: '',
  contractDate: '',
}

const EMPTY_ATOM_FORM: AtomFormState = {
  itemCode: '',
  title: '',
  digitalProduct: '',
  objectType: '',
  workType: '',
  sourceClause: '',
  status: 'draft',
  legacyAlphaRef: '',
  commissionRef: '',
  systemUrl: '',
  notes: '',
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null
}

function canonicalRunLabel(run: AuditTZRun): string {
  if (run.status === 'queued') return 'В очереди'
  if (run.status === 'running') return run.current_phase === 'preflight' ? 'Подготавливаем документ' : 'Runtime обрабатывает документ'
  if (run.status === 'preflight_pass') return 'Документ подготовлен'
  if (run.status === 'atomization_queued') return 'Атомизация в очереди'
  if (run.status === 'atomizing') return 'ИИ анализирует ТЗ'
  if (run.status === 'draft_ready') return 'Черновик атомов готов'
  if (run.status === 'committed') return 'Атомы записаны в реестр'
  if (run.status === 'blocked') return 'Обработка остановлена'
  return 'Техническая ошибка'
}

function canonicalBlockMessage(code: string | null): string {
  const messages: Record<string, string> = {
    BLOCKED_SOURCE_ID_UNCONFIRMED: 'Это результат прежней версии проверки номера. Запустите обработку документа повторно.',
    BLOCKED_SOURCE_ID_CONFLICT: 'Это результат прежней версии проверки номера. Запустите обработку документа повторно.',
    BLOCKED_AMBIGUOUS_IDENTITY: 'Это результат прежней версии проверки номера. Запустите обработку документа повторно.',
    BLOCKED_EMPTY_SOURCE: 'В документе не найдено содержимое для проверки.',
    BLOCKED_UNSAFE_OFFICE: 'Структура DOCX не прошла безопасную проверку.',
    BLOCKED_SOURCE_UNREADABLE: 'DOCX не удалось прочитать как неизменяемый источник.',
    BLOCKED_HASH_CHANGED: 'Файл изменился после загрузки. Загрузите его повторно как новую версию.',
    BLOCKED_UNSUPPORTED_SOURCE_TYPE: 'Текущая версия обработки поддерживает только DOCX.',
  }
  if (code && messages[code]) return messages[code]
  return code ? `Обработка остановлена: ${code}.` : 'Обработка остановлена. Проверьте целостность и формат документа.'
}

function canonicalBlockGuidance(code: string | null): string[] {
  if (!['BLOCKED_SOURCE_ID_UNCONFIRMED', 'BLOCKED_SOURCE_ID_CONFLICT', 'BLOCKED_AMBIGUOUS_IDENTITY'].includes(code ?? '')) return []
  return ['Нажмите «Новая проверка»: номер договора больше не участвует в обработке.']
}

function getString(source: UnknownRecord, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

function getNumber(source: UnknownRecord, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  return null
}

function getArray(source: UnknownRecord, ...keys: string[]): unknown[] {
  for (const key of keys) {
    const value = source[key]
    if (Array.isArray(value)) return value
  }
  return []
}

function nullIfEmpty(value: string): string | null {
  return value.trim() ? value.trim() : null
}

function humanizeToken(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (char) => char.toUpperCase())
}

function formatCaseStatus(status: string): string {
  return CASE_STATUS_LABELS[status] ?? humanizeToken(status)
}

function formatAuditWorkflowStage(stage: string): string {
  return AUDIT_WORKFLOW_LABELS[stage as AuditWorkflowStage] ?? humanizeToken(stage)
}

function caseWorkflowLabel(status: string, stage: string): string {
  return status === 'archived' ? 'Архив' : formatAuditWorkflowStage(stage)
}

function caseWorkflowTone(status: string, stage: string): string {
  return status === 'archived' ? caseStatusTone('archived') : auditWorkflowTone(stage)
}

function formatAtomStatus(status: string): string {
  return ATOM_STATUS_LABELS[status] ?? humanizeToken(status)
}

function formatAuditEventType(type: string): string {
  return AUDIT_EVENT_LABELS[type] ?? humanizeToken(type)
}

function formatCountRu(value: number, one: string, few: string, many: string): string {
  const mod100 = value % 100
  const mod10 = value % 10
  if (mod100 >= 11 && mod100 <= 14) return `${value} ${many}`
  if (mod10 === 1) return `${value} ${one}`
  if (mod10 >= 2 && mod10 <= 4) return `${value} ${few}`
  return `${value} ${many}`
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDateOnly(value: string | null): string {
  if (!value) return '—'
  const date = new Date(`${value.slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('ru-RU')
}

function localISODate(value = new Date()): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function shiftISODate(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + days)
  return localISODate(date)
}

function inclusiveDateRangeDays(dateFrom: string, dateTo: string): number {
  const start = new Date(`${dateFrom}T12:00:00`)
  const end = new Date(`${dateTo}T12:00:00`)
  return Math.floor((end.getTime() - start.getTime()) / 86_400_000) + 1
}

function assignmentDateLabel(value: string): { primary: string; secondary: string } {
  const date = new Date(`${value}T12:00:00`)
  return {
    primary: date.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' }),
    secondary: date.toLocaleDateString('ru-RU', { weekday: 'short' }),
  }
}

function assignmentStage(item: AuditAssignment): string {
  return item.case_status === 'archived' ? 'archived' : item.workflow_stage
}

function assignmentStageColor(stage: string): string {
  switch (stage) {
    case 'unassigned': return 'bg-rose-500'
    case 'atomization': return 'bg-amber-400'
    case 'alpha_review': return 'bg-sky-500'
    case 'commission_pending': return 'bg-violet-500'
    case 'fixes_required': return 'bg-orange-500'
    case 'fixing': return 'bg-blue-500'
    case 'recommission_pending': return 'bg-indigo-500'
    case 'ready': return 'bg-emerald-500'
    case 'archived': return 'bg-zinc-400'
    default: return 'bg-primary'
  }
}

function assignmentCellTone(items: AuditAssignment[]): string {
  const stageOrder = [
    'unassigned',
    'atomization',
    'alpha_review',
    'commission_pending',
    'fixes_required',
    'fixing',
    'recommission_pending',
    'ready',
    'archived',
  ]
  const stageRank = new Map(stageOrder.map((value, index) => [value, index]))
  const stage = items
    .map(assignmentStage)
    .sort((left, right) => (stageRank.get(left) ?? 999) - (stageRank.get(right) ?? 999))[0]
  switch (stage) {
    case 'unassigned': return 'border-rose-500/25 bg-rose-500/10 hover:bg-rose-500/15'
    case 'atomization': return 'border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/15'
    case 'alpha_review': return 'border-sky-500/25 bg-sky-500/10 hover:bg-sky-500/15'
    case 'commission_pending': return 'border-violet-500/25 bg-violet-500/10 hover:bg-violet-500/15'
    case 'fixes_required': return 'border-orange-500/25 bg-orange-500/10 hover:bg-orange-500/15'
    case 'fixing': return 'border-blue-500/25 bg-blue-500/10 hover:bg-blue-500/15'
    case 'recommission_pending': return 'border-indigo-500/25 bg-indigo-500/10 hover:bg-indigo-500/15'
    case 'ready': return 'border-emerald-500/25 bg-emerald-500/10 hover:bg-emerald-500/15'
    default: return 'border-border bg-muted/50 hover:bg-muted'
  }
}

function auditWorkflowTone(stage: string): string {
  switch (stage) {
    case 'unassigned': return 'border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300'
    case 'atomization': return 'border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200'
    case 'alpha_review': return 'border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300'
    case 'commission_pending': return 'border-violet-500/25 bg-violet-500/10 text-violet-700 dark:text-violet-300'
    case 'fixes_required': return 'border-orange-500/25 bg-orange-500/10 text-orange-800 dark:text-orange-300'
    case 'fixing': return 'border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-300'
    case 'recommission_pending': return 'border-indigo-500/25 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
    case 'ready': return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
    default: return 'border-border bg-surface-soft text-muted-foreground'
  }
}

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} КБ`
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

function progressPercent(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0
}

function maskSensitive(value: string | null, start = 3, end = 2): string {
  if (!value) return '—'
  const compact = value.replace(/\s+/g, ' ').trim()
  if (compact.length <= start + end + 1) return compact
  return `${compact.slice(0, start)}***${compact.slice(-end)}`
}

function caseStatusTone(status: string): string {
  switch (status) {
    case 'ready':
    case 'done':
      return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
    case 'review':
    case 'atomization':
      return 'border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200'
    case 'draft':
      return 'border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300'
    case 'archived':
      return 'border-border bg-surface-soft text-muted-foreground'
    default:
      return 'border-primary/20 bg-primary/10 text-primary'
  }
}

function caseNeedsAtomization(item: NormalizedAuditCaseSummary): boolean {
  return (
    item.status !== 'archived' &&
    (item.status === 'draft' || item.atomsTotal === 0 || item.atomsDraft > 0)
  )
}

function atomizationSignal(item: NormalizedAuditCaseSummary): {
  label: string
  toneClass: string
} {
  if (item.status === 'archived') {
    return { label: 'Архив', toneClass: 'text-muted-foreground' }
  }
  if (item.atomsTotal === 0) {
    return {
      label: 'ТЗ не декомпозировано',
      toneClass: 'text-rose-700 dark:text-rose-300',
    }
  }
  if (item.status === 'draft') {
    return {
      label: 'Черновик требует проверки',
      toneClass: 'text-rose-700 dark:text-rose-300',
    }
  }
  if (item.atomsDraft > 0) {
  return {
    label: `Не завершено: ${formatCountRu(item.atomsDraft, 'атом', 'атома', 'атомов')}`,
      toneClass: 'text-amber-900 dark:text-amber-200',
    }
  }
  return {
    label: 'Декомпозиция завершена',
    toneClass: 'text-emerald-700 dark:text-emerald-300',
  }
}

function atomStatusTone(status: string): string {
  switch (status) {
    case 'ready':
      return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
    case 'excluded':
      return 'border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300'
    default:
      return 'border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200'
  }
}

function compactOptions(values: string[]): string[] {
  return Array.from(
    new Set(values.map((value) => value.trim()).filter(Boolean))
  ).sort((left, right) => left.localeCompare(right, 'ru'))
}

function normalizeAuditCaseSummary(input: unknown): NormalizedAuditCaseSummary | null {
  if (!isRecord(input)) return null
  const source = input as AuditCaseSummaryLike
  const id = getString(source, 'id', 'case_id')
  if (!id) return null

  const atomsTotal = getNumber(source, 'atoms_count', 'atoms_total', 'atom_count', 'atomsCount', 'total_atoms') ?? 0
  const atomsReady = getNumber(source, 'ready_atoms_count', 'atoms_ready', 'ready_atoms', 'readyCount') ?? 0
  const atomsDraft = getNumber(source, 'draft_atoms_count', 'atoms_draft', 'draft_atoms', 'draftCount') ?? 0
  const atomsExcluded = getNumber(source, 'excluded_atoms_count', 'atoms_excluded', 'excluded_atoms', 'excludedCount') ?? 0
  const productMasked =
    getString(source, 'digital_product', 'product_name', 'product') ??
    maskSensitive(getString(source, 'product_name', 'product', 'product_title', 'subject'))
  const contractMasked =
    getString(source, 'contract_reference_mask', 'contract_reference_masked', 'masked_contract_reference', 'contract_masked') ??
    '—'

  return {
    id,
    code: getString(source, 'aud_code', 'audit_code', 'code', 'case_code', 'case_number') ?? 'AUD-—',
    title: getString(source, 'title', 'name', 'audit_title') ?? 'Без названия',
    productMasked,
    contractMasked,
    contractDate: getString(source, 'contract_date', 'contractDate'),
    status: getString(source, 'status', 'state') ?? 'draft',
    workflowStage: getString(source, 'workflow_stage', 'workflowStage') ?? 'unassigned',
    atomsTotal,
    atomsReady,
    atomsDraft,
    atomsExcluded,
    updatedAt: getString(source, 'updated_at', 'updatedAt', 'modified_at'),
    createdAt: getString(source, 'created_at', 'createdAt'),
    ownerName: getString(source, 'owner_name', 'author_name', 'created_by_name', 'responsible_name'),
    responsibleUserId: getString(source, 'responsible_user_id', 'assignee_id'),
    responsibleName: getString(source, 'responsible_name', 'assignee_name'),
    responsibleEmail: getString(source, 'responsible_email', 'assignee_email'),
    alphaPassed: getNumber(source, 'alpha_passed_count', 'alpha_passed') ?? 0,
    commissionPassed: getNumber(source, 'commission_passed_count', 'commission_passed') ?? 0,
    documentsCount: getNumber(source, 'documents_count', 'documentsCount') ?? 0,
  }
}

function normalizeAuditAtom(input: unknown): NormalizedAuditAtom | null {
  if (!isRecord(input)) return null
  const source = input as AuditAtomLike
  const id = getString(source, 'id', 'atom_id')
  if (!id) return null

  return {
    id,
    itemCode: getString(source, 'item_code', 'code', 'audit_item_code') ?? '—',
    title: getString(source, 'title', 'name', 'label') ?? 'Без названия',
    digitalProduct: getString(source, 'digital_product', 'digitalProduct', 'product_name') ?? '—',
    objectType: getString(source, 'object_type', 'objectType') ?? '—',
    workType: getString(source, 'work_type', 'workType') ?? '—',
    sourceClause: getString(source, 'source_clause', 'sourceClause', 'clause') ?? '—',
    sourceEvidenceText: getString(source, 'source_evidence_text', 'sourceEvidenceText'),
    sourceRefs: getArray(source, 'source_refs_json', 'sourceRefs').flatMap((item) => {
      if (!isRecord(item)) return []
      const sourceUnitId = getString(item, 'source_unit_id', 'sourceUnitId')
      const locator = getString(item, 'locator')
      if (!sourceUnitId || !locator) return []
      return [{
        source_unit_id: sourceUnitId,
        locator,
        excerpt: getString(item, 'excerpt') ?? '',
      }]
    }),
    status: getString(source, 'status', 'state') ?? 'draft',
    legacyAlphaRef: getString(source, 'alpha_result_raw', 'alpha_result', 'legacy_alpha_reference', 'legacy_alpha_ref', 'alpha_reference'),
    commissionRef: getString(source, 'commission_result_raw', 'commission_result', 'commission_reference', 'commission_ref'),
    systemUrl: getString(source, 'system_url', 'url', 'full_url'),
    notes: getString(source, 'notes', 'description', 'comment'),
    createdAt: getString(source, 'created_at', 'createdAt'),
    updatedAt: getString(source, 'updated_at', 'updatedAt'),
  }
}

function normalizeAuditCaseDetail(input: unknown): NormalizedAuditCaseDetail | null {
  if (!isRecord(input)) return null
  const summary = normalizeAuditCaseSummary(input)
  if (!summary) return null
  const source = input as AuditCaseDetailLike
  const atoms = getArray(source, 'atoms', 'items', 'rows')
    .map((atom) => normalizeAuditAtom(atom))
    .filter((atom): atom is NormalizedAuditAtom => Boolean(atom))

  return {
    ...summary,
    summary: getString(source, 'summary', 'description', 'scope', 'notes'),
    notes: getString(source, 'notes', 'comment', 'remarks'),
    atoms,
  }
}

function normalizeAuditEvent(input: unknown): NormalizedAuditEvent | null {
  if (!isRecord(input)) return null
  const source = input as AuditEventLike
  const id = getString(source, 'id', 'event_id') ?? `${getString(source, 'created_at', 'createdAt')}:${getString(source, 'event_type', 'type')}`
  if (!id) return null

  return {
    id,
    type: getString(source, 'event_type', 'type') ?? 'updated',
    title: getString(source, 'title', 'label') ?? formatAuditEventType(getString(source, 'event_type', 'type') ?? 'updated'),
    body: getString(source, 'body', 'description', 'message'),
    actorName: getString(source, 'actor_name', 'author_name', 'performed_by_name'),
    createdAt: getString(source, 'created_at', 'createdAt'),
  }
}

function normalizeImportPreview(input: unknown, fallbackSha: string | null): NormalizedImportPreview | null {
  if (!isRecord(input)) return null
  const source = input as AuditImportPreviewLike
  const rows = getArray(source, 'rows', 'items')
    .map((rowInput) => {
      if (!isRecord(rowInput)) return null
      const row = rowInput as UnknownRecord
      const issues = getArray(row, 'issues', 'errors', 'messages')
        .map((item) => {
          if (typeof item === 'string') {
            return { text: item.trim(), severity: 'error' as const }
          }
          if (!isRecord(item)) return null
          const field = getString(item, 'field')
          const message = getString(item, 'message', 'detail')
          const severity = getString(item, 'severity') === 'warning' ? 'warning' : 'error'
          return {
            text: [field, message].filter(Boolean).join(': '),
            severity,
          } satisfies NormalizedImportIssue
        })
        .filter((issue): issue is NormalizedImportIssue => Boolean(issue?.text))
      const ready = !issues.some((issue) => issue.severity === 'error')
      return {
        groupId: getString(row, 'group_id', 'groupId') ?? `row-${getNumber(row, 'row_number', 'rowNumber', 'index') ?? 0}`,
        rowNumber: getNumber(row, 'row_number', 'rowNumber', 'index') ?? 0,
        groupName: getString(row, 'contract_reference_mask', 'group_name', 'groupName', 'sheet_name') ?? 'Без группы',
        itemCode: getString(row, 'item_code', 'code') ?? '—',
        title: getString(row, 'title', 'name') ?? '—',
        issues,
        ready,
      } satisfies NormalizedImportRow
    })
    .filter((row): row is NormalizedImportRow => Boolean(row))

  const groupsFromPayload = getArray(source, 'grouped_counts', 'groups')
    .map((groupInput) => {
      if (!isRecord(groupInput)) return null
      const group = groupInput as UnknownRecord
      return {
        id: getString(group, 'group_id', 'groupId') ?? `group-${getString(group, 'contract_reference_mask', 'name', 'group_name', 'title') ?? 'unknown'}`,
        name: getString(group, 'contract_reference_mask', 'name', 'group_name', 'title') ?? 'Без группы',
        rowCount: getNumber(group, 'row_count', 'rowCount', 'total_rows') ?? 0,
        validCount: getNumber(group, 'valid_count', 'validRows', 'valid_rows') ?? 0,
        errorCount: getNumber(group, 'error_count', 'errorRows', 'error_rows') ?? 0,
        warningCount: getNumber(group, 'warning_count', 'warningRows', 'warning_rows') ?? 0,
      } satisfies NormalizedImportGroup
    })
    .filter((group): group is NormalizedImportGroup => Boolean(group))

  const groups =
    groupsFromPayload.length > 0
      ? groupsFromPayload
      : Object.values(
          rows.reduce<Record<string, NormalizedImportGroup>>((accumulator, row) => {
            const current = accumulator[row.groupId] ?? {
              id: row.groupId,
              name: row.groupName,
              rowCount: 0,
              validCount: 0,
              errorCount: 0,
              warningCount: 0,
            }
            current.rowCount += 1
            current.validCount += row.ready ? 1 : 0
            current.errorCount += row.ready ? 0 : 1
            current.warningCount += row.issues.some((issue) => issue.severity === 'warning') ? 1 : 0
            accumulator[row.groupId] = current
            return accumulator
          }, {})
        )

  const totalRows = getNumber(source, 'total_rows', 'totalRows') ?? rows.length
  const validRows =
    getNumber(source, 'valid_rows', 'validRows') ??
    rows.filter((row) => row.ready).length
  const errorRows =
    getNumber(source, 'error_rows', 'errorRows') ??
    rows.filter((row) => !row.ready).length
  const warningRows =
    getNumber(source, 'warning_rows', 'warningRows') ??
    rows.filter((row) => row.issues.some((issue) => issue.severity === 'warning')).length

  return {
    totalRows,
    validRows,
    errorRows,
    warningRows,
    hasErrors: Boolean(source.has_errors ?? source.hasErrors ?? errorRows > 0),
    expectedSha256: getString(source, 'sha256', 'expected_sha256', 'expectedSha256') ?? fallbackSha,
    groups,
    rows,
  }
}

function extractCollection(payload: unknown, collectionKeys: string[]): unknown[] {
  if (Array.isArray(payload)) return payload
  if (!isRecord(payload)) return []
  for (const key of collectionKeys) {
    const value = payload[key]
    if (Array.isArray(value)) return value
  }
  return []
}

async function sha256(file: File): Promise<string> {
  const digest = await window.crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

function DialogShell({
  open,
  title,
  description,
  sizeClassName = 'max-w-4xl',
  busy = false,
  initialFocusRef,
  onRequestClose,
  footer,
  children,
}: DialogShellProps) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusTimer = window.setTimeout(() => {
      const initialElement = initialFocusRef?.current
      if (initialElement) {
        initialElement.focus()
        return
      }
      const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      firstFocusable?.focus()
    }, 0)

    return () => {
      window.clearTimeout(focusTimer)
      document.body.style.overflow = previousOverflow
      previousFocusRef.current?.focus()
    }
  }, [open, initialFocusRef])

  if (!open) return null

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onRequestClose('escape')
      return
    }
    if (event.key !== 'Tab') return

    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? []
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overscroll-contain bg-black/55 p-3 sm:p-4"
      onMouseDown={(event) => event.target === event.currentTarget && event.preventDefault()}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className={cn(
          'flex max-h-[calc(100dvh-1.5rem)] w-full flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-2xl sm:max-h-[calc(100dvh-3rem)]',
          sizeClassName
        )}
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold text-foreground">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-1 text-sm text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => onRequestClose('close-button')}
            disabled={busy}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Закрыть диалог"
            title="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overscroll-contain overflow-y-auto px-4 py-4 sm:px-5">{children}</div>
        {footer ? (
          <div className="border-t border-border bg-surface-soft px-4 py-4 sm:px-5">{footer}</div>
        ) : null}
      </div>
    </div>
  )
}

function MetricTile({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: string
  hint?: string
  tone?: 'neutral' | 'primary' | 'success' | 'warning' | 'danger'
}) {
  return (
    <div
      className={cn(
        'rounded-md border px-3 py-3',
        tone === 'primary' && 'border-primary/20 bg-primary/10',
        tone === 'success' && 'border-emerald-500/20 bg-emerald-500/10',
        tone === 'warning' && 'border-amber-500/20 bg-amber-500/10',
        tone === 'danger' && 'border-rose-500/20 bg-rose-500/10',
        tone === 'neutral' && 'border-border bg-surface-soft'
      )}
    >
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-foreground">{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  )
}

function StatusPill({ label, toneClass }: { label: string; toneClass: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium', toneClass)}>
      {label}
    </span>
  )
}

function emptyCaseFormFromDetail(detail: NormalizedAuditCaseDetail | null): CaseFormState {
  if (!detail) return EMPTY_CASE_FORM
  return {
    title: detail.title,
    productName: detail.productMasked === '—' ? '' : detail.productMasked,
    status: detail.status,
    workflowStage: detail.workflowStage as AuditWorkflowStage,
    summary: detail.summary ?? detail.notes ?? '',
    contractReference: '',
    contractDate: detail.contractDate ?? '',
  }
}

function emptyAtomFormFromAtom(atom: NormalizedAuditAtom | null): AtomFormState {
  if (!atom) return EMPTY_ATOM_FORM
  return {
    itemCode: atom.itemCode === '—' ? '' : atom.itemCode,
    title: atom.title === 'Без названия' ? '' : atom.title,
    digitalProduct: atom.digitalProduct === '—' ? '' : atom.digitalProduct,
    objectType: atom.objectType === '—' ? '' : atom.objectType,
    workType: atom.workType === '—' ? '' : atom.workType,
    sourceClause: atom.sourceClause === '—' ? '' : atom.sourceClause,
    status: atom.status,
    legacyAlphaRef: atom.legacyAlphaRef ?? '',
    commissionRef: atom.commissionRef ?? '',
    systemUrl: atom.systemUrl ?? '',
    notes: atom.notes ?? '',
  }
}

function serializeFormState(value: CaseFormState | AtomFormState): string {
  return JSON.stringify(value)
}

export function AuditPage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const workspaceView = (['dashboard', 'registry', 'assignments', 'case', 'team'].includes(searchParams.get('view') ?? '')
    ? searchParams.get('view')
    : 'dashboard') as WorkspaceView

  const [cases, setCases] = useState<NormalizedAuditCaseSummary[]>([])
  const [casesLoading, setCasesLoading] = useState(true)
  const [casesError, setCasesError] = useState<string | null>(null)
  const [caseQuery, setCaseQuery] = useState('')
  const [caseStatusFilter, setCaseStatusFilter] = useState('all')

  const [detail, setDetail] = useState<NormalizedAuditCaseDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('atoms')
  const detailTabRefs = useRef<Array<HTMLButtonElement | null>>([])
  const [selectedAtomId, setSelectedAtomId] = useState<string | null>(null)
  const [events, setEvents] = useState<NormalizedAuditEvent[]>([])
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [documents, setDocuments] = useState<AuditDocument[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(false)

  const [team, setTeam] = useState<AuditTeamMember[]>([])
  const [teamCandidates, setTeamCandidates] = useState<AuditTeamCandidate[]>([])
  const [teamLoading, setTeamLoading] = useState(true)
  const [teamError, setTeamError] = useState<string | null>(null)
  const [newTeamUserId, setNewTeamUserId] = useState('')
  const [newTeamRole, setNewTeamRole] = useState<AuditTeamRole>('member')
  const [teamSaving, setTeamSaving] = useState(false)

  const [assignmentRangeStart, setAssignmentRangeStart] = useState(() => localISODate())
  const [assignmentRangeEnd, setAssignmentRangeEnd] = useState(() => shiftISODate(localISODate(), 13))
  const [assignments, setAssignments] = useState<AuditAssignment[]>([])
  const [assignmentIndex, setAssignmentIndex] = useState<AuditAssignment[]>([])
  const [assignmentsLoading, setAssignmentsLoading] = useState(false)
  const [assignmentsError, setAssignmentsError] = useState<string | null>(null)
  const [assignmentDialogOpen, setAssignmentDialogOpen] = useState(false)
  const [assignmentTargetDate, setAssignmentTargetDate] = useState('')
  const [assignmentTargetUserId, setAssignmentTargetUserId] = useState('')
  const [assignmentInitialCaseIds, setAssignmentInitialCaseIds] = useState<string[]>([])
  const [assignmentCaseIds, setAssignmentCaseIds] = useState<string[]>([])
  const [assignmentTransferCaseIds, setAssignmentTransferCaseIds] = useState<string[]>([])
  const [assignmentQuery, setAssignmentQuery] = useState('')
  const [assignmentSaving, setAssignmentSaving] = useState(false)

  const canManage =
    user?.role === 'admin' ||
    user?.role === 'teamlead' ||
    team.some((member) => member.user_id === user?.id && member.role === 'leader')

  const [atomQuery, setAtomQuery] = useState('')
  const [atomStatusFilter, setAtomStatusFilter] = useState('all')
  const [atomObjectTypeFilter, setAtomObjectTypeFilter] = useState('all')
  const [atomWorkTypeFilter, setAtomWorkTypeFilter] = useState('all')
  const [selectedAtomIds, setSelectedAtomIds] = useState<string[]>([])
  const [bulkAtomState, setBulkAtomState] = useState<'draft' | 'ready' | 'excluded'>('ready')
  const [bulkAtomBusy, setBulkAtomBusy] = useState(false)

  const [caseDialogOpen, setCaseDialogOpen] = useState(false)
  const [caseDialogMode, setCaseDialogMode] = useState<CaseDialogMode>('create')
  const [caseForm, setCaseForm] = useState<CaseFormState>(EMPTY_CASE_FORM)
  const [caseFormInitial, setCaseFormInitial] = useState<CaseFormState>(EMPTY_CASE_FORM)
  const [caseSaving, setCaseSaving] = useState(false)
  const caseTitleInputRef = useRef<HTMLInputElement>(null)

  const [atomDialogOpen, setAtomDialogOpen] = useState(false)
  const [atomDialogMode, setAtomDialogMode] = useState<AtomDialogMode>('create')
  const [editingAtomId, setEditingAtomId] = useState<string | null>(null)
  const [atomForm, setAtomForm] = useState<AtomFormState>(EMPTY_ATOM_FORM)
  const [atomFormInitial, setAtomFormInitial] = useState<AtomFormState>(EMPTY_ATOM_FORM)
  const [atomSaving, setAtomSaving] = useState(false)
  const atomTitleInputRef = useRef<HTMLInputElement>(null)

  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [importTargetCaseId, setImportTargetCaseId] = useState<string | null>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<NormalizedImportPreview | null>(null)
  const [importPreviewing, setImportPreviewing] = useState(false)
  const [importCommitting, setImportCommitting] = useState(false)
  const [importChecksum, setImportChecksum] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const importFileInputRef = useRef<HTMLInputElement>(null)

  const [documentDialogOpen, setDocumentDialogOpen] = useState(false)
  const [documentFiles, setDocumentFiles] = useState<File[]>([])
  const [documentProduct, setDocumentProduct] = useState('')
  const [documentUploading, setDocumentUploading] = useState(false)
  const documentFileInputRef = useRef<HTMLInputElement>(null)

  const [materialDialogOpen, setMaterialDialogOpen] = useState(false)
  const [materialFiles, setMaterialFiles] = useState<File[]>([])
  const [materialKind, setMaterialKind] = useState<AuditDocumentKind>('other')
  const [materialDisplayName, setMaterialDisplayName] = useState('')
  const [materialUploading, setMaterialUploading] = useState(false)
  const materialFileInputRef = useRef<HTMLInputElement>(null)

  const [deleteCaseDialogOpen, setDeleteCaseDialogOpen] = useState(false)
  const [deleteCaseConfirmation, setDeleteCaseConfirmation] = useState('')
  const [deleteCaseReason, setDeleteCaseReason] = useState('')
  const [deleteCaseBusy, setDeleteCaseBusy] = useState(false)
  const deleteCaseConfirmationRef = useRef<HTMLInputElement>(null)

  const [responsibleDialogOpen, setResponsibleDialogOpen] = useState(false)
  const [responsibleCaseId, setResponsibleCaseId] = useState<string | null>(null)
  const [responsibleUserId, setResponsibleUserId] = useState('')
  const [responsibleSaving, setResponsibleSaving] = useState(false)

  const [aiAtomizationDialogOpen, setAiAtomizationDialogOpen] = useState(false)
  const [aiAtomizationSkills, setAiAtomizationSkills] = useState<AuditAtomizationSkillVersion[]>([])
  const [aiSelectedSkillId, setAiSelectedSkillId] = useState('')
  const [aiSelectedDocumentId, setAiSelectedDocumentId] = useState('')
  const [aiContractIdentifiers, setAiContractIdentifiers] = useState('')
  const [aiPrivacyPreview, setAiPrivacyPreview] = useState<AuditAIPrivacyPreview | null>(null)
  const [aiTransferConfirmed, setAiTransferConfirmed] = useState(false)
  const [aiAttempt, setAiAttempt] = useState<AuditAIAtomizationAttempt | null>(null)
  const [canonicalRun, setCanonicalRun] = useState<AuditTZRun | null>(null)
  const [canonicalAtomizationPreview, setCanonicalAtomizationPreview] = useState<AuditTZAtomizationPreview | null>(null)
  const [aiProviders, setAiProviders] = useState<AuditAIProviderOption[]>([])
  const [aiSelectedProviderId, setAiSelectedProviderId] = useState('')
  const [aiPreparingNextModel, setAiPreparingNextModel] = useState(false)
  const [aiDrafts, setAiDrafts] = useState<EditableAIAtomDraft[]>([])
  const [aiAtomizationBusy, setAiAtomizationBusy] = useState(false)
  const [aiAtomizationError, setAiAtomizationError] = useState<string | null>(null)

  const [modelRegistries, setModelRegistries] = useState<AuditAIModelRegistry[]>([])
  const [selectedModelRegistryIds, setSelectedModelRegistryIds] = useState<string[]>([])
  const [modelComparisons, setModelComparisons] = useState<AuditAIModelComparison[]>([])
  const [modelWorkspaceLoading, setModelWorkspaceLoading] = useState(false)
  const [modelWorkspaceError, setModelWorkspaceError] = useState<string | null>(null)
  const [comparisonDialogOpen, setComparisonDialogOpen] = useState(false)
  const [modelComparison, setModelComparison] = useState<AuditAIModelComparison | null>(null)
  const [comparisonDrafts, setComparisonDrafts] = useState<EditableAIModelComparisonDraft[]>([])
  const [comparisonBusy, setComparisonBusy] = useState(false)
  const [comparisonError, setComparisonError] = useState<string | null>(null)

  const loadCases = useCallback(async () => {
    setCasesLoading(true)
    setCasesError(null)
    try {
      const payload = await api.get<unknown>('/api/audit/cases')
      const nextCases = extractCollection(payload, ['items', 'results', 'cases', 'data'])
        .map((item) => normalizeAuditCaseSummary(item))
        .filter((item): item is NormalizedAuditCaseSummary => Boolean(item))
        .sort((left, right) => {
          const leftTime = left.updatedAt ? new Date(left.updatedAt).getTime() : 0
          const rightTime = right.updatedAt ? new Date(right.updatedAt).getTime() : 0
          return rightTime - leftTime
        })
      setCases(nextCases)
      return nextCases
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить список аудитов'
      setCasesError(message)
      setCases([])
      return []
    } finally {
      setCasesLoading(false)
    }
  }, [])

  const loadTeam = useCallback(async () => {
    setTeamLoading(true)
    setTeamError(null)
    try {
      const nextTeam = await api.get<AuditTeamMember[]>('/api/audit/team')
      setTeam(nextTeam)
      return nextTeam
    } catch (error) {
      setTeam([])
      setTeamError(error instanceof Error ? error.message : 'Не удалось загрузить команду аудита')
      return []
    } finally {
      setTeamLoading(false)
    }
  }, [])

  const loadAssignments = useCallback(async () => {
    setAssignmentsLoading(true)
    setAssignmentsError(null)
    try {
      const [result, index] = await Promise.all([
        api.get<AuditAssignmentList>('/api/audit/assignments', {
          date_from: assignmentRangeStart,
          date_to: assignmentRangeEnd,
        }),
        api.get<AuditAssignment[]>('/api/audit/assignments/index'),
      ])
      setAssignments(result.items)
      setAssignmentIndex(index)
      return result.items
    } catch (error) {
      setAssignments([])
      setAssignmentIndex([])
      setAssignmentsError(error instanceof Error ? error.message : 'Не удалось загрузить назначения')
      return []
    } finally {
      setAssignmentsLoading(false)
    }
  }, [assignmentRangeEnd, assignmentRangeStart])

  const loadTeamCandidates = useCallback(async () => {
    try {
      const candidates = await api.get<AuditTeamCandidate[]>('/api/audit/team/candidates')
      setTeamCandidates(candidates)
      setNewTeamUserId((current) => current || candidates[0]?.user_id || '')
    } catch {
      setTeamCandidates([])
    }
  }, [])

  const loadCaseBundle = useCallback(async (caseId: string) => {
    setDetailLoading(true)
    setDetailError(null)
    setEventsError(null)
    setDocumentsLoading(true)
    try {
      const [detailPayload, eventsResult, documentsResult] = await Promise.all([
        api.get<unknown>(`/api/audit/cases/${caseId}`),
        api.get<unknown>(`/api/audit/cases/${caseId}/events`)
          .then((value) => ({ ok: true as const, value }))
          .catch((error: unknown) => ({ ok: false as const, error })),
        api.get<AuditDocument[]>(`/api/audit/cases/${caseId}/documents`)
          .then((value) => ({ ok: true as const, value }))
          .catch((error: unknown) => ({ ok: false as const, error })),
      ])
      const nextDetail = normalizeAuditCaseDetail(detailPayload)
      if (!nextDetail) {
        throw new Error('Детали аудита не распознаны')
      }
      setDetail(nextDetail)
      if (eventsResult.ok) {
        const nextEvents = extractCollection(eventsResult.value, ['items', 'results', 'events', 'data'])
          .map((item) => normalizeAuditEvent(item))
          .filter((item): item is NormalizedAuditEvent => Boolean(item))
          .sort((left, right) => {
            const leftTime = left.createdAt ? new Date(left.createdAt).getTime() : 0
            const rightTime = right.createdAt ? new Date(right.createdAt).getTime() : 0
            return rightTime - leftTime
          })
        setEvents(nextEvents)
      } else {
        setEvents([])
        setEventsError(eventsResult.error instanceof Error ? eventsResult.error.message : 'История временно недоступна')
      }
      if (documentsResult.ok) {
        setDocuments(documentsResult.value)
      } else {
        setDocuments([])
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось загрузить аудит'
      setDetailError(message)
      setDetail(null)
      setEvents([])
      setDocuments([])
    } finally {
      setDetailLoading(false)
      setDocumentsLoading(false)
    }
  }, [])

  useEffect(() => {
    void Promise.all([loadCases(), loadTeam()])
  }, [loadCases, loadTeam])

  useEffect(() => {
    if (canManage) void loadTeamCandidates()
  }, [canManage, loadTeamCandidates])

  useEffect(() => {
    if (workspaceView === 'assignments') void loadAssignments()
  }, [loadAssignments, workspaceView])

  const selectedCaseId = useMemo(() => {
    const fromUrl = searchParams.get('case')
    return fromUrl || null
  }, [searchParams])

  const loadModelWorkspace = useCallback(async (caseId: string) => {
    setModelWorkspaceLoading(true)
    setModelWorkspaceError(null)
    try {
      const [registryResult, comparisonResult] = await Promise.all([
        api.get<AuditAIModelRegistryList>(`/api/audit/cases/${caseId}/model-registries`),
        api.get<AuditAIModelComparison[]>(`/api/audit/cases/${caseId}/model-comparisons`),
      ])
      setModelRegistries(registryResult.items)
      setModelComparisons(comparisonResult)
      setSelectedModelRegistryIds((current) => {
        const available = new Set(registryResult.items.map((item) => item.id))
        const retained = current.filter((id) => available.has(id))
        return retained.length > 0 ? retained : registryResult.items.map((item) => item.id)
      })
      return registryResult.items
    } catch (error) {
      setModelWorkspaceError(error instanceof Error ? error.message : 'Не удалось загрузить модельные реестры')
      return []
    } finally {
      setModelWorkspaceLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!selectedCaseId) {
      setDetail(null)
      setEvents([])
      setModelRegistries([])
      setModelComparisons([])
      return
    }
    void loadCaseBundle(selectedCaseId)
    void loadModelWorkspace(selectedCaseId)
  }, [loadCaseBundle, loadModelWorkspace, selectedCaseId])

  useEffect(() => {
    if (!detail?.atoms.length) {
      setSelectedAtomId(null)
      return
    }
    if (!selectedAtomId || !detail.atoms.some((atom) => atom.id === selectedAtomId)) {
      setSelectedAtomId(detail.atoms[0].id)
    }
  }, [detail, selectedAtomId])

  useEffect(() => {
    const available = new Set((detail?.atoms ?? []).map((atom) => atom.id))
    setSelectedAtomIds((current) => current.filter((id) => available.has(id)))
  }, [detail])

  const caseCountsByStatus = useMemo(() => {
    return cases.reduce<Record<string, number>>((accumulator, current) => {
      const stage = current.status === 'archived' ? 'archived' : current.workflowStage
      accumulator[stage] = (accumulator[stage] ?? 0) + 1
      return accumulator
    }, {})
  }, [cases])

  const caseStatusOptions = useMemo(() => {
    const dynamic = compactOptions(Object.keys(caseCountsByStatus))
    return CASE_STATUS_ORDER.filter((status) => status === 'all' || dynamic.includes(status)).concat(
      dynamic.filter((status) => !CASE_STATUS_ORDER.includes(status))
    )
  }, [caseCountsByStatus])

  const filteredCases = useMemo(() => {
    const query = caseQuery.trim().toLowerCase()
    return cases.filter((item) => {
      const stage = item.status === 'archived' ? 'archived' : item.workflowStage
      const matchesStatus = caseStatusFilter === 'all' || stage === caseStatusFilter
      if (!matchesStatus) return false
      if (!query) return true
      const haystack = [
        item.code,
        item.title,
        item.productMasked,
        item.contractMasked,
        item.ownerName ?? '',
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [caseQuery, caseStatusFilter, cases])

  const metrics = useMemo(() => {
    const totalCases = cases.length
    const activeCases = cases.filter((item) => !['done', 'archived'].includes(item.status)).length
    const casesNeedingAtomization = cases.filter(caseNeedsAtomization).length
    const atomizedCases = cases.filter((item) => item.atomsTotal > 0).length
    const atomsTotal = cases.reduce((sum, item) => sum + item.atomsTotal, 0)
    const alphaPassed = cases.reduce((sum, item) => sum + item.alphaPassed, 0)
    const commissionPassed = cases.reduce((sum, item) => sum + item.commissionPassed, 0)
    return {
      totalCases,
      activeCases,
      casesNeedingAtomization,
      atomizedCases,
      atomsTotal,
      alphaPassed,
      commissionPassed,
    }
  }, [cases])

  const assignmentRangeDays = useMemo(
    () => Math.max(1, Math.min(92, inclusiveDateRangeDays(assignmentRangeStart, assignmentRangeEnd))),
    [assignmentRangeEnd, assignmentRangeStart]
  )
  const assignmentDates = useMemo(
    () => Array.from({ length: assignmentRangeDays }, (_, index) => shiftISODate(assignmentRangeStart, index)),
    [assignmentRangeDays, assignmentRangeStart]
  )
  const assignmentTeam = useMemo(
    () => team.filter((member) => member.is_active).sort((left, right) => left.full_name.localeCompare(right.full_name, 'ru')),
    [team]
  )
  const assignmentsByCell = useMemo(() => {
    const result = new Map<string, AuditAssignment[]>()
    for (const assignment of assignments) {
      const key = `${assignment.scheduled_date}:${assignment.assignee_id}`
      const cell = result.get(key) ?? []
      cell.push(assignment)
      result.set(key, cell)
    }
    return result
  }, [assignments])
  const assignmentByCaseId = useMemo(
    () => new Map(assignmentIndex.map((assignment) => [assignment.case_id, assignment])),
    [assignmentIndex]
  )
  const assignmentTargetMember = useMemo(
    () => team.find((member) => member.user_id === assignmentTargetUserId) ?? null,
    [assignmentTargetUserId, team]
  )
  const assignmentFilteredCases = useMemo(() => {
    const query = assignmentQuery.trim().toLowerCase()
    if (!query) return cases
    return cases.filter((item) => [item.code, item.title, item.productMasked, item.contractMasked]
      .join(' ')
      .toLowerCase()
      .includes(query))
  }, [assignmentQuery, cases])

  const selectedCaseSummary = useMemo(
    () => detail ?? cases.find((item) => item.id === selectedCaseId) ?? null,
    [cases, detail, selectedCaseId]
  )
  const canEditSelectedAtoms = Boolean(
    selectedCaseSummary &&
      selectedCaseSummary.status !== 'archived' &&
      (canManage || selectedCaseSummary.responsibleUserId === user?.id)
  )
  const workingAtomRegistryExists = (detail?.atomsTotal ?? 0) > 0
  const aiEligibleDocuments = useMemo(
    () => documents.filter((document) => {
      if (document.kind !== 'technical_spec') return false
      const contentType = document.content_type.toLowerCase()
      if (
        contentType === 'application/pdf'
        || contentType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      ) return true
      const filename = document.original_filename.toLowerCase()
      return filename.endsWith('.pdf') || filename.endsWith('.docx')
    }),
    [documents]
  )
  const selectedAIAtomizationSkill = useMemo(
    () => aiAtomizationSkills.find((skill) => skill.id === aiSelectedSkillId) ?? null,
    [aiAtomizationSkills, aiSelectedSkillId]
  )
  const isCanonicalSkill = selectedAIAtomizationSkill?.package_format === 'trusted_skill_archive'
  const canonicalEligibleDocuments = useMemo(
    () => aiEligibleDocuments.filter((document) => (
      document.content_type.includes('wordprocessingml')
      || document.original_filename.toLowerCase().endsWith('.docx')
    )),
    [aiEligibleDocuments]
  )
  const usedCanonicalModelLanes = useMemo(() => {
    if (!canonicalRun) return new Set<string>()
    return new Set(
      modelRegistries
        .filter((registry) => registry.canonical_run_id === canonicalRun.id)
        .map((registry) => `${registry.provider_config_id}:${registry.provider_config_version}:${registry.model_name}`)
    )
  }, [canonicalRun, modelRegistries])

  useEffect(() => {
    if (!isCanonicalSkill) return
    if (canonicalEligibleDocuments.some((document) => document.id === aiSelectedDocumentId)) return
    setAiSelectedDocumentId(canonicalEligibleDocuments[0]?.id ?? '')
    setCanonicalRun(null)
    setCanonicalAtomizationPreview(null)
    setAiTransferConfirmed(false)
    setAiAttempt(null)
    setAiDrafts([])
  }, [aiSelectedDocumentId, canonicalEligibleDocuments, isCanonicalSkill])

  useEffect(() => {
    if (
      !aiAtomizationDialogOpen
      || !selectedCaseId
      || !canonicalRun
      || !['queued', 'running', 'atomization_queued', 'atomizing'].includes(canonicalRun.status)
    ) return
    let cancelled = false
    const timer = window.setInterval(() => {
      void api.get<AuditTZRun>(`/api/audit/cases/${selectedCaseId}/canonical-preflight/runs/${canonicalRun.id}`)
        .then((result) => {
          if (!cancelled) setCanonicalRun(result)
        })
        .catch((error: unknown) => {
          if (!cancelled) setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось обновить состояние runtime')
        })
    }, 1200)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [aiAtomizationDialogOpen, canonicalRun, selectedCaseId])

  useEffect(() => {
    if (
      !aiAtomizationDialogOpen
      || !selectedCaseId
      || !(
        canonicalRun?.status === 'preflight_pass'
        || (canonicalRun?.status === 'draft_ready' && aiPreparingNextModel)
        || (canonicalRun?.status === 'committed' && aiPreparingNextModel)
        || (
          canonicalRun?.status === 'failed'
          && canonicalRun.current_phase === 'atomization_failed'
          && canonicalRun.source_unit_count > 0
        )
      )
      || !aiSelectedProviderId
      || canonicalAtomizationPreview
    ) return
    let cancelled = false
    void api.get<AuditTZAtomizationPreview>(
      `/api/audit/cases/${selectedCaseId}/canonical-preflight/runs/${canonicalRun.id}/atomization-preview`,
      { provider_id: aiSelectedProviderId }
    )
      .then((result) => {
        if (!cancelled) setCanonicalAtomizationPreview(result)
      })
      .catch((error: unknown) => {
        if (!cancelled) setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось подготовить передачу ИИ')
      })
    return () => {
      cancelled = true
    }
  }, [aiAtomizationDialogOpen, aiPreparingNextModel, aiSelectedProviderId, canonicalAtomizationPreview, canonicalRun, selectedCaseId])

  useEffect(() => {
    if (
      !aiAtomizationDialogOpen
      || !selectedCaseId
      || canonicalRun?.status !== 'draft_ready'
      || aiPreparingNextModel
      || aiAttempt
    ) return
    let cancelled = false
    let loading = false
    const loadDraft = () => {
      if (loading) return
      loading = true
      void api.get<AuditAIAtomizationAttempt>(`/api/audit/cases/${selectedCaseId}/canonical-preflight/runs/${canonicalRun.id}/attempt`)
        .then((result) => {
          if (cancelled) return
          setAiAttempt(result)
          setAiSelectedProviderId(result.provider_config_id)
          setAiDrafts(result.drafts.map((draft) => ({ ...draft, included: true })))
          setAiAtomizationError(null)
        })
        .catch((error: unknown) => {
          if (!cancelled) setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось загрузить черновик атомов')
        })
        .finally(() => {
          loading = false
        })
    }
    loadDraft()
    const timer = window.setInterval(loadDraft, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [aiAtomizationDialogOpen, aiAttempt, aiPreparingNextModel, canonicalRun, selectedCaseId])

  const atomStatusOptions = useMemo(() => {
    const dynamic = compactOptions(detail?.atoms.map((atom) => atom.status) ?? [])
    return ATOM_STATUS_ORDER.filter((status) => status === 'all' || dynamic.includes(status)).concat(
      dynamic.filter((status) => !ATOM_STATUS_ORDER.includes(status))
    )
  }, [detail])

  const atomObjectTypeOptions = useMemo(
    () => compactOptions(detail?.atoms.map((atom) => atom.objectType).filter((value) => value !== '—') ?? []),
    [detail]
  )
  const atomWorkTypeOptions = useMemo(
    () => compactOptions(detail?.atoms.map((atom) => atom.workType).filter((value) => value !== '—') ?? []),
    [detail]
  )

  const filteredAtoms = useMemo(() => {
    const query = atomQuery.trim().toLowerCase()
    return (detail?.atoms ?? []).filter((atom) => {
      if (atomStatusFilter !== 'all' && atom.status !== atomStatusFilter) return false
      if (atomObjectTypeFilter !== 'all' && atom.objectType !== atomObjectTypeFilter) return false
      if (atomWorkTypeFilter !== 'all' && atom.workType !== atomWorkTypeFilter) return false
      if (!query) return true
      return [
        atom.itemCode,
        atom.title,
        atom.digitalProduct,
        atom.objectType,
        atom.workType,
        atom.sourceClause,
        atom.legacyAlphaRef ?? '',
        atom.commissionRef ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(query)
    })
  }, [atomObjectTypeFilter, atomQuery, atomStatusFilter, atomWorkTypeFilter, detail])

  const selectedAtom = useMemo(
    () => detail?.atoms.find((atom) => atom.id === selectedAtomId) ?? null,
    [detail, selectedAtomId]
  )

  const caseFormDirty = useMemo(
    () => serializeFormState(caseForm) !== serializeFormState(caseFormInitial),
    [caseForm, caseFormInitial]
  )
  const atomFormDirty = useMemo(
    () => serializeFormState(atomForm) !== serializeFormState(atomFormInitial),
    [atomForm, atomFormInitial]
  )
  const importDirty = Boolean(importFile || importPreview)
  const documentDirty = documentFiles.length > 0 || Boolean(documentProduct.trim())
  const materialDirty = materialFiles.length > 0 || Boolean(materialDisplayName.trim())
  const deleteCaseDirty = Boolean(deleteCaseConfirmation.trim() || deleteCaseReason.trim())
  const aiAtomizationDirty = !isCanonicalSkill && Boolean(
    aiContractIdentifiers.trim() || aiPrivacyPreview
  ) || Boolean(
    (aiAttempt && aiAttempt.status === 'draft_ready' && !isCanonicalSkill) || aiTransferConfirmed
  )
  const assignmentDirty = useMemo(
    () => [...assignmentCaseIds].sort().join(',') !== [...assignmentInitialCaseIds].sort().join(','),
    [assignmentCaseIds, assignmentInitialCaseIds]
  )

  useEffect(() => {
    const hasUnsavedDialog =
      (caseDialogOpen && caseFormDirty) ||
      (atomDialogOpen && atomFormDirty) ||
      (importDialogOpen && importDirty) ||
      (documentDialogOpen && documentDirty) ||
      (materialDialogOpen && materialDirty) ||
      (deleteCaseDialogOpen && deleteCaseDirty) ||
      (aiAtomizationDialogOpen && aiAtomizationDirty) ||
      (assignmentDialogOpen && assignmentDirty)
    if (!hasUnsavedDialog) return

    const protectUnsavedChanges = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', protectUnsavedChanges)
    return () => window.removeEventListener('beforeunload', protectUnsavedChanges)
  }, [aiAtomizationDialogOpen, aiAtomizationDirty, assignmentDialogOpen, assignmentDirty, atomDialogOpen, atomFormDirty, caseDialogOpen, caseFormDirty, deleteCaseDialogOpen, deleteCaseDirty, documentDialogOpen, documentDirty, importDialogOpen, importDirty, materialDialogOpen, materialDirty])

  const setWorkspaceView = (view: WorkspaceView) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('view', view)
    if (view !== 'case') nextParams.delete('case')
    setSearchParams(nextParams)
  }

  const selectCase = (caseId: string) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('case', caseId)
    nextParams.set('view', 'case')
    setSearchParams(nextParams)
  }

  const requestDiscard = (message: string) => window.confirm(message)

  const changeAssignmentRangeStart = (value: string) => {
    const nextStart = value || localISODate()
    setAssignmentRangeStart(nextStart)
    const currentEndIsValid = inclusiveDateRangeDays(nextStart, assignmentRangeEnd) > 0
      && inclusiveDateRangeDays(nextStart, assignmentRangeEnd) <= 92
    if (!currentEndIsValid) {
      setAssignmentRangeEnd(shiftISODate(nextStart, assignmentRangeDays - 1))
    }
  }

  const changeAssignmentRangeEnd = (value: string) => {
    const requestedEnd = value || assignmentRangeStart
    if (inclusiveDateRangeDays(assignmentRangeStart, requestedEnd) < 1) {
      setAssignmentRangeEnd(assignmentRangeStart)
      return
    }
    setAssignmentRangeEnd(
      inclusiveDateRangeDays(assignmentRangeStart, requestedEnd) > 92
        ? shiftISODate(assignmentRangeStart, 91)
        : requestedEnd
    )
  }

  const shiftAssignmentRange = (days: number) => {
    setAssignmentRangeStart((current) => shiftISODate(current, days))
    setAssignmentRangeEnd((current) => shiftISODate(current, days))
  }

  const resetAssignmentRange = () => {
    const today = localISODate()
    setAssignmentRangeStart(today)
    setAssignmentRangeEnd(shiftISODate(today, 13))
  }

  const closeCaseDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    if (caseSaving) return
    if (caseFormDirty && !requestDiscard('Форма аудита изменена. Закрыть и потерять несохраненные правки?')) return
    setCaseDialogOpen(false)
    if (reason !== 'cancel') {
      setCaseForm(EMPTY_CASE_FORM)
      setCaseFormInitial(EMPTY_CASE_FORM)
    }
  }

  const closeAtomDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    if (atomSaving) return
    if (atomFormDirty && !requestDiscard('Форма атома изменена. Закрыть и потерять несохраненные правки?')) return
    setAtomDialogOpen(false)
    setEditingAtomId(null)
    if (reason !== 'cancel') {
      setAtomForm(EMPTY_ATOM_FORM)
      setAtomFormInitial(EMPTY_ATOM_FORM)
    }
  }

  const closeImportDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    void reason
    if (importPreviewing || importCommitting) return
    if (importDirty && !requestDiscard('Импорт еще не завершен. Закрыть окно и потерять загруженный файл?')) return
    setImportDialogOpen(false)
    setImportFile(null)
    setImportPreview(null)
    setImportChecksum(null)
    setImportError(null)
    setImportTargetCaseId(null)
  }

  const closeDocumentDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    void reason
    if (documentUploading) return
    if (documentDirty && !requestDiscard('Документы еще не загружены. Закрыть окно и потерять выбранные файлы?')) return
    setDocumentDialogOpen(false)
    setDocumentFiles([])
    setDocumentProduct('')
  }

  const closeMaterialDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    void reason
    if (materialUploading) return
    if (materialDirty && !requestDiscard('Материалы еще не загружены. Закрыть окно и потерять выбранные файлы?')) return
    setMaterialDialogOpen(false)
    setMaterialFiles([])
    setMaterialKind('other')
    setMaterialDisplayName('')
  }

  const closeDeleteCaseDialog = (reason: 'escape' | 'backdrop' | 'close-button' | 'cancel') => {
    void reason
    if (deleteCaseBusy) return
    if (deleteCaseDirty && !requestDiscard('Удаление не выполнено. Закрыть окно?')) return
    setDeleteCaseDialogOpen(false)
    setDeleteCaseConfirmation('')
    setDeleteCaseReason('')
  }

  const resetAIAtomizationDialog = () => {
    setAiAtomizationDialogOpen(false)
    setAiAtomizationSkills([])
    setAiSelectedSkillId('')
    setAiSelectedDocumentId('')
    setAiContractIdentifiers('')
    setAiPrivacyPreview(null)
    setAiTransferConfirmed(false)
    setAiAttempt(null)
    setCanonicalRun(null)
    setCanonicalAtomizationPreview(null)
    setAiSelectedProviderId('')
    setAiPreparingNextModel(false)
    setAiDrafts([])
    setAiAtomizationError(null)
  }

  const closeAIAtomizationDialog = () => {
    if (aiAtomizationBusy) return
    if (aiAtomizationDirty && !requestDiscard('Черновик ИИ еще не подтвержден. Закрыть окно и отказаться от текущей проверки?')) return
    resetAIAtomizationDialog()
  }

  const openAIAtomizationDialog = async () => {
    if (!selectedCaseId || !canEditSelectedAtoms) return
    if (aiEligibleDocuments.length === 0) {
      toast.error('Добавьте неизменяемое ТЗ в формате PDF или DOCX')
      setDetailTab('materials')
      return
    }
    setAiAtomizationDialogOpen(true)
    setAiSelectedDocumentId(aiEligibleDocuments[0].id)
    setAiSelectedSkillId('')
    setAiContractIdentifiers('')
    setAiPrivacyPreview(null)
    setAiTransferConfirmed(false)
    setAiAttempt(null)
    setCanonicalRun(null)
    setCanonicalAtomizationPreview(null)
    setAiSelectedProviderId('')
    setAiPreparingNextModel(false)
    setAiDrafts([])
    setAiAtomizationError(null)
    setAiAtomizationBusy(true)
    try {
      const [result, providerResult, registryResult] = await Promise.all([
        api.get<AuditAtomizationSkillList>('/api/audit/ai-atomization/skills'),
        api.get<AuditAIProviderOptionList>('/api/audit/ai-providers'),
        api.get<AuditAIModelRegistryList>(`/api/audit/cases/${selectedCaseId}/model-registries`),
      ])
      const selectedSkill = (
        canonicalEligibleDocuments.length > 0
          ? result.items.find((skill) => skill.package_format === 'trusted_skill_archive')
          : null
      ) ?? result.items[0]
      const selectedDocument = selectedSkill?.package_format === 'trusted_skill_archive'
        ? canonicalEligibleDocuments[0]
        : aiEligibleDocuments[0]
      setAiAtomizationSkills(result.items)
      setAiProviders(providerResult.items)
      setModelRegistries(registryResult.items)
      setAiSelectedSkillId(selectedSkill?.id ?? '')
      setAiSelectedDocumentId(selectedDocument?.id ?? '')
      let nextProvider: AuditAIProviderOption | undefined = providerResult.items[0]
      let nextProviderError: string | null = null
      if (result.items.length === 0) {
        setAiAtomizationError('Администратор еще не установил и не активировал skill атомизации')
      } else if (providerResult.items.length === 0) {
        setAiAtomizationError('Нет проверенных активных ИИ-подключений')
      } else if (selectedSkill?.package_format === 'trusted_skill_archive') {
        const runs = await api.get<{ items: AuditTZRun[] }>(`/api/audit/cases/${selectedCaseId}/canonical-preflight/runs`)
        const resumableRun = runs.items.find((run) => (
          run.document_id === selectedDocument?.id
          && run.skill_version_id === selectedSkill.id
        ))
        if (resumableRun) {
          setCanonicalRun(resumableRun)
          const runRegistries = registryResult.items.filter((registry) => registry.canonical_run_id === resumableRun.id)
          const usedLanes = new Set(runRegistries.map((registry) => `${registry.provider_config_id}:${registry.provider_config_version}:${registry.model_name}`))
          const unusedProvider = providerResult.items.find((provider) => !usedLanes.has(`${provider.id}:${provider.config_version}:${provider.model_name}`))
          if (runRegistries.length > 0 && ['draft_ready', 'committed'].includes(resumableRun.status)) {
            setAiPreparingNextModel(true)
            nextProvider = unusedProvider
            if (!unusedProvider) {
              nextProviderError = 'Все проверенные ИИ-профили уже использованы для этого документа. Добавьте новый профиль или новую версию модели.'
            }
          }
        }
      }
      setAiSelectedProviderId(nextProvider?.id ?? '')
      if (nextProviderError) setAiAtomizationError(nextProviderError)
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось загрузить skills атомизации')
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const updateAIAtomDraft = <K extends keyof EditableAIAtomDraft>(
    draftId: string,
    field: K,
    value: EditableAIAtomDraft[K]
  ) => {
    setAiDrafts((current) => current.map((draft) => (
      draft.id === draftId ? { ...draft, [field]: value } : draft
    )))
  }

  const contractIdentifierList = () => (
    aiContractIdentifiers
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
  )

  const invalidateAIPrivacyPreview = () => {
    setAiPrivacyPreview(null)
    setAiTransferConfirmed(false)
    setCanonicalRun(null)
    setCanonicalAtomizationPreview(null)
    setAiAttempt(null)
    setAiDrafts([])
  }

  const startCanonicalPreflight = async () => {
    if (!selectedCaseId || !aiSelectedDocumentId || !aiSelectedSkillId || aiAtomizationBusy) return
    setAiAtomizationBusy(true)
    setAiAtomizationError(null)
    try {
      const result = await api.post<AuditTZRun>(`/api/audit/cases/${selectedCaseId}/canonical-preflight/runs`, {
        request_id: window.crypto.randomUUID(),
        document_id: aiSelectedDocumentId,
        skill_version_id: aiSelectedSkillId,
      })
      setCanonicalRun(result)
      setCanonicalAtomizationPreview(null)
      setAiTransferConfirmed(false)
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось поставить canonical preflight в очередь')
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const startCanonicalAtomization = async () => {
    if (!selectedCaseId || !canonicalRun || !canonicalAtomizationPreview || !aiSelectedProviderId || !aiTransferConfirmed || aiAtomizationBusy) return
    setAiAtomizationBusy(true)
    setAiAtomizationError(null)
    try {
      const result = await api.post<AuditTZRun>(`/api/audit/cases/${selectedCaseId}/canonical-preflight/runs/${canonicalRun.id}/atomization`, {
        request_id: window.crypto.randomUUID(),
        provider_id: aiSelectedProviderId,
        consent_token: canonicalAtomizationPreview.consent_token,
        data_transfer_confirmed: true,
      })
      setCanonicalRun(result)
      setAiPreparingNextModel(false)
      setAiTransferConfirmed(false)
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось запустить атомизацию ТЗ')
      setCanonicalAtomizationPreview(null)
      setAiTransferConfirmed(false)
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const previewAIAtomizationPrivacy = async () => {
    if (!selectedCaseId || !aiSelectedDocumentId || !aiSelectedSkillId || aiAtomizationBusy) return
    const contractIdentifiers = contractIdentifierList()
    if (contractIdentifiers.length === 0) {
      setAiAtomizationError('Укажите номер договора и, при необходимости, варианты его написания')
      return
    }
    setAiAtomizationBusy(true)
    setAiAtomizationError(null)
    setAiPrivacyPreview(null)
    setAiTransferConfirmed(false)
    try {
      const result = await api.post<AuditAIPrivacyPreview>(`/api/audit/cases/${selectedCaseId}/ai-atomization/privacy-preview`, {
        document_id: aiSelectedDocumentId,
        skill_version_id: aiSelectedSkillId,
        contract_identifiers: contractIdentifiers,
      })
      setAiPrivacyPreview(result)
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось проверить обезличивание')
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const generateAIAtomDrafts = async () => {
    if (!selectedCaseId || !aiSelectedDocumentId || !aiSelectedSkillId || !aiTransferConfirmed || !aiPrivacyPreview) return
    const contractIdentifiers = contractIdentifierList()
    setAiAtomizationBusy(true)
    setAiAtomizationError(null)
    try {
      const result = await api.post<AuditAIAtomizationAttempt>(`/api/audit/cases/${selectedCaseId}/ai-atomization/attempts`, {
        document_id: aiSelectedDocumentId,
        skill_version_id: aiSelectedSkillId,
        request_id: window.crypto.randomUUID(),
        privacy_token: aiPrivacyPreview.privacy_token,
        contract_identifiers: contractIdentifiers,
        data_transfer_confirmed: true,
      })
      setAiAttempt(result)
      setAiDrafts(result.drafts.map((draft) => ({ ...draft, included: true })))
      if (result.warnings.length > 0) {
        toast(`${result.warnings.length} предупреждений требуют проверки`)
      }
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'ИИ не смог сформировать черновик атомов')
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const commitAIAtomDrafts = async () => {
    if (!selectedCaseId || !aiAttempt || aiAtomizationBusy) return
    const selectedDrafts = aiDrafts.filter((draft) => draft.included)
    if (selectedDrafts.length === 0) {
      setAiAtomizationError('Выберите хотя бы один атом')
      return
    }
    const invalidDraft = selectedDrafts.find((draft) => !draft.title.trim() || !draft.digital_product.trim())
    if (invalidDraft) {
      setAiAtomizationError('У каждого выбранного атома должны быть заполнены название и цифровой продукт')
      return
    }
    setAiAtomizationBusy(true)
    setAiAtomizationError(null)
    try {
      const result = await api.post<AuditAIAtomizationCommitResult>(`/api/audit/cases/${selectedCaseId}/ai-atomization/attempts/${aiAttempt.id}/commit`, {
        request_id: window.crypto.randomUUID(),
        expected_config_version: aiAttempt.config_version,
        drafts: aiDrafts.map((draft) => ({
          id: draft.id,
          included: draft.included,
          title: draft.title,
          digital_product: draft.digital_product,
          work_type: draft.work_type || null,
          object_type: draft.object_type || null,
          notes: draft.notes || null,
        })),
      })
      resetAIAtomizationDialog()
      setDetailTab('atoms')
      await Promise.all([loadCases(), loadCaseBundle(selectedCaseId)])
      toast.success(`Создано черновиков атомов: ${result.atoms_created}`)
    } catch (error) {
      setAiAtomizationError(error instanceof Error ? error.message : 'Не удалось подтвердить атомы')
    } finally {
      setAiAtomizationBusy(false)
    }
  }

  const prepareNextCanonicalModel = () => {
    const usedLanes = new Set(
      modelRegistries
        .filter((item) => item.canonical_run_id === canonicalRun?.id)
        .map((item) => `${item.provider_config_id}:${item.provider_config_version}:${item.model_name}`)
    )
    const nextProvider = aiProviders.find((item) => !usedLanes.has(`${item.id}:${item.config_version}:${item.model_name}`))
    setAiAttempt(null)
    setAiDrafts([])
    setAiSelectedProviderId(nextProvider?.id ?? '')
    setCanonicalAtomizationPreview(null)
    setAiTransferConfirmed(false)
    setAiPreparingNextModel(true)
    setAiAtomizationError(nextProvider ? null : 'Нет проверенного ИИ-подключения для запуска')
  }

  const finishCanonicalModelResult = async () => {
    if (!selectedCaseId) return
    await loadModelWorkspace(selectedCaseId)
    resetAIAtomizationDialog()
    toast.success('Результат модели сохранен отдельно')
  }

  const toggleModelRegistry = (registryId: string) => {
    setSelectedModelRegistryIds((current) => current.includes(registryId)
      ? current.filter((id) => id !== registryId)
      : [...current, registryId])
  }

  const showModelComparison = (comparison: AuditAIModelComparison) => {
    setModelComparison(comparison)
    setComparisonDrafts(comparison.drafts.map((draft) => ({
      ...draft,
      included: draft.review_status !== 'rejected',
    })))
    setComparisonError(null)
    setComparisonDialogOpen(true)
  }

  const runModelComparison = async () => {
    if (!selectedCaseId || selectedModelRegistryIds.length < 2 || comparisonBusy) return
    setComparisonBusy(true)
    setComparisonError(null)
    try {
      const result = await api.post<AuditAIModelComparison>(`/api/audit/cases/${selectedCaseId}/model-comparisons`, {
        registry_ids: selectedModelRegistryIds,
      })
      setModelComparisons((current) => [result, ...current.filter((item) => item.id !== result.id)])
      showModelComparison(result)
    } catch (error) {
      setModelWorkspaceError(error instanceof Error ? error.message : 'Не удалось сравнить модельные реестры')
    } finally {
      setComparisonBusy(false)
    }
  }

  const updateComparisonDraft = <K extends keyof EditableAIModelComparisonDraft>(
    draftId: string,
    field: K,
    value: EditableAIModelComparisonDraft[K]
  ) => {
    setComparisonDrafts((current) => current.map((draft) => (
      draft.id === draftId ? { ...draft, [field]: value } : draft
    )))
  }

  const closeComparisonDialog = () => {
    if (comparisonBusy) return
    setComparisonDialogOpen(false)
    setModelComparison(null)
    setComparisonDrafts([])
    setComparisonError(null)
  }

  const commitModelComparison = async () => {
    if (!selectedCaseId || !modelComparison || comparisonBusy) return
    const included = comparisonDrafts.filter((draft) => draft.included)
    if (included.length === 0) {
      setComparisonError('Выберите хотя бы один атом генерального реестра')
      return
    }
    if (included.some((draft) => !draft.title.trim() || !draft.digital_product.trim())) {
      setComparisonError('У каждого выбранного атома должны быть название и цифровой продукт')
      return
    }
    setComparisonBusy(true)
    setComparisonError(null)
    try {
      const result = await api.post<AuditAIModelComparisonCommitResult>(
        `/api/audit/cases/${selectedCaseId}/model-comparisons/${modelComparison.id}/commit`,
        {
          request_id: window.crypto.randomUUID(),
          expected_config_version: modelComparison.config_version,
          drafts: comparisonDrafts.map((draft) => ({
            id: draft.id,
            included: draft.included,
            title: draft.title,
            digital_product: draft.digital_product,
            work_type: draft.work_type || null,
            object_type: draft.object_type || null,
            notes: draft.notes || null,
          })),
        }
      )
      setComparisonDialogOpen(false)
      setModelComparison(null)
      setComparisonDrafts([])
      await Promise.all([loadCases(), loadCaseBundle(selectedCaseId), loadModelWorkspace(selectedCaseId)])
      setDetailTab('atoms')
      toast.success(`В генеральный реестр записано атомов: ${result.atoms_created}`)
    } catch (error) {
      setComparisonError(error instanceof Error ? error.message : 'Не удалось опубликовать генеральный реестр')
    } finally {
      setComparisonBusy(false)
    }
  }

  const openAssignmentCell = (scheduledDate: string, assigneeId: string) => {
    const currentIds = (assignmentsByCell.get(`${scheduledDate}:${assigneeId}`) ?? [])
      .map((item) => item.case_id)
    setAssignmentTargetDate(scheduledDate)
    setAssignmentTargetUserId(assigneeId)
    setAssignmentInitialCaseIds(currentIds)
    setAssignmentCaseIds(currentIds)
    setAssignmentTransferCaseIds([])
    setAssignmentQuery('')
    setAssignmentDialogOpen(true)
  }

  const resetAssignmentDialog = () => {
    setAssignmentDialogOpen(false)
    setAssignmentTargetDate('')
    setAssignmentTargetUserId('')
    setAssignmentInitialCaseIds([])
    setAssignmentCaseIds([])
    setAssignmentTransferCaseIds([])
    setAssignmentQuery('')
  }

  const closeAssignmentDialog = () => {
    if (assignmentSaving) return
    if (assignmentDirty && !requestDiscard('Назначения изменены. Закрыть окно без сохранения?')) return
    resetAssignmentDialog()
  }

  const toggleAssignmentCase = (caseId: string, checked: boolean) => {
    const existingAssignment = assignmentByCaseId.get(caseId)
    const assignedElsewhere = Boolean(
      existingAssignment
      && (
        existingAssignment.assignee_id !== assignmentTargetUserId
        || existingAssignment.scheduled_date !== assignmentTargetDate
      )
    )
    if (checked && existingAssignment && assignedElsewhere) {
      const confirmed = window.confirm(
        `${existingAssignment.case_number} уже назначен: ${existingAssignment.assignee_name}, ${formatDateOnly(existingAssignment.scheduled_date)}. Передать договор в выбранную ячейку?`
      )
      if (!confirmed) return
      setAssignmentTransferCaseIds((current) => Array.from(new Set([...current, caseId])))
    } else if (!checked) {
      setAssignmentTransferCaseIds((current) => current.filter((item) => item !== caseId))
    }
    setAssignmentCaseIds((current) => (
      checked
        ? Array.from(new Set([...current, caseId]))
        : current.filter((item) => item !== caseId)
    ))
  }

  const saveAssignmentCell = async () => {
    if (!assignmentTargetDate || !assignmentTargetUserId || assignmentSaving) return
    setAssignmentSaving(true)
    try {
      await api.put<AuditAssignmentList>('/api/audit/assignments/cell', {
        scheduled_date: assignmentTargetDate,
        assignee_id: assignmentTargetUserId,
        expected_case_ids: assignmentInitialCaseIds,
        case_ids: assignmentCaseIds,
        transfer_case_ids: assignmentTransferCaseIds,
      })
      resetAssignmentDialog()
      await Promise.all([loadAssignments(), loadCases()])
      toast.success(assignmentTransferCaseIds.length > 0 ? 'Назначения сохранены, договоры переданы' : 'Назначения сохранены')
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          const refreshed = await loadAssignments()
          const freshCaseIds = refreshed
            .filter((item) => (
              item.scheduled_date === assignmentTargetDate
              && item.assignee_id === assignmentTargetUserId
            ))
            .map((item) => item.case_id)
          setAssignmentInitialCaseIds(freshCaseIds)
          setAssignmentCaseIds(freshCaseIds)
          setAssignmentTransferCaseIds([])
          toast.error('Ячейка была изменена другим пользователем. Данные обновлены; проверьте выбор и сохраните повторно.')
        } catch {
          toast.error(error.message)
        }
        return
      }
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить назначения')
    } finally {
      setAssignmentSaving(false)
    }
  }

  const openResponsibleDialog = (auditCase: NormalizedAuditCaseSummary) => {
    setResponsibleCaseId(auditCase.id)
    setResponsibleUserId(auditCase.responsibleUserId ?? '')
    setResponsibleDialogOpen(true)
  }

  const openCreateCaseDialog = () => {
    setCaseDialogMode('create')
    setCaseForm(EMPTY_CASE_FORM)
    setCaseFormInitial(EMPTY_CASE_FORM)
    setCaseDialogOpen(true)
  }

  const openImportDialog = (targetCaseId: string | null = null) => {
    setImportTargetCaseId(targetCaseId)
    setImportFile(null)
    setImportPreview(null)
    setImportChecksum(null)
    setImportError(null)
    setImportDialogOpen(true)
  }

  const openEditCaseDialog = () => {
    if (!detail) return
    const nextForm = emptyCaseFormFromDetail(detail)
    setCaseDialogMode('edit')
    setCaseForm(nextForm)
    setCaseFormInitial(nextForm)
    setCaseDialogOpen(true)
  }

  const openCreateAtomDialog = () => {
    setAtomDialogMode('create')
    setEditingAtomId(null)
    const nextForm = {
      ...EMPTY_ATOM_FORM,
      digitalProduct: detail?.productMasked === '—' ? '' : detail?.productMasked ?? '',
    }
    setAtomForm(nextForm)
    setAtomFormInitial(nextForm)
    setAtomDialogOpen(true)
  }

  const openEditAtomDialog = (atom: NormalizedAuditAtom) => {
    const nextForm = emptyAtomFormFromAtom(atom)
    setAtomDialogMode('edit')
    setEditingAtomId(atom.id)
    setAtomForm(nextForm)
    setAtomFormInitial(nextForm)
    setAtomDialogOpen(true)
  }

  const refreshSelected = async () => {
    const nextCases = await loadCases()
    if (!selectedCaseId) return
    const stillExists = nextCases.some((item) => item.id === selectedCaseId)
    if (stillExists) {
      await loadCaseBundle(selectedCaseId)
    }
  }

  const saveCase = async () => {
    if (!canManage) return
    if (!caseForm.title.trim()) {
      toast.error('Введите название аудита')
      return
    }
    if (!caseForm.productName.trim()) {
      toast.error('Укажите цифровой продукт')
      return
    }
    setCaseSaving(true)
    try {
      const basePayload: UnknownRecord = {
        title: caseForm.title.trim(),
        status: caseForm.status.trim() || 'draft',
        workflow_stage: caseForm.workflowStage,
        digital_product: caseForm.productName.trim(),
        notes: nullIfEmpty(caseForm.summary),
        contract_date: nullIfEmpty(caseForm.contractDate),
      }
      if (caseForm.contractReference.trim()) {
        basePayload.contract_reference = caseForm.contractReference.trim()
      }
      const payload =
        caseDialogMode === 'create'
          ? (basePayload as AuditCaseCreatePayload)
          : (basePayload as AuditCaseUpdatePayload)

      const response =
        caseDialogMode === 'create'
          ? await api.post<unknown>('/api/audit/cases', payload)
          : await api.patch<unknown>(`/api/audit/cases/${selectedCaseId}`, payload)

      const savedId =
        normalizeAuditCaseDetail(response)?.id ??
        normalizeAuditCaseSummary(response)?.id ??
        selectedCaseId
      const nextCases = await loadCases()
      if (savedId && nextCases.some((item) => item.id === savedId)) {
        const nextParams = new URLSearchParams(searchParams)
        nextParams.set('case', savedId)
        nextParams.set('view', 'case')
        setSearchParams(nextParams)
        await loadCaseBundle(savedId)
      }
      setCaseDialogOpen(false)
      setCaseForm(EMPTY_CASE_FORM)
      setCaseFormInitial(EMPTY_CASE_FORM)
      toast.success(caseDialogMode === 'create' ? 'Аудит создан' : 'Договор обновлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить аудит')
    } finally {
      setCaseSaving(false)
    }
  }

  const saveAtom = async () => {
    if (!canManage || !selectedCaseId) return
    if (!atomForm.title.trim()) {
      toast.error('Введите название атома')
      return
    }
    if (!atomForm.digitalProduct.trim()) {
      toast.error('Укажите цифровой продукт')
      return
    }
    setAtomSaving(true)
    try {
      const basePayload: UnknownRecord = {
        item_code: nullIfEmpty(atomForm.itemCode),
        title: atomForm.title.trim(),
        digital_product: atomForm.digitalProduct.trim(),
        object_type: nullIfEmpty(atomForm.objectType),
        work_type: nullIfEmpty(atomForm.workType),
        source_clause: nullIfEmpty(atomForm.sourceClause),
        state: atomForm.status.trim() || 'draft',
        alpha_result_raw: nullIfEmpty(atomForm.legacyAlphaRef),
        commission_result_raw: nullIfEmpty(atomForm.commissionRef),
        system_url: nullIfEmpty(atomForm.systemUrl),
        notes: nullIfEmpty(atomForm.notes),
      }
      const payload =
        atomDialogMode === 'create'
          ? (basePayload as AuditAtomCreatePayload)
          : (basePayload as AuditAtomUpdatePayload)

      const response =
        atomDialogMode === 'create'
          ? await api.post<unknown>(`/api/audit/cases/${selectedCaseId}/atoms`, payload)
          : await api.patch<unknown>(`/api/audit/cases/${selectedCaseId}/atoms/${editingAtomId}`, payload)

      const savedAtomId = normalizeAuditAtom(response)?.id ?? editingAtomId
      await Promise.all([loadCases(), loadCaseBundle(selectedCaseId)])
      if (savedAtomId) setSelectedAtomId(savedAtomId)
      setAtomDialogOpen(false)
      setEditingAtomId(null)
      setAtomForm(EMPTY_ATOM_FORM)
      setAtomFormInitial(EMPTY_ATOM_FORM)
      toast.success(atomDialogMode === 'create' ? 'Атом добавлен' : 'Атом обновлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить атом')
    } finally {
      setAtomSaving(false)
    }
  }

  const handleImportFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null
    setImportFile(nextFile)
    setImportPreview(null)
    setImportChecksum(null)
    setImportError(null)
  }

  const previewImport = async () => {
    if (!importFile || importPreviewing || importCommitting) return
    setImportPreviewing(true)
    setImportError(null)
    try {
      const checksum = await sha256(importFile)
      setImportChecksum(checksum)
      const formData = new FormData()
      formData.append('file', importFile)
      const endpoint = importTargetCaseId
        ? `/api/audit/cases/${importTargetCaseId}/imports/preview`
        : '/api/audit/imports/preview'
      const payload = await api.upload<unknown>(endpoint, formData)
      const preview = normalizeImportPreview(payload, checksum)
      if (!preview) throw new Error('Предпросмотр импорта не распознан')
      setImportPreview(preview)
      if (preview.hasErrors) {
        toast.error(`Найдено строк с ошибками: ${preview.errorRows}`)
      } else if (preview.warningRows > 0) {
        toast.success(`Файл готов: ${preview.validRows} строк, предупреждений: ${preview.warningRows}`)
      } else {
        toast.success(`Готово к импорту: ${preview.validRows} строк`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось проверить Excel'
      setImportError(message)
      toast.error(message)
    } finally {
      setImportPreviewing(false)
    }
  }

  const commitImport = async () => {
    if (!importFile || !importPreview || importPreview.hasErrors || importCommitting) return
    const expectedSha = importChecksum ?? importPreview.expectedSha256
    if (!expectedSha) {
      toast.error('Не удалось вычислить SHA-256 файла')
      return
    }
    setImportCommitting(true)
    setImportError(null)
    try {
      const targetCaseId = importTargetCaseId
      const formData = new FormData()
      formData.append('file', importFile)
      formData.append('expected_sha256', expectedSha)
      const endpoint = targetCaseId
        ? `/api/audit/cases/${targetCaseId}/imports/commit`
        : '/api/audit/imports/commit'
      const payload = await api.upload<unknown>(endpoint, formData)
      const createdCount = isRecord(payload) ? getNumber(payload, 'created_atom_count', 'created_count', 'imported_count', 'count') : null
      const alreadyCommitted = isRecord(payload) && payload.already_committed === true
      await Promise.all([
        loadCases(),
        targetCaseId ? loadCaseBundle(targetCaseId) : Promise.resolve(),
      ])
      setImportDialogOpen(false)
      setImportTargetCaseId(null)
      setImportFile(null)
      setImportPreview(null)
      setImportChecksum(null)
      setImportError(null)
      if (targetCaseId) setDetailTab('atoms')
      toast.success(
        alreadyCommitted
          ? 'Этот файл уже был импортирован. Дубли не созданы.'
          : createdCount
            ? `Импортировано строк: ${createdCount}`
            : 'Импорт завершен'
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось завершить импорт'
      setImportError(message)
      toast.error(message)
    } finally {
      setImportCommitting(false)
    }
  }

  const uploadDocuments = async () => {
    if (!canManage || documentFiles.length === 0 || documentUploading) return
    setDocumentUploading(true)
    try {
      const body = new FormData()
      documentFiles.forEach((file) => body.append('files', file))
      if (documentProduct.trim()) body.append('digital_product', documentProduct.trim())
      const result = await api.upload<AuditDocumentBatchResponse>('/api/audit/documents', body)
      const firstCaseId = result.items[0]?.case.id
      await loadCases()
      setDocumentDialogOpen(false)
      setDocumentFiles([])
      setDocumentProduct('')
      if (firstCaseId) selectCase(firstCaseId)
      toast.success(`Загружено документов: ${result.items.length}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить документы')
    } finally {
      setDocumentUploading(false)
    }
  }

  const uploadCaseMaterials = async () => {
    if (!selectedCaseId || !canEditSelectedAtoms || materialFiles.length === 0 || materialUploading) return
    if (materialDisplayName.trim() && materialFiles.length !== 1) {
      toast.error('Собственное название можно указать только для одного файла')
      return
    }
    setMaterialUploading(true)
    try {
      const body = new FormData()
      materialFiles.forEach((file) => body.append('files', file))
      body.append('kind', materialKind)
      if (materialDisplayName.trim()) body.append('display_name', materialDisplayName.trim())
      const uploaded = await api.upload<AuditDocument[]>(`/api/audit/cases/${selectedCaseId}/documents`, body)
      await Promise.all([loadCases(), loadCaseBundle(selectedCaseId)])
      setMaterialDialogOpen(false)
      setMaterialFiles([])
      setMaterialKind('other')
      setMaterialDisplayName('')
      setDetailTab('materials')
      toast.success(`Добавлено материалов: ${uploaded.length}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить материалы')
    } finally {
      setMaterialUploading(false)
    }
  }

  const deleteSelectedCase = async () => {
    if (!selectedCaseId || !selectedCaseSummary || !canManage || deleteCaseBusy) return
    setDeleteCaseBusy(true)
    try {
      const result = await api.delete<AuditCaseDeleteResponse>(`/api/audit/cases/${selectedCaseId}`, {
        confirmation_code: deleteCaseConfirmation,
        reason: deleteCaseReason.trim() || null,
      })
      setDeleteCaseDialogOpen(false)
      setDeleteCaseConfirmation('')
      setDeleteCaseReason('')
      setDetail(null)
      setDocuments([])
      setEvents([])
      const nextParams = new URLSearchParams(searchParams)
      nextParams.set('view', 'registry')
      nextParams.delete('case')
      setSearchParams(nextParams)
      await loadCases()
      toast.success(`${result.case_number} удален`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить договор')
    } finally {
      setDeleteCaseBusy(false)
    }
  }

  const downloadDocument = async (document: AuditDocument) => {
    try {
      const blob = await api.blob(`/api/audit/documents/${document.id}/content`)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = document.original_filename || document.display_name
      window.document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось скачать документ')
    }
  }

  const downloadAtomTemplate = async () => {
    if (!selectedCaseId) return
    try {
      const blob = await api.blob(`/api/audit/cases/${selectedCaseId}/atom-template`)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = `${selectedCaseSummary?.code ?? 'AUD'}-atoms-template.xlsx`
      window.document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось скачать Excel-шаблон')
    }
  }

  const downloadAtomExport = async () => {
    if (!selectedCaseId || user?.role !== 'admin') return
    try {
      const blob = await api.blob(`/api/audit/cases/${selectedCaseId}/atoms/export`)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = `${selectedCaseSummary?.code ?? 'AUD'}-general-atoms.xlsx`
      window.document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      toast.success('Генеральный реестр выгружен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось выгрузить генеральный реестр')
    }
  }

  const toggleAtomSelection = (atomId: string) => {
    setSelectedAtomIds((current) => current.includes(atomId)
      ? current.filter((id) => id !== atomId)
      : [...current, atomId])
  }

  const toggleAllFilteredAtoms = () => {
    const filteredIds = filteredAtoms.map((atom) => atom.id)
    const allSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedAtomIds.includes(id))
    setSelectedAtomIds((current) => allSelected
      ? current.filter((id) => !filteredIds.includes(id))
      : Array.from(new Set([...current, ...filteredIds])))
  }

  const updateSelectedAtomStatuses = async () => {
    if (!selectedCaseId || selectedAtomIds.length === 0 || bulkAtomBusy) return
    setBulkAtomBusy(true)
    try {
      const result = await api.patch<{ updated_count: number }>(`/api/audit/cases/${selectedCaseId}/atoms/bulk-status`, {
        atom_ids: selectedAtomIds,
        state: bulkAtomState,
      })
      setSelectedAtomIds([])
      await Promise.all([loadCases(), loadCaseBundle(selectedCaseId)])
      toast.success(`Обновлено атомов: ${result.updated_count}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить статус выбранных атомов')
    } finally {
      setBulkAtomBusy(false)
    }
  }

  const saveResponsible = async () => {
    if (!responsibleCaseId || responsibleSaving) return
    setResponsibleSaving(true)
    try {
      await api.patch(`/api/audit/cases/${responsibleCaseId}/responsible`, {
        user_id: responsibleUserId || null,
      })
      await Promise.all([loadCases(), loadCaseBundle(responsibleCaseId)])
      setResponsibleDialogOpen(false)
      toast.success(responsibleUserId ? 'Ответственный назначен' : 'Ответственный снят')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить ответственного')
    } finally {
      setResponsibleSaving(false)
    }
  }

  const addTeamMember = async () => {
    if (!newTeamUserId || teamSaving) return
    setTeamSaving(true)
    try {
      await api.post('/api/audit/team', { user_id: newTeamUserId, role: newTeamRole })
      await Promise.all([loadTeam(), loadTeamCandidates()])
      setNewTeamUserId('')
      toast.success('Сотрудник добавлен в команду аудита')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить сотрудника')
    } finally {
      setTeamSaving(false)
    }
  }

  const updateTeamRole = async (member: AuditTeamMember, role: AuditTeamRole) => {
    try {
      await api.patch(`/api/audit/team/${member.id}`, { role })
      await loadTeam()
      toast.success('Роль в команде обновлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить роль')
    }
  }

  const removeTeamMember = async (member: AuditTeamMember) => {
    if (!window.confirm(`Убрать ${member.full_name} из команды аудита?`)) return
    try {
      await api.delete(`/api/audit/team/${member.id}`)
      await Promise.all([loadTeam(), loadTeamCandidates()])
      toast.success('Сотрудник удален из команды аудита')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить сотрудника')
    }
  }

  const handleDetailTabKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    const tabs: DetailTab[] = ['materials', 'atoms', 'history']
    let nextIndex = currentIndex
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = tabs.length - 1
    else return
    event.preventDefault()
    setDetailTab(tabs[nextIndex])
    detailTabRefs.current[nextIndex]?.focus()
  }

  return (
    <div className="grid w-full max-w-none gap-4 xl:grid-cols-[224px_minmax(0,1fr)]">
      <div className="min-w-0 xl:sticky xl:top-4 xl:self-start">
        <div className="rounded-lg border border-border bg-surface p-2 shadow-sm">
          <div className="px-2 pb-2 pt-1">
            <h1 className="text-lg font-semibold text-foreground">Аудит</h1>
            <p className="mt-1 text-xs text-muted-foreground">ТЗ, договоры и атомы</p>
          </div>
          <nav className="flex gap-1 overflow-x-auto pb-1 xl:grid xl:grid-cols-1 xl:overflow-visible xl:pb-0" aria-label="Разделы аудита">
            {canManage ? (
              <button
                type="button"
                onClick={() => setDocumentDialogOpen(true)}
                className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-primary/30 bg-transparent px-3 text-sm font-medium text-primary transition hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 xl:min-w-0 xl:justify-start"
              >
                <FilePlus2 className="h-4 w-4 shrink-0" />
                <span>Новый документ</span>
              </button>
            ) : null}
            {([
              ['dashboard', 'Статистика', BarChart3],
              ['registry', 'Реестр', ClipboardList],
              ['assignments', 'Назначения', CalendarDays],
              ['team', 'Сотрудники', Users],
            ] as const).map(([view, label, Icon]) => (
              <button
                key={view}
                type="button"
                onClick={() => setWorkspaceView(view)}
                className={cn(
                  'inline-flex min-h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 xl:min-w-0 xl:justify-start',
                  workspaceView === view
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          {!canManage ? (
            <div className="mt-2 border-t border-border pt-2">
              <div className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm text-muted-foreground xl:justify-start">
                <Lock className="h-4 w-4" />
                Только просмотр
              </div>
            </div>
          ) : null}
        </div>
        {workspaceView === 'case' && selectedCaseSummary ? (
          <div className="mt-3 rounded-lg border border-border bg-surface p-2 shadow-sm">
            <div className="px-2 pb-2 pt-1">
              <div className="font-mono text-xs font-medium text-muted-foreground">{selectedCaseSummary.code}</div>
              <h2 className="mt-1 text-sm font-semibold text-foreground">Управление договором</h2>
              <p className={cn('mt-1 text-xs', atomizationSignal(selectedCaseSummary).toneClass)}>
                {atomizationSignal(selectedCaseSummary).label}
              </p>
            </div>

            <div role="tablist" aria-label="Разделы договора" className="grid grid-cols-3 gap-1 xl:grid-cols-1">
              {([
                ['materials', 'Материалы', FileText],
                ['atoms', 'Атомы', Boxes],
                ['history', 'История', History],
              ] as const).map(([tab, label, Icon], index) => {
                const active = detailTab === tab
                return (
                  <button
                    key={tab}
                    ref={(element) => {
                      detailTabRefs.current[index] = element
                    }}
                    id={`audit-tab-${tab}`}
                    role="tab"
                    aria-selected={active}
                    aria-controls={`audit-panel-${tab}`}
                    tabIndex={active ? 0 : -1}
                    type="button"
                    onClick={() => setDetailTab(tab)}
                    onKeyDown={(event) => handleDetailTabKeyDown(event, index)}
                    className={cn(
                      'inline-flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-md px-2 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 xl:justify-start xl:px-3 xl:text-sm',
                      active
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </button>
                )
              })}
            </div>

            {canEditSelectedAtoms ? (
              <div className="mt-2 grid gap-1 border-t border-border pt-2 sm:grid-cols-2 xl:grid-cols-1">
                <button type="button" onClick={() => void downloadAtomTemplate()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-foreground hover:bg-muted xl:justify-start">
                  <FileDown className="h-4 w-4" />
                  Скачать Excel-шаблон
                </button>
                <button type="button" onClick={() => openImportDialog(selectedCaseSummary.id)} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90 xl:justify-start">
                  <Upload className="h-4 w-4" />
                  Загрузить реестр атомов
                </button>
                <button type="button" onClick={() => void openAIAtomizationDialog()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-primary/30 px-3 text-sm font-medium text-primary hover:bg-primary/5 xl:justify-start">
                  <Sparkles className="h-4 w-4" />
                  Сформировать реестр с ИИ
                </button>
                <button type="button" onClick={openCreateAtomDialog} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-foreground hover:bg-muted xl:justify-start">
                  <Plus className="h-4 w-4" />
                  Добавить атом вручную
                </button>
                {user?.role === 'admin' && selectedCaseSummary.atomsTotal > 0 ? (
                  <button type="button" onClick={() => void downloadAtomExport()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-foreground hover:bg-muted xl:justify-start">
                    <Download className="h-4 w-4" />
                    Выгрузить генеральный реестр
                  </button>
                ) : null}
              </div>
            ) : null}

            {canManage ? (
              <div className="mt-2 grid gap-1 border-t border-border pt-2 sm:grid-cols-2 xl:grid-cols-1">
                <button type="button" onClick={() => openResponsibleDialog(selectedCaseSummary)} className="inline-flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-foreground hover:bg-muted xl:justify-start">
                  <UserPlus className="h-4 w-4 shrink-0" />
                  <span className="truncate">{selectedCaseSummary.responsibleName ?? 'Назначить ответственного'}</span>
                </button>
                <button type="button" onClick={openEditCaseDialog} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-foreground hover:bg-muted xl:justify-start">
                  <Pencil className="h-4 w-4" />
                  Редактировать договор
                </button>
                {selectedCaseSummary.status === 'archived' ? (
                  <button
                    type="button"
                    onClick={() => setDeleteCaseDialogOpen(true)}
                    className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-rose-700 hover:bg-rose-500/10 dark:text-rose-300 xl:justify-start"
                  >
                    <Trash2 className="h-4 w-4" />
                    Удалить договор
                  </button>
                ) : null}
              </div>
            ) : null}

            <div className="mt-2 border-t border-border pt-2">
              <button type="button" onClick={() => void refreshSelected()} className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground xl:justify-start">
                <RefreshCcw className={cn('h-4 w-4', detailLoading && 'animate-spin')} />
                Обновить данные
              </button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="min-w-0 space-y-4">
      {workspaceView === 'dashboard' ? (
      <section className="rounded-lg border border-border bg-surface px-4 py-4 shadow-sm sm:px-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-foreground">Состояние аудита</h2>
            <p className="mt-1 text-sm text-muted-foreground">Сводка по загруженным договорам и этапам проверки</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            {canManage ? (
              <>
                <button
                  type="button"
                  onClick={() => setWorkspaceView('registry')}
                  className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-4 text-sm font-medium text-foreground transition hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                >
                  <ClipboardList className="h-4 w-4" />
                  Открыть реестр
                </button>
                <button
                  type="button"
                  onClick={() => setDocumentDialogOpen(true)}
                  className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                >
                  <Plus className="h-4 w-4" />
                  Новый документ
                </button>
              </>
            ) : (
              <div className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-4 text-sm font-medium text-muted-foreground">
                <Lock className="h-4 w-4" />
                Только просмотр
              </div>
            )}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-5">
          <MetricTile label="Договоров" value={String(metrics.totalCases)} hint={`${metrics.activeCases} в работе`} tone="primary" />
          <MetricTile label="Требуют атомизации" value={String(metrics.casesNeedingAtomization)} hint="договоров без завершенной декомпозиции" tone={metrics.casesNeedingAtomization > 0 ? 'danger' : 'success'} />
          <MetricTile label="Атомов" value={String(metrics.atomsTotal)} hint={`${metrics.atomizedCases} договоров содержат атомы`} />
          <MetricTile label="Альфа-проверка" value={`${metrics.alphaPassed} / ${metrics.atomsTotal}`} hint={`${progressPercent(metrics.alphaPassed, metrics.atomsTotal)}% подтверждено`} tone="success" />
          <MetricTile label="Комиссия" value={`${metrics.commissionPassed} / ${metrics.atomsTotal}`} hint={`${progressPercent(metrics.commissionPassed, metrics.atomsTotal)}% подтверждено`} tone={metrics.commissionPassed > 0 ? 'success' : 'neutral'} />
        </div>
        <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Последние договоры</h3>
            <p className="mt-1 text-xs text-muted-foreground">Откройте карточку, чтобы перейти к атомам и материалам</p>
          </div>
          <button type="button" onClick={() => setWorkspaceView('registry')} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted">
            Все договоры
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {cases.slice(0, 4).map((item) => (
            <button key={item.id} type="button" onClick={() => selectCase(item.id)} className="rounded-md border border-border bg-surface-soft p-3 text-left transition hover:border-primary/40 hover:bg-muted">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-muted-foreground">{item.code}</span><StatusPill label={caseWorkflowLabel(item.status, item.workflowStage)} toneClass={caseWorkflowTone(item.status, item.workflowStage)} /></div>
                  <div className="mt-2 truncate text-sm font-semibold text-foreground">{item.productMasked}</div>
                  <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{item.contractMasked}</div>
                </div>
                <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
              </div>
            </button>
          ))}
        </div>
      </section>
      ) : null}

      {workspaceView === 'assignments' ? (
        <section className="rounded-lg border border-border bg-surface shadow-sm" aria-labelledby="audit-assignments-title">
          <div className="border-b border-border px-4 py-4 sm:px-5">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <h2 id="audit-assignments-title" className="text-xl font-semibold text-foreground">Назначения</h2>
                <p className="mt-1 text-sm text-muted-foreground">Даты по строкам, команда аудита по столбцам. Нажмите ячейку, чтобы изменить состав.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => shiftAssignmentRange(-assignmentRangeDays)} className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Предыдущий период" title="Предыдущий период"><ChevronLeft className="h-4 w-4" /></button>
                <button type="button" onClick={resetAssignmentRange} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted">Сегодня</button>
                <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground" htmlFor="audit-assignment-range-start">
                  С
                  <input id="audit-assignment-range-start" type="date" value={assignmentRangeStart} onChange={(event) => changeAssignmentRangeStart(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm" />
                </label>
                <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground" htmlFor="audit-assignment-range-end">
                  По
                  <input id="audit-assignment-range-end" type="date" min={assignmentRangeStart} max={shiftISODate(assignmentRangeStart, 91)} value={assignmentRangeEnd} onChange={(event) => changeAssignmentRangeEnd(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm" />
                </label>
                <button type="button" onClick={() => shiftAssignmentRange(assignmentRangeDays)} className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Следующий период" title="Следующий период"><ChevronRight className="h-4 w-4" /></button>
                <button type="button" onClick={() => void loadAssignments()} className="inline-flex h-11 w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Обновить назначения" title="Обновить"><RefreshCcw className={cn('h-4 w-4', assignmentsLoading && 'animate-spin')} /></button>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{formatDateOnly(assignmentRangeStart)} — {formatDateOnly(assignmentRangeEnd)}</span>
              {AUDIT_WORKFLOW_ORDER.map((stage) => <span key={stage} className="inline-flex items-center gap-1.5"><span className={cn('h-2.5 w-2.5 rounded-full', assignmentStageColor(stage))} />{formatAuditWorkflowStage(stage)}</span>)}
            </div>
          </div>

          {assignmentsError ? (
            <div className="m-4 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">{assignmentsError}</div>
          ) : teamLoading || assignmentsLoading ? (
            <div className="flex min-h-[360px] items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Загружаем матрицу</div>
          ) : assignmentTeam.length === 0 ? (
            <div className="px-6 py-14 text-center"><Users className="mx-auto h-8 w-8 text-muted-foreground" /><h3 className="mt-3 font-semibold text-foreground">Список сотрудников не сформирован</h3><p className="mt-1 text-sm text-muted-foreground">Сначала добавьте участников в разделе «Сотрудники».</p></div>
          ) : (
            <div className="max-h-[calc(100dvh-15rem)] min-h-[420px] overflow-auto">
              <table className="min-w-max border-collapse text-sm">
                <thead className="sticky top-0 z-20 bg-surface-soft shadow-[0_1px_0_hsl(var(--border))]">
                  <tr>
                    <th className="sticky left-0 z-30 min-w-[116px] bg-surface-soft px-3 py-2.5 text-left text-xs font-medium uppercase text-muted-foreground">Дата</th>
                    {assignmentTeam.map((member) => (
                      <th key={member.user_id} className="min-w-[190px] max-w-[230px] border-l border-border px-3 py-2.5 text-left">
                        <div className="truncate text-sm font-semibold text-foreground" title={member.full_name}>{member.full_name}</div>
                        <div className="mt-0.5 truncate text-xs font-normal text-muted-foreground">{member.role === 'leader' ? 'Руководитель' : 'Аудитор'}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {assignmentDates.map((scheduledDate) => {
                    const dateLabel = assignmentDateLabel(scheduledDate)
                    const isToday = scheduledDate === localISODate()
                    return (
                      <tr key={scheduledDate} className="border-b border-border last:border-b-0">
                        <th className={cn('sticky left-0 z-10 bg-surface px-3 py-2 text-left', isToday && 'bg-primary/5')}>
                          <div className={cn('font-semibold tabular-nums text-foreground', isToday && 'text-primary')}>{dateLabel.primary}</div>
                          <div className="mt-0.5 text-xs font-normal capitalize text-muted-foreground">{dateLabel.secondary}{isToday ? ' · сегодня' : ''}</div>
                        </th>
                        {assignmentTeam.map((member) => {
                          const cellItems = assignmentsByCell.get(`${scheduledDate}:${member.user_id}`) ?? []
                          return (
                            <td key={member.user_id} className="border-l border-border p-1 align-middle">
                              <button
                                type="button"
                                onClick={() => canManage && openAssignmentCell(scheduledDate, member.user_id)}
                                disabled={!canManage}
                                className={cn(
                                  'flex min-h-[52px] w-full flex-col justify-center rounded-md border px-2.5 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-default',
                                  cellItems.length > 0 ? assignmentCellTone(cellItems) : 'border-transparent bg-transparent hover:border-border hover:bg-muted/45'
                                )}
                                title={canManage ? 'Изменить назначенные договоры' : 'Назначения доступны только для просмотра'}
                              >
                                {cellItems.length > 0 ? (
                                  <>
                                    <div className="flex items-start gap-2">
                                      <div className="min-w-0 flex-1 space-y-1">
                                        {cellItems.map((item) => (
                                          <div key={item.id} className="flex min-w-0 items-center gap-1.5 text-xs">
                                            <span className={cn('h-2 w-2 shrink-0 rounded-full', assignmentStageColor(assignmentStage(item)))} aria-hidden="true" />
                                            <span className="min-w-0 flex-1 truncate font-medium text-foreground" title={`${item.case_number} · ${item.digital_product} · ${item.case_title}`}>
                                              {item.digital_product}
                                            </span>
                                            <span className="shrink-0 tabular-nums text-muted-foreground">
                                              {formatCountRu(item.atoms_count, 'атом', 'атома', 'атомов')}
                                            </span>
                                          </div>
                                        ))}
                                      </div>
                                      <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full border border-current/15 bg-surface/65 px-1 text-[11px] font-semibold tabular-nums text-foreground" title={formatCountRu(cellItems.length, 'назначенный договор', 'назначенных договора', 'назначенных договоров')}>
                                        {cellItems.length}
                                      </span>
                                    </div>
                                    <div className="mt-1 truncate pl-3.5 font-mono text-[10px] text-muted-foreground" title={cellItems.map((item) => item.case_number).join(', ')}>
                                      {cellItems.map((item) => item.case_number).join(', ')}
                                    </div>
                                  </>
                                ) : (
                                  <span className="text-center text-xs text-muted-foreground">{canManage ? '+ назначить' : '—'}</span>
                                )}
                              </button>
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {(workspaceView === 'registry' || workspaceView === 'case') ? (
      <div className="grid gap-4">
        {workspaceView === 'registry' ? (
        <section className="rounded-lg border border-border bg-surface shadow-sm" aria-labelledby="audit-registry-title">
          <div className="border-b border-border px-4 py-4 sm:px-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 id="audit-registry-title" className="text-xl font-semibold text-foreground">Реестр</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {filteredCases.length} из {cases.length}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void refreshSelected()}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                aria-label="Обновить список аудитов"
                title="Обновить"
              >
                <RefreshCcw className={cn('h-4 w-4', casesLoading && 'animate-spin')} />
              </button>
            </div>
            <label className="mt-3 flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-3">
              <Search className="h-4 w-4 text-muted-foreground" />
              <span className="sr-only">Поиск по аудитам</span>
              <input
                value={caseQuery}
                onChange={(event) => setCaseQuery(event.target.value)}
                placeholder="Поиск по коду, названию, продукту"
                className="min-w-0 flex-1 bg-transparent py-2 text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
              />
            </label>
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Фильтр статуса аудитов">
              {caseStatusOptions.map((status) => {
                const active = caseStatusFilter === status
                const count = status === 'all' ? cases.length : caseCountsByStatus[status] ?? 0
                return (
                  <button
                    key={status}
                    type="button"
                    onClick={() => setCaseStatusFilter(status)}
                    className={cn(
                      'inline-flex min-h-11 items-center gap-2 rounded-md border px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30',
                      active
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-surface-soft text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                  >
                    <Filter className="h-4 w-4" />
                    {status === 'all' ? 'Все' : status === 'archived' ? 'Архив' : formatAuditWorkflowStage(status)}
                    <span className={cn('rounded bg-black/10 px-1.5 py-0.5 text-xs', !active && 'bg-surface text-muted-foreground')}>
                      {count}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="p-3 sm:p-4">
            {casesLoading ? (
              <div className="space-y-2 p-2" role="status" aria-live="polite">
                {[0, 1, 2, 3].map((index) => (
                  <div key={index} className="h-24 animate-pulse rounded-md bg-muted" />
                ))}
              </div>
            ) : casesError ? (
              <div className="m-2 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
                {casesError}
              </div>
            ) : filteredCases.length === 0 ? (
              <div className="p-6 text-center">
                <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-surface-soft text-muted-foreground">
                  <Search className="h-5 w-5" />
                </div>
                <h3 className="mt-3 text-base font-semibold text-foreground">Ничего не найдено</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Смените поисковый запрос или статусный фильтр.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredCases.map((item) => {
                  const atomizationPercent = progressPercent(item.atomsReady + item.atomsExcluded, item.atomsTotal)
                  const alphaPercent = progressPercent(item.alphaPassed, item.atomsTotal)
                  const commissionPercent = progressPercent(item.commissionPassed, item.atomsTotal)
                  const signal = atomizationSignal(item)
                  const requiresAttention = caseNeedsAtomization(item)
                  return (
                    <article
                      key={item.id}
                      className={cn(
                        'grid min-w-0 overflow-hidden rounded-md border bg-surface-soft transition hover:border-primary/35 lg:grid-cols-[minmax(0,1.4fr)_minmax(260px,0.75fr)_minmax(220px,0.55fr)]',
                        item.status === 'draft' || item.atomsTotal === 0
                          ? 'border-l-4 border-l-rose-500'
                          : item.atomsDraft > 0
                            ? 'border-l-4 border-l-amber-500'
                            : 'border-border'
                      )}
                    >
                      <div className="min-w-0 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="shrink-0 font-mono text-xs font-semibold text-muted-foreground">{item.code}</span>
                            <StatusPill label={caseWorkflowLabel(item.status, item.workflowStage)} toneClass={caseWorkflowTone(item.status, item.workflowStage)} />
                          </div>
                          <div className={cn('flex min-w-0 items-center gap-1.5 text-xs font-medium', signal.toneClass)}>
                            {requiresAttention ? <AlertTriangle className="h-3.5 w-3.5 shrink-0" /> : <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />}
                            <span className="truncate">{signal.label}</span>
                          </div>
                        </div>
                        <div className="mt-2 flex min-w-0 items-baseline gap-2">
                          <h3 className="shrink-0 truncate text-sm font-semibold text-foreground sm:max-w-[42%] sm:text-base" title={item.productMasked}>{item.productMasked}</h3>
                          <span className="text-muted-foreground">·</span>
                          <p className="min-w-0 truncate text-sm text-muted-foreground" title={item.title}>{item.title}</p>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          <span className="font-mono">{item.contractMasked}</span>
                          <span>от {formatDateOnly(item.contractDate)}</span>
                        </div>
                      </div>

                      <div className="border-t border-border p-3 text-xs lg:border-l lg:border-t-0">
                        <div className="grid grid-cols-[72px_minmax(0,1fr)_64px] items-center gap-2">
                          <span className="text-muted-foreground">Атомы</span>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                            <div className="h-full bg-primary" style={{ width: `${atomizationPercent}%` }} />
                          </div>
                          <span className="text-right font-semibold tabular-nums text-foreground">{item.atomsReady + item.atomsExcluded} / {item.atomsTotal}</span>
                        </div>
                        <div className="mt-2 grid grid-cols-[72px_minmax(0,1fr)_64px] items-center gap-2">
                          <span className="text-muted-foreground">Альфа</span>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-emerald-500" style={{ width: `${alphaPercent}%` }} /></div>
                          <span className="text-right font-semibold tabular-nums text-foreground">{item.alphaPassed} · {alphaPercent}%</span>
                        </div>
                        <div className="mt-2 grid grid-cols-[72px_minmax(0,1fr)_64px] items-center gap-2">
                          <span className="text-muted-foreground">Комиссия</span>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary" style={{ width: `${commissionPercent}%` }} /></div>
                          <span className="text-right font-semibold tabular-nums text-foreground">{item.commissionPassed} · {commissionPercent}%</span>
                        </div>
                      </div>

                      <div className="flex min-w-0 flex-col justify-center gap-2 border-t border-border p-3 lg:border-l lg:border-t-0">
                        <div className="flex min-w-0 items-center gap-3 text-xs text-muted-foreground">
                          <span className="flex min-w-0 items-center gap-1.5"><UserPlus className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{item.responsibleName ?? 'Не назначен'}</span></span>
                          <span className="flex shrink-0 items-center gap-1.5"><FolderOpen className="h-3.5 w-3.5" />{item.documentsCount}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          {canManage ? (
                            <button
                              type="button"
                              onClick={() => openResponsibleDialog(item)}
                              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground"
                              aria-label={item.responsibleName ? 'Изменить ответственного' : 'Назначить ответственного'}
                              title={item.responsibleName ? 'Изменить ответственного' : 'Назначить ответственного'}
                            >
                              <UserPlus className="h-4 w-4" />
                            </button>
                          ) : null}
                          <button type="button" onClick={() => selectCase(item.id)} className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90">
                          Открыть договор
                          <ChevronRight className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </section>
        ) : null}

        {workspaceView === 'case' ? (
        <section className="min-w-0 rounded-lg border border-border bg-surface shadow-sm">
          {!selectedCaseId ? (
            <div className="flex min-h-[520px] flex-col items-center justify-center px-6 py-10 text-center">
              <Shield className="h-10 w-10 text-muted-foreground" />
              <h2 className="mt-3 text-lg font-semibold text-foreground">Аудиты пока не загружены</h2>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                После первого импорта или ручного создания аудит появится здесь вместе с атомами и историей.
              </p>
              {canManage ? (
                <button
                  type="button"
                  onClick={openCreateCaseDialog}
                  className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:opacity-90"
                >
                  <Plus className="h-4 w-4" />
                  Создать аудит
                </button>
              ) : null}
            </div>
          ) : (
            <div>
              <div className="border-b border-border px-4 py-4 sm:px-5">
                <button type="button" onClick={() => setWorkspaceView('registry')} className="mb-3 inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
                  <ArrowLeft className="h-4 w-4" />
                  Реестр
                </button>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-muted-foreground">{selectedCaseSummary?.code ?? 'AUD-—'}</span>
                      <StatusPill label={caseWorkflowLabel(selectedCaseSummary?.status ?? 'draft', selectedCaseSummary?.workflowStage ?? 'unassigned')} toneClass={caseWorkflowTone(selectedCaseSummary?.status ?? 'draft', selectedCaseSummary?.workflowStage ?? 'unassigned')} />
                    </div>
                    <h2 className="mt-2 text-xl font-semibold text-foreground">{selectedCaseSummary?.productMasked ?? 'Аудит'}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">{selectedCaseSummary?.title ?? 'Карточка аудита'}</p>
                  </div>
                  <div className={cn('inline-flex items-center gap-2 text-sm font-medium', selectedCaseSummary ? atomizationSignal(selectedCaseSummary).toneClass : 'text-muted-foreground')}>
                    {selectedCaseSummary && caseNeedsAtomization(selectedCaseSummary) ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                    {selectedCaseSummary ? atomizationSignal(selectedCaseSummary).label : 'Загружаем состояние'}
                  </div>
                </div>

                <dl className="mt-4 grid gap-x-5 gap-y-3 border-y border-border py-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
                  <div className="min-w-0"><dt className="text-xs text-muted-foreground">Договор</dt><dd className="mt-1 truncate font-mono text-foreground" title={selectedCaseSummary?.contractMasked}>{selectedCaseSummary?.contractMasked ?? '—'}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Дата договора</dt><dd className="mt-1 text-foreground">{formatDateOnly(selectedCaseSummary?.contractDate ?? null)}</dd></div>
                  <div className="min-w-0"><dt className="text-xs text-muted-foreground">Ответственный</dt><dd className="mt-1 truncate text-foreground" title={selectedCaseSummary?.responsibleName ?? undefined}>{selectedCaseSummary?.responsibleName ?? 'Не назначен'}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Обновлено</dt><dd className="mt-1 text-foreground">{formatDateTime(selectedCaseSummary?.updatedAt ?? null)}</dd></div>
                </dl>

                {selectedCaseSummary?.atomsTotal === 0 && selectedCaseSummary.status !== 'archived' ? (
                  <div className="mt-4 flex items-start gap-3 border-l-2 border-rose-500 bg-rose-500/5 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div><div className="font-medium">Техническое задание еще не декомпозировано</div><div className="mt-1 text-xs">Реестр атомов по этому договору не загружен.</div></div>
                  </div>
                ) : null}

                <div className="mt-4 grid grid-cols-2 divide-x divide-y divide-border border border-border text-sm sm:grid-cols-4 sm:divide-y-0">
                  <div className="px-3 py-2"><div className="text-xs text-muted-foreground">Атомов</div><div className="mt-1 font-semibold tabular-nums text-foreground">{detail?.atomsTotal ?? 0}</div></div>
                  <div className="px-3 py-2"><div className="text-xs text-muted-foreground">Черновых атомов</div><div className="mt-1 font-semibold tabular-nums text-foreground">{detail?.atomsDraft ?? 0}</div></div>
                  <div className="px-3 py-2"><div className="text-xs text-muted-foreground">Альфа-проверка</div><div className="mt-1 font-semibold tabular-nums text-foreground">{detail?.alphaPassed ?? 0} / {detail?.atomsTotal ?? 0}</div></div>
                  <div className="px-3 py-2"><div className="text-xs text-muted-foreground">Комиссия</div><div className="mt-1 font-semibold tabular-nums text-foreground">{detail?.commissionPassed ?? 0} / {detail?.atomsTotal ?? 0}</div></div>
                </div>
                {detail?.summary ? <p className="mt-3 max-w-4xl whitespace-pre-wrap text-sm text-muted-foreground">{detail.summary}</p> : null}
              </div>

              <div
                id="audit-panel-materials"
                role="tabpanel"
                aria-labelledby="audit-tab-materials"
                hidden={detailTab !== 'materials'}
                className="px-4 py-4 sm:px-5"
              >
                <div className="flex flex-col gap-3 border-b border-border pb-3 sm:flex-row sm:items-center sm:justify-between">
                  <div><h3 className="text-sm font-semibold text-foreground">Материалы договора</h3><p className="mt-1 text-xs text-muted-foreground">Исходные версии хранятся без изменения</p></div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted-foreground">{formatCountRu(documents.length, 'файл', 'файла', 'файлов')}</span>
                    {canEditSelectedAtoms ? (
                      <button
                        type="button"
                        onClick={() => setMaterialDialogOpen(true)}
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90"
                      >
                        <Paperclip className="h-4 w-4" />
                        Добавить документ
                      </button>
                    ) : null}
                  </div>
                </div>
                {documentsLoading ? (
                  <div className="flex min-h-[180px] items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Загружаем материалы</div>
                ) : documents.length > 0 ? (
                  <div className="divide-y divide-border">
                    {documents.map((document) => (
                      <div key={document.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex min-w-0 items-start gap-3">
                          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="truncate text-sm font-medium text-foreground">{document.display_name}</div>
                              <span className="rounded-md border border-border bg-surface-soft px-1.5 py-0.5 text-[11px] text-muted-foreground">{AUDIT_DOCUMENT_KIND_LABELS[document.kind]}</span>
                            </div>
                            <div className="mt-1 truncate text-xs text-muted-foreground" title={document.original_filename}>{document.original_filename}</div>
                            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground"><span>{formatBytes(document.size_bytes)}</span><span>{formatDateTime(document.created_at)}</span><span>{document.uploaded_by_name ?? 'Система'}</span></div>
                          </div>
                        </div>
                        <button type="button" onClick={() => void downloadDocument(document)} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted" title={`SHA-256: ${document.sha256}`}><Download className="h-4 w-4" />Скачать</button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-12 text-center"><FolderOpen className="mx-auto h-8 w-8 text-muted-foreground" /><h3 className="mt-3 text-base font-semibold text-foreground">Материалов пока нет</h3></div>
                )}
              </div>

              <div
                id="audit-panel-atoms"
                role="tabpanel"
                aria-labelledby="audit-tab-atoms"
                hidden={detailTab !== 'atoms'}
                className="px-4 py-4 sm:px-5"
              >
                {(detail?.atomsTotal ?? 0) > 0 ? (
                <div className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-end">
                  <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium text-foreground">
                    Поиск по атомам
                    <div className="flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface px-3">
                      <Search className="h-4 w-4 text-muted-foreground" />
                      <input
                        value={atomQuery}
                        onChange={(event) => setAtomQuery(event.target.value)}
                        placeholder="Код, название, пункт, наличие"
                        className="min-w-0 flex-1 bg-transparent py-2 text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm"
                      />
                    </div>
                  </label>
                  <label className="flex min-w-[180px] flex-col gap-1 text-sm font-medium text-foreground">
                    Статус
                    <select
                      value={atomStatusFilter}
                      onChange={(event) => setAtomStatusFilter(event.target.value)}
                      className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
                    >
                      {atomStatusOptions.map((option) => (
                        <option key={option} value={option}>
                          {option === 'all' ? 'Все статусы' : formatAtomStatus(option)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex min-w-[180px] flex-col gap-1 text-sm font-medium text-foreground">
                    Объект
                    <select
                      value={atomObjectTypeFilter}
                      onChange={(event) => setAtomObjectTypeFilter(event.target.value)}
                      className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
                    >
                      <option value="all">Все объекты</option>
                      {atomObjectTypeOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex min-w-[180px] flex-col gap-1 text-sm font-medium text-foreground">
                    Вид работ
                    <select
                      value={atomWorkTypeFilter}
                      onChange={(event) => setAtomWorkTypeFilter(event.target.value)}
                      className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
                    >
                      <option value="all">Все виды</option>
                      {atomWorkTypeOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                ) : null}

                {(detail?.atomsTotal ?? 0) > 0 && canEditSelectedAtoms ? (
                  <div className="mt-3 flex flex-col gap-2 border-b border-border pb-3 sm:flex-row sm:items-center sm:justify-between">
                    <label className="inline-flex min-h-10 items-center gap-2 text-sm font-medium text-foreground">
                      <input
                        type="checkbox"
                        checked={filteredAtoms.length > 0 && filteredAtoms.every((atom) => selectedAtomIds.includes(atom.id))}
                        onChange={toggleAllFilteredAtoms}
                        className="h-5 w-5 rounded border-input text-primary focus:ring-primary"
                      />
                      Выбрать по текущему фильтру
                    </label>
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                      <span className="text-xs text-muted-foreground">Выбрано: {selectedAtomIds.length}</span>
                      <select value={bulkAtomState} onChange={(event) => setBulkAtomState(event.target.value as 'draft' | 'ready' | 'excluded')} disabled={bulkAtomBusy} className="min-h-10 rounded-md border border-border bg-surface px-3 text-sm text-foreground">
                        <option value="draft">Черновик</option>
                        <option value="ready">Готов</option>
                        <option value="excluded">Исключен</option>
                      </select>
                      <button type="button" onClick={() => void updateSelectedAtomStatuses()} disabled={bulkAtomBusy || selectedAtomIds.length === 0} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-50">
                        {bulkAtomBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        Применить статус
                      </button>
                    </div>
                  </div>
                ) : null}

                {modelWorkspaceError ? (
                  <div className="mt-4 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
                    {modelWorkspaceError}
                  </div>
                ) : null}

                {modelRegistries.length > 0 ? (
                  <section className="mt-4 border-y border-border py-4" aria-labelledby="model-registries-title">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <h3 id="model-registries-title" className="text-sm font-semibold text-foreground">Модельные реестры</h3>
                        <p className="mt-1 text-xs text-muted-foreground">Независимые результаты сохранены отдельно. Генеральный список появляется только после ручного сравнения.</p>
                      </div>
                      {canEditSelectedAtoms ? (
                        <div className="flex flex-wrap gap-2">
                          <button type="button" onClick={() => void openAIAtomizationDialog()} className="inline-flex min-h-10 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium text-foreground hover:bg-muted">
                            <Sparkles className="h-4 w-4" />
                            Запустить другую модель
                          </button>
                          {modelComparisons.find((item) => item.status === 'draft_ready') ? (
                            <button type="button" onClick={() => showModelComparison(modelComparisons.find((item) => item.status === 'draft_ready')!)} className="inline-flex min-h-10 items-center gap-2 rounded-md border border-primary px-3 text-sm font-medium text-primary hover:bg-primary/5">
                              <Boxes className="h-4 w-4" />
                              {workingAtomRegistryExists ? 'Открыть сравнение' : 'Продолжить сравнение'}
                            </button>
                          ) : null}
                          <button type="button" onClick={() => void runModelComparison()} disabled={comparisonBusy || selectedModelRegistryIds.length < 2} className="inline-flex min-h-10 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                            {comparisonBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Boxes className="h-4 w-4" />}
                            Запустить сравнительный анализ
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <div className="mt-3 divide-y divide-border overflow-hidden rounded-md border border-border">
                      {modelRegistries.map((registry) => (
                        <details key={registry.id} className="group bg-surface">
                          <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-3 py-2 hover:bg-muted/50">
                            {canEditSelectedAtoms ? (
                              <input
                                type="checkbox"
                                checked={selectedModelRegistryIds.includes(registry.id)}
                                onClick={(event) => event.stopPropagation()}
                                onChange={() => toggleModelRegistry(registry.id)}
                                className="h-5 w-5 shrink-0 rounded border-input text-primary focus:ring-primary"
                                aria-label={`Выбрать реестр ${registry.provider_name}`}
                              />
                            ) : null}
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-semibold text-foreground">{registry.provider_name}</span>
                              <span className="block truncate font-mono text-xs text-muted-foreground">{registry.model_name} · конфигурация v{registry.provider_config_version}</span>
                            </span>
                            <span className="shrink-0 text-right">
                              <span className="block text-sm font-semibold text-foreground">{registry.atom_count}</span>
                              <span className="block text-[11px] text-muted-foreground">атомов</span>
                            </span>
                            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-open:rotate-90" />
                          </summary>
                          <div className="max-h-80 overflow-auto border-t border-border bg-surface-soft px-3 py-2">
                            {registry.items.map((item, index) => (
                              <div key={item.id} className="grid gap-1 border-b border-border/70 py-2 text-xs last:border-b-0 sm:grid-cols-[3rem_minmax(0,1fr)_minmax(12rem,0.7fr)]">
                                <span className="font-mono text-muted-foreground">{index + 1}</span>
                                <span className="font-medium text-foreground">{item.title}</span>
                                <span className="text-muted-foreground">
                                  {item.source_refs[0]?.excerpt || item.source_clause}
                                </span>
                              </div>
                            ))}
                          </div>
                        </details>
                      ))}
                    </div>
                  </section>
                ) : modelWorkspaceLoading ? (
                  <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Проверяем модельные реестры</div>
                ) : null}

                {detailLoading ? (
                  <div className="mt-4 flex min-h-[220px] items-center justify-center rounded-md border border-border bg-surface-soft text-sm text-muted-foreground">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Загружаем аудит
                  </div>
                ) : detailError ? (
                  <div className="mt-4 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
                    {detailError}
                  </div>
                ) : (detail?.atomsTotal ?? 0) === 0 ? (
                  <div className="mt-2 border-l-2 border-rose-500 bg-rose-500/5 px-5 py-8">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600 dark:text-rose-300" />
                      <div>
                        <h3 className="text-base font-semibold text-foreground">Реестр атомов еще не загружен</h3>
                        <p className="mt-1 text-sm text-muted-foreground">Договор находится в черновике и ожидает декомпозиции технического задания.</p>
                      </div>
                    </div>
                    {canEditSelectedAtoms ? (
                      <div className="mt-4 flex flex-wrap gap-2 pl-8">
                        <button type="button" onClick={() => void downloadAtomTemplate()} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface px-3 text-sm font-medium text-foreground hover:bg-muted"><FileDown className="h-4 w-4" />Скачать Excel-шаблон</button>
                        <button type="button" onClick={() => selectedCaseId && openImportDialog(selectedCaseId)} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:opacity-90"><Upload className="h-4 w-4" />Загрузить реестр атомов</button>
                        <button type="button" onClick={() => void openAIAtomizationDialog()} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-primary/30 bg-surface px-3 text-sm font-medium text-primary hover:bg-primary/5"><Sparkles className="h-4 w-4" />Сформировать реестр с ИИ</button>
                      </div>
                    ) : null}
                  </div>
                ) : filteredAtoms.length === 0 ? (
                  <div className="mt-4 rounded-md border border-dashed border-border bg-surface-soft px-6 py-12 text-center">
                    <Boxes className="mx-auto h-8 w-8 text-muted-foreground" />
                    <h3 className="mt-3 text-base font-semibold text-foreground">Атомов по фильтру нет</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Уточните фильтр или добавьте атом вручную.
                    </p>
                  </div>
                ) : (
                  <>
                    <div className="mt-4 hidden overflow-hidden rounded-md border border-border lg:block">
                      <div className="max-h-[440px] overflow-auto">
                        <table className="min-w-full border-collapse text-sm">
                          <thead className="sticky top-0 bg-surface-soft">
                            <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              {canEditSelectedAtoms ? <th className="w-12 px-3 py-3"><span className="sr-only">Выбор</span></th> : null}
                              <th className="px-3 py-3">Код</th>
                              <th className="px-3 py-3">Атом</th>
                              <th className="px-3 py-3">Объект</th>
                              <th className="px-3 py-3">Работы</th>
                              <th className="px-3 py-3">Пункт</th>
                              <th className="px-3 py-3">Статус</th>
                              <th className="px-3 py-3">Наличие / Комиссия</th>
                              {canEditSelectedAtoms ? <th className="px-3 py-3 text-right">Действие</th> : null}
                            </tr>
                          </thead>
                          <tbody>
                            {filteredAtoms.map((atom) => {
                              const active = atom.id === selectedAtomId
                              return (
                                <tr
                                  key={atom.id}
                                  className={cn(
                                    'border-b border-border/80 align-top transition last:border-b-0',
                                    active ? 'bg-primary/5' : 'bg-surface hover:bg-muted/60'
                                  )}
                                >
                                  {canEditSelectedAtoms ? (
                                    <td className="px-3 py-3">
                                      <input type="checkbox" checked={selectedAtomIds.includes(atom.id)} onChange={() => toggleAtomSelection(atom.id)} className="h-5 w-5 rounded border-input text-primary focus:ring-primary" aria-label={`Выбрать атом ${atom.itemCode}`} />
                                    </td>
                                  ) : null}
                                  <td className="px-3 py-3">
                                    <button
                                      type="button"
                                      onClick={() => setSelectedAtomId(atom.id)}
                                      className="font-mono text-xs font-medium text-primary hover:underline"
                                    >
                                      {atom.itemCode}
                                    </button>
                                  </td>
                                  <td className="min-w-[24rem] px-3 py-3">
                                    <div className="whitespace-normal break-words font-medium text-foreground">
                                      {atom.title}
                                    </div>
                                    <div className="mt-1 whitespace-normal break-words text-xs text-muted-foreground">
                                      {atom.digitalProduct}
                                    </div>
                                  </td>
                                  <td className="px-3 py-3 text-muted-foreground">{atom.objectType}</td>
                                  <td className="px-3 py-3 text-muted-foreground">{atom.workType}</td>
                                  <td className="min-w-[12rem] px-3 py-3 text-muted-foreground">{atom.sourceClause}</td>
                                  <td className="px-3 py-3">
                                    <StatusPill label={formatAtomStatus(atom.status)} toneClass={atomStatusTone(atom.status)} />
                                  </td>
                                  <td className="min-w-[14rem] px-3 py-3 text-muted-foreground">
                                    <div>{atom.legacyAlphaRef ?? '—'}</div>
                                    <div className="mt-1">{atom.commissionRef ?? '—'}</div>
                                  </td>
                                  {canEditSelectedAtoms ? (
                                    <td className="px-3 py-3 text-right">
                                      <button
                                        type="button"
                                        onClick={() => openEditAtomDialog(atom)}
                                        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border bg-surface-soft text-muted-foreground transition hover:bg-muted hover:text-foreground"
                                        aria-label={`Изменить атом ${atom.itemCode}`}
                                        title="Изменить атом"
                                      >
                                        <Pencil className="h-4 w-4" />
                                      </button>
                                    </td>
                                  ) : null}
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div className="mt-4 space-y-3 lg:hidden">
                      {filteredAtoms.map((atom) => {
                        const active = atom.id === selectedAtomId
                        return (
                          <div
                            key={atom.id}
                            className={cn(
                              'rounded-md border p-3',
                              active ? 'border-primary bg-primary/10' : 'border-border bg-surface-soft'
                            )}
                          >
                            <div className="flex items-start justify-between gap-3">
                              {canEditSelectedAtoms ? (
                                <input type="checkbox" checked={selectedAtomIds.includes(atom.id)} onChange={() => toggleAtomSelection(atom.id)} className="mt-0.5 h-5 w-5 shrink-0 rounded border-input text-primary focus:ring-primary" aria-label={`Выбрать атом ${atom.itemCode}`} />
                              ) : null}
                              <button
                                type="button"
                                onClick={() => setSelectedAtomId(atom.id)}
                                className="min-w-0 text-left"
                              >
                                <div className="font-mono text-xs font-medium text-primary">{atom.itemCode}</div>
                                <div className="mt-1 whitespace-normal break-words text-sm font-semibold text-foreground">
                                  {atom.title}
                                </div>
                                <div className="mt-1 whitespace-normal break-words text-xs text-muted-foreground">
                                  {atom.digitalProduct}
                                </div>
                              </button>
                              {canEditSelectedAtoms ? (
                                <button
                                  type="button"
                                  onClick={() => openEditAtomDialog(atom)}
                                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground"
                                  aria-label={`Изменить атом ${atom.itemCode}`}
                                >
                                  <Pencil className="h-4 w-4" />
                                </button>
                              ) : null}
                            </div>
                            <div className="mt-3 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Объект</div>
                                <div className="mt-1 text-foreground">{atom.objectType}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Работы</div>
                                <div className="mt-1 text-foreground">{atom.workType}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Пункт</div>
                                <div className="mt-1 text-foreground">{atom.sourceClause}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Статус</div>
                                <div className="mt-1">
                                  <StatusPill label={formatAtomStatus(atom.status)} toneClass={atomStatusTone(atom.status)} />
                                </div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Наличие в системе</div>
                                <div className="mt-1 text-foreground">{atom.legacyAlphaRef ?? '—'}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Комиссия</div>
                                <div className="mt-1 text-foreground">{atom.commissionRef ?? '—'}</div>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>

                    <div className="mt-4 rounded-md border border-border bg-surface-soft px-4 py-4">
                      <div className="flex items-center gap-2">
                        <EyeOff className="h-4 w-4 text-muted-foreground" />
                        <h3 className="text-sm font-semibold text-foreground">Деталь атома</h3>
                      </div>
                      {selectedAtom ? (
                        <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-xs font-medium text-primary">{selectedAtom.itemCode}</span>
                              <StatusPill label={formatAtomStatus(selectedAtom.status)} toneClass={atomStatusTone(selectedAtom.status)} />
                            </div>
                            <h4 className="mt-2 text-base font-semibold text-foreground">{selectedAtom.title}</h4>
                            <div className="mt-3 grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Цифровой продукт</div>
                                <div className="mt-1 text-foreground">{selectedAtom.digitalProduct}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Объект</div>
                                <div className="mt-1 text-foreground">{selectedAtom.objectType}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Работы</div>
                                <div className="mt-1 text-foreground">{selectedAtom.workType}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Пункт источника</div>
                                <div className="mt-1 text-foreground">{selectedAtom.sourceClause}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Наличие / Комиссия</div>
                                <div className="mt-1 text-foreground">
                                  {selectedAtom.legacyAlphaRef ?? '—'} / {selectedAtom.commissionRef ?? '—'}
                                </div>
                              </div>
                            </div>
                            {selectedAtom.sourceEvidenceText || selectedAtom.sourceRefs.length > 0 ? (
                              <div className="mt-3 border-l-2 border-primary pl-3">
                                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Текстовое основание</div>
                                {selectedAtom.sourceRefs.length > 0 ? (
                                  <div className="mt-2 space-y-3">
                                    {selectedAtom.sourceRefs.map((source) => (
                                      <div key={`${selectedAtom.id}-${source.source_unit_id}-${source.locator}`} className="text-sm text-muted-foreground">
                                        <div className="font-mono text-xs text-foreground">{source.locator}</div>
                                        <p className="mt-1 whitespace-pre-wrap text-foreground">{source.excerpt}</p>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{selectedAtom.sourceEvidenceText}</p>
                                )}
                              </div>
                            ) : null}
                            {selectedAtom.notes ? (
                              <div className="mt-3 rounded-md border border-border bg-surface px-3 py-3 text-sm text-muted-foreground">
                                {selectedAtom.notes}
                              </div>
                            ) : null}
                          </div>
                          <div className="rounded-md border border-border bg-surface px-3 py-3 text-sm text-muted-foreground">
                            <div className="flex items-center gap-2 font-medium text-foreground">
                              <Clock3 className="h-4 w-4 text-muted-foreground" />
                              Метаданные
                            </div>
                            <div className="mt-3 space-y-3">
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Создан</div>
                                <div className="mt-1 text-foreground">{formatDateTime(selectedAtom.createdAt)}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Обновлен</div>
                                <div className="mt-1 text-foreground">{formatDateTime(selectedAtom.updatedAt)}</div>
                              </div>
                              <div>
                                <div className="text-[11px] uppercase tracking-wide">Полный URL системы</div>
                                {selectedAtom.systemUrl ? (
                                  <a
                                    href={selectedAtom.systemUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mt-1 inline-flex max-w-full items-start gap-2 break-all text-primary hover:underline"
                                  >
                                    <ExternalLink className="mt-0.5 h-4 w-4 shrink-0" />
                                    <span>{selectedAtom.systemUrl}</span>
                                  </a>
                                ) : (
                                  <div className="mt-1 text-foreground">—</div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <p className="mt-3 text-sm text-muted-foreground">Выберите атом, чтобы посмотреть полные реквизиты и URL.</p>
                      )}
                    </div>
                  </>
                )}
              </div>

              <div
                id="audit-panel-history"
                role="tabpanel"
                aria-labelledby="audit-tab-history"
                hidden={detailTab !== 'history'}
                className="px-4 py-4 sm:px-5"
              >
                {detailLoading ? (
                  <div className="flex min-h-[220px] items-center justify-center rounded-md border border-border bg-surface-soft text-sm text-muted-foreground">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Загружаем историю
                  </div>
                ) : eventsError ? (
                  <div className="rounded-md border border-rose-500/25 bg-rose-500/10 px-4 py-4 text-sm text-rose-700 dark:text-rose-300">
                    <div className="font-medium">История временно недоступна</div>
                    <div className="mt-1">{eventsError}</div>
                    <button type="button" onClick={() => selectedCaseId && void loadCaseBundle(selectedCaseId)} className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-md border border-current/20 px-3 font-medium"><RefreshCcw className="h-4 w-4" />Повторить</button>
                  </div>
                ) : events.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border bg-surface-soft px-6 py-12 text-center">
                    <History className="mx-auto h-8 w-8 text-muted-foreground" />
                    <h3 className="mt-3 text-base font-semibold text-foreground">История пока пуста</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      После импорта, правок и фиксаций здесь появятся события по аудиту.
                    </p>
                  </div>
                ) : (
                  <div className="rounded-md border border-border bg-surface-soft px-4 py-4">
                    <div className="space-y-4">
                      {events.map((event) => (
                        <div key={event.id} className="border-l-2 border-primary/30 pl-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusPill label={formatAuditEventType(event.type)} toneClass="border-border bg-surface text-muted-foreground" />
                            {event.title !== formatAuditEventType(event.type) ? (
                              <span className="text-sm font-medium text-foreground">{event.title}</span>
                            ) : null}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                            <span>{formatDateTime(event.createdAt)}</span>
                            <span>{event.actorName ?? 'Система'}</span>
                          </div>
                          {event.body ? (
                            <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{event.body}</p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
        ) : null}
      </div>
      ) : null}

      {workspaceView === 'team' ? (
        <section className="rounded-lg border border-border bg-surface shadow-sm">
          <div className="flex flex-col gap-4 border-b border-border px-4 py-4 sm:px-5 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-foreground">Сотрудники</h2>
              <p className="mt-1 text-sm text-muted-foreground">Только участники команды могут работать с общим реестром и назначаться ответственными.</p>
            </div>
            <button type="button" onClick={() => void loadTeam()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted">
              <RefreshCcw className={cn('h-4 w-4', teamLoading && 'animate-spin')} />
              Обновить
            </button>
          </div>
          {canManage ? (
            <div className="grid gap-3 border-b border-border bg-surface-soft px-4 py-4 sm:px-5 lg:grid-cols-[minmax(0,1fr)_180px_auto]">
              <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
                Контакт
                <select value={newTeamUserId} onChange={(event) => setNewTeamUserId(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm">
                  <option value="">Выберите принятый контакт</option>
                  {teamCandidates.map((candidate) => <option key={candidate.user_id} value={candidate.user_id}>{candidate.full_name} · {candidate.email}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
                Роль
                <select value={newTeamRole} onChange={(event) => setNewTeamRole(event.target.value as AuditTeamRole)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm">
                  <option value="member">Аудитор</option>
                  <option value="leader">Руководитель аудита</option>
                </select>
              </label>
              <button type="button" onClick={() => void addTeamMember()} disabled={!newTeamUserId || teamSaving} className="inline-flex min-h-11 items-center justify-center gap-2 self-end rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                {teamSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                Добавить
              </button>
            </div>
          ) : null}
          <div className="p-3 sm:p-4">
            {teamError ? <div className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">{teamError}</div> : teamLoading ? (
              <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />Загружаем команду</div>
            ) : team.length === 0 ? (
              <div className="rounded-md border border-dashed border-border px-6 py-12 text-center"><Users className="mx-auto h-8 w-8 text-muted-foreground" /><h3 className="mt-3 font-semibold text-foreground">Команда пока не сформирована</h3><p className="mt-1 text-sm text-muted-foreground">Добавьте сотрудника из принятых контактов.</p></div>
            ) : (
              <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                {team.map((member) => (
                  <div key={member.id} className="grid gap-3 bg-surface px-3 py-3 sm:grid-cols-[minmax(0,1fr)_190px_auto] sm:items-center">
                    <div className="min-w-0"><div className="truncate text-sm font-semibold text-foreground">{member.full_name}</div><div className="truncate text-xs text-muted-foreground">{member.email}</div></div>
                    {canManage ? (
                      <select value={member.role} onChange={(event) => void updateTeamRole(member, event.target.value as AuditTeamRole)} className="min-h-11 rounded-md border border-border bg-surface-soft px-3 text-sm text-foreground outline-none focus:border-primary">
                        <option value="member">Аудитор</option><option value="leader">Руководитель аудита</option>
                      </select>
                    ) : <span className="text-sm text-muted-foreground">{member.role === 'leader' ? 'Руководитель аудита' : 'Аудитор'}</span>}
                    {canManage ? <button type="button" onClick={() => void removeTeamMember(member)} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border px-3 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground">Убрать</button> : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      ) : null}
      </div>

      <DialogShell
        open={assignmentDialogOpen}
        title={`Назначения · ${formatDateOnly(assignmentTargetDate)}`}
        description={assignmentTargetMember ? `${assignmentTargetMember.full_name}: выберите договоры для работы в этот день.` : 'Выберите договоры для ячейки календаря.'}
        sizeClassName="max-w-3xl"
        busy={assignmentSaving}
        onRequestClose={closeAssignmentDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-xs text-muted-foreground">Выбрано: {assignmentCaseIds.length}</span>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="button" onClick={closeAssignmentDialog} disabled={assignmentSaving} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">Отмена</button>
              <button type="button" onClick={() => void saveAssignmentCell()} disabled={assignmentSaving || !assignmentDirty} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                {assignmentSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Сохранить назначения
              </button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          <label className="flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <span className="sr-only">Поиск договора</span>
            <input value={assignmentQuery} onChange={(event) => setAssignmentQuery(event.target.value)} placeholder="Поиск по коду, продукту или названию" className="min-w-0 flex-1 bg-transparent py-2 text-base text-foreground outline-none placeholder:text-muted-foreground sm:text-sm" />
          </label>
          {assignmentFilteredCases.length === 0 ? (
            <div className="rounded-md border border-dashed border-border px-5 py-10 text-center text-sm text-muted-foreground">Договоры по запросу не найдены</div>
          ) : (
            <div className="max-h-[55dvh] divide-y divide-border overflow-y-auto rounded-md border border-border">
              {assignmentFilteredCases.map((item) => {
                const checked = assignmentCaseIds.includes(item.id)
                const wasAssigned = assignmentInitialCaseIds.includes(item.id)
                const unavailable = item.status === 'archived' && !wasAssigned
                const existingAssignment = assignmentByCaseId.get(item.id)
                const assignedElsewhere = Boolean(
                  existingAssignment
                  && (
                    existingAssignment.assignee_id !== assignmentTargetUserId
                    || existingAssignment.scheduled_date !== assignmentTargetDate
                  )
                )
                const willTransfer = assignmentTransferCaseIds.includes(item.id)
                return (
                  <label key={item.id} className={cn('flex min-h-16 items-start gap-3 px-3 py-3', unavailable ? 'cursor-not-allowed opacity-55' : 'cursor-pointer hover:bg-muted/50')}>
                    <input type="checkbox" checked={checked} disabled={unavailable || assignmentSaving} onChange={(event) => toggleAssignmentCase(item.id, event.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 rounded border-input text-primary focus:ring-primary" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-muted-foreground">{item.code}</span>
                        <StatusPill label={caseWorkflowLabel(item.status, item.workflowStage)} toneClass={caseWorkflowTone(item.status, item.workflowStage)} />
                        {unavailable ? <span className="text-xs text-muted-foreground">нельзя назначить</span> : null}
                        {assignedElsewhere && existingAssignment ? (
                          <span className={cn('inline-flex items-center gap-1 text-xs font-medium', willTransfer ? 'text-primary' : 'text-amber-800 dark:text-amber-200')}>
                            <Lock className="h-3.5 w-3.5" />
                            {willTransfer
                              ? 'Будет передан'
                              : `Назначен: ${existingAssignment.assignee_name}, ${formatDateOnly(existingAssignment.scheduled_date)}`}
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-1.5 block truncate text-sm font-medium text-foreground" title={item.title}>{item.productMasked} · {item.title}</span>
                      <span className="mt-1 block truncate font-mono text-xs text-muted-foreground">{item.contractMasked}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          )}
        </div>
      </DialogShell>

      <DialogShell
        open={documentDialogOpen}
        title="Новый документ"
        description="Загрузите одно или несколько технических заданий. Каждый файл создаст черновую карточку в реестре."
        sizeClassName="max-w-3xl"
        busy={documentUploading}
        initialFocusRef={documentFileInputRef}
        onRequestClose={closeDocumentDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => closeDocumentDialog('cancel')} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted">Отмена</button>
            <button type="button" onClick={() => void uploadDocuments()} disabled={documentFiles.length === 0 || documentUploading} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
              {documentUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              Загрузить {documentFiles.length > 1 ? `${documentFiles.length} документа` : 'документ'}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="rounded-md border border-border bg-surface-soft p-4">
            <label className="flex flex-col gap-2 text-sm font-medium text-foreground">
              Технические задания
              <input ref={documentFileInputRef} type="file" multiple accept=".pdf,.docx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setDocumentFiles(Array.from(event.target.files ?? []))} className="min-h-11 rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground file:mr-3 file:border-0 file:bg-surface-soft file:px-3 file:py-2 file:text-sm file:font-medium sm:text-sm" />
            </label>
            <p className="mt-2 text-xs text-muted-foreground">PDF, DOCX или XLSX, до 25 МБ на файл и до 20 файлов за раз. Исходная версия не перезаписывается.</p>
          </div>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Цифровой продукт для пакета (необязательно)
            <input value={documentProduct} onChange={(event) => setDocumentProduct(event.target.value)} placeholder="Например: OPEC или DASH" className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm" />
            <span className="text-xs font-normal text-muted-foreground">Если продукты разные, оставьте поле пустым и заполните карточки после загрузки.</span>
          </label>
          {documentFiles.length > 0 ? (
            <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
              {documentFiles.map((file) => <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm"><span className="min-w-0 truncate text-foreground">{file.name}</span><span className="shrink-0 text-xs text-muted-foreground">{formatBytes(file.size)}</span></div>)}
            </div>
          ) : null}
          <div className="border-t border-border pt-4">
            <div className="text-sm font-medium text-foreground">Другой способ</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" disabled={documentDirty} onClick={() => { setDocumentDialogOpen(false); openCreateCaseDialog() }} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-40"><Plus className="h-4 w-4" />Создать карточку вручную</button>
              <button type="button" disabled={documentDirty} onClick={() => { setDocumentDialogOpen(false); openImportDialog() }} className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-40"><FileSpreadsheet className="h-4 w-4" />Импортировать реестр атомов</button>
            </div>
          </div>
        </div>
      </DialogShell>

      <DialogShell
        open={materialDialogOpen}
        title="Добавить документы в договор"
        description={`Материалы будут добавлены в ${selectedCaseSummary?.code ?? 'выбранный договор'} и не создадут новую карточку.`}
        sizeClassName="max-w-2xl"
        busy={materialUploading}
        initialFocusRef={materialFileInputRef}
        onRequestClose={closeMaterialDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => closeMaterialDialog('cancel')} disabled={materialUploading} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">Отмена</button>
            <button type="button" onClick={() => void uploadCaseMaterials()} disabled={materialFiles.length === 0 || materialUploading} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
              {materialUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              Добавить {materialFiles.length > 1 ? `${materialFiles.length} файла` : 'документ'}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Категория материала
            <select value={materialKind} onChange={(event) => setMaterialKind(event.target.value as AuditDocumentKind)} disabled={materialUploading} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm">
              {(Object.entries(AUDIT_DOCUMENT_KIND_LABELS) as Array<[AuditDocumentKind, string]>).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-2 text-sm font-medium text-foreground">
            Файлы
            <input ref={materialFileInputRef} type="file" multiple accept=".pdf,.docx,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setMaterialFiles(Array.from(event.target.files ?? []))} disabled={materialUploading} className="min-h-11 rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground file:mr-3 file:border-0 file:bg-surface-soft file:px-3 file:py-2 file:text-sm file:font-medium disabled:opacity-50 sm:text-sm" />
            <span className="text-xs font-normal text-muted-foreground">PDF, DOCX или XLSX, до 25 МБ на файл и до 20 файлов за раз.</span>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Название в материалах (необязательно)
            <input value={materialDisplayName} onChange={(event) => setMaterialDisplayName(event.target.value)} disabled={materialUploading || materialFiles.length > 1} placeholder="Например: Протокол комиссии от 24.08.2026" className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-50 sm:text-sm" />
            <span className="text-xs font-normal text-muted-foreground">Для нескольких файлов система сформирует названия по категории и именам файлов.</span>
          </label>
          {materialFiles.length > 0 ? (
            <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
              {materialFiles.map((file) => <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm"><span className="min-w-0 truncate text-foreground">{file.name}</span><span className="shrink-0 text-xs text-muted-foreground">{formatBytes(file.size)}</span></div>)}
            </div>
          ) : null}
          <div className="border-l-2 border-primary bg-primary/5 px-3 py-2 text-xs text-muted-foreground">Загруженный файл сохраняется как новая неизменяемая версия. Исходный материал не перезаписывается.</div>
        </div>
      </DialogShell>

      <DialogShell
        open={deleteCaseDialogOpen}
        title={`Удалить ${selectedCaseSummary?.code ?? 'договор'}`}
        description="Удаление необратимо. Доступно только для договора, который уже перенесен в архив."
        sizeClassName="max-w-lg"
        busy={deleteCaseBusy}
        initialFocusRef={deleteCaseConfirmationRef}
        onRequestClose={closeDeleteCaseDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => closeDeleteCaseDialog('cancel')} disabled={deleteCaseBusy} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">Отмена</button>
            <button type="button" onClick={() => void deleteSelectedCase()} disabled={deleteCaseBusy || deleteCaseConfirmation.trim().toUpperCase() !== selectedCaseSummary?.code.toUpperCase()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-rose-600 px-4 text-sm font-medium text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50">
              {deleteCaseBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Удалить без восстановления
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="border-l-2 border-rose-500 bg-rose-500/5 px-3 py-3 text-sm text-foreground">
            Будут удалены карточка, {formatCountRu(selectedCaseSummary?.documentsCount ?? 0, 'документ', 'документа', 'документов')}, {formatCountRu(selectedCaseSummary?.atomsTotal ?? 0, 'атом', 'атома', 'атомов')} и связанная история. Факт удаления останется в системном журнале.
          </div>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Введите код {selectedCaseSummary?.code ?? 'договора'}
            <input ref={deleteCaseConfirmationRef} value={deleteCaseConfirmation} onChange={(event) => setDeleteCaseConfirmation(event.target.value)} autoComplete="off" disabled={deleteCaseBusy} className="min-h-11 rounded-md border border-border bg-surface px-3 font-mono text-base text-foreground outline-none focus:border-rose-500 disabled:opacity-50 sm:text-sm" />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Причина (необязательно)
            <textarea value={deleteCaseReason} onChange={(event) => setDeleteCaseReason(event.target.value)} rows={3} maxLength={500} disabled={deleteCaseBusy} placeholder="Например: ошибочно загружен не тот договор" className="resize-y rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none focus:border-rose-500 disabled:opacity-50 sm:text-sm" />
          </label>
        </div>
      </DialogShell>

      <DialogShell
        open={responsibleDialogOpen}
        title="Ответственный по договору"
        description="Назначение доступно только из сформированной команды аудита и фиксируется в истории."
        sizeClassName="max-w-lg"
        busy={responsibleSaving}
        onRequestClose={() => { if (!responsibleSaving) setResponsibleDialogOpen(false) }}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => setResponsibleDialogOpen(false)} disabled={responsibleSaving} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border px-4 text-sm font-medium text-foreground hover:bg-muted">Отмена</button>
            <button type="button" onClick={() => void saveResponsible()} disabled={responsibleSaving} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">{responsibleSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}Сохранить</button>
          </div>
        }
      >
        <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
          Сотрудник
          <select value={responsibleUserId} onChange={(event) => setResponsibleUserId(event.target.value)} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm">
            <option value="">Не назначен</option>
            {team.filter((member) => member.is_active).map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name} · {member.role === 'leader' ? 'руководитель' : 'аудитор'}</option>)}
          </select>
        </label>
      </DialogShell>

      <DialogShell
        open={caseDialogOpen}
        title={caseDialogMode === 'create' ? 'Новый аудит' : 'Редактировать договор'}
        description="Номер договора необязателен и не влияет на обработку документов."
        sizeClassName="max-w-3xl"
        busy={caseSaving}
        initialFocusRef={caseTitleInputRef}
        onRequestClose={closeCaseDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => closeCaseDialog('cancel')}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground transition hover:bg-muted"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => void saveCase()}
              disabled={caseSaving}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {caseSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {caseDialogMode === 'create' ? 'Создать аудит' : 'Сохранить изменения'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Название аудита
            <input
              ref={caseTitleInputRef}
              value={caseForm.title}
              onChange={(event) => setCaseForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="Например: Аудит атомизации договоров 2026"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Продукт / объект
            <input
              value={caseForm.productName}
              onChange={(event) => setCaseForm((current) => ({ ...current, productName: event.target.value }))}
              placeholder="Название цифрового продукта"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Этап аудита
            <select
              value={caseForm.workflowStage}
              disabled={caseDialogMode === 'create'}
              onChange={(event) => setCaseForm((current) => ({ ...current, workflowStage: event.target.value as AuditWorkflowStage }))}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:cursor-not-allowed disabled:opacity-70 sm:text-sm"
            >
              {AUDIT_WORKFLOW_ORDER.map((stage) => (
                <option key={stage} value={stage}>
                  {formatAuditWorkflowStage(stage)}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-muted-foreground">
              Новый договор получает этап автоматически после назначения.
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Состояние карточки
            <select
              value={caseForm.status}
              onChange={(event) => setCaseForm((current) => ({ ...current, status: event.target.value }))}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            >
              {['draft', 'atomization', 'ready', 'archived'].map((status) => (
                <option key={status} value={status}>
                  {formatCaseStatus(status)}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-muted-foreground">
              Техническое состояние черновика, готовности или архива.
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Номер договора <span className="font-normal text-muted-foreground">(необязательно)</span>
            <input
              value={caseForm.contractReference}
              onChange={(event) => setCaseForm((current) => ({ ...current, contractReference: event.target.value }))}
              placeholder={caseDialogMode === 'edit' ? 'Оставьте пустым, если менять не нужно' : 'Номер или код договора'}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
            <span className="text-xs font-normal text-muted-foreground">
              Только справочная метка карточки. Runtime использует выбранный документ и его SHA-256.
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Дата договора
            <input
              type="date"
              value={caseForm.contractDate}
              onChange={(event) => setCaseForm((current) => ({ ...current, contractDate: event.target.value }))}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Контекст аудита
            <textarea
              value={caseForm.summary}
              onChange={(event) => setCaseForm((current) => ({ ...current, summary: event.target.value }))}
              rows={5}
              placeholder="Что именно проверяем, какие ограничения и ожидаемый результат."
              className="min-h-[132px] rounded-md border border-border bg-surface px-3 py-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
        </div>
      </DialogShell>

      <DialogShell
        open={atomDialogOpen}
        title={atomDialogMode === 'create' ? 'Новый атом' : 'Изменить атом'}
        description="Полный URL системы доступен только в деталях и в этой форме, не в списке."
        sizeClassName="max-w-4xl"
        busy={atomSaving}
        initialFocusRef={atomTitleInputRef}
        onRequestClose={closeAtomDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => closeAtomDialog('cancel')}
              className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground transition hover:bg-muted"
            >
              Отмена
            </button>
            <button
              type="button"
              onClick={() => void saveAtom()}
              disabled={atomSaving}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {atomSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {atomDialogMode === 'create' ? 'Добавить атом' : 'Сохранить атом'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Код атома (необязательно)
            <input
              value={atomForm.itemCode}
              onChange={(event) => setAtomForm((current) => ({ ...current, itemCode: event.target.value }))}
              placeholder="DPMS назначит автоматически"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Статус
            <select
              value={atomForm.status}
              onChange={(event) => setAtomForm((current) => ({ ...current, status: event.target.value }))}
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            >
              {['draft', 'ready', 'excluded'].map((status) => (
                <option key={status} value={status}>
                  {formatAtomStatus(status)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Название атома
            <input
              ref={atomTitleInputRef}
              value={atomForm.title}
              onChange={(event) => setAtomForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="Читаемое название с длинной русской формулировкой"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Цифровой продукт
            <input
              value={atomForm.digitalProduct}
              onChange={(event) => setAtomForm((current) => ({ ...current, digitalProduct: event.target.value }))}
              placeholder="Продукт, к которому относится этот атом"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Тип объекта
            <input
              value={atomForm.objectType}
              onChange={(event) => setAtomForm((current) => ({ ...current, objectType: event.target.value }))}
              placeholder="Договор, приложение, карточка"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Вид работ
            <input
              value={atomForm.workType}
              onChange={(event) => setAtomForm((current) => ({ ...current, workType: event.target.value }))}
              placeholder="Проверка, атрибуция, исключение"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Пункт источника
            <input
              value={atomForm.sourceClause}
              onChange={(event) => setAtomForm((current) => ({ ...current, sourceClause: event.target.value }))}
              placeholder="Например: Раздел 4.2, подпункт 3"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Наличие в системе (из Excel)
            <input
              value={atomForm.legacyAlphaRef}
              onChange={(event) => setAtomForm((current) => ({ ...current, legacyAlphaRef: event.target.value }))}
              placeholder="Исходное значение реестра"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
            Решение комиссии (из Excel)
            <input
              value={atomForm.commissionRef}
              onChange={(event) => setAtomForm((current) => ({ ...current, commissionRef: event.target.value }))}
              placeholder="Исходное значение реестра"
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Полный URL системы
            <input
              value={atomForm.systemUrl}
              onChange={(event) => setAtomForm((current) => ({ ...current, systemUrl: event.target.value }))}
              placeholder="https://..."
              className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-foreground sm:col-span-2">
            Комментарий
            <textarea
              value={atomForm.notes}
              onChange={(event) => setAtomForm((current) => ({ ...current, notes: event.target.value }))}
              rows={4}
              placeholder="Что важно учесть при работе с атомом."
              className="min-h-[120px] rounded-md border border-border bg-surface px-3 py-3 text-base text-foreground outline-none focus:border-primary sm:text-sm"
            />
          </label>
        </div>
      </DialogShell>

      <DialogShell
        open={aiAtomizationDialogOpen}
        title={isCanonicalSkill ? 'Атомизация технического задания' : 'ИИ-атомизация технического задания'}
        description={isCanonicalSkill
          ? 'DPMS проверит DOCX, передаст настроенной модели только обезличенные фрагменты и покажет найденные элементы до записи в реестр. Номер договора не требуется.'
          : 'ИИ сформирует только проверяемый черновик. Атомы появятся в реестре после вашего подтверждения.'}
        sizeClassName="max-w-6xl"
        busy={aiAtomizationBusy}
        onRequestClose={closeAIAtomizationDialog}
        footer={
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-xs text-muted-foreground">
              {aiAttempt
                ? isCanonicalSkill
                  ? `${aiAttempt.provider_name} · ${aiAttempt.model_name}: сохранено ${aiDrafts.length} атомов в отдельном модельном реестре.`
                  : `Выбрано ${aiDrafts.filter((draft) => draft.included).length} из ${aiDrafts.length}. Исходный документ не изменяется.`
                : isCanonicalSkill
                  ? canonicalRun
                    ? canonicalRun.status === 'preflight_pass'
                      ? '634 и подобные значения здесь означают исходные фрагменты, а не атомы. Итоговый список сформирует модель.'
                      : canonicalRun.status === 'atomizing'
                        ? `Обработано пакетов: ${canonicalRun.completed_batch_count} из ${canonicalRun.total_batch_count}. Прогресс сохраняется.`
                        : `${canonicalRunLabel(canonicalRun)}. Результат сохраняется в истории аудита.`
                    : 'Сначала документ проверяется локально. Внешний запрос возможен только после отдельного подтверждения.'
                : aiPrivacyPreview
                  ? `Обезличивание проверено: ${aiPrivacyPreview.replacement_count} замен. Подтверждение действует до ${formatDateTime(aiPrivacyPreview.expires_at)}.`
                  : 'Сначала выполните локальный предпросмотр обезличивания. До подтверждения внешний запрос не выполняется.'}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="button" onClick={closeAIAtomizationDialog} disabled={aiAtomizationBusy} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">
                Отмена
              </button>
              {aiAttempt && isCanonicalSkill ? (
                <>
                  <button type="button" onClick={prepareNextCanonicalModel} disabled={aiAtomizationBusy || aiProviders.length === 0} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">
                    <RefreshCcw className="h-4 w-4" />
                    Другая модель
                  </button>
                  <button type="button" onClick={() => void finishCanonicalModelResult()} disabled={aiAtomizationBusy} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                    <CheckCircle2 className="h-4 w-4" />
                    Готово
                  </button>
                </>
              ) : aiAttempt ? (
                <button type="button" onClick={() => void commitAIAtomDrafts()} disabled={aiAtomizationBusy || aiDrafts.every((draft) => !draft.included)} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                  {aiAtomizationBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Записать в реестр
                </button>
              ) : isCanonicalSkill ? (
                !canonicalRun ? (
                  <button type="button" onClick={() => void startCanonicalPreflight()} disabled={aiAtomizationBusy || Boolean(canonicalRun) || !aiSelectedDocumentId || !aiSelectedSkillId} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                    {aiAtomizationBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
                    Подготовить документ
                  </button>
                ) : canonicalRun.status === 'preflight_pass'
                  || (canonicalRun.status === 'draft_ready' && aiPreparingNextModel)
                  || (canonicalRun.status === 'committed' && aiPreparingNextModel)
                  || (
                  canonicalRun.status === 'failed'
                  && canonicalRun.current_phase === 'atomization_failed'
                  && canonicalRun.source_unit_count > 0
                ) ? (
                  <button type="button" onClick={() => void startCanonicalAtomization()} disabled={aiAtomizationBusy || !canonicalAtomizationPreview || !aiTransferConfirmed} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                    {aiAtomizationBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                    {canonicalRun.status === 'failed' ? 'Повторить атомизацию' : 'Запустить атомизацию'}
                  </button>
                ) : ['queued', 'running', 'atomization_queued', 'atomizing', 'draft_ready'].includes(canonicalRun.status) ? (
                  <button type="button" disabled className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground opacity-60">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {canonicalRun.status === 'draft_ready' ? 'Загружаем черновик' : canonicalRunLabel(canonicalRun)}
                  </button>
                ) : canonicalRun.status !== 'committed' ? (
                  <button type="button" onClick={() => { setCanonicalRun(null); setCanonicalAtomizationPreview(null); setAiTransferConfirmed(false); setAiAtomizationError(null) }} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted">
                    <RefreshCcw className="h-4 w-4" />
                    Новая проверка
                  </button>
                ) : null
              ) : (
                <button type="button" onClick={() => void generateAIAtomDrafts()} disabled={aiAtomizationBusy || !aiSelectedDocumentId || !aiSelectedSkillId || !aiTransferConfirmed || !aiPrivacyPreview} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
                  {aiAtomizationBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Сформировать черновик
                </button>
              )}
            </div>
          </div>
        }
      >
        <div className="space-y-5">
          {aiAtomizationError ? (
            <div className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
              {aiAtomizationError}
            </div>
          ) : null}

          {isCanonicalSkill && !aiAttempt ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-foreground">
                  Неизменяемое ТЗ
                  <select value={aiSelectedDocumentId} onChange={(event) => { setAiSelectedDocumentId(event.target.value); setCanonicalRun(null); setCanonicalAtomizationPreview(null); setAiTransferConfirmed(false) }} disabled={aiAtomizationBusy || Boolean(canonicalRun)} className="min-h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm">
                    {canonicalEligibleDocuments.length === 0 ? <option value="">Нет подходящего DOCX</option> : null}
                    {canonicalEligibleDocuments.map((document) => (
                      <option key={document.id} value={document.id}>{document.display_name}</option>
                    ))}
                  </select>
                  <span className="break-words text-xs font-normal text-muted-foreground">Canonical audit-tz v0.3.0 принимает DOCX. Версия файла фиксируется по SHA-256.</span>
                </label>
                <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-foreground">
                  Проверенная методика
                  <select value={aiSelectedSkillId} onChange={(event) => { setAiSelectedSkillId(event.target.value); invalidateAIPrivacyPreview() }} disabled={aiAtomizationBusy || Boolean(canonicalRun) || aiAtomizationSkills.length === 0} className="min-h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm">
                    {aiAtomizationSkills.map((skill) => (
                      <option key={skill.id} value={skill.id}>{skill.name} · v{skill.version}</option>
                    ))}
                  </select>
                  <span className="break-words text-xs font-normal text-muted-foreground">Активная версия прошла hash-проверку и встроенный self-test отдельного runtime.</span>
                </label>
              </div>

              <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-foreground">
                ИИ-подключение для этого прогона
                <select
                  value={aiSelectedProviderId}
                  onChange={(event) => {
                    setAiSelectedProviderId(event.target.value)
                    setCanonicalAtomizationPreview(null)
                    setAiTransferConfirmed(false)
                  }}
                  disabled={aiAtomizationBusy || ['atomization_queued', 'atomizing'].includes(canonicalRun?.status ?? '') || aiProviders.length === 0}
                  className="min-h-11 w-full rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm"
                >
                  {aiProviders.length === 0 ? <option value="">Нет проверенных подключений</option> : null}
                  {aiProviders.map((provider) => {
                    const laneUsed = usedCanonicalModelLanes.has(`${provider.id}:${provider.config_version}:${provider.model_name}`)
                    return (
                      <option key={provider.id} value={provider.id} disabled={laneUsed}>
                        {provider.display_name} · {provider.model_name}{laneUsed ? ' · реестр уже сформирован' : ''}
                      </option>
                    )
                  })}
                </select>
                <span className="text-xs font-normal text-muted-foreground">Результат точной версии профиля сохранится отдельно и не перезапишет результаты других моделей.</span>
              </label>

              <section className="rounded-md border border-border bg-surface-soft" aria-label="Этапы canonical atomization">
                <div className="grid divide-y divide-border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
                  <div className="px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground"><CheckCircle2 className="h-4 w-4 text-emerald-600" />1. Runtime</div>
                    <p className="mt-1 text-xs text-muted-foreground">Пакет и self-test подтверждены</p>
                  </div>
                  <div className="px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      {canonicalRun && ['queued', 'running'].includes(canonicalRun.status)
                        ? <Loader2 className="h-4 w-4 animate-spin text-primary" />
                        : canonicalRun && (
                          ['preflight_pass', 'atomization_queued', 'atomizing', 'draft_ready', 'committed'].includes(canonicalRun.status)
                          || (canonicalRun.status === 'failed' && canonicalRun.current_phase === 'atomization_failed')
                        )
                          ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                          : <Shield className="h-4 w-4 text-primary" />}
                      2. Preflight
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">Hash, структура и извлечение содержимого</p>
                  </div>
                  <div className="px-4 py-3">
                    <div className={cn(
                      'flex items-center gap-2 text-sm font-semibold',
                      canonicalRun && ['atomization_queued', 'atomizing', 'draft_ready', 'committed'].includes(canonicalRun.status)
                        ? 'text-foreground'
                        : 'text-muted-foreground'
                    )}>
                      {canonicalRun && ['atomization_queued', 'atomizing'].includes(canonicalRun.status)
                        ? <Loader2 className="h-4 w-4 animate-spin text-primary" />
                        : canonicalRun && ['draft_ready', 'committed'].includes(canonicalRun.status)
                          ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                          : canonicalRun?.status === 'preflight_pass'
                            ? <Sparkles className="h-4 w-4 text-primary" />
                            : <Lock className="h-4 w-4" />}
                      3. Атомизация
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">ИИ-черновик, проверка человеком и запись в реестр</p>
                  </div>
                </div>
              </section>

              {canonicalRun ? (
                <section className={cn(
                  'border-l-2 px-4 py-4',
                  canonicalRun.status === 'preflight_pass' && 'border-emerald-500 bg-emerald-500/5',
                  canonicalRun.status === 'blocked' && 'border-amber-500 bg-amber-500/5',
                  canonicalRun.status === 'failed' && 'border-rose-500 bg-rose-500/5',
                  ['queued', 'running', 'atomization_queued', 'atomizing'].includes(canonicalRun.status) && 'border-primary bg-primary/5',
                  ['draft_ready', 'committed'].includes(canonicalRun.status) && 'border-emerald-500 bg-emerald-500/5'
                )}>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      {['queued', 'running', 'atomization_queued', 'atomizing'].includes(canonicalRun.status)
                        ? <Loader2 className="h-4 w-4 animate-spin text-primary" />
                        : ['preflight_pass', 'draft_ready', 'committed'].includes(canonicalRun.status)
                          ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                          : <AlertTriangle className="h-4 w-4 text-amber-600" />}
                      {canonicalRunLabel(canonicalRun)}
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">run {canonicalRun.id.slice(0, 8)}</span>
                  </div>
                  {canonicalRun.status === 'preflight_pass' ? (
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <MetricTile label="Исходных фрагментов" value={String(canonicalRun.source_unit_count)} tone="success" />
                      <MetricTile label="Предупреждений" value={String(canonicalRun.warning_count)} />
                      <MetricTile label="Следующий этап" value="ИИ-анализ" hint="после вашего подтверждения" />
                    </div>
                  ) : ['atomization_queued', 'atomizing', 'draft_ready', 'committed'].includes(canonicalRun.status) ? (
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <MetricTile label="Исходных фрагментов" value={String(canonicalRun.source_unit_count)} />
                      <MetricTile
                        label="Обработано пакетов"
                        value={`${canonicalRun.completed_batch_count}/${canonicalRun.total_batch_count || '—'}`}
                        tone={canonicalRun.status === 'draft_ready' || canonicalRun.status === 'committed' ? 'success' : 'primary'}
                      />
                      <MetricTile
                        label="Найдено атомов"
                        value={canonicalRun.status === 'draft_ready' || canonicalRun.status === 'committed' ? String(canonicalRun.atom_count) : '—'}
                        hint="до ручного подтверждения"
                      />
                    </div>
                  ) : canonicalRun.status === 'blocked' ? (
                    <div className="mt-2 text-sm text-foreground">
                      <p>{canonicalBlockMessage(canonicalRun.error_code)}</p>
                      {canonicalBlockGuidance(canonicalRun.error_code).length > 0 ? (
                        <ol className="mt-3 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
                          {canonicalBlockGuidance(canonicalRun.error_code).map((step) => <li key={step}>{step}</li>)}
                        </ol>
                      ) : null}
                      {canonicalRun.error_code ? <p className="mt-2 font-mono text-xs text-muted-foreground">{canonicalRun.error_code}</p> : null}
                    </div>
                  ) : canonicalRun.status === 'failed' ? (
                    <div className="mt-2 text-sm text-foreground">
                      <p>{canonicalRun.current_phase === 'atomization_failed'
                        ? 'Атомизация остановилась. Уже обработанные пакеты сохранены; после повторного запуска работа продолжится.'
                        : 'Локальная подготовка документа завершилась технической ошибкой. Внешняя модель не вызывалась.'}</p>
                      {canonicalRun.error_code ? <p className="mt-2 font-mono text-xs text-muted-foreground">{canonicalRun.error_code}</p> : null}
                    </div>
                  ) : (
                    <p className="mt-2 text-sm text-muted-foreground">Worker продолжит работу в фоне. Окно можно закрыть: состояние запуска сохранено.</p>
                  )}
                </section>
              ) : (
                <div className="border-l-2 border-primary bg-primary/5 px-4 py-3 text-sm text-muted-foreground">
                  <div className="font-medium text-foreground">Что получится после нажатия</div>
                  <p className="mt-1">DPMS локально зафиксирует выбранный DOCX по SHA-256 и подготовит доказуемый набор исходных фрагментов. Содержимое документа на этом этапе не отправляется в интернет.</p>
                </div>
              )}

              {canonicalAtomizationPreview && canonicalRun && (
                canonicalRun.status === 'preflight_pass'
                || (canonicalRun.status === 'draft_ready' && aiPreparingNextModel)
                || (canonicalRun.status === 'committed' && aiPreparingNextModel)
                || (canonicalRun.status === 'failed' && canonicalRun.current_phase === 'atomization_failed')
              ) ? (
                <section className="border-l-2 border-primary bg-primary/5 px-4 py-4" aria-label="Подтверждение внешней атомизации">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-foreground">Передача в настроенную ИИ-модель</h3>
                      <p className="mt-1 text-xs text-muted-foreground">{canonicalAtomizationPreview.provider_name} · {canonicalAtomizationPreview.model_name}</p>
                    </div>
                    <span className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-muted-foreground">
                      {canonicalAtomizationPreview.source_unit_count} исходных фрагментов
                    </span>
                  </div>
                  <div className="mt-3 grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="text-xs font-medium text-foreground">Будет передано</div>
                      <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                        {canonicalAtomizationPreview.outbound_fields.map((item) => <li key={item}>• {item}</li>)}
                      </ul>
                    </div>
                    <div>
                      <div className="text-xs font-medium text-foreground">Защита данных</div>
                      <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                        {canonicalAtomizationPreview.warnings.map((item) => <li key={item}>• {item}</li>)}
                      </ul>
                    </div>
                  </div>
                  <label className="mt-4 flex items-start gap-3 border-t border-border pt-4 text-sm text-foreground">
                    <input
                      type="checkbox"
                      checked={aiTransferConfirmed}
                      onChange={(event) => setAiTransferConfirmed(event.target.checked)}
                      disabled={aiAtomizationBusy}
                      className="mt-0.5 h-5 w-5 rounded border-input text-primary focus:ring-primary"
                    />
                    <span>
                      Подтверждаю передачу перечисленных обезличенных данных для формирования черновика атомов.
                      <span className="mt-1 block text-xs text-muted-foreground">Атомы не попадут в реестр автоматически: сначала вы увидите и проверите полный список.</span>
                    </span>
                  </label>
                </section>
              ) : null}
            </>
          ) : !aiAttempt ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-foreground">
                  Неизменяемое ТЗ
                  <select value={aiSelectedDocumentId} onChange={(event) => { setAiSelectedDocumentId(event.target.value); invalidateAIPrivacyPreview() }} disabled={aiAtomizationBusy} className="min-h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm">
                    {aiEligibleDocuments.map((document) => (
                      <option key={document.id} value={document.id}>{document.display_name}</option>
                    ))}
                  </select>
                  <span className="break-words text-xs font-normal text-muted-foreground">Поддерживаются PDF и DOCX. Версия фиксируется по SHA-256.</span>
                </label>
                <label className="flex min-w-0 flex-col gap-1 text-sm font-medium text-foreground">
                  Skill атомизации
                  <select value={aiSelectedSkillId} onChange={(event) => { setAiSelectedSkillId(event.target.value); invalidateAIPrivacyPreview() }} disabled={aiAtomizationBusy || aiAtomizationSkills.length === 0} className="min-h-11 w-full min-w-0 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-50 sm:text-sm">
                    {aiAtomizationSkills.length === 0 ? <option value="">Нет активного skill</option> : null}
                    {aiAtomizationSkills.map((skill) => (
                      <option key={skill.id} value={skill.id}>{skill.name} · v{skill.version}</option>
                    ))}
                  </select>
                  <span className="break-words text-xs font-normal text-muted-foreground">Используется активная версия, установленная администратором.</span>
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <label className="flex flex-col gap-1 text-sm font-medium text-foreground">
                  Номер договора и точные варианты написания
                  <textarea
                    value={aiContractIdentifiers}
                    onChange={(event) => { setAiContractIdentifiers(event.target.value); invalidateAIPrivacyPreview() }}
                    disabled={aiAtomizationBusy}
                    rows={3}
                    placeholder={'Основной номер договора\nВариант с другим разделителем'}
                    className="min-h-24 resize-y rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none placeholder:text-muted-foreground focus:border-primary disabled:opacity-50"
                  />
                  <span className="text-xs font-normal text-muted-foreground">Один вариант на строку. Значения используются в памяти запроса и не записываются в БД или журнал.</span>
                </label>
                <button
                  type="button"
                  onClick={() => void previewAIAtomizationPrivacy()}
                  disabled={aiAtomizationBusy || !aiSelectedDocumentId || !aiSelectedSkillId || contractIdentifierList().length === 0}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-primary px-4 text-sm font-medium text-primary hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {aiAtomizationBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
                  Проверить обезличивание
                </button>
              </div>

              {aiPrivacyPreview ? (
                <section className="border-l-2 border-emerald-500 bg-emerald-500/5 px-4 py-3" aria-label="Результат проверки обезличивания">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      Исходящий запрос обезличен
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">SHA {aiPrivacyPreview.payload_sha256.slice(0, 12)}</span>
                  </div>
                  <div className="mt-2 grid gap-x-5 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
                    <span>Замен: <strong className="text-foreground">{aiPrivacyPreview.replacement_count}</strong></span>
                    <span>Фрагментов: <strong className="text-foreground">{aiPrivacyPreview.source_unit_count}</strong></span>
                    <span>Псевдоним: <strong className="font-mono text-foreground">{aiPrivacyPreview.pseudonym}</strong></span>
                    <span>Модель: <strong className="text-foreground">{aiPrivacyPreview.model_name}</strong></span>
                  </div>
                  {aiPrivacyPreview.samples.length > 0 ? (
                    <details className="mt-3 text-xs text-muted-foreground">
                      <summary className="cursor-pointer font-medium text-foreground">Показать обезличенные фрагменты</summary>
                      <div className="mt-2 divide-y divide-border border-y border-border">
                        {aiPrivacyPreview.samples.map((sample) => (
                          <div key={sample.source_unit_id} className="py-2">
                            <div className="font-medium text-foreground">{sample.source_unit_id} · {sample.locator}</div>
                            <p className="mt-1 whitespace-pre-wrap break-words">{sample.excerpt}</p>
                          </div>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </section>
              ) : (
                <div className="border-l-2 border-primary bg-primary/5 px-4 py-3 text-sm text-muted-foreground">
                  <div className="font-medium text-foreground">До внешнего запроса</div>
                  <p className="mt-1">DPMS локально заменит номер договора, проверит фактический payload и покажет обезличенные фрагменты. Имя файла, путь и SHA исходного документа модели не передаются.</p>
                </div>
              )}

              <label className="flex items-start gap-3 text-sm text-foreground">
                <input type="checkbox" checked={aiTransferConfirmed} onChange={(event) => setAiTransferConfirmed(event.target.checked)} disabled={aiAtomizationBusy || !aiPrivacyPreview} className="mt-0.5 h-5 w-5 rounded border-input text-primary focus:ring-primary" />
                <span>
                  Подтверждаю передачу показанного обезличенного текста провайдеру {aiPrivacyPreview?.provider_name ?? 'ИИ'} для атомизации.
                  <span className="mt-1 block text-xs text-muted-foreground">Подтверждение привязано к этому документу, skill, модели и введенным вариантам номера на 10 минут.</span>
                </span>
              </label>
            </>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricTile label="Найдено атомов" value={String(aiDrafts.length)} tone="primary" />
                <MetricTile label={isCanonicalSkill ? 'Сохранено в реестре модели' : 'Будет записано'} value={String(aiDrafts.filter((draft) => draft.included).length)} tone="success" />
                <MetricTile label="Skill" value={`v${aiAttempt.skill_version}`} hint={aiAttempt.skill_name} />
                <MetricTile label="Модель" value={aiAttempt.model_name} hint="зафиксирована для попытки" />
              </div>

              {Object.keys(aiAttempt.coverage_summary).length > 0 ? (
                <div className="flex flex-wrap gap-x-4 gap-y-2 border-y border-border py-3 text-xs text-muted-foreground">
                  <span>Атомизировано: <strong className="text-foreground">{aiAttempt.coverage_summary.ATOMIZED ?? 0}</strong></span>
                  <span>Служебный текст: <strong className="text-foreground">{aiAttempt.coverage_summary.NON_REQUIREMENT ?? 0}</strong></span>
                  <span>Повторы: <strong className="text-foreground">{aiAttempt.coverage_summary.DUPLICATE ?? 0}</strong></span>
                  <span>Требует уточнения: <strong className="text-foreground">{(aiAttempt.coverage_summary.QUESTION ?? 0) + (aiAttempt.coverage_summary.BLOCKED ?? 0)}</strong></span>
                </div>
              ) : null}

              {aiAttempt.warnings.length > 0 ? (
                <div className="border-l-2 border-amber-500 bg-amber-500/5 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
                  <div className="font-medium">Предупреждения модели</div>
                  <ul className="mt-2 space-y-1">
                    {aiAttempt.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}
                  </ul>
                </div>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
                <div>
                  <h3 className="text-sm font-semibold text-foreground">{isCanonicalSkill ? 'Результат выбранной модели' : 'Проверка черновика'}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">{isCanonicalSkill ? 'Этот снимок неизменяем. Ручная правка выполняется после сравнительного анализа.' : 'Отредактируйте формулировки и исключите неподходящие варианты до публикации.'}</p>
                </div>
                {!isCanonicalSkill ? <label className="inline-flex min-h-10 items-center gap-2 text-sm font-medium text-foreground">
                  <input
                    type="checkbox"
                    checked={aiDrafts.length > 0 && aiDrafts.every((draft) => draft.included)}
                    onChange={(event) => setAiDrafts((current) => current.map((draft) => ({ ...draft, included: event.target.checked })))}
                    className="h-5 w-5 rounded border-input text-primary focus:ring-primary"
                  />
                  Выбрать все
                </label> : null}
              </div>

              <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                {aiDrafts.map((draft, index) => (
                  <section key={draft.id} className={cn('px-3 py-4 sm:px-4', !draft.included && 'bg-muted/35 opacity-70')}>
                    <div className="flex items-start gap-3">
                      {!isCanonicalSkill ? <input type="checkbox" checked={draft.included} onChange={(event) => updateAIAtomDraft(draft.id, 'included', event.target.checked)} className="mt-1 h-5 w-5 shrink-0 rounded border-input text-primary focus:ring-primary" aria-label={`Включить атом ${index + 1}`} /> : null}
                      <div className="min-w-0 flex-1 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono text-xs font-medium text-muted-foreground">Черновик {index + 1}</span>
                          {draft.confidence_percent !== null ? <span className="text-xs text-muted-foreground">Уверенность модели: {draft.confidence_percent}%</span> : null}
                        </div>
                        <div className="grid gap-3 lg:grid-cols-2">
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground lg:col-span-2">
                            Название атома
                            <textarea value={draft.title} onChange={(event) => updateAIAtomDraft(draft.id, 'title', event.target.value)} rows={2} disabled={isCanonicalSkill || !draft.included} className="min-h-[72px] resize-y rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                          </label>
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                            Цифровой продукт
                            <input value={draft.digital_product} onChange={(event) => updateAIAtomDraft(draft.id, 'digital_product', event.target.value)} disabled={isCanonicalSkill || !draft.included} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                          </label>
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                            Вид работ
                            <input value={draft.work_type ?? ''} onChange={(event) => updateAIAtomDraft(draft.id, 'work_type', event.target.value)} disabled={isCanonicalSkill || !draft.included} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                          </label>
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                            Тип объекта
                            <input value={draft.object_type ?? ''} onChange={(event) => updateAIAtomDraft(draft.id, 'object_type', event.target.value)} disabled={isCanonicalSkill || !draft.included} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                          </label>
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                            Пункт источника
                            <input value={draft.source_clause} readOnly className="min-h-11 rounded-md border border-border bg-muted/45 px-3 text-base text-foreground sm:text-sm" />
                          </label>
                          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground lg:col-span-2">
                            Комментарий аудитора
                            <textarea value={draft.notes ?? ''} onChange={(event) => updateAIAtomDraft(draft.id, 'notes', event.target.value)} rows={2} disabled={isCanonicalSkill || !draft.included} className="min-h-[72px] resize-y rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                          </label>
                        </div>
                        <div className="border-l-2 border-border pl-3">
                          <div className="text-xs font-medium text-foreground">Основание в документе</div>
                          <div className="mt-2 space-y-2">
                            {draft.source_refs.map((source) => (
                              <div key={`${draft.id}-${source.source_unit_id}`} className="text-xs text-muted-foreground">
                                <span className="font-mono text-foreground">{source.locator}</span>
                                <span className="mt-1 block whitespace-pre-wrap">{source.excerpt}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>
                ))}
              </div>
            </>
          )}
        </div>
      </DialogShell>

      <DialogShell
        open={comparisonDialogOpen}
        title="Сравнительный анализ моделей"
        description={workingAtomRegistryExists
          ? 'Сравните независимые результаты моделей. Уже опубликованный рабочий реестр не будет изменен или перезаписан.'
          : 'Проверьте расхождения, отредактируйте итоговые формулировки и только затем запишите генеральный реестр.'}
        sizeClassName="max-w-6xl"
        busy={comparisonBusy}
        onRequestClose={closeComparisonDialog}
        footer={
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-xs text-muted-foreground">
              {workingAtomRegistryExists
                ? 'Сравнение сохранено отдельно. Текущий рабочий реестр остается без изменений.'
                : `Выбрано ${comparisonDrafts.filter((draft) => draft.included).length} из ${comparisonDrafts.length}. Все исходные модельные варианты сохраняются.`}
            </span>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="button" onClick={closeComparisonDialog} disabled={comparisonBusy} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50">{workingAtomRegistryExists ? 'Закрыть' : 'Отмена'}</button>
              {!workingAtomRegistryExists ? (
                <button type="button" onClick={() => void commitModelComparison()} disabled={comparisonBusy || comparisonDrafts.every((draft) => !draft.included)} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50">
                  {comparisonBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Записать генеральный реестр
                </button>
              ) : null}
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          {comparisonError ? (
            <div className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">{comparisonError}</div>
          ) : null}
          {modelComparison ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <MetricTile label="Модельных реестров" value={String(modelComparison.registry_ids.length)} />
              <MetricTile label="Итоговых кандидатов" value={String(comparisonDrafts.length)} tone="primary" />
              <MetricTile label="Полное согласие" value={String(comparisonDrafts.filter((draft) => draft.agreement_count === draft.registry_count).length)} tone="success" />
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
            <p className="text-xs text-muted-foreground">Согласие показывает, сколько независимых реестров содержат сопоставимый атом. Оно не заменяет решение аудитора.</p>
            {!workingAtomRegistryExists ? (
              <label className="inline-flex min-h-10 items-center gap-2 text-sm font-medium text-foreground">
                <input type="checkbox" checked={comparisonDrafts.length > 0 && comparisonDrafts.every((draft) => draft.included)} onChange={(event) => setComparisonDrafts((current) => current.map((draft) => ({ ...draft, included: event.target.checked })))} className="h-5 w-5 rounded border-input text-primary focus:ring-primary" />
                Выбрать все
              </label>
            ) : null}
          </div>
          <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
            {comparisonDrafts.map((draft, index) => (
              <section key={draft.id} className={cn('px-3 py-4 sm:px-4', !draft.included && 'bg-muted/35 opacity-70')}>
                <div className="flex items-start gap-3">
                  <input type="checkbox" checked={draft.included} onChange={(event) => updateComparisonDraft(draft.id, 'included', event.target.checked)} disabled={workingAtomRegistryExists} className="mt-1 h-5 w-5 shrink-0 rounded border-input text-primary focus:ring-primary disabled:opacity-60" aria-label={`Включить генеральный атом ${index + 1}`} />
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-xs text-muted-foreground">Кандидат {index + 1}</span>
                      <span className={cn('rounded px-2 py-1 text-xs font-medium', draft.agreement_count === draft.registry_count ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200')}>
                        Согласие {draft.agreement_count}/{draft.registry_count}
                      </span>
                    </div>
                    <div className="grid gap-3 lg:grid-cols-2">
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground lg:col-span-2">Название атома
                        <textarea value={draft.title} onChange={(event) => updateComparisonDraft(draft.id, 'title', event.target.value)} rows={2} disabled={!draft.included || workingAtomRegistryExists} className="min-h-[72px] resize-y rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                      </label>
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">Цифровой продукт
                        <input value={draft.digital_product} onChange={(event) => updateComparisonDraft(draft.id, 'digital_product', event.target.value)} disabled={!draft.included || workingAtomRegistryExists} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                      </label>
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">Тип объекта
                        <input value={draft.object_type ?? ''} onChange={(event) => updateComparisonDraft(draft.id, 'object_type', event.target.value)} disabled={!draft.included || workingAtomRegistryExists} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                      </label>
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">Вид работ
                        <input value={draft.work_type ?? ''} onChange={(event) => updateComparisonDraft(draft.id, 'work_type', event.target.value)} disabled={!draft.included || workingAtomRegistryExists} className="min-h-11 rounded-md border border-border bg-surface px-3 text-base text-foreground outline-none focus:border-primary disabled:opacity-60 sm:text-sm" />
                      </label>
                      <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">Пункт источника
                        <input value={draft.source_clause} readOnly className="min-h-11 rounded-md border border-border bg-muted/45 px-3 text-base text-foreground sm:text-sm" />
                      </label>
                    </div>
                    <div className="border-l-2 border-border pl-3">
                      <div className="text-xs font-medium text-foreground">Текстовое основание</div>
                      <div className="mt-2 space-y-2">
                        {draft.source_refs.map((source) => (
                          <div key={`${draft.id}-${source.source_unit_id}-${source.locator}`} className="text-xs text-muted-foreground">
                            <span className="font-mono text-foreground">{source.locator}</span>
                            <span className="mt-1 block whitespace-pre-wrap">{source.excerpt}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <details className="text-xs text-muted-foreground">
                      <summary className="cursor-pointer font-medium text-primary">Варианты моделей ({draft.model_variants.length})</summary>
                      <div className="mt-2 divide-y divide-border border-y border-border">
                        {draft.model_variants.map((variant) => (
                          <div key={variant.registry_item_id} className="grid gap-1 py-2 sm:grid-cols-[minmax(10rem,0.4fr)_minmax(0,1fr)]">
                            <span>{variant.provider_name} · <span className="font-mono">{variant.model_name}</span></span>
                            <span className="text-foreground">{variant.title}</span>
                          </div>
                        ))}
                      </div>
                    </details>
                  </div>
                </div>
              </section>
            ))}
          </div>
        </div>
      </DialogShell>

      <DialogShell
        open={importDialogOpen}
        title={importTargetCaseId ? 'Загрузить реестр атомов' : 'Импорт аудита из Excel'}
        description={importTargetCaseId
          ? `Excel будет проверен и привязан только к ${selectedCaseSummary?.code ?? 'выбранному договору'}. Файл с другим договором система отклонит.`
          : 'Система сначала проверит файл. Данные сохранятся только после явного подтверждения.'}
        sizeClassName="max-w-5xl"
        busy={importPreviewing || importCommitting}
        initialFocusRef={importFileInputRef}
        onRequestClose={closeImportDialog}
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
            <div className="text-xs text-muted-foreground">
              {importPreview ? 'Файл проверен. До подтверждения данные не изменятся.' : 'Целостность файла проверяется автоматически.'}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={() => closeImportDialog('cancel')}
                className="inline-flex min-h-11 items-center justify-center rounded-md border border-border bg-surface px-4 text-sm font-medium text-foreground transition hover:bg-muted"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => void previewImport()}
                disabled={!importFile || importPreviewing || importCommitting}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border bg-surface-soft px-4 text-sm font-medium text-foreground transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                {importPreviewing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                Проверить файл
              </button>
              <button
                type="button"
                onClick={() => void commitImport()}
                disabled={!importPreview || importPreview.hasErrors || importPreview.validRows === 0 || importCommitting}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {importCommitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
                Подтвердить импорт
              </button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          {importError ? (
            <div className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
              {importError}
            </div>
          ) : null}
          <div className="rounded-md border border-border bg-surface-soft px-4 py-4">
            <label className="flex flex-col gap-2 text-sm font-medium text-foreground">
              Excel-файл
              <input
                ref={importFileInputRef}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={handleImportFileChange}
                className="min-h-11 rounded-md border border-border bg-surface px-3 py-2 text-base text-foreground outline-none file:mr-3 file:border-0 file:bg-surface-soft file:px-3 file:py-2 file:text-sm file:font-medium sm:text-sm"
              />
            </label>
            <p className="mt-2 text-sm text-muted-foreground">
              Файл не импортируется автоматически. До подтверждения можно перепроверить договоры, строки и найденные проблемы.
            </p>
          </div>

          {importPreview ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricTile label="Строк" value={String(importPreview.totalRows)} />
                <MetricTile label="Готово" value={String(importPreview.validRows)} tone="success" />
                <MetricTile label="Предупреждений" value={String(importPreview.warningRows)} tone={importPreview.warningRows > 0 ? 'warning' : 'neutral'} />
                <MetricTile label="Ошибок" value={String(importPreview.errorRows)} tone={importPreview.errorRows > 0 ? 'danger' : 'neutral'} />
              </div>

              <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
                <div className="rounded-md border border-border bg-surface-soft px-4 py-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Boxes className="h-4 w-4 text-muted-foreground" />
                    {importTargetCaseId ? 'Договор в файле' : 'Договоры в файле'}
                  </div>
                  <div className="mt-3 space-y-2">
                    {importPreview.groups.map((group) => (
                      <div key={group.id} className="rounded-md border border-border bg-surface px-3 py-3 text-sm">
                        <div className="font-medium text-foreground">{group.name}</div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                          <span>{group.rowCount} строк</span>
                          <span className="text-emerald-700 dark:text-emerald-300">{group.validCount} готово</span>
                          {group.warningCount > 0 ? (
                            <span className="text-amber-700 dark:text-amber-300">{group.warningCount} предупреждений</span>
                          ) : null}
                          <span className="text-rose-700 dark:text-rose-300">{group.errorCount} ошибок</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-md border border-border bg-surface-soft">
                  <div className="border-b border-border px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
                      {importPreview.hasErrors ? (
                        <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-300" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-300" />
                      )}
                      Атомы для импорта
                    </div>
                  </div>
                  <div className="max-h-[420px] overflow-auto">
                    <table className="min-w-full border-collapse text-sm">
                      <thead className="sticky top-0 bg-surface">
                        <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
                          <th className="px-3 py-3">Строка</th>
                          <th className="px-3 py-3">Договор</th>
                          <th className="px-3 py-3">Название</th>
                          <th className="px-3 py-3">Проверка</th>
                        </tr>
                      </thead>
                      <tbody>
                        {importPreview.rows.map((row) => (
                          <tr key={`${row.groupId}-${row.rowNumber}`} className={cn('border-b border-border/80 align-top', !row.ready && 'bg-rose-500/5')}>
                            <td className="px-3 py-3 text-muted-foreground">{row.rowNumber}</td>
                            <td className="px-3 py-3 text-muted-foreground">{row.groupName}</td>
                            <td className="min-w-[20rem] px-3 py-3 whitespace-normal break-words text-foreground">{row.title}</td>
                            <td className="min-w-[18rem] px-3 py-3 text-muted-foreground">
                              {row.issues.length === 0 ? (
                                <span className="text-emerald-700 dark:text-emerald-300">Готово</span>
                              ) : (
                                <ul className="space-y-1">
                                  {row.issues.map((issue, issueIndex) => (
                                    <li
                                      key={`${issue.severity}-${issueIndex}-${issue.text}`}
                                      className={cn(
                                        'whitespace-normal break-words',
                                        issue.severity === 'warning'
                                          ? 'text-amber-700 dark:text-amber-300'
                                          : 'text-rose-700 dark:text-rose-300'
                                      )}
                                    >
                                      {issue.text}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-md border border-dashed border-border bg-surface-soft px-6 py-12 text-center">
              <Upload className="mx-auto h-8 w-8 text-muted-foreground" />
              <h3 className="mt-3 text-base font-semibold text-foreground">Сначала проверьте файл</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                После проверки здесь появятся договоры, атомы и найденные ошибки.
              </p>
            </div>
          )}
        </div>
      </DialogShell>
    </div>
  )
}
