import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  CircleDollarSign,
  Link2,
  Loader2,
  RefreshCw,
  Search,
  LockKeyhole,
  Unlink,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  AcceptanceMode,
  Complexity,
  League,
  TaskPriority,
  TaskStatus,
  TaskType,
  WorkEntityExecutionContract,
  WorkEntityExecutionContractCreate,
  WorkEntityExecutionContractTaskOption,
  WorkEntityStatus,
  WorkEntityTask,
} from '@/api/types'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { cn } from '@/lib/utils'

const inputClass =
  'h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15'
const textareaClass =
  'w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15'

const taskStatusLabels: Record<TaskStatus, string> = {
  new: 'Новая',
  estimated: 'Оценена',
  in_queue: 'В очереди',
  in_progress: 'В работе',
  review: 'На приемке',
  done: 'Принята',
  cancelled: 'Отменена',
}

const taskTypeLabels: Record<TaskType, string> = {
  widget: 'Виджет',
  etl: 'ETL',
  api: 'API',
  docs: 'Документация',
  proactive: 'Проактивная работа',
  bugfix: 'Исправление ошибки',
}

const priorityLabels: Record<TaskPriority, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  critical: 'Критичный',
}

const acceptanceStateLabels = {
  none: 'Не настроена',
  submitted: 'Ожидает решения',
  partially_accepted: 'Принята частично',
  returned: 'Возвращена',
  accepted: 'Принята',
} as const

function formatDate(value: string | null | undefined) {
  if (!value) return 'не задан'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function toInputDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function uuidV4() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`
}

function contractTone(status: TaskStatus) {
  if (status === 'done') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (status === 'in_progress' || status === 'review') {
    return 'border-sky-200 bg-sky-50 text-sky-800'
  }
  if (status === 'cancelled') return 'border-slate-200 bg-slate-100 text-slate-500'
  return 'border-violet-200 bg-violet-50 text-violet-800'
}

export function OperationExecutionContractButton({
  operation,
  projectStatus,
  onClick,
  compact = false,
}: {
  operation: WorkEntityTask
  projectStatus: WorkEntityStatus
  onClick: () => void
  compact?: boolean
}) {
  const contract = operation.execution_contract
  if (!contract && !operation.can_manage_execution_contract) return null
  const publicationLocked = !contract && projectStatus !== 'active'
  const publicationTitle = projectStatus === 'draft'
    ? 'Сначала активируйте проект и зафиксируйте базовый план'
    : 'Публикация в Q-пул доступна только в активном проекте'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={publicationLocked}
      className={cn(
        'inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold transition hover:brightness-95 disabled:cursor-not-allowed disabled:hover:brightness-100',
        contract
          ? contractTone(contract.task_status)
          : publicationLocked
            ? 'border-slate-200 bg-slate-100 text-slate-500'
          : 'border-primary/25 bg-primary/5 text-primary hover:bg-primary/10',
      )}
      title={contract ? 'Открыть контракт Q-исполнения' : publicationLocked ? publicationTitle : 'Опубликовать операцию в Q-пул'}
    >
      {contract
        ? <CircleDollarSign className="h-4 w-4" />
        : publicationLocked
          ? <LockKeyhole className="h-4 w-4" />
          : <ArrowRightLeft className="h-4 w-4" />}
      {contract ? (
        <>
          <span>Q #{contract.task_number}</span>
          {!compact && <span className="font-medium">· {Number(contract.estimated_q)} Q</span>}
        </>
      ) : (
        <span>{compact ? 'Q-пул' : 'Опубликовать в Q-пул'}</span>
      )}
    </button>
  )
}

function ContractSummary({ contract }: { contract: WorkEntityExecutionContract }) {
  const accepted = contract.acceptance_mode === 'criteria'
    ? `${contract.acceptance_required_accepted_count}/${contract.acceptance_required_count} обязательных · ${acceptanceStateLabels[contract.acceptance_state]}`
    : `Целиком · ${acceptanceStateLabels[contract.acceptance_state]}`
  const resultUrl = (() => {
    if (!contract.result_url) return null
    try {
      const parsed = new URL(contract.result_url)
      return parsed.protocol === 'http:' || parsed.protocol === 'https:'
        ? parsed.toString()
        : null
    } catch {
      return null
    }
  })()

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-slate-900">Q #{contract.task_number}</span>
          <span className={cn('rounded px-2 py-0.5 text-xs font-medium', contractTone(contract.task_status))}>
            {taskStatusLabels[contract.task_status]}
          </span>
          <span className="rounded bg-white px-2 py-0.5 text-xs font-semibold text-slate-700">
            {Number(contract.estimated_q)} Q
          </span>
        </div>
        <h4 className="mt-2 break-words text-base font-semibold text-slate-900 [overflow-wrap:anywhere]">
          {contract.task_title}
        </h4>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-slate-500">Исполнитель</dt>
            <dd className="mt-0.5 font-medium text-slate-800">{contract.assignee_name || 'Еще не назначен'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Срок Q-задачи</dt>
            <dd className="mt-0.5 font-medium text-slate-800">{formatDate(contract.due_date)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Приемка</dt>
            <dd className="mt-0.5 font-medium text-slate-800">{accepted}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Источник</dt>
            <dd className="mt-0.5 font-medium text-slate-800">
              {contract.source === 'created_from_operation' ? 'Создана из операции' : 'Связана существующая Q-задача'}
            </dd>
          </div>
        </dl>
        {(contract.result_comment || contract.result_url) && (
          <div className="mt-4 border-t border-slate-200 pt-3 text-sm">
            <p className="text-xs font-semibold uppercase text-slate-500">Результат Q-задачи</p>
            {contract.result_comment && (
              <p className="mt-2 whitespace-pre-wrap break-words text-slate-700 [overflow-wrap:anywhere]">
                {contract.result_comment}
              </p>
            )}
            {contract.result_url && (
              resultUrl ? (
                <a
                  href={resultUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex max-w-full items-center gap-1 break-all font-medium text-primary hover:underline"
                >
                  <Link2 className="h-4 w-4 shrink-0" />
                  {contract.result_url}
                </a>
              ) : (
                <p className="mt-2 break-all text-slate-600">{contract.result_url}</p>
              )
            )}
          </div>
        )}
      </div>
      <p className="text-xs leading-5 text-slate-500">
        Статус, исполнитель, результат и приемка берутся из глобальной Q-задачи. Проектная операция сохраняет собственный план и журнал.
      </p>
    </div>
  )
}

export function OperationExecutionContractModal({
  entityId,
  operation,
  onClose,
  onChanged,
}: {
  entityId: string
  operation: WorkEntityTask
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const panelRef = useProtectedModal<HTMLDivElement>()
  const [currentContract, setCurrentContract] = useState(operation.execution_contract)
  const [contractLoading, setContractLoading] = useState(true)
  const [contractLoadError, setContractLoadError] = useState<string | null>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [mode, setMode] = useState<'publish' | 'link'>('publish')
  const [idempotencyKey] = useState(uuidV4)
  const [busy, setBusy] = useState(false)
  const [optionsLoading, setOptionsLoading] = useState(false)
  const [optionsError, setOptionsError] = useState<string | null>(null)
  const [options, setOptions] = useState<WorkEntityExecutionContractTaskOption[]>([])
  const [search, setSearch] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [title, setTitle] = useState(operation.title)
  const [description, setDescription] = useState(operation.description || '')
  const [taskType, setTaskType] = useState<TaskType>('docs')
  const [complexity, setComplexity] = useState<Complexity>('M')
  const [estimatedQ, setEstimatedQ] = useState('1')
  const [priority, setPriority] = useState<TaskPriority>(operation.priority)
  const [minLeague, setMinLeague] = useState<League>('C')
  const [dueDate, setDueDate] = useState(
    toInputDate(operation.forecast_due_at || operation.baseline_due_at),
  )
  const [tags, setTags] = useState('')
  const [acceptanceMode, setAcceptanceMode] = useState<AcceptanceMode>('criteria')
  const [criteriaText, setCriteriaText] = useState(operation.acceptance_criteria || '')
  const [releaseReason, setReleaseReason] = useState('')

  const criteria = useMemo(
    () => criteriaText
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean),
    [criteriaText],
  )

  const loadContract = useCallback(async () => {
    setContractLoading(true)
    setContractLoadError(null)
    try {
      const result = await api.get<WorkEntityExecutionContract | null>(
        `/api/work-entities/${entityId}/tasks/${operation.id}/execution-contract`,
      )
      setCurrentContract(result)
    } catch (error) {
      setContractLoadError(
        error instanceof Error ? error.message : 'Не удалось проверить актуальный Q-контракт',
      )
    } finally {
      setContractLoading(false)
    }
  }, [entityId, operation.id])

  useEffect(() => {
    void loadContract()
  }, [loadContract])

  const loadOptions = async () => {
    setOptionsLoading(true)
    setOptionsError(null)
    try {
      const result = await api.get<WorkEntityExecutionContractTaskOption[]>(
        `/api/work-entities/${entityId}/tasks/${operation.id}/execution-contract-options`,
        { search: search.trim(), limit: '50' },
      )
      setOptions(result)
      if (selectedTaskId && !result.some((item) => item.task_id === selectedTaskId)) {
        setSelectedTaskId('')
      }
    } catch (error) {
      setOptionsError(error instanceof Error ? error.message : 'Не удалось загрузить Q-задачи')
    } finally {
      setOptionsLoading(false)
    }
  }

  useEffect(() => {
    if (mode === 'link' && !currentContract && !contractLoading && !contractLoadError) {
      void loadOptions()
    }
    // Search is applied explicitly so typing does not issue a request per key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, entityId, operation.id, currentContract, contractLoading, contractLoadError])

  const refreshParent = async (successMessage: string) => {
    toast.success(successMessage)
    setRefreshError(null)
    try {
      await onChanged()
      onClose()
    } catch {
      setRefreshError('Изменение сохранено, но список проекта не обновился. Повторите обновление.')
      toast.error('Изменение сохранено. Не удалось обновить экран проекта.')
    }
  }

  const retryParentRefresh = async () => {
    setBusy(true)
    setRefreshError(null)
    try {
      await onChanged()
      toast.success('Данные проекта обновлены')
      onClose()
    } catch {
      setRefreshError('Изменение сохранено, но список проекта не обновился. Повторите обновление.')
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const payload: WorkEntityExecutionContractCreate = mode === 'link'
      ? {
          mode: 'link',
          idempotency_key: idempotencyKey,
          task_id: selectedTaskId,
        }
      : {
          mode: 'publish',
          idempotency_key: idempotencyKey,
          title: title.trim(),
          description: description.trim() || null,
          task_type: taskType,
          complexity,
          estimated_q: Number(estimatedQ),
          priority,
          min_league: minLeague,
          due_date: dueDate ? new Date(dueDate).toISOString() : undefined,
          tags: tags.split(',').map((item) => item.trim()).filter(Boolean),
          acceptance_mode: acceptanceMode,
          acceptance_criteria: acceptanceMode === 'criteria'
            ? criteria.map((criterion) => ({ title: criterion, kind: 'required' as const }))
            : [],
        }

    if (mode === 'link' && !selectedTaskId) {
      toast.error('Выберите Q-задачу')
      return
    }
    if (mode === 'publish') {
      if (!title.trim() || title.trim().length < 5 || !dueDate || Number(estimatedQ) < 0) {
        toast.error('Заполните название, Q и срок исполнения')
        return
      }
      if (acceptanceMode === 'criteria' && criteria.length === 0) {
        toast.error('Добавьте хотя бы один критерий приемки')
        return
      }
    }

    setBusy(true)
    try {
      const contract = await api.post<WorkEntityExecutionContract>(
        `/api/work-entities/${entityId}/tasks/${operation.id}/execution-contract`,
        payload,
      )
      setCurrentContract(contract)
      await refreshParent(
        mode === 'publish' ? 'Операция опубликована в Q-пул' : 'Q-задача связана с операцией',
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось создать Q-контракт')
    } finally {
      setBusy(false)
    }
  }

  const release = async () => {
    if (releaseReason.trim().length < 5) {
      toast.error('Укажите причину освобождения')
      return
    }
    setBusy(true)
    try {
      const contract = await api.patch<WorkEntityExecutionContract>(
        `/api/work-entities/${entityId}/tasks/${operation.id}/execution-contract`,
        { reason: releaseReason.trim() },
      )
      setCurrentContract(contract)
      await refreshParent('Q-контракт освобожден')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось освободить контракт')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/55 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="operation-contract-title"
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="max-h-[100dvh] w-full overflow-y-auto rounded-t-lg bg-white pb-[env(safe-area-inset-bottom)] shadow-2xl sm:max-h-[92vh] sm:max-w-3xl sm:rounded-lg sm:pb-0"
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <div className="min-w-0">
            <h3 id="operation-contract-title" className="text-base font-semibold text-slate-900">
              Q-исполнение операции PRJ-{operation.task_number}
            </h3>
            <p className="mt-0.5 truncate text-xs text-slate-500">{operation.title}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 disabled:opacity-50"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="p-4 sm:p-5">
          {refreshError && (
            <div role="alert" className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p>{refreshError}</p>
                <button
                  type="button"
                  onClick={() => void retryParentRefresh()}
                  disabled={busy}
                  className="mt-2 inline-flex items-center gap-1.5 font-semibold text-amber-950 hover:underline disabled:opacity-50"
                >
                  <RefreshCw className={cn('h-4 w-4', busy && 'animate-spin')} />
                  Обновить проект
                </button>
              </div>
            </div>
          )}
          {contractLoading ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Проверяем Q-контракт
            </div>
          ) : contractLoadError ? (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">Не удалось проверить актуальное состояние</p>
                  <p className="mt-1 break-words text-red-800">{contractLoadError}</p>
                  <button
                    type="button"
                    onClick={() => void loadContract()}
                    className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-red-200 bg-white px-3 font-semibold hover:bg-red-100"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Повторить
                  </button>
                </div>
              </div>
            </div>
          ) : currentContract ? (
            <div className="space-y-5">
              <ContractSummary contract={currentContract} />
              {currentContract.can_release && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                  <div className="flex items-start gap-2">
                    <Unlink className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
                    <div>
                      <h4 className="text-sm font-semibold text-amber-950">Освободить контракт</h4>
                      <p className="mt-1 text-xs leading-5 text-amber-800">
                        Доступно только до назначения исполнителя и начала работы. Действие и причина сохранятся в истории.
                      </p>
                    </div>
                  </div>
                  <textarea
                    value={releaseReason}
                    onChange={(event) => setReleaseReason(event.target.value)}
                    rows={3}
                    maxLength={4000}
                    placeholder="Почему Q-задача больше не должна исполнять эту операцию"
                    className={cn(textareaClass, 'mt-3 border-amber-200')}
                  />
                  <button
                    type="button"
                    onClick={() => void release()}
                    disabled={busy || releaseReason.trim().length < 5}
                    className="mt-3 inline-flex h-10 items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                  >
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Unlink className="h-4 w-4" />}
                    Освободить
                  </button>
                </div>
              )}
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-5">
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
                <button
                  type="button"
                  onClick={() => setMode('publish')}
                  aria-pressed={mode === 'publish'}
                  className={cn(
                    'inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium',
                    mode === 'publish' ? 'bg-white text-primary shadow-sm' : 'text-slate-600',
                  )}
                >
                  <CircleDollarSign className="h-4 w-4" />
                  Новая Q-задача
                </button>
                <button
                  type="button"
                  onClick={() => setMode('link')}
                  aria-pressed={mode === 'link'}
                  className={cn(
                    'inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium',
                    mode === 'link' ? 'bg-white text-primary shadow-sm' : 'text-slate-600',
                  )}
                >
                  <Link2 className="h-4 w-4" />
                  Связать готовую
                </button>
              </div>

              {mode === 'link' ? (
                <div className="space-y-3">
                  <div className="flex gap-2">
                    <label className="relative min-w-0 flex-1">
                      <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-400" />
                      <input
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Номер или название Q-задачи"
                        className={cn(inputClass, 'pl-9')}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => void loadOptions()}
                      disabled={optionsLoading}
                      className="inline-flex h-11 items-center justify-center rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {optionsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Найти'}
                    </button>
                  </div>
                  <div className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
                    {optionsError && (
                      <div role="alert" className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="break-words">{optionsError}</p>
                          <button type="button" onClick={() => void loadOptions()} className="mt-1 font-semibold hover:underline">
                            Повторить загрузку
                          </button>
                        </div>
                      </div>
                    )}
                    {options.length === 0 && !optionsLoading && !optionsError ? (
                      <p className="p-4 text-sm text-slate-500">
                        Нет доступных неназначенных Q-задач со сроком.
                      </p>
                    ) : options.map((option) => (
                      <label key={option.task_id} className="flex cursor-pointer items-start gap-3 p-3 hover:bg-slate-50">
                        <input
                          type="radio"
                          name="q-task"
                          value={option.task_id}
                          checked={selectedTaskId === option.task_id}
                          onChange={() => setSelectedTaskId(option.task_id)}
                          className="mt-1 h-4 w-4 border-slate-300 text-primary"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block break-words text-sm font-semibold text-slate-900 [overflow-wrap:anywhere]">
                            Q #{option.task_number} · {option.title}
                          </span>
                          <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                            <span>{Number(option.estimated_q)} Q</span>
                            <span>{priorityLabels[option.priority]}</span>
                            <span>до {formatDate(option.due_date)}</span>
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="sm:col-span-2">
                      <span className="mb-1 block text-sm font-medium text-slate-800">Название Q-задачи</span>
                      <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} className={inputClass} autoFocus />
                    </label>
                    <label className="sm:col-span-2">
                      <span className="mb-1 block text-sm font-medium text-slate-800">Что должен получить заказчик</span>
                      <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} maxLength={8000} className={textareaClass} />
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Тип работы</span>
                      <select value={taskType} onChange={(event) => setTaskType(event.target.value as TaskType)} className={inputClass}>
                        {Object.entries(taskTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Сложность</span>
                      <select value={complexity} onChange={(event) => setComplexity(event.target.value as Complexity)} className={inputClass}>
                        {(['S', 'M', 'L', 'XL'] as Complexity[]).map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Цена, Q</span>
                      <input type="number" min={0} max={9999} step="0.1" value={estimatedQ} onChange={(event) => setEstimatedQ(event.target.value)} className={inputClass} />
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Приоритет</span>
                      <select value={priority} onChange={(event) => setPriority(event.target.value as TaskPriority)} className={inputClass}>
                        {Object.entries(priorityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Минимальная лига</span>
                      <select value={minLeague} onChange={(event) => setMinLeague(event.target.value as League)} className={inputClass}>
                        {(['C', 'B', 'A'] as League[]).map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    </label>
                    <label>
                      <span className="mb-1 block text-sm font-medium text-slate-800">Срок исполнения</span>
                      <input type="datetime-local" value={dueDate} onChange={(event) => setDueDate(event.target.value)} className={inputClass} />
                    </label>
                    <label className="sm:col-span-2">
                      <span className="mb-1 block text-sm font-medium text-slate-800">Теги</span>
                      <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="проект, дизайн, закупка" className={inputClass} />
                    </label>
                  </div>

                  <fieldset className="rounded-lg border border-slate-200 p-4">
                    <legend className="px-1 text-sm font-semibold text-slate-900">Приемка результата</legend>
                    <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
                      <button type="button" aria-pressed={acceptanceMode === 'criteria'} onClick={() => setAcceptanceMode('criteria')} className={cn('min-h-9 rounded-md px-2 text-xs font-medium', acceptanceMode === 'criteria' ? 'bg-white text-primary shadow-sm' : 'text-slate-600')}>По критериям</button>
                      <button type="button" aria-pressed={acceptanceMode === 'full'} onClick={() => setAcceptanceMode('full')} className={cn('min-h-9 rounded-md px-2 text-xs font-medium', acceptanceMode === 'full' ? 'bg-white text-primary shadow-sm' : 'text-slate-600')}>Целиком</button>
                    </div>
                    {acceptanceMode === 'criteria' && (
                      <label className="mt-3 block">
                        <span className="mb-1 block text-xs text-slate-500">Один обязательный критерий на строку. Исполнитель сможет сдавать их частями.</span>
                        <textarea value={criteriaText} onChange={(event) => setCriteriaText(event.target.value)} rows={5} className={textareaClass} placeholder={'Макет согласован\nФайлы переданы заказчику'} />
                      </label>
                    )}
                  </fieldset>
                </div>
              )}

              <div className="flex flex-col-reverse gap-2 border-t border-slate-200 pt-4 sm:flex-row sm:justify-end">
                <button type="button" onClick={onClose} disabled={busy} className="h-11 rounded-lg border border-slate-200 px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">Отмена</button>
                <button type="submit" disabled={busy} className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {mode === 'publish' ? 'Опубликовать в Q-пул' : 'Связать Q-задачу'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
