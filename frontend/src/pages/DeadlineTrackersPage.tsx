import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive, CalendarClock, CheckCircle2, ChevronDown, ChevronRight, Clock3, FolderCog, History,
  List, Link2, Network, PauseCircle, Pencil, PlayCircle, Plus, RefreshCw, Repeat2, Search, Square, Tags, Trash2, X,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import { deadlineTrackers } from '@/api/deadlineTrackers'
import type { DeadlineTracker, DeadlineTrackerStatus, DeadlineTrackerType, DeadlineTrackerUpdate, PersonalTask } from '@/api/types'
import { cn } from '@/lib/utils'
import { WorkEntityBacklinks } from '@/components/WorkEntityBacklinks'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { TrackerEditor } from '@/components/deadline-trackers/TrackerEditor'
import { TrackerHistory, type TrackerOccurrence } from '@/components/deadline-trackers/TrackerHistory'
import { TrackerOrganizationManager } from '@/components/deadline-trackers/TrackerOrganizationManager'
import { TrackerIconButton, trackerButton, trackerInput } from '@/components/deadline-trackers/TrackerDialog'
import { formFromTracker, newTrackerForm, trackerFormPayload, type TrackerForm, type TrackerOrganization } from '@/components/deadline-trackers/trackerForm'

type TrackerFilter = DeadlineTrackerStatus | 'all'

const trackerTypeLabel: Record<DeadlineTrackerType, string> = {
  subscription: 'Абонемент',
  system: 'Система',
  password: 'Пароль',
  task: 'Задача',
  document: 'Документ',
  payment: 'Оплата',
  other: 'Другое',
}

const statusLabel: Record<DeadlineTrackerStatus, string> = {
  active: 'Активно',
  paused: 'Пауза',
  done: 'Закрыто',
  archived: 'Архив',
}

const filterOptions: Array<{ value: TrackerFilter; label: string }> = [
  { value: 'active', label: 'Активные' },
  { value: 'paused', label: 'Пауза' },
  { value: 'done', label: 'Закрытые' },
  { value: 'archived', label: 'Архив' },
  { value: 'all', label: 'Все' },
]

function formatDate(value: string | null, timeZone?: string): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  })
}

function formatDateCompact(value: string | null): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
  })
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function pauseDays(tracker: DeadlineTracker): number {
  if (!tracker.total_pause_seconds && tracker.status !== 'paused') return 0
  if (!tracker.total_pause_seconds && tracker.status === 'paused') return 1
  return Math.max(1, Math.ceil(tracker.total_pause_seconds / 86_400))
}

function shiftedDueAt(tracker: DeadlineTracker): Date {
  const due = new Date(tracker.current_occurrence?.due_at || tracker.due_at)
  if (tracker.recurrence || tracker.personal_task_id || tracker.linked_task_id) return due
  const apiShiftedDue = tracker.shifted_due_at ? new Date(tracker.shifted_due_at) : null
  if (apiShiftedDue && apiShiftedDue.getTime() > due.getTime()) return apiShiftedDue
  return new Date(due.getTime() + pauseDays(tracker) * 86_400_000)
}

function trackerState(tracker: DeadlineTracker) {
  const noCurrentOccurrence = Boolean(tracker.recurrence && tracker.current_occurrence?.status !== 'pending')
  if (noCurrentOccurrence) {
    return { remainingPct: 0, originalRemainingPct: 0, elapsedPct: 0, overdue: false, daysLeft: 0, tone: 'muted', hasShift: false, shiftPct: 0, noCurrentOccurrence }
  }
  const start = new Date(tracker.starts_at).getTime()
  const due = new Date(tracker.recurrence ? tracker.current_occurrence?.due_at || tracker.due_at : tracker.due_at).getTime()
  const shiftedDue = shiftedDueAt(tracker).getTime()
  const now = Date.now()
  const total = Math.max(1, due - start)
  const shiftedTotal = Math.max(1, shiftedDue - start)
  const remaining = shiftedDue - now
  const originalRemaining = due - now
  const remainingPct = clamp(Math.round((remaining / total) * 100), 0, 100)
  const originalRemainingPct = clamp(Math.round((originalRemaining / total) * 100), 0, 100)
  const elapsedPct = 100 - remainingPct
  const overdue = tracker.status === 'active' && remaining < 0
  const daysLeft = Math.ceil(remaining / 86_400_000)
  const tone = overdue || remainingPct <= 20 ? 'danger' : remainingPct <= 50 ? 'warn' : 'ok'
  const hasShift = !tracker.recurrence && !tracker.personal_task_id && !tracker.linked_task_id && (tracker.total_pause_seconds > 0 || tracker.status === 'paused')
  const shiftMs = pauseDays(tracker) * 86_400_000
  const shiftPct = hasShift ? clamp(Math.round((shiftMs / shiftedTotal) * 100), 2, 100) : 0
  return { remainingPct, originalRemainingPct, elapsedPct, overdue, daysLeft, tone, hasShift, shiftPct, noCurrentOccurrence }
}

function remainingLabel(tracker: DeadlineTracker): string {
  const state = trackerState(tracker)
  if (tracker.status === 'done') return 'закрыто'
  if (tracker.status === 'archived') return 'архив'
  if (state.noCurrentOccurrence && tracker.series_exhausted) return 'Повторения завершены'
  if (tracker.status === 'paused') return 'на паузе'
  if (state.noCurrentOccurrence) return 'Нет текущего повторения'
  if (state.overdue) return `просрочено на ${Math.abs(state.daysLeft)} дн.`
  if (state.daysLeft <= 0) return 'сегодня'
  return `осталось ${state.daysLeft} дн.`
}

function shiftLabel(tracker: DeadlineTracker): string {
  const days = pauseDays(tracker)
  return days ? `+${days} дн.` : ''
}

function Metric({ label, value, tone = 'muted' }: { label: string; value: number; tone?: 'muted' | 'danger' | 'ok' }) {
  return (
        <div className="min-w-0 border-r border-slate-100 px-2 py-3 last:border-r-0 sm:px-4">
      <div className={cn('text-lg font-semibold', tone === 'danger' ? 'text-rose-600' : tone === 'ok' ? 'text-emerald-600' : 'text-slate-900')}>
        {value}
      </div>
      <div className="break-words text-[10px] text-slate-500">{label}</div>
    </div>
  )
}

function DeadlineBar({ tracker, compact = false }: { tracker: DeadlineTracker; compact?: boolean }) {
  const state = trackerState(tracker)
  if (state.noCurrentOccurrence) return null
  const label = remainingLabel(tracker)
  return (
    <div className={cn('space-y-1.5', compact && 'space-y-1')}>
      <div className="grid grid-cols-[44px_minmax(0,1fr)] items-center gap-2">
        <span className="text-[10px] font-medium uppercase text-slate-400">срок</span>
        <div
          className={cn('overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-700/70', compact ? 'h-2' : 'h-2.5')}
          title={label}
          aria-label={label}
        >
          <div
            className={cn(
              'ml-auto h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none',
              state.tone === 'danger' ? 'bg-rose-500' : state.tone === 'warn' ? 'bg-amber-500' : 'bg-emerald-500',
            )}
            style={{ width: `${Math.max(state.originalRemainingPct, 2)}%` }}
          />
        </div>
      </div>
      {state.hasShift && (
        <div className="grid grid-cols-[44px_minmax(0,1fr)] items-center gap-2" title="Смещение срока из-за паузы">
          <span className="text-[10px] font-medium uppercase text-rose-400">сдвиг</span>
          <div className={cn('overflow-hidden rounded-full bg-slate-200/80 ring-1 ring-inset ring-slate-300/70 dark:bg-slate-700/70 dark:ring-slate-600/70', compact ? 'h-2' : 'h-2.5')}>
            <div
              className="h-full rounded-full bg-rose-500 transition-[width] duration-300 motion-reduce:transition-none"
              style={{ width: `${state.shiftPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

function EntityLinkModal({
  tracker,
  onClose,
}: {
  tracker: DeadlineTracker
  onClose: () => void
}) {
  const panelRef = useProtectedModal<HTMLDivElement>()

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Проекты и цели: ${tracker.title}`}
      onPointerDown={preventBackdropDismiss}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className="w-full rounded-t-lg bg-white p-4 shadow-2xl sm:max-w-xl sm:rounded-lg"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900">Проекты и цели</h2>
            <p className="truncate text-xs text-slate-500">{tracker.title}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <WorkEntityBacklinks
          targetType="deadline_tracker"
          targetId={tracker.id}
          className="bg-white"
        />
      </div>
    </div>
  )
}


function sourceLabel(tracker: DeadlineTracker) {
  return tracker.personal_task_id ? 'Личная задача' : tracker.linked_task_id ? 'Q-задача' : 'Самостоятельный'
}

function TrackerActions({ tracker, busy, onLinks, onEdit, onHistory, onPatch, onComplete, onFinish, onDelete }: {
  tracker: DeadlineTracker; busy: boolean; onLinks: () => void; onEdit: () => void; onHistory: () => void
  onPatch: (patch: DeadlineTrackerUpdate, message: string) => void; onComplete: () => void; onFinish: () => void; onDelete: () => void
}) {
  const live = tracker.status === 'active' || tracker.status === 'paused'
  return <div className="flex flex-wrap items-center justify-end gap-1" aria-label="Действия трекера">
    <TrackerIconButton label="Проекты и цели" icon={Network} onClick={onLinks} disabled={busy} />
    {tracker.status === 'paused' && <TrackerIconButton label="Снять паузу" icon={PlayCircle} disabled={busy} onClick={() => onPatch({ status: 'active' }, 'Пауза снята')} />}
    {tracker.status === 'active' && <TrackerIconButton label="Поставить на паузу" icon={PauseCircle} tone="warning" disabled={busy} onClick={() => onPatch({ status: 'paused' }, 'Трекер на паузе')} />}
    {live && (tracker.recurrence ? <>
      {tracker.current_occurrence?.status === 'pending' && <TrackerIconButton label="Завершить повторение" icon={CheckCircle2} tone="success" disabled={busy} onClick={onComplete} />}
      <TrackerIconButton label="Завершить серию" icon={Square} disabled={busy} onClick={onFinish} />
    </> : <TrackerIconButton label="Закрыть трекер" icon={CheckCircle2} tone="success" disabled={busy} onClick={() => onPatch({ status: 'done' }, 'Трекер закрыт')} />)}
    {!live && <TrackerIconButton label="Вернуть трекер" icon={Clock3} disabled={busy} onClick={() => onPatch({ status: 'active' }, 'Трекер активен')} />}
    <TrackerIconButton label="Редактировать трекер" icon={Pencil} disabled={busy} onClick={onEdit} />
    <TrackerIconButton label="История трекера" icon={History} disabled={busy} onClick={onHistory} />
    {tracker.status !== 'archived' && <TrackerIconButton label="Архивировать трекер" icon={Archive} disabled={busy} onClick={() => onPatch({ status: 'archived' }, 'Трекер в архиве')} />}
    <TrackerIconButton label="Удалить трекер" icon={Trash2} tone="danger" disabled={busy} onClick={onDelete} />
  </div>
}

export function DeadlineTrackersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTrackerId = searchParams.get('tracker')
  const filterValue = searchParams.get('status') || (requestedTrackerId ? 'all' : 'active')
  const filter: TrackerFilter = filterOptions.some((item) => item.value === filterValue) ? filterValue as TrackerFilter : 'active'
  const categoryFilter = searchParams.get('category') || 'all'
  const search = searchParams.get('q') || ''
  const showArchivedGroups = searchParams.get('archived_groups') === 'true'
  const compactView = searchParams.get('view') !== 'full' && !requestedTrackerId
  const [searchInput, setSearchInput] = useState(search)
  const [trackers, setTrackers] = useState<DeadlineTracker[]>([])
  const [groups, setGroups] = useState<TrackerOrganization[]>([])
  const [categories, setCategories] = useState<TrackerOrganization[]>([])
  const [personalTasks, setPersonalTasks] = useState<PersonalTask[]>([])
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [organizationError, setOrganizationError] = useState('')
  const [organizationLoading, setOrganizationLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [paging, setPaging] = useState({ key: '', index: 0 })
  const [hasMore, setHasMore] = useState(false)
  const [organizationRevision, setOrganizationRevision] = useState(0)
  const [editor, setEditor] = useState<{ tracker: DeadlineTracker | null; initial: TrackerForm } | null>(null)
  const [manager, setManager] = useState<'groups' | 'categories' | null>(null)
  const [entityLinkTracker, setEntityLinkTracker] = useState<DeadlineTracker | null>(null)
  const [target, setTarget] = useState<DeadlineTracker | null>(null)
  const [targetError, setTargetError] = useState('')
  const [targetLoading, setTargetLoading] = useState(false)
  const [targetRevision, setTargetRevision] = useState(0)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [readError, setReadError] = useState('')
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const pending = useRef(new Set<string>())
  const listGeneration = useRef(0)
  const listAbort = useRef<AbortController | null>(null)
  const organizationAbort = useRef<AbortController | null>(null)
  const organizationGeneration = useRef(0)
  const sourceAbort = useRef<AbortController | null>(null)
  const activeTarget = useRef(requestedTrackerId)
  activeTarget.current = requestedTrackerId
  const queryKey = JSON.stringify([categoryFilter, filter, search, revision])
  const pageIndex = paging.key === queryKey ? paging.index : 0

  const updateQuery = useCallback((key: string, value: string | null, replace = false) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace })
  }, [setSearchParams])

  useEffect(() => { setSearchInput(search) }, [search])
  useEffect(() => {
    if (searchInput === search) return
    const timer = window.setTimeout(() => updateQuery('q', searchInput.trim() || null, true), 300)
    return () => window.clearTimeout(timer)
  }, [search, searchInput, updateQuery])

  useEffect(() => {
    const controller = new AbortController()
    listAbort.current = controller
    const generation = ++listGeneration.current
    setLoading(true); setLoadError('')
    const params: Record<string, string> = { include_archived: 'true', limit: '300', offset: String(pageIndex * 300) }
    if (filter !== 'all') params.status = filter
    if (categoryFilter !== 'all' && categoryFilter !== 'none') params.category_id = categoryFilter
    if (search) params.search = search
    void deadlineTrackers.list(params, controller.signal).then((data) => {
      if (!controller.signal.aborted && generation === listGeneration.current) {
        setTrackers((previous) => pageIndex === 0 ? data : [...previous.filter((item) => !data.some((row) => row.id === item.id)), ...data])
        setHasMore(data.length === 300)
      }
    }).catch((error) => {
      if (!controller.signal.aborted && generation === listGeneration.current) setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить трекеры')
    }).finally(() => {
      if (!controller.signal.aborted && generation === listGeneration.current) setLoading(false)
    })
    return () => controller.abort()
  }, [categoryFilter, filter, pageIndex, revision, search])

  useEffect(() => {
    const controller = new AbortController()
    organizationAbort.current = controller
    const generation = ++organizationGeneration.current
    setOrganizationLoading(true); setOrganizationError('')
    void deadlineTrackers.organizations(controller.signal).then((data) => {
      if (!controller.signal.aborted && generation === organizationGeneration.current) { setGroups(data.groups); setCategories(data.categories) }
    }).catch((error) => {
      if (!controller.signal.aborted && generation === organizationGeneration.current) setOrganizationError(error instanceof Error ? error.message : 'Не удалось загрузить группы и категории')
    }).finally(() => { if (!controller.signal.aborted && generation === organizationGeneration.current) setOrganizationLoading(false) })
    return () => controller.abort()
  }, [organizationRevision])

  const loadSources = useCallback(() => {
    sourceAbort.current?.abort()
    const controller = new AbortController()
    sourceAbort.current = controller
    setSourceError(null)
    void api.get<PersonalTask[]>('/api/personal-tasks', { status: 'active', limit: '300' }, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setPersonalTasks(data)
    }).catch((error) => { if (!controller.signal.aborted) setSourceError(error instanceof Error ? error.message : 'Задачи недоступны') })
  }, [])
  useEffect(() => () => sourceAbort.current?.abort(), [])

  const markRead = useCallback(async (id: string) => {
    try {
      await deadlineTrackers.markRead(id)
      if (activeTarget.current === id) setReadError('')
      window.dispatchEvent(new Event('dpms:attention-refresh'))
    } catch (error) {
      if (activeTarget.current === id) setReadError(error instanceof Error ? error.message : 'Не удалось отметить напоминания прочитанными')
    }
  }, [])

  useEffect(() => {
    if (!requestedTrackerId) { setTarget(null); setTargetError(''); setHistoryOpen(false); return }
    const controller = new AbortController()
    setTargetLoading(true); setTargetError(''); setReadError(''); setTarget(null)
    // A deep link is not limited by the current list, group visibility, or its 300-row cap.
    void deadlineTrackers.get(requestedTrackerId, controller.signal).then((tracker) => {
      if (controller.signal.aborted) return
      setTarget(tracker); setHistoryOpen(true)
      void markRead(tracker.id)
    }).catch((error) => {
      if (!controller.signal.aborted) setTargetError(error instanceof Error ? error.message : 'Трекер недоступен или удален')
    }).finally(() => { if (!controller.signal.aborted) setTargetLoading(false) })
    return () => controller.abort()
  }, [markRead, requestedTrackerId, targetRevision])

  useEffect(() => {
    if (!target || target.id !== requestedTrackerId) return
    const frame = window.requestAnimationFrame(() => document.getElementById('deadline-tracker-' + target.id)?.scrollIntoView({ block: 'center' }))
    return () => window.cancelAnimationFrame(frame)
  }, [requestedTrackerId, target])

  const runMutation = useCallback(async (id: string, action: () => Promise<DeadlineTracker | null>, message: string) => {
    if (pending.current.has(id)) return
    pending.current.add(id); setBusyIds(new Set(pending.current))
    listGeneration.current += 1; listAbort.current?.abort(); setLoading(false)
    setRowErrors((previous) => ({ ...previous, [id]: '' }))
    try {
      const changed = await action()
      setTrackers((previous) => changed ? previous.map((item) => item.id === id ? changed : item) : previous.filter((item) => item.id !== id))
      if (changed) setTarget((current) => current?.id === id ? changed : current)
      else if (activeTarget.current === id) { setTarget(null); setHistoryOpen(false); updateQuery('tracker', null, true) }
      setRevision((value) => value + 1)
      window.dispatchEvent(new Event('dpms:attention-refresh'))
      toast.success(message)
    } catch (error) {
      const messageText = error instanceof Error ? error.message : 'Не удалось сохранить изменения'
      setRowErrors((previous) => ({ ...previous, [id]: messageText }))
      toast.error(messageText)
      setRevision((value) => value + 1)
    } finally { pending.current.delete(id); setBusyIds(new Set(pending.current)) }
  }, [updateQuery])

  const patchTracker = (tracker: DeadlineTracker, patch: DeadlineTrackerUpdate, message: string) => {
    if (patch.status === 'archived' && !window.confirm('Архивировать трекер? Новые напоминания поступать не будут.')) return
    void runMutation(tracker.id, () => deadlineTrackers.update(tracker.id, patch), message)
  }
  const finishSeries = (tracker: DeadlineTracker) => {
    if (!window.confirm('Завершить всю серию? Будущие повторения и напоминания прекратятся. История сохранится.')) return
    void runMutation(tracker.id, () => deadlineTrackers.finishSeries(tracker.id), 'Серия завершена')
  }
  const completeOccurrence = (tracker: DeadlineTracker, occurrence: TrackerOccurrence) =>
    runMutation(tracker.id, () => deadlineTrackers.completeOccurrence(tracker.id, occurrence.id), 'Повторение завершено')
  const deleteTracker = (tracker: DeadlineTracker) => {
    if (!window.confirm('Удалить трекер срока вместе с его историей? Исходная задача не удалится.')) return
    void runMutation(tracker.id, async () => { await deadlineTrackers.remove(tracker.id); return null }, 'Трекер удален')
  }
  const openEdit = async (tracker: DeadlineTracker) => {
    if (pending.current.has(tracker.id)) return
    pending.current.add(tracker.id); setBusyIds(new Set(pending.current))
    try {
      const fresh = await deadlineTrackers.get(tracker.id)
      setHistoryOpen(false)
      setEditor({ tracker: fresh, initial: formFromTracker(fresh) })
      void markRead(fresh.id)
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Трекер недоступен') }
    finally { pending.current.delete(tracker.id); setBusyIds(new Set(pending.current)) }
  }
  const saveEditor = async (form: TrackerForm) => {
    if (!editor) return
    const linkedTask = personalTasks.find((task) => task.id === form.personalTaskId)
    const submitted = linkedTask && !editor.tracker
      ? { ...form, startsAt: linkedTask.start_at, dueAt: linkedTask.due_at || '' }
      : form
    const payload = trackerFormPayload(submitted)
    listGeneration.current += 1; listAbort.current?.abort()
    let saved: DeadlineTracker
    try {
      if (editor.tracker) {
        const fresh = await deadlineTrackers.get(editor.tracker.id)
        if (fresh.updated_at !== editor.tracker.updated_at) {
          setRevision((value) => value + 1)
          throw new Error('Трекер изменился после открытия формы. Черновик сохранен в этой форме; закройте ее и откройте актуальный трекер перед повторным изменением.')
        }
        const original = trackerFormPayload(editor.initial)
        const patch = Object.fromEntries(Object.entries(payload).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key as keyof typeof original]))) as DeadlineTrackerUpdate
        if (fresh.personal_task_id || fresh.linked_task_id) {
          delete patch.title; delete patch.description; delete patch.starts_at; delete patch.due_at; delete patch.recurrence; delete patch.personal_task_id; delete patch.linked_task_id
        }
        saved = Object.keys(patch).length ? await deadlineTrackers.update(fresh.id, patch) : fresh
      } else saved = await deadlineTrackers.create(payload)
      setTrackers((previous) => [...previous.filter((item) => item.id !== saved.id), saved])
      setTarget((current) => current?.id === saved.id ? saved : current)
      setEditor(null)
      toast.success(editor.tracker ? 'Трекер обновлен' : 'Трекер создан')
      window.dispatchEvent(new Event('dpms:attention-refresh'))
    } finally { setRevision((value) => value + 1) }
  }

  const organizedMutation = async (action: () => Promise<unknown>) => {
    await action()
    setRevision((value) => value + 1)
    organizationAbort.current?.abort()
    const generation = ++organizationGeneration.current
    try {
      const data = await deadlineTrackers.organizations()
      if (generation === organizationGeneration.current) { setGroups(data.groups); setCategories(data.categories) }
    } catch (error) {
      setOrganizationError('Изменения отправлены. Не удалось обновить группы и категории; проверьте список перед следующей правкой.')
      throw error
    } finally { setOrganizationLoading(false) }
  }
  const categoryName = (tracker: DeadlineTracker) => {
    if (tracker.category_id) return categories.find((item) => item.id === tracker.category_id)?.name || 'Категория недоступна'
    return tracker.category_id === undefined ? trackerTypeLabel[tracker.tracker_type] : 'Без категории'
  }
  const visibleTrackers = useMemo(() => {
    const items = trackers.filter((tracker) => categoryFilter !== 'none' || !tracker.category_id)
    if (target && !items.some((item) => item.id === target.id)) items.push(target)
    return items.sort((a, b) => {
      if (a.status === 'active' && b.status !== 'active') return -1
      if (b.status === 'active' && a.status !== 'active') return 1
      return new Date(a.current_occurrence?.due_at || a.due_at).getTime() - new Date(b.current_occurrence?.due_at || b.due_at).getTime()
    })
  }, [categoryFilter, target, trackers])
  const sections = useMemo(() => {
    const sortedGroups = [...groups].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'ru'))
    const known = new Set(groups.map((group) => group.id))
    return [
      ...sortedGroups.filter((group) => !group.is_archived || showArchivedGroups || target?.group_id === group.id).map((group) => ({
        group, rows: visibleTrackers.filter((tracker) => tracker.group_id === group.id),
        collapsed: group.is_collapsed && target?.group_id !== group.id,
      })),
      { group: null, rows: visibleTrackers.filter((tracker) => !tracker.group_id || !known.has(tracker.group_id)), collapsed: false },
    ]
  }, [groups, showArchivedGroups, target, visibleTrackers])
  const stats = {
    active: trackers.filter((item) => item.status === 'active').length,
    paused: trackers.filter((item) => item.status === 'paused').length,
    overdue: trackers.filter((item) => trackerState(item).overdue).length,
    done: trackers.filter((item) => item.status === 'done').length,
  }
  const historyTracker = target && target.id === requestedTrackerId ? target : null

  const renderTracker = (tracker: DeadlineTracker) => {
    const state = trackerState(tracker)
    const due = tracker.recurrence ? tracker.current_occurrence?.due_at || tracker.due_at : tracker.due_at
    const trackerParams = new URLSearchParams(searchParams)
    trackerParams.set('tracker', tracker.id)
    return <article id={'deadline-tracker-' + tracker.id} key={tracker.id} aria-busy={busyIds.has(tracker.id)}
      className={cn('min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-3 dark:border-slate-700 dark:bg-slate-900', tracker.id === requestedTrackerId && 'ring-2 ring-primary/30')}>
      <div className={cn('flex flex-col gap-3', compactView && 'xl:flex-row xl:items-center')}>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className={cn('min-w-0 font-semibold text-slate-950 dark:text-slate-100', compactView ? 'text-sm' : 'text-base')}>
              <Link title={tracker.title} to={'?' + trackerParams.toString()} className="block break-words hover:text-primary focus-visible:ring-2 focus-visible:ring-primary">{tracker.title}</Link>
            </h3>
            {tracker.personal_task_key && <span className="inline-flex shrink-0 items-center gap-1 text-xs text-sky-700 dark:text-sky-300"><Link2 className="h-3 w-3" aria-hidden="true" />{tracker.personal_task_key}</span>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span className="break-words">{categoryName(tracker)}</span><span aria-hidden="true">/</span><span>{statusLabel[tracker.status]}</span>
            <span className="inline-flex items-center gap-1">{tracker.recurrence && <Repeat2 className="h-3 w-3 text-sky-600" aria-hidden="true" />}{tracker.recurrence ? 'Периодический' : sourceLabel(tracker)}</span>
          </div>
          {tracker.recurrence && !state.noCurrentOccurrence && <p className="mt-1 break-words text-xs tabular-nums text-sky-700 dark:text-sky-300">Ближайший срок: {formatDate(due, tracker.recurrence.timezone)} · {tracker.recurrence.timezone}</p>}
          {tracker.next_action && <p className="mt-1 break-words text-xs text-slate-500">{tracker.next_action}</p>}
          {!compactView && tracker.description && <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-500">{tracker.description}</p>}
        </div>
        <div className={cn('min-w-0', compactView ? 'xl:w-64 xl:shrink-0' : 'w-full')}>
          {!compactView && !state.noCurrentOccurrence && <div className="mb-2 flex flex-wrap items-center gap-1 text-xs tabular-nums text-slate-500"><CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />{formatDate(tracker.starts_at)} → {formatDate(due)}</div>}
          <DeadlineBar tracker={tracker} compact={compactView} />
          <div className="mt-1 flex flex-wrap justify-between gap-x-2 gap-y-1 text-xs tabular-nums">
            <span className={cn(state.tone === 'muted' ? 'text-slate-500 dark:text-slate-400' : state.tone === 'danger' ? 'text-rose-600 dark:text-rose-300' : state.tone === 'warn' ? 'text-amber-700 dark:text-amber-300' : 'text-emerald-700 dark:text-emerald-300')}>{remainingLabel(tracker)}</span>
            {!state.noCurrentOccurrence && <span className="text-slate-500">до {formatDateCompact(due)}</span>}
            {state.hasShift && <span className="text-rose-600 dark:text-rose-300">{shiftLabel(tracker)} до {formatDateCompact(shiftedDueAt(tracker).toISOString())}</span>}
          </div>
        </div>
        <TrackerActions tracker={tracker} busy={busyIds.has(tracker.id)} onLinks={() => setEntityLinkTracker(tracker)} onEdit={() => void openEdit(tracker)}
          onHistory={() => updateQuery('tracker', tracker.id)} onPatch={(patch, message) => patchTracker(tracker, patch, message)}
          onComplete={() => { if (tracker.current_occurrence) void completeOccurrence(tracker, tracker.current_occurrence) }}
          onFinish={() => finishSeries(tracker)} onDelete={() => deleteTracker(tracker)} />
      </div>
      {rowErrors[tracker.id] && <p role="alert" className="mt-2 break-words text-sm text-rose-700 dark:text-rose-300">{rowErrors[tracker.id]}</p>}
      {!compactView && <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
        {(tracker.personal_task_id || tracker.linked_task_id) && <span>Исполнитель: {tracker.source_responsible || 'не указан'}</span>}
        {tracker.source_available === false && <span className="text-amber-700">Источник больше недоступен</span>}
        {tracker.tags.map((tag) => <span key={tag} className="break-all">#{tag}</span>)}
        {tracker.url && /^https?:\/\//i.test(tracker.url) && <a href={tracker.url} target="_blank" rel="noreferrer" className="break-all text-primary underline">{tracker.url}</a>}
      </div>}
    </article>
  }

  return <div className="mx-auto w-full min-w-0 space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <h1 className="text-2xl font-semibold text-slate-950 dark:text-slate-100">Трекер сроков</h1>
      <div className="grid w-full grid-cols-4 sm:w-auto"><Metric label="активно" value={stats.active} /><Metric label="пауза" value={stats.paused} /><Metric label="просрочено" value={stats.overdue} tone={stats.overdue ? 'danger' : 'muted'} /><Metric label="закрыто" value={stats.done} tone="ok" /></div>
    </header>
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" aria-label="Новый трекер" title="Новый трекер" className={cn(trackerButton, 'w-11 bg-primary text-primary-foreground hover:bg-primary/90 dark:text-primary-foreground sm:w-auto')} onClick={() => { setEditor({ tracker: null, initial: newTrackerForm() }); loadSources() }} disabled={organizationLoading || Boolean(organizationError)}><Plus className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="hidden sm:inline">Новый трекер</span></button>
      <button type="button" aria-label={compactView ? 'Полный вид' : 'Компактный вид'} title={compactView ? 'Полный вид' : 'Компактный вид'} className={cn(trackerButton, 'w-11 sm:w-auto')} onClick={() => updateQuery('view', compactView ? 'full' : 'compact')} disabled={Boolean(requestedTrackerId)}><List className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="hidden sm:inline">{compactView ? 'Полный вид' : 'Компактный вид'}</span></button>
      <button type="button" aria-label="Группы" title="Группы" className={cn(trackerButton, 'w-11 sm:w-auto')} disabled={organizationLoading || Boolean(organizationError)} onClick={() => setManager('groups')}><FolderCog className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="hidden sm:inline">Группы</span></button>
      <button type="button" aria-label="Категории" title="Категории" className={cn(trackerButton, 'w-11 sm:w-auto')} disabled={organizationLoading || Boolean(organizationError)} onClick={() => setManager('categories')}><Tags className="h-4 w-4 shrink-0" aria-hidden="true" /><span className="hidden sm:inline">Категории</span></button>
      <TrackerIconButton label="Обновить трекеры" icon={RefreshCw} disabled={loading} onClick={() => setRevision((value) => value + 1)} />
    </div>
    <section aria-label="Фильтры трекеров" className="space-y-3 border-y border-slate-200 py-3 dark:border-slate-700">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 basis-64 grow"><label htmlFor="tracker-search" className="sr-only">Поиск по трекерам</label><Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-400" aria-hidden="true" /><input id="tracker-search" type="search" className={cn(trackerInput, 'pl-9')} maxLength={100} value={searchInput} onChange={(e) => setSearchInput(e.target.value)} placeholder="Поиск по трекерам" /></div>
        <div className="min-w-0 basis-48 grow sm:grow-0"><label className="sr-only" htmlFor="tracker-category-filter">Фильтр по категории</label><select id="tracker-category-filter" className={trackerInput} value={categoryFilter} onChange={(e) => updateQuery('category', e.target.value === 'all' ? null : e.target.value)}>
          <option value="all">Все категории</option><option value="none">Без категории</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_archived ? ' (архив)' : ''}</option>)}
        </select></div>
        <label className="flex min-h-11 items-center gap-2 text-sm text-slate-600 dark:text-slate-300"><input type="checkbox" checked={showArchivedGroups} onChange={(e) => updateQuery('archived_groups', e.target.checked ? 'true' : null)} />Архивные группы</label>
      </div>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Статус трекеров">{filterOptions.map((item) => <button key={item.value} type="button" aria-pressed={filter === item.value} className={cn(trackerButton, 'border-transparent', filter === item.value && 'border-primary/30 bg-primary/10 text-primary dark:text-primary')} onClick={() => updateQuery('status', item.value)}>{item.label}</button>)}</div>
    </section>
    {organizationError && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-rose-700 dark:text-rose-300">{organizationError}<button type="button" className={trackerButton} onClick={() => setOrganizationRevision((value) => value + 1)}>Повторить загрузку групп</button></div>}
    {loadError && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-rose-700 dark:text-rose-300">{loadError}<button type="button" className={trackerButton} onClick={() => setRevision((value) => value + 1)}>Повторить загрузку трекеров</button></div>}
    {(loading || targetLoading) && <p role="status" className="text-sm text-slate-500">Загрузка трекеров...</p>}
    {targetError && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-rose-700 dark:text-rose-300">{targetError}<button type="button" className={trackerButton} onClick={() => setTargetRevision((value) => value + 1)}>Повторить открытие трекера</button><button type="button" className={trackerButton} onClick={() => updateQuery('tracker', null)}>Закрыть ссылку</button></div>}
    <div className="space-y-5">{sections.map(({ group, rows, collapsed }) => <section key={group?.id || 'ungrouped'} className="min-w-0 space-y-2" aria-label={group?.name || 'Без группы'}>
      <div className="flex min-w-0 items-center gap-2 border-b border-slate-200 pb-2 dark:border-slate-700">
        {group && <TrackerIconButton label={(collapsed ? 'Развернуть ' : 'Свернуть ') + group.name} icon={collapsed ? ChevronRight : ChevronDown} disabled={busyIds.has('group-' + group.id) || target?.group_id === group.id} onClick={() => {
          void runMutation('group-' + group.id, async () => {
            await deadlineTrackers.patchOrganization('groups', group.id, { is_collapsed: !group.is_collapsed })
            setGroups((previous) => previous.map((item) => item.id === group.id ? { ...item, is_collapsed: !group.is_collapsed } : item))
            return null
          }, group.is_collapsed ? 'Группа развернута' : 'Группа свернута')
        }} />}
        {group?.color && <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: group.color }} />}
        <h2 className="min-w-0 break-words text-sm font-semibold">{group?.name || 'Без группы'}</h2>
        <span className="text-xs tabular-nums text-slate-500">{rows.length}{group?.is_archived ? ' · Архив' : ''}</span>
      </div>
      {group && rowErrors['group-' + group.id] && <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{rowErrors['group-' + group.id]}</p>}
      {!collapsed && <div className="grid min-w-0 gap-2">{rows.map(renderTracker)}{!rows.length && !loading && <p className="py-2 text-sm text-slate-500">Нет трекеров под текущий фильтр.</p>}</div>}
    </section>)}</div>
    {hasMore && <button type="button" className={trackerButton} disabled={loading} onClick={() => setPaging({ key: queryKey, index: pageIndex + 1 })}>Загрузить еще трекеры</button>}
    {editor && <TrackerEditor initial={editor.initial} editing={Boolean(editor.tracker)} groups={groups} categories={categories} personalTasks={personalTasks} sourceError={sourceError} onRetrySources={loadSources}
      linkedSource={editor.tracker && (editor.tracker.personal_task_id || editor.tracker.linked_task_id) ? {
        label: sourceLabel(editor.tracker) + ': ' + (editor.tracker.source_title || editor.tracker.personal_task_title || editor.tracker.title),
        assignee: editor.tracker.source_responsible || null, startsAt: editor.tracker.starts_at, dueAt: editor.tracker.due_at,
        href: editor.tracker.source_available === false ? null : editor.tracker.personal_task_id ? '/personal-tasks?task=' + editor.tracker.personal_task_id : '/queue?task=' + editor.tracker.linked_task_id,
      } : undefined}
      onClose={() => setEditor(null)} onSave={saveEditor} />}
    {manager && <TrackerOrganizationManager kind={manager} items={manager === 'groups' ? groups : categories} onClose={() => setManager(null)}
      onCreate={(payload) => organizedMutation(() => deadlineTrackers.createOrganization(manager, payload))}
      onPatch={(id, payload) => organizedMutation(() => deadlineTrackers.patchOrganization(manager, id, payload))}
      onDelete={(id) => organizedMutation(() => deadlineTrackers.deleteOrganization(manager, id))}
      onReorder={(ids) => organizedMutation(() => deadlineTrackers.reorderGroups(ids))} />}
    {historyOpen && historyTracker && !editor && <TrackerHistory tracker={historyTracker} busy={busyIds.has(historyTracker.id)} error={rowErrors[historyTracker.id]} readError={readError} onRetryRead={() => void markRead(historyTracker.id)} onLoad={deadlineTrackers.history}
      onComplete={(occurrence) => completeOccurrence(historyTracker, occurrence)} onFinish={() => finishSeries(historyTracker)} onEdit={() => void openEdit(historyTracker)}
      onClose={() => { setHistoryOpen(false); updateQuery('tracker', null, true) }} />}
    {entityLinkTracker && <EntityLinkModal tracker={entityLinkTracker} onClose={() => setEntityLinkTracker(null)} />}
  </div>
}
