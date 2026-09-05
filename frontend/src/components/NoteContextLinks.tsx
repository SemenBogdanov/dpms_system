import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Link2, Plus, Trash2 } from 'lucide-react'
import { noteGroupsApi, type NoteContextLink, type NoteTarget } from '@/api/noteGroups'
import { noteControl, noteInput } from './NoteGroupDialog'

export function NoteContextLinks({ sourceType, sourceId, readOnly = false }: {
  sourceType: 'group' | 'note'; sourceId: string; readOnly?: boolean
}) {
  const [links, setLinks] = useState<NoteContextLink[]>([])
  const [targets, setTargets] = useState<NoteTarget[]>([])
  const [selected, setSelected] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(0)
  const load = useCallback(async () => {
    const id = ++request.current
    setLoading(true)
    try {
      const data = await noteGroupsApi.links(sourceType, sourceId)
      const options = readOnly ? [] : await noteGroupsApi.targets()
      if (id !== request.current) return
      setLinks(data); setTargets(options); setError('')
    } catch (error) {
      if (id === request.current) setError(error instanceof Error ? error.message : 'Связи недоступны')
    } finally { if (id === request.current) setLoading(false) }
  }, [sourceId, sourceType, readOnly])
  useEffect(() => { setLinks([]); setTargets([]); setSelected(''); void load(); return () => { request.current += 1 } }, [load])
  const mutate = async (action: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    try { await action(); setSelected(''); await load() }
    catch (error) { setError(error instanceof Error ? error.message : 'Не удалось изменить связь') }
    finally { setBusy(false) }
  }
  const options = targets.filter(target => !links.some(link => !link.inherited && link.target_id === target.target_id && link.target_type === target.target_type))
  return <section className="min-w-0 space-y-2 border-t border-slate-200 py-3 text-slate-900 dark:border-slate-700 dark:text-slate-100" aria-label="Контекстные связи">
    <h3 className="text-sm font-semibold">Связи</h3>
    {loading && <p role="status" className="text-sm">Загрузка связей...</p>}
    {error && <p role="alert" className="break-words text-sm text-red-600">{error} <button type="button" className={noteControl} onClick={() => void load()}>Повторить</button></p>}
    {!loading && !error && links.length === 0 && <p className="text-sm text-slate-500">Нет связей</p>}
    <ul className="divide-y divide-slate-200 dark:divide-slate-700">
      {links.map(link => <li key={`${link.origin}:${link.id}`} className="flex min-w-0 items-center gap-2 py-1">
        <Link2 className="h-4 w-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <Link to={link.target_type === 'entity' ? `/work-entities?entity=${link.target_id}` : `/personal-tasks?task=${link.target_id}`}
            className="block min-h-11 content-center break-words text-sm text-primary underline-offset-2 hover:underline">{link.title}</Link>
          {link.inherited && <span className="text-xs text-slate-500">Из группы</span>}
          {link.origin === 'source' && <span className="text-xs text-slate-500">Источник задачи</span>}
        </div>
        {!readOnly && link.can_remove && <button type="button" disabled={busy} className={noteControl} title="Убрать связь" aria-label={`Убрать связь: ${link.title}`}
          onClick={() => void mutate(() => noteGroupsApi.removeLink(sourceType, sourceId, link))}><Trash2 className="h-4 w-4" /></button>}
      </li>)}
    </ul>
    {!readOnly && <form className="flex min-w-0 gap-2" onSubmit={event => {
      event.preventDefault()
      const target = options.find(item => `${item.target_type}:${item.target_id}` === selected)
      if (target) void mutate(() => noteGroupsApi.addLink(sourceType, sourceId, target))
    }}>
      <label className="min-w-0 flex-1"><span className="sr-only">Проект, цель или своя задача</span>
        <select className={noteInput} value={selected} onChange={event => setSelected(event.target.value)} disabled={busy || loading} required>
          <option value="">Проект, цель или своя задача</option>
          {options.map(target => <option key={`${target.target_type}:${target.target_id}`} value={`${target.target_type}:${target.target_id}`}>{target.target_type === 'personal_task' ? 'Задача: ' : ''}{target.title}</option>)}
        </select>
      </label>
      <button type="submit" className={noteControl} disabled={busy || loading} title="Добавить связь" aria-label="Добавить связь"><Plus className="h-4 w-4" /></button>
    </form>}
  </section>
}
