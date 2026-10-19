import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive,
  ArrowDown,
  ArrowUp,
  Boxes,
  CalendarClock,
  CheckCircle2,
  Circle,
  GitBranch,
  Link2,
  ListChecks,
  PauseCircle,
  Pencil,
  PlayCircle,
  Plus,
  Save,
  Search,
  Send,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  PersonalTask,
  Task,
  WorkMethodology,
  WorkTrack,
  WorkTrackApplyMethodologyRequest,
  WorkTrackAssignedItem,
  WorkTrackCreate,
  WorkTrackReadiness,
  WorkTrackItem,
  WorkTrackItemCreate,
  WorkTrackItemStatus,
  WorkTrackItemType,
  WorkTrackStatus,
  WorkTrackUpdate,
} from '@/api/types'
import { cn } from '@/lib/utils'

type TrackFilter = WorkTrackStatus | 'all'

const emptyTrackForm = {
  title: '',
  description: '',
  status: 'draft' as WorkTrackStatus,
  startAt: '',
  dueAt: '',
  color: 'slate',
}

const emptyItemForm = {
  itemType: 'personal_task' as WorkTrackItemType,
  taskId: '',
  personalTaskId: '',
  title: '',
  description: '',
  status: 'active' as WorkTrackItemStatus,
  startsAt: '',
  dueAt: '',
  notes: '',
}

const emptyMethodologyForm = {
  methodologyId: '',
  routeKey: '',
  productKey: '',
  replaceExisting: false,
}

const filterOptions: Array<{ value: TrackFilter; label: string }> = [
  { value: 'draft', label: 'Черновики' },
  { value: 'active', label: 'Активные' },
  { value: 'paused', label: 'Пауза' },
  { value: 'done', label: 'Закрытые' },
  { value: 'archived', label: 'Архив' },
  { value: 'all', label: 'Все' },
]

const trackStatusLabel: Record<WorkTrackStatus, string> = {
  draft: 'Черновик',
  active: 'Активен',
  paused: 'Пауза',
  done: 'Закрыт',
  archived: 'Архив',
}

const itemStatusLabel: Record<WorkTrackItemStatus, string> = {
  active: 'Активно',
  waiting: 'Ожидание',
  blocked: 'Блокер',
  done: 'Готово',
  skipped: 'Пропущено',
}

const reservationStatusLabel: Record<string, string> = {
  draft: 'Черновик',
  sent: 'На рассмотрении',
  reserved: 'Забронировано',
  declined: 'Отказ',
  released: 'Освобождено',
}

const itemTypeLabel: Record<WorkTrackItemType, string> = {
  task: 'DPMS-задача',
  personal_task: 'Личная задача',
  manual: 'Ручной шаг',
  cube: 'Кубик',
}

const colorOptions = [
  { value: 'slate', label: 'Серый', className: 'bg-slate-500' },
  { value: 'blue', label: 'Синий', className: 'bg-blue-500' },
  { value: 'green', label: 'Зеленый', className: 'bg-emerald-500' },
  { value: 'amber', label: 'Желтый', className: 'bg-amber-500' },
  { value: 'rose', label: 'Розовый', className: 'bg-rose-500' },
]

function toPayloadDate(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function toInputDate(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset()
  const local = new Date(date.getTime() - offset * 60_000)
  return local.toISOString().slice(0, 16)
}

function formatDate(value: string | null | undefined): string {
  if (!value) return 'без срока'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'без срока'
  return date.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
  })
}

function daysUntil(value: string | null | undefined): string {
  if (!value) return 'срок не задан'
  const due = new Date(value).getTime()
  if (Number.isNaN(due)) return 'срок не задан'
  const days = Math.ceil((due - Date.now()) / 86_400_000)
  if (days < 0) return `просрочено ${Math.abs(days)} дн.`
  if (days === 0) return 'сегодня'
  if (days === 1) return 'завтра'
  return `через ${days} дн.`
}

function itemTone(item: WorkTrackItem): 'done' | 'danger' | 'warn' | 'neutral' {
  if (item.is_done) return 'done'
  if (!item.effective_due_at) return 'neutral'
  const days = Math.ceil((new Date(item.effective_due_at).getTime() - Date.now()) / 86_400_000)
  if (days < 0) return 'danger'
  if (days <= 3) return 'warn'
  return 'neutral'
}

function linkedLabel(item: WorkTrackItem): string {
  if (item.item_type === 'task') return item.linked_number ? `#${item.linked_number}` : 'DPMS'
  if (item.item_type === 'personal_task') return item.linked_number ? `Л-${item.linked_number}` : 'Личная'
  if (item.item_type === 'cube') return item.methodology_node_id || 'Кубик'
  return 'Шаг'
}

function methodologyRoutes(methodology: WorkMethodology | null) {
  const routes = methodology?.payload.routes
  if (!routes || typeof routes !== 'object' || Array.isArray(routes)) return []
  return Object.entries(routes as Record<string, Record<string, unknown>>).map(([key, route]) => ({
    key,
    label: typeof route?.name === 'string' ? route.name : key,
  }))
}

function methodologyProducts(methodology: WorkMethodology | null) {
  const products = methodology?.payload.products
  if (!Array.isArray(products)) return []
  return products
    .filter((product): product is Record<string, unknown> => Boolean(product) && typeof product === 'object')
    .map((product) => ({
      key: String(product.id || ''),
      label: typeof product.name === 'string' ? product.name : String(product.id || ''),
    }))
    .filter((product) => product.key)
}

function trackPayload(form: typeof emptyTrackForm): WorkTrackCreate {
  return {
    title: form.title.trim(),
    description: form.description.trim() || null,
    status: form.status,
    start_at: toPayloadDate(form.startAt),
    due_at: toPayloadDate(form.dueAt),
    color: form.color,
  }
}

function itemPayload(form: typeof emptyItemForm): WorkTrackItemCreate {
  const itemType = form.itemType
  return {
    item_type: itemType,
    task_id: itemType === 'task' ? form.taskId || null : null,
    personal_task_id: itemType === 'personal_task' ? form.personalTaskId || null : null,
    title: form.title.trim() || null,
    description: form.description.trim() || null,
    status: form.status,
    starts_at: toPayloadDate(form.startsAt),
    due_at: toPayloadDate(form.dueAt),
    notes: form.notes.trim() || null,
  }
}

function trackFormFrom(track: WorkTrack) {
  return {
    title: track.title,
    description: track.description || '',
    status: track.status,
    startAt: toInputDate(track.start_at),
    dueAt: toInputDate(track.due_at),
    color: track.color || 'slate',
  }
}

export function WorkTracksPage() {
  const [tracks, setTracks] = useState<WorkTrack[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [personalTasks, setPersonalTasks] = useState<PersonalTask[]>([])
  const [assignedItems, setAssignedItems] = useState<WorkTrackAssignedItem[]>([])
  const [activeMethodology, setActiveMethodology] = useState<WorkMethodology | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<TrackFilter>('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [methodologyBusy, setMethodologyBusy] = useState(false)
  const [showTrackForm, setShowTrackForm] = useState(false)
  const [editingTrackId, setEditingTrackId] = useState<string | null>(null)
  const [trackForm, setTrackForm] = useState(emptyTrackForm)
  const [itemForm, setItemForm] = useState(emptyItemForm)
  const [methodologyForm, setMethodologyForm] = useState(emptyMethodologyForm)

  const selectedTrack = useMemo(
    () => tracks.find((track) => track.id === selectedId) || tracks[0] || null,
    [selectedId, tracks]
  )
  const selectedTrackId = selectedTrack?.id || null
  const selectedTrackUpdatedAt = selectedTrack?.updated_at || null
  const routeOptions = useMemo(() => methodologyRoutes(activeMethodology), [activeMethodology])
  const productOptions = useMemo(() => methodologyProducts(activeMethodology), [activeMethodology])

  const loadTracks = useCallback(async () => {
    const params = new URLSearchParams({ status: filter, limit: '300' })
    if (search.trim()) params.set('search', search.trim())
    const data = await api.get<WorkTrack[]>(`/api/work-tracks?${params.toString()}`)
    setTracks(data)
    setSelectedId((current) => {
      if (current && data.some((track) => track.id === current)) return current
      return data[0]?.id || null
    })
  }, [filter, search])

  const loadReferenceData = useCallback(async () => {
    const [taskList, personalTaskList, assignedList, methodology] = await Promise.all([
      api.get<Task[]>('/api/tasks'),
      api.get<PersonalTask[]>('/api/personal-tasks?status=all&limit=300'),
      api.get<WorkTrackAssignedItem[]>('/api/work-tracks/assigned-items?reservation_status=all&limit=100'),
      api.get<WorkMethodology | null>('/api/work-tracks/methodologies/active'),
    ])
    setTasks(taskList)
    setPersonalTasks(personalTaskList)
    setAssignedItems(assignedList)
    setActiveMethodology(methodology)
  }, [])

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([loadTracks(), loadReferenceData()])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось загрузить треки')
    } finally {
      setLoading(false)
    }
  }, [loadReferenceData, loadTracks])

  useEffect(() => {
    void reload()
  }, [reload])

  const loadReadiness = useCallback(async (trackId: string) => {
    try {
      const data = await api.get<WorkTrackReadiness>(`/api/work-tracks/${trackId}/readiness`)
      return data
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось проверить готовность трека')
      return null
    }
  }, [])

  useEffect(() => {
    if (!selectedTrackId) {
      return
    }
    void loadReadiness(selectedTrackId)
  }, [loadReadiness, selectedTrackId, selectedTrackUpdatedAt])

  useEffect(() => {
    if (!activeMethodology) return
    setMethodologyForm((form) => {
      const routes = methodologyRoutes(activeMethodology)
      const products = methodologyProducts(activeMethodology)
      return {
        ...form,
        methodologyId: activeMethodology.id,
        routeKey: form.routeKey || routes[0]?.key || '',
        productKey: form.productKey || products[0]?.key || '',
      }
    })
  }, [activeMethodology])

  const saveTrack = async () => {
    if (!trackForm.title.trim()) {
      toast.error('Укажите название трека')
      return
    }
    setSaving(true)
    try {
      let saved: WorkTrack
      if (editingTrackId) {
        saved = await api.patch<WorkTrack>(`/api/work-tracks/${editingTrackId}`, trackPayload(trackForm) as WorkTrackUpdate)
      } else {
        saved = await api.post<WorkTrack>('/api/work-tracks', trackPayload(trackForm))
      }
      await loadTracks()
      setSelectedId(saved.id)
      setShowTrackForm(false)
      setEditingTrackId(null)
      setTrackForm(emptyTrackForm)
      toast.success(editingTrackId ? 'Трек обновлен' : 'Трек создан')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить трек')
    } finally {
      setSaving(false)
    }
  }

  const startEditTrack = (track: WorkTrack) => {
    setEditingTrackId(track.id)
    setTrackForm(trackFormFrom(track))
    setShowTrackForm(true)
  }

  const patchTrack = async (track: WorkTrack, payload: WorkTrackUpdate) => {
    try {
      const updated = await api.patch<WorkTrack>(`/api/work-tracks/${track.id}`, payload)
      setTracks((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      void loadReadiness(updated.id)
      toast.success('Трек обновлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось обновить трек')
    }
  }

  const activateTrack = async (track: WorkTrack) => {
    const readinessData = await loadReadiness(track.id)
    if (!readinessData?.can_activate) {
      toast.error('Трек пока нельзя активировать: заполните обязательные поля')
      return
    }
    await patchTrack(track, { status: 'active' })
  }

  const deleteTrack = async (track: WorkTrack) => {
    if (!window.confirm(`Удалить трек «${track.title}»?`)) return
    try {
      await api.delete(`/api/work-tracks/${track.id}`)
      setTracks((current) => current.filter((item) => item.id !== track.id))
      setSelectedId(null)
      toast.success('Трек удален')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить трек')
    }
  }

  const applyMethodology = async () => {
    if (!selectedTrack) return
    if (!activeMethodology) {
      toast.error('Администратор должен выбрать активную методологию')
      return
    }
    setMethodologyBusy(true)
    try {
      const payload: WorkTrackApplyMethodologyRequest = {
        methodology_id: activeMethodology.id,
        route_key: methodologyForm.routeKey || null,
        product_key: methodologyForm.productKey || null,
        replace_existing_cubes: methodologyForm.replaceExisting,
      }
      const updated = await api.post<WorkTrack>(`/api/work-tracks/${selectedTrack.id}/methodology/apply`, payload)
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
      void loadReadiness(updated.id)
      toast.success('Методология применена к треку')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось применить методологию')
    } finally {
      setMethodologyBusy(false)
    }
  }

  const sendForReview = async () => {
    if (!selectedTrack) return
    setMethodologyBusy(true)
    try {
      const updated = await api.post<WorkTrack>(`/api/work-tracks/${selectedTrack.id}/methodology/send-review`, {})
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
      await loadReferenceData()
      toast.success('Отправлено исполнителям на рассмотрение')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось отправить на рассмотрение')
    } finally {
      setMethodologyBusy(false)
    }
  }

  const addItem = async () => {
    if (!selectedTrack) return
    if (itemForm.itemType === 'task' && !itemForm.taskId) {
      toast.error('Выберите DPMS-задачу')
      return
    }
    if (itemForm.itemType === 'personal_task' && !itemForm.personalTaskId) {
      toast.error('Выберите личную задачу')
      return
    }
    if (itemForm.itemType === 'manual' && !itemForm.title.trim()) {
      toast.error('Укажите название ручного шага')
      return
    }
    if (itemForm.itemType === 'cube' && !itemForm.title.trim()) {
      toast.error('Укажите название кубика')
      return
    }
    setSaving(true)
    try {
      const updated = await api.post<WorkTrack>(`/api/work-tracks/${selectedTrack.id}/items`, itemPayload(itemForm))
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
      void loadReadiness(updated.id)
      setItemForm(emptyItemForm)
      toast.success('Элемент добавлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить элемент')
    } finally {
      setSaving(false)
    }
  }

  const patchItem = async (item: WorkTrackItem, payload: Partial<WorkTrackItem>) => {
    if (!selectedTrack) return
    try {
      const updated = await api.patch<WorkTrack>(
        `/api/work-tracks/${selectedTrack.id}/items/${item.id}`,
        payload
      )
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
      void loadReadiness(updated.id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось обновить элемент')
    }
  }

  const deleteItem = async (item: WorkTrackItem) => {
    if (!selectedTrack) return
    if (!window.confirm(`Удалить элемент «${item.effective_title}» из трека?`)) return
    try {
      const updated = await api.delete<WorkTrack>(`/api/work-tracks/${selectedTrack.id}/items/${item.id}`)
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
      void loadReadiness(updated.id)
      toast.success('Элемент удален')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить элемент')
    }
  }

  const moveItem = async (itemId: string, direction: -1 | 1) => {
    if (!selectedTrack) return
    const items = [...selectedTrack.items].sort((a, b) => a.position - b.position)
    const index = items.findIndex((item) => item.id === itemId)
    const nextIndex = index + direction
    if (index < 0 || nextIndex < 0 || nextIndex >= items.length) return
    const nextItems = [...items]
    const [item] = nextItems.splice(index, 1)
    nextItems.splice(nextIndex, 0, item)
    try {
      const updated = await api.post<WorkTrack>(`/api/work-tracks/${selectedTrack.id}/items/reorder`, {
        item_ids: nextItems.map((nextItem) => nextItem.id),
      })
      setTracks((current) => current.map((track) => (track.id === updated.id ? updated : track)))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить порядок')
    }
  }

  const decideAssignedItem = async (assigned: WorkTrackAssignedItem, decision: 'reserved' | 'declined') => {
    const comment = decision === 'declined'
      ? window.prompt('Комментарий к отказу, если нужно')?.trim() || null
      : null
    try {
      const updated = await api.post<WorkTrackAssignedItem>(
        `/api/work-tracks/assigned-items/${assigned.item.id}/decision`,
        { decision, comment }
      )
      setAssignedItems((current) =>
        current.map((entry) => (entry.item.id === assigned.item.id ? updated : entry))
      )
      toast.success(decision === 'reserved' ? 'Задача забронирована' : 'Отказ отправлен')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось отправить решение')
    }
  }

  const activeTracks = tracks.filter((track) => track.status === 'active').length
  const totalItems = tracks.reduce((sum, track) => sum + track.items_count, 0)
  const nearestDue = useMemo(() => {
    const dates = tracks
      .flatMap((track) => [track.next_due_at, track.due_at])
      .filter((value): value is string => Boolean(value))
      .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())
    return dates[0] || null
  }, [tracks])

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <GitBranch className="h-4 w-4" />
            Треки задач
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-foreground">Последовательности работ</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Собирайте связанные DPMS-задачи, личные задачи и ручные шаги в один управляемый процесс.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="rounded-md border border-border bg-surface-soft px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Активно</div>
            <div className="text-lg font-semibold text-foreground">{activeTracks}</div>
          </div>
          <div className="rounded-md border border-border bg-surface-soft px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Шагов</div>
            <div className="text-lg font-semibold text-foreground">{totalItems}</div>
          </div>
          <div className="rounded-md border border-border bg-surface-soft px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Ближайший срок</div>
            <div className="text-lg font-semibold text-foreground">{formatDate(nearestDue)}</div>
          </div>
        </div>
      </div>

      {assignedItems.length > 0 && (
        <section className="rounded-lg border border-border bg-surface p-4 shadow-sm">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <CalendarClock className="h-4 w-4 text-muted-foreground" />
                Предстоящие назначения по трекам
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Это задачи, которые предложены вам на будущее. Подтвердите бронь или откажитесь, чтобы владелец трека переназначил работу.
              </p>
            </div>
            <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
              {assignedItems.length}
            </span>
          </div>
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {assignedItems.slice(0, 6).map((assigned) => (
              <div key={assigned.item.id} className="rounded-md border border-border bg-surface-soft p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-foreground">{assigned.item.effective_title}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {assigned.track_title} · {formatDate(assigned.item.effective_due_at)}
                    </div>
                  </div>
                  <span className="shrink-0 rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground">
                    {reservationStatusLabel[assigned.item.reservation_status] || assigned.item.reservation_status}
                  </span>
                </div>
                {assigned.item.reservation_status === 'sent' && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => decideAssignedItem(assigned, 'reserved')}
                      className="inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition hover:opacity-90"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Подтвердить
                    </button>
                    <button
                      type="button"
                      onClick={() => decideAssignedItem(assigned, 'declined')}
                      className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-surface px-3 text-xs font-medium text-foreground transition hover:bg-muted"
                    >
                      <X className="h-4 w-4" />
                      Отказаться
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="rounded-lg border border-border bg-surface shadow-sm">
          <div className="border-b border-border p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-foreground">Список треков</h2>
              <button
                type="button"
                onClick={() => {
                  setEditingTrackId(null)
                  setTrackForm(emptyTrackForm)
                  setShowTrackForm((value) => !value)
                }}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90"
              >
                <Plus className="h-4 w-4" />
                Новый
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {filterOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFilter(option.value)}
                  className={cn(
                    'rounded-md border px-3 py-1.5 text-xs font-medium transition',
                    filter === option.value
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-surface-soft text-muted-foreground hover:text-foreground'
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <label className="mt-3 flex items-center gap-2 rounded-md border border-border bg-surface-soft px-3 py-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Поиск по трекам"
                className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              />
            </label>
          </div>

          {showTrackForm && (
            <div className="border-b border-border bg-surface-soft p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">
                  {editingTrackId ? 'Редактировать трек' : 'Новый трек'}
                </h3>
                <button
                  type="button"
                  onClick={() => {
                    setShowTrackForm(false)
                    setEditingTrackId(null)
                    setTrackForm(emptyTrackForm)
                  }}
                  className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label="Закрыть форму"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-3 space-y-3">
                <input
                  value={trackForm.title}
                  onChange={(event) => setTrackForm((form) => ({ ...form, title: event.target.value }))}
                  placeholder="Название трека"
                  className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                />
                <textarea
                  value={trackForm.description}
                  onChange={(event) => setTrackForm((form) => ({ ...form, description: event.target.value }))}
                  placeholder="Описание"
                  rows={3}
                  className="w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="text-xs font-medium text-muted-foreground">
                    Старт
                    <input
                      type="datetime-local"
                      value={trackForm.startAt}
                      onChange={(event) => setTrackForm((form) => ({ ...form, startAt: event.target.value }))}
                      className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    />
                  </label>
                  <label className="text-xs font-medium text-muted-foreground">
                    Срок
                    <input
                      type="datetime-local"
                      value={trackForm.dueAt}
                      onChange={(event) => setTrackForm((form) => ({ ...form, dueAt: event.target.value }))}
                      className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    />
                  </label>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <select
                    value={trackForm.status}
                    onChange={(event) =>
                      setTrackForm((form) => ({ ...form, status: event.target.value as WorkTrackStatus }))
                    }
                    className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                  >
                    {Object.entries(trackStatusLabel).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={trackForm.color}
                    onChange={(event) => setTrackForm((form) => ({ ...form, color: event.target.value }))}
                    className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                  >
                    {colorOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={saveTrack}
                  disabled={saving}
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  Сохранить
                </button>
              </div>
            </div>
          )}

          <div className="max-h-[620px] overflow-y-auto p-2">
            {loading ? (
              <div className="space-y-2 p-2">
                {[0, 1, 2].map((item) => (
                  <div key={item} className="h-24 animate-pulse rounded-md bg-muted" />
                ))}
              </div>
            ) : tracks.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">Треков пока нет.</div>
            ) : (
              <div className="space-y-2">
                {tracks.map((track) => {
                  const selected = selectedTrack?.id === track.id
                  const color = colorOptions.find((option) => option.value === track.color) || colorOptions[0]
                  return (
                    <button
                      key={track.id}
                      type="button"
                      onClick={() => setSelectedId(track.id)}
                      className={cn(
                        'w-full rounded-md border p-3 text-left transition',
                        selected
                          ? 'border-primary bg-primary/10'
                          : 'border-border bg-surface-soft hover:border-primary/60 hover:bg-muted'
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={cn('h-2.5 w-2.5 rounded-full', color.className)} />
                            <span className="truncate text-sm font-semibold text-foreground">{track.title}</span>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {trackStatusLabel[track.status]} · {track.items_count} шагов · {track.progress_percent}%
                          </div>
                        </div>
                        <span className="shrink-0 rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground">
                          {formatDate(track.next_due_at || track.due_at)}
                        </span>
                      </div>
                      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${track.progress_percent}%` }}
                        />
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </aside>

        <section className="min-w-0 rounded-lg border border-border bg-surface shadow-sm">
          {!selectedTrack ? (
            <div className="flex min-h-[420px] flex-col items-center justify-center p-6 text-center">
              <GitBranch className="h-10 w-10 text-muted-foreground" />
              <h2 className="mt-3 text-lg font-semibold text-foreground">Выберите или создайте трек</h2>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                Трек помогает держать под контролем последовательность шагов, даже если часть работы живет в разных разделах системы.
              </p>
            </div>
          ) : (
            <div>
              <div className="border-b border-border p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-xl font-semibold text-foreground">{selectedTrack.title}</h2>
                      <span className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                        {trackStatusLabel[selectedTrack.status]}
                      </span>
                    </div>
                    {selectedTrack.description && (
                      <p className="mt-2 max-w-3xl whitespace-pre-wrap text-sm text-muted-foreground">
                        {selectedTrack.description}
                      </p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span className="rounded-md bg-surface-soft px-2 py-1">
                        Старт: {formatDate(selectedTrack.start_at)}
                      </span>
                      <span className="rounded-md bg-surface-soft px-2 py-1">
                        Срок: {formatDate(selectedTrack.due_at)}
                      </span>
                      <span className="rounded-md bg-surface-soft px-2 py-1">
                        Ближайший шаг: {daysUntil(selectedTrack.next_due_at)}
                      </span>
                      {selectedTrack.methodology_title && (
                        <span className="rounded-md bg-primary/10 px-2 py-1 font-medium text-primary">
                          {selectedTrack.methodology_title}
                          {selectedTrack.methodology_version ? ` · ${selectedTrack.methodology_version}` : ''}
                        </span>
                      )}
                      {selectedTrack.route_name && (
                        <span className="rounded-md bg-surface-soft px-2 py-1">
                          Маршрут: {selectedTrack.route_name}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
                    {selectedTrack.status === 'draft' && (
                      <button
                        type="button"
                        onClick={() => activateTrack(selectedTrack)}
                        className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90"
                      >
                        <PlayCircle className="h-4 w-4" />
                        Активировать
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={sendForReview}
                      disabled={methodologyBusy}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-primary/40 bg-primary/10 px-3 text-sm font-medium text-primary transition hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Send className="h-4 w-4" />
                      На рассмотрение
                    </button>
                    <button
                      type="button"
                      onClick={() => startEditTrack(selectedTrack)}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground transition hover:bg-muted"
                    >
                      <Pencil className="h-4 w-4" />
                      Изменить
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        patchTrack(selectedTrack, { status: selectedTrack.status === 'paused' ? 'active' : 'paused' })
                      }
                      disabled={selectedTrack.status !== 'active' && selectedTrack.status !== 'paused'}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground transition hover:bg-muted"
                    >
                      {selectedTrack.status === 'paused' ? <PlayCircle className="h-4 w-4" /> : <PauseCircle className="h-4 w-4" />}
                      {selectedTrack.status === 'paused' ? 'Возобновить' : 'Пауза'}
                    </button>
                    <button
                      type="button"
                      onClick={() => patchTrack(selectedTrack, { status: 'done' })}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 text-sm font-medium text-emerald-700 transition hover:bg-emerald-500/20 dark:text-emerald-300"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Закрыть
                    </button>
                    <button
                      type="button"
                      onClick={() => patchTrack(selectedTrack, { status: 'archived' })}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface-soft px-3 text-sm font-medium text-foreground transition hover:bg-muted"
                    >
                      <Archive className="h-4 w-4" />
                      Архив
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteTrack(selectedTrack)}
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-red-500/40 bg-red-500/10 px-3 text-sm font-medium text-red-700 transition hover:bg-red-500/20 dark:text-red-300"
                    >
                      <Trash2 className="h-4 w-4" />
                      Удалить
                    </button>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <div className="rounded-md border border-border bg-surface-soft p-3">
                    <div className="text-xs text-muted-foreground">Прогресс</div>
                    <div className="mt-1 text-2xl font-semibold text-foreground">{selectedTrack.progress_percent}%</div>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${selectedTrack.progress_percent}%` }}
                      />
                    </div>
                  </div>
                  <div className="rounded-md border border-border bg-surface-soft p-3">
                    <div className="text-xs text-muted-foreground">Готово</div>
                    <div className="mt-1 text-2xl font-semibold text-foreground">
                      {selectedTrack.done_count}/{selectedTrack.items_count}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">по элементам последовательности</div>
                  </div>
                  <div className="rounded-md border border-border bg-surface-soft p-3">
                    <div className="text-xs text-muted-foreground">Следующий срок</div>
                    <div className="mt-1 text-2xl font-semibold text-foreground">{formatDate(selectedTrack.next_due_at)}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{daysUntil(selectedTrack.next_due_at)}</div>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-base font-semibold text-foreground">Последовательность</h3>
                    <span className="text-xs text-muted-foreground">Порядок шагов можно менять стрелками</span>
                  </div>
                  <div className="mt-3 space-y-2">
                    {selectedTrack.items.length === 0 ? (
                      <div className="rounded-md border border-dashed border-border bg-surface-soft p-6 text-center text-sm text-muted-foreground">
                        В треке пока нет элементов. Добавьте задачу, личную задачу или ручной шаг.
                      </div>
                    ) : (
                      selectedTrack.items
                        .slice()
                        .sort((a, b) => a.position - b.position)
                        .map((item, index, array) => {
                          const tone = itemTone(item)
                          return (
                            <div
                              key={item.id}
                              className="rounded-md border border-border bg-surface-soft p-3"
                            >
                              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-2">
                                    {item.is_done ? (
                                      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-300" />
                                    ) : (
                                      <Circle className="h-4 w-4 text-muted-foreground" />
                                    )}
                                    <span className="rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground">
                                      {linkedLabel(item)}
                                    </span>
                                    <span className="rounded-md bg-surface px-2 py-1 text-xs font-medium text-muted-foreground">
                                      {itemTypeLabel[item.item_type]}
                                    </span>
                                    {!item.source_available && (
                                      <span className="rounded-md bg-red-500/10 px-2 py-1 text-xs font-medium text-red-700 dark:text-red-300">
                                        источник удален
                                      </span>
                                    )}
                                  </div>
                                  <div className="mt-2 truncate text-sm font-semibold text-foreground">
                                    {item.effective_title}
                                  </div>
                                  {(item.description || item.notes) && (
                                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                                      {item.description || item.notes}
                                    </p>
                                  )}
                                  {item.item_type === 'cube' && (
                                    <div className="mt-3 grid gap-2 rounded-md border border-border bg-surface p-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                                      <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                        Исполнитель email
                                        <input
                                          defaultValue={item.proposed_executor_email || ''}
                                          onBlur={(event) => {
                                            const value = event.currentTarget.value.trim().toLowerCase()
                                            if ((item.proposed_executor_email || '') !== value) {
                                              void patchItem(item, { proposed_executor_email: value || null })
                                            }
                                          }}
                                          placeholder="name@example.com"
                                          className="mt-1 w-full rounded-md border border-border bg-surface-soft px-2 py-1.5 text-sm normal-case tracking-normal text-foreground outline-none focus:border-primary"
                                        />
                                      </label>
                                      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                        Роль из методологии
                                        <div className="mt-1 rounded-md bg-surface-soft px-2 py-1.5 text-sm normal-case tracking-normal text-foreground">
                                          {item.proposed_executor_name || 'не указана'}
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                    <span
                                      className={cn(
                                        'rounded-md px-2 py-1 font-medium',
                                        tone === 'done' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
                                        tone === 'danger' && 'bg-red-500/10 text-red-700 dark:text-red-300',
                                        tone === 'warn' && 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
                                        tone === 'neutral' && 'bg-surface text-muted-foreground'
                                      )}
                                    >
                                      {formatDate(item.effective_due_at)} · {daysUntil(item.effective_due_at)}
                                    </span>
                                    <span className="rounded-md bg-surface px-2 py-1 text-muted-foreground">
                                      {itemStatusLabel[item.status]}
                                    </span>
                                    {item.linked_status && (
                                      <span className="rounded-md bg-surface px-2 py-1 text-muted-foreground">
                                        источник: {item.linked_status}
                                      </span>
                                    )}
                                    {item.item_type === 'cube' && (
                                      <span className="rounded-md bg-primary/10 px-2 py-1 font-medium text-primary">
                                        {reservationStatusLabel[item.reservation_status] || item.reservation_status}
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <div className="flex shrink-0 flex-wrap gap-1">
                                  <button
                                    type="button"
                                    onClick={() => moveItem(item.id, -1)}
                                    disabled={index === 0}
                                    className="rounded-md border border-border bg-surface p-2 text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                                    aria-label="Поднять элемент"
                                  >
                                    <ArrowUp className="h-4 w-4" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => moveItem(item.id, 1)}
                                    disabled={index === array.length - 1}
                                    className="rounded-md border border-border bg-surface p-2 text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                                    aria-label="Опустить элемент"
                                  >
                                    <ArrowDown className="h-4 w-4" />
                                  </button>
                                  {(item.item_type === 'manual' || item.item_type === 'cube') && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        patchItem(item, { status: item.status === 'done' ? 'active' : 'done' })
                                      }
                                      className="rounded-md border border-border bg-surface p-2 text-muted-foreground transition hover:text-foreground"
                                      aria-label="Переключить готовность"
                                    >
                                      <CheckCircle2 className="h-4 w-4" />
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => deleteItem(item)}
                                    className="rounded-md border border-red-500/30 bg-red-500/10 p-2 text-red-700 transition hover:bg-red-500/20 dark:text-red-300"
                                    aria-label="Удалить элемент"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </button>
                                </div>
                              </div>
                            </div>
                          )
                        })
                    )}
                  </div>
                </div>

                <aside className="rounded-md border border-border bg-surface-soft p-4">
                  <div className="border-b border-border pb-4">
                    <div className="flex items-center gap-2">
                      <Boxes className="h-4 w-4 text-muted-foreground" />
                      <h3 className="text-sm font-semibold text-foreground">Методология</h3>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Версия методологии выбирается администратором. В треке выбирается только продукт и маршрут.
                    </p>
                    <div className="mt-3 space-y-3">
                      <div className="rounded-md border border-border bg-surface p-3">
                        {activeMethodology ? (
                          <>
                            <div className="text-sm font-medium text-foreground">{activeMethodology.title}</div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {activeMethodology.display_version || activeMethodology.methodology_version || 'без версии'} · кубиков: {activeMethodology.cubes_count} · маршрутов: {activeMethodology.routes_count}
                            </div>
                          </>
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            Активная методология не выбрана. Откройте админку и выберите применяемую версию.
                          </div>
                        )}
                      </div>

                      {productOptions.length > 0 && (
                        <select
                          value={methodologyForm.productKey}
                          onChange={(event) => setMethodologyForm((form) => ({ ...form, productKey: event.target.value }))}
                          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                        >
                          {productOptions.map((product) => (
                            <option key={product.key} value={product.key}>
                              {product.label}
                            </option>
                          ))}
                        </select>
                      )}

                      {routeOptions.length > 0 && (
                        <select
                          value={methodologyForm.routeKey}
                          onChange={(event) => setMethodologyForm((form) => ({ ...form, routeKey: event.target.value }))}
                          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                        >
                          {routeOptions.map((route) => (
                            <option key={route.key} value={route.key}>
                              {route.label}
                            </option>
                          ))}
                        </select>
                      )}

                      <label className="flex items-start gap-2 rounded-md bg-surface px-3 py-2 text-xs text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={methodologyForm.replaceExisting}
                          onChange={(event) => setMethodologyForm((form) => ({ ...form, replaceExisting: event.target.checked }))}
                          className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-primary"
                        />
                        Заменить уже добавленные кубики этого трека
                      </label>

                      <button
                        type="button"
                        onClick={applyMethodology}
                        disabled={!activeMethodology || methodologyBusy}
                        className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <Boxes className="h-4 w-4" />
                        Применить маршрут
                      </button>
                    </div>
                  </div>

                  <div className="pt-4">
                  <div className="flex items-center gap-2">
                    <Plus className="h-4 w-4 text-muted-foreground" />
                    <h3 className="text-sm font-semibold text-foreground">Добавить элемент</h3>
                  </div>
                  <div className="mt-3 space-y-3">
                    <select
                      value={itemForm.itemType}
                      onChange={(event) =>
                        setItemForm({
                          ...emptyItemForm,
                          itemType: event.target.value as WorkTrackItemType,
                        })
                      }
                      className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    >
                      {Object.entries(itemTypeLabel).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>

                    {itemForm.itemType === 'task' && (
                      <select
                        value={itemForm.taskId}
                        onChange={(event) => setItemForm((form) => ({ ...form, taskId: event.target.value }))}
                        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                      >
                        <option value="">Выберите DPMS-задачу</option>
                        {tasks.map((task) => (
                          <option key={task.id} value={task.id}>
                            #{task.task_number} · {task.title}
                          </option>
                        ))}
                      </select>
                    )}

                    {itemForm.itemType === 'personal_task' && (
                      <select
                        value={itemForm.personalTaskId}
                        onChange={(event) => setItemForm((form) => ({ ...form, personalTaskId: event.target.value }))}
                        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                      >
                        <option value="">Выберите личную задачу</option>
                        {personalTasks.map((task) => (
                          <option key={task.id} value={task.id}>
                            Л-{task.task_number} · {task.title}
                          </option>
                        ))}
                      </select>
                    )}

                    <input
                      value={itemForm.title}
                      onChange={(event) => setItemForm((form) => ({ ...form, title: event.target.value }))}
                      placeholder={
                        itemForm.itemType === 'manual'
                          ? 'Название ручного шага'
                          : itemForm.itemType === 'cube'
                            ? 'Название кубика'
                            : 'Переопределить название, если нужно'
                      }
                      className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    />
                    <textarea
                      value={itemForm.notes}
                      onChange={(event) => setItemForm((form) => ({ ...form, notes: event.target.value }))}
                      placeholder="Заметка по шагу"
                      rows={3}
                      className="w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    />
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
                      <label className="text-xs font-medium text-muted-foreground">
                        Старт шага
                        <input
                          type="datetime-local"
                          value={itemForm.startsAt}
                          onChange={(event) => setItemForm((form) => ({ ...form, startsAt: event.target.value }))}
                          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                        />
                      </label>
                      <label className="text-xs font-medium text-muted-foreground">
                        Срок шага
                        <input
                          type="datetime-local"
                          value={itemForm.dueAt}
                          onChange={(event) => setItemForm((form) => ({ ...form, dueAt: event.target.value }))}
                          className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                        />
                      </label>
                    </div>
                    <select
                      value={itemForm.status}
                      onChange={(event) =>
                        setItemForm((form) => ({ ...form, status: event.target.value as WorkTrackItemStatus }))
                      }
                      className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    >
                      {Object.entries(itemStatusLabel).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={addItem}
                      disabled={saving}
                      className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Link2 className="h-4 w-4" />
                      Добавить в трек
                    </button>
                  </div>
                  <div className="mt-4 rounded-md bg-surface p-3 text-xs text-muted-foreground">
                    <div className="flex items-center gap-2 font-medium text-foreground">
                      <ListChecks className="h-4 w-4" />
                      Логика завершения
                    </div>
                    <p className="mt-2">
                      DPMS-задачи и личные задачи считаются готовыми по статусу источника. Ручной шаг закрывается здесь.
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      <CalendarClock className="h-4 w-4" />
                      Если срок шага не указан, берется срок связанной задачи.
                    </div>
                  </div>
                  </div>
                </aside>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
