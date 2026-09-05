import { useState } from 'react'
import { Archive, ArrowDown, ArrowUp, ChevronDown, ChevronRight, Folder, Pencil, Plus, RotateCcw, Save, Share2, Trash2 } from 'lucide-react'
import { noteGroupsApi, type NoteGroup } from '@/api/noteGroups'
import { NoteContextLinks } from './NoteContextLinks'
import { NoteGroupDialog, noteControl, noteInput } from './NoteGroupDialog'

export function NoteGroupsPanel({ groups, view, onView, onChanged, onShare }: {
  groups: NoteGroup[]; view: string; onView: (id: string) => void; onChanged: () => Promise<void>; onShare: (groupId: string) => void
}) {
  const [editing, setEditing] = useState<NoteGroup | 'new' | null>(null)
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const current = typeof editing === 'object' && editing ? groups.find(group => group.id === editing.id) ?? editing : null
  const change = async (action: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true); setError('')
    try { await action(); await onChanged() }
    catch (error) { setError(error instanceof Error ? error.message : 'Не удалось изменить группу') }
    finally { setBusy(false) }
  }
  const reorder = (id: string, offset: number) => {
    const next = [...groups]
    const index = next.findIndex(group => group.id === id)
    if (index + offset < 0 || index + offset >= next.length) return
    ;[next[index], next[index + offset]] = [next[index + offset], next[index]]
    void change(() => noteGroupsApi.order(next))
  }
  return <section aria-label="Группы заметок" className="space-y-2 border-y border-slate-200 py-3 text-slate-900 dark:border-slate-700 dark:text-slate-100">
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={noteControl} aria-pressed={view === 'all'} onClick={() => onView('all')}>Все</button>
      <button type="button" className={noteControl} aria-pressed={view === 'ungrouped'} onClick={() => onView('ungrouped')}>Без группы</button>
      <button type="button" className={noteControl} onClick={() => { setTitle(''); setEditing('new'); setError('') }} title="Создать группу" aria-label="Создать группу"><Plus className="h-4 w-4" /></button>
      <label className="flex min-h-11 items-center gap-2 text-sm"><input className="h-4 w-4 shrink-0" type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} />Архив групп</label>
    </div>
    <ul className="divide-y divide-slate-200 dark:divide-slate-700">{groups.filter(group => showArchived || !group.archived || group.id === view).map(group => <li key={group.id} className="flex min-w-0 flex-wrap items-center gap-1 py-1">
      <button type="button" className={noteControl} disabled={busy} aria-expanded={!group.collapsed} title={group.collapsed ? 'Развернуть группу' : 'Свернуть группу'} aria-label={`${group.collapsed ? 'Развернуть' : 'Свернуть'}: ${group.title}`}
        onClick={() => void change(() => noteGroupsApi.update(group, { collapsed: !group.collapsed }))}>{group.collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</button>
      <button type="button" className={`flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-2 text-left text-sm ${view === group.id ? 'bg-primary/10 font-semibold text-primary' : ''}`} aria-pressed={view === group.id} onClick={() => onView(group.id)}>
        <Folder className="h-4 w-4 shrink-0" /><span className="min-w-0 break-words">{group.title}{group.archived ? ' (архив)' : ''}</span><span className="shrink-0 text-xs tabular-nums">{group.note_count}</span>
      </button>
      <button type="button" className={noteControl} title="Настроить группу" aria-label={`Настроить группу: ${group.title}`} onClick={() => { setTitle(group.title); setEditing(group); setError('') }}><Pencil className="h-4 w-4" /></button>
    </li>)}</ul>
    {error && !editing && <p role="alert" className="text-sm text-red-600">{error}</p>}
    {editing && <NoteGroupDialog title={current ? 'Настройки группы' : 'Новая группа'} dirty={title !== (current?.title ?? '')} busy={busy} onClose={() => setEditing(null)}>
      <form className="space-y-3" onSubmit={event => { event.preventDefault(); void change(async () => {
        if (current) await noteGroupsApi.update(current, { title })
        else await noteGroupsApi.create(title)
        setEditing(null)
      }) }}>
        <label className="block text-sm">Название группы<input name="groupTitle" className={`${noteInput} mt-1`} maxLength={160} required value={title} onChange={event => setTitle(event.target.value)} disabled={busy} /></label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <button type="submit" className={`${noteControl} bg-primary text-primary-foreground`} disabled={busy}><Save className="h-4 w-4" />Сохранить</button>
      </form>
      {current && <>
        <div className="my-3 flex flex-wrap gap-2">
          <button type="button" className={noteControl} disabled={busy || groups[0]?.id === current.id} title="Переместить выше" aria-label="Переместить выше" onClick={() => reorder(current.id, -1)}><ArrowUp className="h-4 w-4" /></button>
          <button type="button" className={noteControl} disabled={busy || groups.at(-1)?.id === current.id} title="Переместить ниже" aria-label="Переместить ниже" onClick={() => reorder(current.id, 1)}><ArrowDown className="h-4 w-4" /></button>
          <button type="button" className={noteControl} disabled={busy} onClick={() => void change(() => noteGroupsApi.update(current, { archived: !current.archived }))}>{current.archived ? <RotateCcw className="h-4 w-4" /> : <Archive className="h-4 w-4" />}{current.archived ? 'Восстановить' : 'Архивировать'}</button>
          {!current.archived && <button type="button" className={noteControl} disabled={busy || current.note_count === 0} onClick={() => {
            if (title !== current.title && !window.confirm('Закрыть без сохранения названия?')) return
            setEditing(null); onShare(current.id)
          }}><Share2 className="h-4 w-4" />Открыть доступ</button>}
          {current.archived && <button type="button" className={`${noteControl} text-red-600`} disabled={busy} onClick={() => {
            if (window.confirm('Удалить группу? Все заметки сохранятся в «Без группы».')) void change(async () => { await noteGroupsApi.remove(current); setEditing(null); if (view === current.id) onView('ungrouped') })
          }}><Trash2 className="h-4 w-4" />Удалить группу</button>}
        </div>
        <NoteContextLinks sourceType="group" sourceId={current.id} readOnly={current.archived} />
      </>}
    </NoteGroupDialog>}
  </section>
}
