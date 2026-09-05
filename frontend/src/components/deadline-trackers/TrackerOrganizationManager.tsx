import { useRef, useState, type FormEvent } from 'react'
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ApiError, ApiUnavailableError } from '@/api/client'
import { TrackerDialog, TrackerField, TrackerIconButton, trackerButton, trackerInput } from './TrackerDialog'
import type { TrackerOrganization } from './trackerForm'

const swatches = [
  { value: '#0284c7', label: 'Голубой' }, { value: '#059669', label: 'Зеленый' },
  { value: '#d97706', label: 'Янтарный' }, { value: '#e11d48', label: 'Розовый' }, { value: '#64748b', label: 'Серый' },
]

export function TrackerOrganizationManager({ kind, items, onCreate, onPatch, onDelete, onReorder, onClose }: {
  kind: 'groups' | 'categories'
  items: TrackerOrganization[]
  onCreate: (payload: { name: string; color: string | null }) => Promise<void>
  onPatch: (id: string, payload: Partial<TrackerOrganization>) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onReorder: (ids: string[]) => Promise<void>
  onClose: () => void
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [color, setColor] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [error, setError] = useState('')
  const [nameError, setNameError] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const inFlight = useRef(false)
  const editing = items.find((item) => item.id === editingId)
  const dirty = name !== (editing?.name || '') || color !== (editing?.color || null)
  const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'ru'))

  const mutate = async (action: () => Promise<void>, reset = false) => {
    if (inFlight.current || uncertain) return
    inFlight.current = true; setBusy(true); setError('')
    try {
      await action()
      if (reset) { setEditingId(null); setName(''); setColor(null) }
    } catch (cause) {
      const unknownOutcome = cause instanceof ApiUnavailableError || (cause instanceof ApiError && cause.status >= 500)
      setUncertain(unknownOutcome)
      setError(unknownOutcome ? 'Ответ сервера потерян. Изменения могли сохраниться. Закройте окно и обновите список перед следующей правкой.' : cause instanceof Error ? cause.message : 'Не удалось сохранить изменения')
    }
    finally { inFlight.current = false; setBusy(false) }
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim()) { setNameError('Укажите название'); document.getElementById('tracker-organization-name')?.focus(); return }
    setNameError('')
    void mutate(() => editingId ? onPatch(editingId, { name: name.trim(), color }) : onCreate({ name: name.trim(), color }), true)
  }
  const select = (item: TrackerOrganization | null) => {
    if (dirty && !window.confirm('Отменить несохраненные изменения названия и цвета?')) return
    setEditingId(item?.id || null); setName(item?.name || ''); setColor(item?.color || null); setNameError('')
    document.getElementById('tracker-organization-name')?.focus()
  }
  const reorder = (item: TrackerOrganization, offset: number) => {
    const index = sorted.findIndex((row) => row.id === item.id)
    const next = [...sorted]
    const target = index + offset
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    void mutate(() => onReorder(next.map((row) => row.id)))
  }

  return <TrackerDialog title={kind === 'groups' ? 'Группы трекеров' : 'Категории трекеров'} dirty={dirty} busy={busy} onClose={onClose}>
    <div className="space-y-4">
      {error && <p role="alert" className="break-words text-sm text-rose-700 dark:text-rose-300">{error}</p>}
      <form onSubmit={submit} className="space-y-3" autoComplete="off">
        <TrackerField name="organization-name" label={editingId ? 'Новое название' : kind === 'groups' ? 'Новая группа' : 'Новая категория'} error={nameError}>
          <input id="tracker-organization-name" name="name" className={trackerInput} maxLength={100} value={name} disabled={busy} aria-invalid={Boolean(nameError)} aria-describedby={nameError ? 'tracker-organization-name-error' : undefined} onChange={(e) => { setName(e.target.value); setNameError('') }} />
        </TrackerField>
        <div role="group" aria-label="Цвет маркера" className="flex flex-wrap items-center gap-2">
          <button type="button" title="Без цвета" aria-label="Без цвета" aria-pressed={color === null} disabled={busy} className={cn(trackerButton, 'h-11 w-11 p-0', color === null && 'ring-2 ring-primary')} onClick={() => setColor(null)}><X className="h-4 w-4" aria-hidden="true" /></button>
          {swatches.map((swatch) => <button key={swatch.value} type="button" aria-label={swatch.label} title={swatch.label} aria-pressed={color === swatch.value} disabled={busy} onClick={() => setColor(swatch.value)} className={cn(trackerButton, 'h-11 w-11 p-0', color === swatch.value && 'ring-2 ring-primary')}><span className="h-5 w-5 rounded-full" style={{ backgroundColor: swatch.value }} /></button>)}
          <label className="sr-only" htmlFor="tracker-custom-color">Другой цвет</label><input id="tracker-custom-color" aria-label="Другой цвет" type="color" disabled={busy} value={color || '#64748b'} className="h-11 w-11 cursor-pointer rounded-md border border-slate-300 bg-transparent p-1" onChange={(e) => setColor(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-2"><button disabled={busy} type="submit" className={cn(trackerButton, 'bg-primary text-primary-foreground hover:bg-primary/90 dark:text-primary-foreground')}>
          {editingId ? <Save className="h-4 w-4" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}{editingId ? 'Сохранить название и цвет' : 'Создать'}
        </button>{editingId && <button type="button" disabled={busy} className={trackerButton} onClick={() => select(null)}>Отменить правку</button>}</div>
      </form>
      <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />Показать архив</label>
      <ul className="divide-y divide-slate-200 dark:divide-slate-700">
        {sorted.filter((item) => !item.is_archived || showArchived).map((item) => <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">{item.color && <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: item.color }} />}<span className="min-w-0 break-words text-sm">{item.name}{item.is_archived && <span className="ml-2 text-slate-500">Архив</span>}</span></div>
          <div className="flex flex-wrap gap-1" aria-label={`Действия: ${item.name}`}>
            <TrackerIconButton label={`Переименовать ${item.name}`} icon={Pencil} disabled={busy} onClick={() => select(item)} />
            {kind === 'groups' && <><TrackerIconButton label={`Выше: ${item.name}`} icon={ArrowUp} disabled={busy || sorted[0]?.id === item.id} onClick={() => reorder(item, -1)} />
            <TrackerIconButton label={`Ниже: ${item.name}`} icon={ArrowDown} disabled={busy || sorted[sorted.length - 1]?.id === item.id} onClick={() => reorder(item, 1)} /></>}
            <TrackerIconButton label={`${item.is_archived ? 'Восстановить' : 'Архивировать'} ${item.name}`} icon={item.is_archived ? ArchiveRestore : Archive} disabled={busy} onClick={() => {
              if (!item.is_archived && !window.confirm(kind === 'groups' ? 'Архивировать группу? Трекеры сохранятся. Напоминания трекеров продолжат работать.' : 'Архивировать категорию? Старые трекеры сохранят эту категорию.')) return
              void mutate(() => onPatch(item.id, { is_archived: !item.is_archived }))
            }} />
            {item.is_archived && !item.legacy_type && <TrackerIconButton label={`Удалить ${item.name}`} icon={Trash2} tone="danger" disabled={busy} onClick={() => {
              if (!window.confirm(kind === 'groups' ? 'Удалить группу? Ее трекеры не удалятся и перейдут в «Без группы».' : 'Удалить категорию? Трекеры сохранятся без этой категории.')) return
              void mutate(() => onDelete(item.id), editingId === item.id)
            }} />}
          </div>
        </li>)}
      </ul>
      {!sorted.some((item) => showArchived || !item.is_archived) && <p className="text-sm text-slate-500">{showArchived ? 'Список пуст' : 'Нет активных записей'}</p>}
    </div>
  </TrackerDialog>
}
