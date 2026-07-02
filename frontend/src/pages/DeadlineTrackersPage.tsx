import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive,
  CalendarClock,
  CheckCircle2,
  Clock3,
  List,
  Link2,
  PauseCircle,
  Pencil,
  PlayCircle,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  DeadlineTracker,
  DeadlineTrackerCreate,
  DeadlineTrackerStatus,
  DeadlineTrackerType,
  DeadlineTrackerUpdate,
  PersonalTask,
} from '@/api/types'
import { cn } from '@/lib/utils'

type TrackerFilter = DeadlineTrackerStatus | 'all'

const emptyForm = {
  title: '',
  description: '',
  trackerType: 'task' as DeadlineTrackerType,
  status: 'active' as DeadlineTrackerStatus,
  startsAt: '',
  dueAt: '',
  nextAction: '',
  responsible: '',
  tags: '',
  personalTaskId: '',
  linkedTaskId: '',
}

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

function toPayloadDate(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function toInputDate(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset()
  const local = new Date(date.getTime() - offset * 60_000)
  return local.toISOString().slice(0, 16)
}

function nowInputDate(): string {
  return toInputDate(new Date().toISOString())
}

function formatDate(value: string | null): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
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

function splitTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 20)
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
  const due = new Date(tracker.due_at)
  const apiShiftedDue = tracker.shifted_due_at ? new Date(tracker.shifted_due_at) : null
  if (apiShiftedDue && apiShiftedDue.getTime() > due.getTime()) return apiShiftedDue
  return new Date(due.getTime() + pauseDays(tracker) * 86_400_000)
}

function trackerState(tracker: DeadlineTracker) {
  const start = new Date(tracker.starts_at).getTime()
  const due = new Date(tracker.due_at).getTime()
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
  const hasShift = tracker.total_pause_seconds > 0 || tracker.status === 'paused'
  const shiftMs = pauseDays(tracker) * 86_400_000
  const shiftPct = hasShift ? clamp(Math.round((shiftMs / shiftedTotal) * 100), 2, 100) : 0
  return { remainingPct, originalRemainingPct, elapsedPct, overdue, daysLeft, tone, hasShift, shiftPct }
}

function remainingLabel(tracker: DeadlineTracker): string {
  const state = trackerState(tracker)
  if (tracker.status === 'done') return 'закрыто'
  if (tracker.status === 'archived') return 'архив'
  if (tracker.status === 'paused') return 'на паузе'
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
    <div className="border-r border-slate-100 px-4 py-3 last:border-r-0">
      <div className={cn('text-lg font-semibold', tone === 'danger' ? 'text-rose-600' : tone === 'ok' ? 'text-emerald-600' : 'text-slate-900')}>
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  )
}

function DeadlineBar({ tracker, compact = false }: { tracker: DeadlineTracker; compact?: boolean }) {
  const state = trackerState(tracker)
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
              'ml-auto h-full rounded-full transition-all duration-300',
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
              className="h-full rounded-full bg-rose-500 transition-all duration-300"
              style={{ width: `${state.shiftPct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export function DeadlineTrackersPage() {
  const [trackers, setTrackers] = useState<DeadlineTracker[]>([])
  const [personalTasks, setPersonalTasks] = useState<PersonalTask[]>([])
  const [filter, setFilter] = useState<TrackerFilter>('active')
  const [typeFilter, setTypeFilter] = useState<DeadlineTrackerType | 'all'>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [compactView, setCompactView] = useState(true)
  const [editing, setEditing] = useState<DeadlineTracker | null>(null)
  const [form, setForm] = useState({ ...emptyForm, startsAt: nowInputDate() })

  const loadTrackers = useCallback(async () => {
    const params = new URLSearchParams()
    params.set('include_archived', 'true')
    params.set('limit', '300')
    if (filter !== 'all') params.set('status', filter)
    if (typeFilter !== 'all') params.set('tracker_type', typeFilter)
    if (search.trim()) params.set('search', search.trim())
    const data = await api.get<DeadlineTracker[]>(`/api/deadline-trackers?${params.toString()}`)
    setTrackers(data)
  }, [filter, search, typeFilter])

  const loadPersonalTasks = useCallback(async () => {
    const data = await api.get<PersonalTask[]>('/api/personal-tasks?status=active&limit=300')
    setPersonalTasks(data)
  }, [])

  useEffect(() => {
    setLoading(true)
    loadTrackers()
      .catch((e) => toast.error(e instanceof Error ? e.message : 'Ошибка загрузки трекера'))
      .finally(() => setLoading(false))
  }, [loadTrackers])

  useEffect(() => {
    void loadPersonalTasks().catch(() => undefined)
  }, [loadPersonalTasks])

  const stats = useMemo(() => {
    const active = trackers.filter((item) => item.status === 'active').length
    const paused = trackers.filter((item) => item.status === 'paused').length
    const overdue = trackers.filter((item) => trackerState(item).overdue).length
    const done = trackers.filter((item) => item.status === 'done').length
    return { active, paused, overdue, done }
  }, [trackers])

  const sortedTrackers = useMemo(() => {
    return [...trackers].sort((a, b) => {
      if (a.status === 'active' && b.status !== 'active') return -1
      if (b.status === 'active' && a.status !== 'active') return 1
      return new Date(a.due_at).getTime() - new Date(b.due_at).getTime()
    })
  }, [trackers])

  const resetForm = () => {
    setEditing(null)
    setForm({ ...emptyForm, startsAt: nowInputDate() })
    setFormOpen(false)
  }

  const openCreate = () => {
    setEditing(null)
    setForm({ ...emptyForm, startsAt: nowInputDate() })
    setFormOpen(true)
  }

  const openEdit = (tracker: DeadlineTracker) => {
    setEditing(tracker)
    setForm({
      title: tracker.title,
      description: tracker.description || '',
      trackerType: tracker.tracker_type,
      status: tracker.status,
      startsAt: toInputDate(tracker.starts_at),
      dueAt: toInputDate(tracker.due_at),
      nextAction: tracker.next_action || '',
      responsible: tracker.responsible || '',
      tags: tracker.tags.join(', '),
      personalTaskId: tracker.personal_task_id || '',
      linkedTaskId: tracker.linked_task_id || '',
    })
    setFormOpen(true)
  }

  const payloadFromForm = (): DeadlineTrackerCreate => {
    const startsAt = toPayloadDate(form.startsAt)
    const dueAt = toPayloadDate(form.dueAt)
    if (!startsAt || !dueAt) throw new Error('Укажите старт и дедлайн')
    return {
      title: form.title,
      description: form.description || null,
      tracker_type: form.trackerType,
      status: form.status,
      starts_at: startsAt,
      due_at: dueAt,
      next_action: form.nextAction || null,
      responsible: form.responsible || null,
      tags: splitTags(form.tags),
      personal_task_id: form.personalTaskId || null,
      linked_task_id: form.linkedTaskId || null,
    }
  }

  const saveTracker = async () => {
    try {
      setLoading(true)
      if (!form.title.trim()) throw new Error('Укажите название')
      const payload = payloadFromForm()
      if (editing) {
        await api.patch<DeadlineTracker>(`/api/deadline-trackers/${editing.id}`, payload as DeadlineTrackerUpdate)
        toast.success('Трекер обновлен')
      } else {
        await api.post<DeadlineTracker>('/api/deadline-trackers', payload)
        toast.success('Трекер создан')
      }
      resetForm()
      await loadTrackers()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setLoading(false)
    }
  }

  const patchTracker = async (tracker: DeadlineTracker, payload: DeadlineTrackerUpdate, message: string) => {
    try {
      await api.patch<DeadlineTracker>(`/api/deadline-trackers/${tracker.id}`, payload)
      await loadTrackers()
      toast.success(message)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка обновления')
    }
  }

  const deleteTracker = async (tracker: DeadlineTracker) => {
    if (!window.confirm('Удалить трекер срока?')) return
    try {
      await api.delete(`/api/deadline-trackers/${tracker.id}`)
      await loadTrackers()
      toast.success('Трекер удален')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Time control</p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-950">Трекер сроков</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Универсальные полоски для задач, абонементов, оплат, паролей, документов и системных сроков.
          </p>
        </div>
        <div className="flex flex-col items-end gap-3">
          <div className="grid grid-cols-4 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <Metric label="активно" value={stats.active} />
            <Metric label="пауза" value={stats.paused} tone={stats.paused ? 'danger' : 'muted'} />
            <Metric label="просрочено" value={stats.overdue} tone={stats.overdue ? 'danger' : 'muted'} />
            <Metric label="закрыто" value={stats.done} tone="ok" />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => setCompactView((value) => !value)}
              className={cn(
                'inline-flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium',
                compactView ? 'border-primary bg-primary text-primary-foreground' : 'border-primary/30 bg-white text-primary hover:bg-primary/10',
              )}
            >
              <List className="h-4 w-4" />
              {compactView ? 'Полный вид' : 'Компактный вид'}
            </button>
            <button
              type="button"
              onClick={openCreate}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <Plus className="h-4 w-4" />
              Новый трекер
            </button>
          </div>
        </div>
      </div>

      {formOpen && (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                {editing ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              </span>
              <div>
                <h2 className="text-sm font-semibold text-slate-900">
                  {editing ? 'Редактирование трекера' : 'Новый трекер срока'}
                </h2>
                <p className="text-xs text-slate-500">Старт и дедлайн задают всю длину полоски.</p>
              </div>
            </div>
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              <X className="h-4 w-4" />
              Закрыть
            </button>
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.3fr)_180px_160px_160px]">
            <input
              value={form.title}
              onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="Название"
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <select
              value={form.trackerType}
              onChange={(e) => setForm((prev) => ({ ...prev, trackerType: e.target.value as DeadlineTrackerType }))}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            >
              {Object.entries(trackerTypeLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <select
              value={form.status}
              onChange={(e) => setForm((prev) => ({ ...prev, status: e.target.value as DeadlineTrackerStatus }))}
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            >
              {Object.entries(statusLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <input
              value={form.responsible}
              onChange={(e) => setForm((prev) => ({ ...prev, responsible: e.target.value }))}
              placeholder="Ответственный"
              className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-4">
            <label className="space-y-1">
              <span className="text-xs text-slate-500">Старт периода</span>
              <input
                type="datetime-local"
                value={form.startsAt}
                onChange={(e) => setForm((prev) => ({ ...prev, startsAt: e.target.value }))}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-slate-500">Дедлайн</span>
              <input
                type="datetime-local"
                value={form.dueAt}
                onChange={(e) => setForm((prev) => ({ ...prev, dueAt: e.target.value }))}
                className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              />
            </label>
            <input
              value={form.nextAction}
              onChange={(e) => setForm((prev) => ({ ...prev, nextAction: e.target.value }))}
              placeholder="Следующее действие"
              className="self-end rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <input
              value={form.tags}
              onChange={(e) => setForm((prev) => ({ ...prev, tags: e.target.value }))}
              placeholder="Теги через запятую"
              className="self-end rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <textarea
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="Описание / контекст"
              rows={3}
              className="resize-none rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
            />
            <div className="grid gap-3">
              <select
                value={form.personalTaskId}
                onChange={(e) => setForm((prev) => ({ ...prev, personalTaskId: e.target.value }))}
                className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-slate-400"
              >
                <option value="">Без личной задачи</option>
                {personalTasks.map((task) => (
                  <option key={task.id} value={task.id}>{task.task_key} · {task.title}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void saveTracker()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {editing ? 'Сохранить' : 'Создать трекер'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-4 py-2.5 text-sm text-slate-600 hover:bg-slate-50"
            >
              <X className="h-4 w-4" />
              Отмена
            </button>
          </div>
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по трекерам"
              className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-slate-400"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {filterOptions.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={cn(
                  'rounded-lg border px-3 py-2 text-sm',
                  filter === item.value ? 'border-primary bg-primary text-primary-foreground' : 'border-slate-200 text-slate-600 hover:bg-slate-50',
                )}
              >
                {item.label}
              </button>
            ))}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as DeadlineTrackerType | 'all')}
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
            >
              <option value="all">Все типы</option>
              {Object.entries(trackerTypeLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <div className="grid gap-3">
        {sortedTrackers.map((tracker) => {
          const state = trackerState(tracker)
          if (compactView) {
            return (
              <article key={tracker.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm transition hover:border-slate-300">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2">
                        <h2 className="truncate text-sm font-semibold text-slate-950">{tracker.title}</h2>
                        {tracker.personal_task_key && (
                          <span className="inline-flex shrink-0 items-center gap-1 rounded bg-indigo-50 px-1.5 py-0.5 text-[11px] text-indigo-700">
                            <Link2 className="h-3 w-3" aria-hidden="true" />
                            {tracker.personal_task_key}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex min-w-0 items-center gap-2 text-[11px] text-slate-500">
                        <span className="shrink-0">{trackerTypeLabel[tracker.tracker_type]}</span>
                        <span aria-hidden="true">/</span>
                        <span className="shrink-0">{statusLabel[tracker.status]}</span>
                        {tracker.next_action && (
                          <>
                            <span aria-hidden="true">/</span>
                            <span className="truncate">{tracker.next_action}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="min-w-0 flex-[1.15] lg:max-w-[460px]">
                    <DeadlineBar tracker={tracker} compact />
                  </div>

                  <div className="flex shrink-0 items-center justify-between gap-3 lg:justify-end">
                    <div className="min-w-[92px] text-[11px] lg:text-right">
                      <div className={cn(
                        'whitespace-nowrap font-medium',
                        state.tone === 'danger' ? 'text-rose-600' : state.tone === 'warn' ? 'text-amber-600' : 'text-emerald-600',
                      )}>
                        {remainingLabel(tracker)}
                      </div>
                      <div className="whitespace-nowrap text-slate-500">до {formatDateCompact(tracker.due_at)}</div>
                      {state.hasShift && (
                        <div className="whitespace-nowrap text-rose-600">{shiftLabel(tracker)} до {formatDateCompact(shiftedDueAt(tracker).toISOString())}</div>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {tracker.status === 'paused' ? (
                        <button
                          type="button"
                          aria-label="Снять паузу"
                          title="Снять паузу"
                          onClick={() => void patchTracker(tracker, { status: 'active' }, 'Пауза снята')}
                          className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
                        >
                          <PlayCircle className="h-4 w-4" aria-hidden="true" />
                        </button>
                      ) : tracker.status === 'active' ? (
                        <button
                          type="button"
                          aria-label="Поставить на паузу"
                          title="Пауза"
                          onClick={() => void patchTracker(tracker, { status: 'paused' }, 'Трекер на паузе')}
                          className="rounded-md border border-amber-200 p-1.5 text-amber-700 hover:bg-amber-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-200"
                        >
                          <PauseCircle className="h-4 w-4" aria-hidden="true" />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        aria-label="Закрыть трекер"
                        title="Закрыть"
                        onClick={() => void patchTracker(tracker, { status: 'done' }, 'Трекер закрыт')}
                        className="rounded-md border border-emerald-200 p-1.5 text-emerald-700 hover:bg-emerald-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200"
                      >
                        <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        aria-label="Редактировать трекер"
                        title="Редактировать"
                        onClick={() => openEdit(tracker)}
                        className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
                      >
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        aria-label="Удалить трекер"
                        title="Удалить"
                        onClick={() => void deleteTracker(tracker)}
                        className="rounded-md border border-rose-200 p-1.5 text-rose-600 hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-200"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            )
          }
          return (
            <article key={tracker.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{trackerTypeLabel[tracker.tracker_type]}</span>
                    <span className={cn(
                      'rounded border px-2 py-0.5 text-xs',
                      tracker.status === 'done'
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : tracker.status === 'archived'
                          ? 'border-slate-200 bg-slate-50 text-slate-500'
                          : tracker.status === 'paused'
                            ? 'border-amber-200 bg-amber-50 text-amber-700'
                            : 'border-sky-200 bg-sky-50 text-sky-700',
                    )}>
                      {statusLabel[tracker.status]}
                    </span>
                    {tracker.personal_task_key && (
                      <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
                        {tracker.personal_task_key}
                      </span>
                    )}
                  </div>
                  <h2 className="mt-2 truncate text-base font-semibold text-slate-950">{tracker.title}</h2>
                  {(tracker.description || tracker.next_action || tracker.personal_task_title) && (
                    <p className="mt-1 line-clamp-2 text-sm text-slate-500">
                      {tracker.next_action || tracker.description || tracker.personal_task_title}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {tracker.status === 'active' && (
                    <button
                      type="button"
                      onClick={() => void patchTracker(tracker, { status: 'paused' }, 'Трекер на паузе')}
                      className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-3 py-2 text-sm text-amber-700 hover:bg-amber-50"
                    >
                      <PauseCircle className="h-4 w-4" />
                      Пауза
                    </button>
                  )}
                  {tracker.status === 'paused' && (
                    <button
                      type="button"
                      onClick={() => void patchTracker(tracker, { status: 'active' }, 'Пауза снята')}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                    >
                      <PlayCircle className="h-4 w-4" />
                      Снять паузу
                    </button>
                  )}
                  {(tracker.status === 'active' || tracker.status === 'paused') ? (
                    <button
                      type="button"
                      onClick={() => void patchTracker(tracker, { status: 'done' }, 'Трекер закрыт')}
                      className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Закрыть
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void patchTracker(tracker, { status: 'active' }, 'Трекер активен')}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                    >
                      <Clock3 className="h-4 w-4" />
                      Вернуть
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => openEdit(tracker)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    <Pencil className="h-4 w-4" />
                    Править
                  </button>
                  <button
                    type="button"
                    onClick={() => void patchTracker(tracker, { status: 'archived' }, 'Трекер в архиве')}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                  >
                    <Archive className="h-4 w-4" />
                    Архив
                  </button>
                  <button
                    type="button"
                    onClick={() => void deleteTracker(tracker)}
                    className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-600 hover:bg-rose-50"
                  >
                    <Trash2 className="h-4 w-4" />
                    Удалить
                  </button>
                </div>
              </div>

              <div className="mt-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock className="h-3.5 w-3.5" />
                    {formatDate(tracker.starts_at)} → {formatDate(tracker.due_at)}
                    {state.hasShift ? <span className="text-rose-600">→ сдвиг: {formatDate(tracker.shifted_due_at)}</span> : null}
                  </span>
                  <span className={cn(
                    'font-medium',
                    state.tone === 'danger' ? 'text-rose-600' : state.tone === 'warn' ? 'text-amber-600' : 'text-emerald-600',
                  )}>
                    {remainingLabel(tracker)} · осталось {state.remainingPct}%
                  </span>
                </div>
                <DeadlineBar tracker={tracker} />
              </div>

              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {tracker.responsible && <span>Ответственный: {tracker.responsible}</span>}
                {tracker.tags.map((tag) => (
                  <span key={tag} className="rounded bg-slate-100 px-2 py-0.5">#{tag}</span>
                ))}
              </div>
            </article>
          )
        })}
      </div>

      {!loading && sortedTrackers.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Нет трекеров под текущий фильтр.
        </div>
      )}
    </div>
  )
}
