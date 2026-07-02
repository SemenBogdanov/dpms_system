import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive,
  ArrowRightCircle,
  CheckCircle2,
  Pencil,
  RotateCcw,
  Save,
  Search,
  StickyNote,
  Trash2,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { PersonalTask, QuickNote, QuickNoteCreate, QuickNoteStatus, QuickNoteUpdate } from '@/api/types'
import { cn } from '@/lib/utils'

type NoteFilter = QuickNoteStatus | 'all'

const emptyForm = {
  title: '',
  body: '',
  context: '',
  tagsText: '',
}

const statusLabel: Record<QuickNoteStatus, string> = {
  draft: 'Черновик',
  processed: 'Разобрано',
  archived: 'Архив',
}

const filterOptions: Array<{ value: NoteFilter; label: string }> = [
  { value: 'draft', label: 'Черновики' },
  { value: 'processed', label: 'Разобрано' },
  { value: 'archived', label: 'Архив' },
  { value: 'all', label: 'Все' },
]

function parseTags(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 8)
}

function tagsToText(value: string[] | null | undefined): string {
  return (value ?? []).join(', ')
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusClass(status: QuickNoteStatus): string {
  if (status === 'draft') return 'bg-blue-50 text-blue-700'
  if (status === 'processed') return 'bg-emerald-50 text-emerald-700'
  return 'bg-slate-100 text-slate-600'
}

function previewText(value: string): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact
}

export function QuickNotesPage() {
  const [notes, setNotes] = useState<QuickNote[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<NoteFilter>('draft')
  const [search, setSearch] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [editing, setEditing] = useState<QuickNote | null>(null)
  const [busy, setBusy] = useState(false)

  const loadNotes = useCallback(async () => {
    const params: Record<string, string> = { limit: '200' }
    if (filter !== 'all') params.status = filter
    if (search.trim()) params.search = search.trim()
    try {
      const data = await api.get<QuickNote[]>('/api/quick-notes', params)
      setNotes(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка загрузки заметок')
    } finally {
      setLoading(false)
    }
  }, [filter, search])

  useEffect(() => {
    loadNotes()
  }, [loadNotes])

  const stats = useMemo(() => {
    return notes.reduce(
      (acc, note) => {
        acc[note.status] += 1
        acc.total += 1
        return acc
      },
      { total: 0, draft: 0, processed: 0, archived: 0 } as Record<QuickNoteStatus | 'total', number>
    )
  }, [notes])

  const resetForm = () => {
    setEditing(null)
    setForm(emptyForm)
  }

  const editNote = (note: QuickNote) => {
    setEditing(note)
    setForm({
      title: note.title,
      body: note.body,
      context: note.context ?? '',
      tagsText: tagsToText(note.tags),
    })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleSave = async () => {
    if (!form.body.trim()) {
      toast.error('Введите текст заметки')
      return
    }
    setBusy(true)
    try {
      if (editing) {
        const payload: QuickNoteUpdate = {
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
        }
        await api.patch<QuickNote>(`/api/quick-notes/${editing.id}`, payload)
        toast.success('Заметка сохранена')
      } else {
        const payload: QuickNoteCreate = {
          title: form.title.trim() || null,
          body: form.body,
          context: form.context.trim() || null,
          tags: parseTags(form.tagsText),
        }
        await api.post<QuickNote>('/api/quick-notes', payload)
        toast.success('Заметка создана')
      }
      resetForm()
      await loadNotes()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  const updateStatus = async (note: QuickNote, status: QuickNoteStatus) => {
    try {
      await api.patch<QuickNote>(`/api/quick-notes/${note.id}`, { status })
      await loadNotes()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка статуса')
    }
  }

  const deleteNote = async (note: QuickNote) => {
    if (!window.confirm('Удалить заметку?')) return
    try {
      await api.delete(`/api/quick-notes/${note.id}`)
      if (editing?.id === note.id) resetForm()
      await loadNotes()
      toast.success('Заметка удалена')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка удаления')
    }
  }

  const createPersonalTask = async (note: QuickNote) => {
    try {
      await api.post<PersonalTask>('/api/personal-tasks', {
        title: note.title,
        description: note.context,
        notes: note.body,
        priority: 'medium',
        status: 'planned',
        source_quick_note_id: note.id,
      })
      await loadNotes()
      toast.success('Личная задача создана')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Ошибка создания личной задачи')
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Заметки</h1>
          <p className="mt-1 text-sm text-slate-500">Быстрый личный capture</p>
        </div>
        <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white text-center text-xs">
          <div className="px-3 py-2">
            <div className="font-semibold text-slate-900">{stats.total}</div>
            <div className="text-slate-400">в списке</div>
          </div>
          <div className="border-l border-slate-200 px-3 py-2">
            <div className="font-semibold text-blue-700">{stats.draft}</div>
            <div className="text-slate-400">черновики</div>
          </div>
          <div className="border-l border-slate-200 px-3 py-2">
            <div className="font-semibold text-emerald-700">{stats.processed}</div>
            <div className="text-slate-400">разобрано</div>
          </div>
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <StickyNote className="h-4 w-4 text-slate-400" />
          {editing ? 'Редактирование заметки' : 'Новая заметка'}
        </div>
        <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_180px]">
          <input
            type="text"
            value={form.context}
            onChange={(event) => setForm((current) => ({ ...current, context: event.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
            placeholder="Контекст"
            maxLength={160}
          />
          <input
            type="text"
            value={form.tagsText}
            onChange={(event) => setForm((current) => ({ ...current, tagsText: event.target.value }))}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
            placeholder="Теги"
          />
        </div>
        <input
          type="text"
          value={form.title}
          onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
          className="mt-3 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
          placeholder="Заголовок"
          maxLength={160}
        />
        <textarea
          value={form.body}
          onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
          className="mt-3 min-h-[190px] w-full resize-y rounded-lg border border-slate-200 px-3 py-3 text-base leading-6 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
          placeholder="Текст заметки"
        />
        <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
          {editing && (
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              <X className="h-4 w-4" />
              Отмена
            </button>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={busy || !form.body.trim()}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {busy ? 'Сохранение...' : editing ? 'Сохранить' : 'Сохранить заметку'}
          </button>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {filterOptions.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={cn(
                  'rounded-lg px-3 py-2 text-sm font-medium transition',
                  filter === item.value
                    ? 'bg-slate-900 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="min-h-10 w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 lg:w-72"
              placeholder="Поиск"
            />
          </label>
        </div>

        {loading && <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">Загрузка...</div>}
        {!loading && notes.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
            Заметок пока нет.
          </div>
        )}
        <div className="grid gap-3">
          {notes.map((note) => (
            <article key={note.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="break-words text-base font-semibold text-slate-900">{note.title}</h2>
                    <span className={cn('rounded px-2 py-0.5 text-xs font-medium', statusClass(note.status))}>
                      {statusLabel[note.status]}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
                    <span>{formatDate(note.updated_at)}</span>
                    {note.context && <span>{note.context}</span>}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => createPersonalTask(note)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-blue-600 hover:bg-blue-50"
                    title="Создать личную задачу"
                    aria-label="Создать личную задачу"
                  >
                    <ArrowRightCircle className="h-4 w-4" />
                  </button>
                  {note.status !== 'processed' && (
                    <button
                      type="button"
                      onClick={() => updateStatus(note, 'processed')}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-emerald-600 hover:bg-emerald-50"
                      title="Разобрано"
                      aria-label="Разобрано"
                    >
                      <CheckCircle2 className="h-4 w-4" />
                    </button>
                  )}
                  {note.status !== 'archived' ? (
                    <button
                      type="button"
                      onClick={() => updateStatus(note, 'archived')}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50"
                      title="В архив"
                      aria-label="В архив"
                    >
                      <Archive className="h-4 w-4" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => updateStatus(note, 'draft')}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-blue-600 hover:bg-blue-50"
                      title="Вернуть в черновики"
                      aria-label="Вернуть в черновики"
                    >
                      <RotateCcw className="h-4 w-4" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => editNote(note)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50"
                    title="Редактировать"
                    aria-label="Редактировать"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteNote(note)}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-100 text-red-500 hover:bg-red-50"
                    title="Удалить"
                    aria-label="Удалить"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{previewText(note.body)}</p>
              {note.tags.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {note.tags.map((tag) => (
                    <span key={tag} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
