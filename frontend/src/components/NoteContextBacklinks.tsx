import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Folder, StickyNote } from 'lucide-react'
import { noteGroupsApi, type NoteBacklinks, type NoteTargetType } from '@/api/noteGroups'
import { noteControl } from './NoteGroupDialog'

export type NoteContextBacklinksProps = { targetType: NoteTargetType; targetId: string; className?: string; excludeNoteIds?: string[] }

export function NoteContextBacklinks({ targetType, targetId, className = '', excludeNoteIds = [] }: NoteContextBacklinksProps) {
  const [data, setData] = useState<NoteBacklinks | null>(null)
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const load = useCallback(async () => {
    const id = ++sequence.current
    setData(null); setError('')
    try { const result = await noteGroupsApi.backlinks(targetType, targetId); if (id === sequence.current) setData(result) }
    catch (error) { if (id === sequence.current) setError(error instanceof Error ? error.message : 'Не удалось загрузить заметки') }
  }, [targetId, targetType])
  useEffect(() => { void load(); return () => { sequence.current += 1 } }, [load])
  const visibleNotes = data?.notes.filter(note => !excludeNoteIds.includes(note.id)) ?? []
  return <section aria-label="Связанные заметки" className={`min-w-0 border-t border-slate-200 py-3 text-slate-900 dark:border-slate-700 dark:text-slate-100 ${className}`}>
    <h3 className="mb-2 text-sm font-semibold">Заметки</h3>
    {error ? <p role="alert" className="text-sm">{error} <button type="button" className={noteControl} onClick={() => void load()}>Повторить</button></p>
      : !data ? <p role="status" className="text-sm">Загрузка...</p>
        : visibleNotes.length + data.groups.length === 0 ? <p className="text-sm text-slate-500">Нет доступных заметок</p>
          : <ul>{data.groups.map(group => <li key={group.id}>
            <Link className="flex min-h-11 min-w-0 items-center gap-2 text-sm text-primary hover:underline" to={`/quick-notes?group=${group.id}`}><Folder className="h-4 w-4 shrink-0" /><span className="break-words">{group.title}{group.archived ? ' (архив)' : ''}</span></Link>
          </li>)}{visibleNotes.map(note => <li key={note.id}>
            <Link className="flex min-h-11 min-w-0 items-center gap-2 text-sm text-primary hover:underline" to={`/quick-notes/${note.id}`}><StickyNote className="h-4 w-4 shrink-0" /><span className="break-words">{note.title}</span></Link>
          </li>)}</ul>}
  </section>
}
