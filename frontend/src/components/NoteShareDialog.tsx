import { useEffect, useRef, useState } from 'react'
import { Share2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { noteGroupsApi, type NoteRecipient, type NoteSharePreview, type NoteTarget } from '@/api/noteGroups'
import { NoteGroupDialog, noteControl, noteInput } from './NoteGroupDialog'

export function NoteShareDialog({ noteIds, groupId, onClose, onApplied }: {
  noteIds?: string[]; groupId?: string; onClose: () => void; onApplied: () => void
}) {
  const [recipients, setRecipients] = useState<NoteRecipient[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [projects, setProjects] = useState<NoteTarget[]>([])
  const [project, setProject] = useState('')
  const [preview, setPreview] = useState<NoteSharePreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const submitting = useRef(false)
  useEffect(() => {
    let cancelled = false
    setLoading(true); setRecipients([]); setSelected([]); setPreview(null); setConfirmed(false)
    void noteGroupsApi.recipients(project || undefined).then(data => { if (!cancelled) { setRecipients(data); setError('') } })
      .catch(error => { if (!cancelled) setError(error instanceof Error ? error.message : 'Получатели недоступны') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [project])
  useEffect(() => { let cancelled = false; void noteGroupsApi.targets().then(targets => { if (!cancelled) setProjects(targets.filter(target => target.target_type === 'entity')) }).catch(() => {}); return () => { cancelled = true } }, [])
  const submit = async () => {
    if (submitting.current) return
    if (!selected.length) { setError('Выберите хотя бы одного получателя'); return }
    submitting.current = true; setBusy(true); setError('')
    try {
      if (preview) {
        if (!confirmed) { setError('Подтвердите список заметок и получателей'); return }
        await noteGroupsApi.apply(preview.id)
        onApplied(); onClose()
      } else {
        setPreview(await noteGroupsApi.preview({ ...(groupId ? { group_id: groupId } : { note_ids: noteIds }), recipient_ids: selected, ...(project ? { project_id: project } : {}) }))
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Не удалось открыть доступ')
      if (error instanceof ApiError && [403, 404, 409].includes(error.status)) { setPreview(null); setConfirmed(false) }
    } finally { submitting.current = false; setBusy(false) }
  }
  return <NoteGroupDialog title="Открыть доступ" dirty={selected.length > 0} busy={busy} onClose={onClose}>
    <form className="space-y-4" onSubmit={event => { event.preventDefault(); void submit() }}>
      {!preview ? <>
        <label className="block text-sm">Участники проекта или цели
          <select className={`${noteInput} mt-1`} value={project} disabled={busy} onChange={event => setProject(event.target.value)}>
            <option value="">Все принятые контакты</option>{projects.map(item => <option value={item.target_id} key={item.target_id}>{item.title}</option>)}
          </select>
        </label>
        <fieldset disabled={busy || loading}><legend className="text-sm font-medium">Получатели</legend>
          {loading && <p role="status">Загрузка...</p>}
          {!loading && recipients.length === 0 && <p className="text-sm text-slate-500">Нет принятых контактов в выбранном списке</p>}
          {recipients.map(recipient => <label key={recipient.id} className="flex min-h-11 items-center gap-3 py-1 text-sm">
            <input className="h-4 w-4 shrink-0" type="checkbox" checked={selected.includes(recipient.id)} onChange={event => setSelected(ids => event.target.checked ? [...ids, recipient.id] : ids.filter(id => id !== recipient.id))} />
            <span className="break-words">{recipient.name}</span>
          </label>)}
        </fieldset>
      </> : <>
        <h3 className="text-sm font-semibold">Предпросмотр доступа</h3>
        <ul className="divide-y divide-slate-200 dark:divide-slate-700">{preview.notes.map(note => <li className="min-w-0 space-y-1 py-2" key={note.id}>
          <Link target="_blank" rel="noreferrer" to={`/quick-notes/${note.id}`} className="block break-words text-sm font-semibold text-primary">{note.title}</Link>
          <p className="break-words text-sm">{note.excerpt}</p>
          <p className="text-xs text-slate-500">Файлы: {note.files.length}. Комментарии: {note.comment_count}.</p>
          {note.files.map(file => <p key={file.id} className="break-words text-xs">{file.name}</p>)}
        </li>)}</ul>
        <div className="text-sm"><h3 className="font-semibold">Получатели</h3><ul>{preview.recipients.map(recipient => <li className="break-words" key={recipient.id}>{recipient.name}</li>)}</ul></div>
        <p className="text-sm">Новых доступов: {preview.new_share_count}. Уже открыто: {preview.existing_share_count}.</p>
        <label className="flex min-h-11 items-start gap-3 text-sm"><input className="mt-1 h-4 w-4 shrink-0" type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} required />
          <span>Открыть выбранным получателям заметки целиком, включая текущие и будущие файлы и обсуждение. Новые заметки группы не будут открыты автоматически.</span>
        </label>
      </>}
      {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {preview && <button type="button" className={noteControl} disabled={busy} onClick={() => { setPreview(null); setConfirmed(false) }}>Изменить получателей</button>}
        <button type="submit" disabled={busy || loading} className={`${noteControl} bg-primary px-4 text-primary-foreground`}><Share2 className="h-4 w-4" />{busy ? 'Проверка...' : preview ? 'Открыть доступ' : 'Проверить доступ'}</button>
      </div>
    </form>
  </NoteGroupDialog>
}
