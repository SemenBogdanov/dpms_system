import { useState } from 'react'
import { FolderInput, Share2, X } from 'lucide-react'
import { noteGroupsApi, type NoteGroup } from '@/api/noteGroups'
import { noteControl, noteInput } from './NoteGroupDialog'

export function NoteBulkActions({ noteIds, groups, onChanged, onClear, onShare }: {
  noteIds: string[]; groups: NoteGroup[]; onChanged: () => Promise<void>; onClear: () => void; onShare: () => void
}) {
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <section aria-label="Выбранные заметки" className="flex min-w-0 flex-wrap items-center gap-2 border-b border-slate-200 py-3 text-slate-900 dark:border-slate-700 dark:text-slate-100">
    <span className="text-sm">Выбрано: {noteIds.length}</span>
    <label className="w-full min-w-0 sm:w-60"><span className="sr-only">Перенести в группу</span>
      <select className={noteInput} value={target} disabled={busy} onChange={event => setTarget(event.target.value)}><option value="">Без группы</option>{groups.filter(group => !group.archived).map(group => <option key={group.id} value={group.id}>{group.title}</option>)}</select>
    </label>
    <button type="button" className={noteControl} disabled={busy} onClick={async () => {
      if (busy) return
      setBusy(true); setError('')
      try { await noteGroupsApi.move(noteIds, target || null); await onChanged(); onClear() }
      catch (error) { setError(error instanceof Error ? error.message : 'Не удалось перенести заметки') }
      finally { setBusy(false) }
    }}><FolderInput className="h-4 w-4" />Перенести</button>
    <button type="button" className={noteControl} disabled={busy} onClick={onShare}><Share2 className="h-4 w-4" />Открыть доступ</button>
    <button type="button" className={noteControl} disabled={busy} onClick={onClear} title="Снять выбор" aria-label="Снять выбор"><X className="h-4 w-4" /></button>
    {error && <p className="w-full break-words text-sm text-red-600" role="alert">{error}</p>}
  </section>
}
