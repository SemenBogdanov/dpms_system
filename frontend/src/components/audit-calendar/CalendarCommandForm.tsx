import { useState, type FormEvent, type ReactNode } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { auditCalendar, type CalendarCommand } from '@/api/auditCalendar'
import { useCalendarMutation } from '@/lib/auditCalendarHooks'
import { errorText } from '@/lib/auditCalendar'
import { CalendarModal } from './CalendarModal'

export function CalendarCommandForm({ title, version, onRefresh, onClose, children, command, validate, initialDirty = false }: {
  title: string; version: number; onRefresh: () => Promise<unknown>; onClose: () => void; children: ReactNode; command: () => CalendarCommand; validate?: () => string; initialDirty?: boolean
}) {
  const mutation = useCalendarMutation()
  const [dirty, setDirty] = useState(initialDirty)
  const [confirmed, setConfirmed] = useState(false)
  const [draftVersion, setDraftVersion] = useState(version)
  async function submit(event: FormEvent) {
    event.preventDefault()
    const error = validate?.()
    if (error) { mutation.setError(error); return }
    const body = command()
    const result = await mutation.run(body, draftVersion, (id, expected) => auditCalendar.command(body, id, expected))
    if (!result) return
    setConfirmed(true)
    onClose()
    await onRefresh().catch(() => undefined)
  }
  return <CalendarModal title={title} dirty={dirty && !confirmed} busy={mutation.busy} onClose={onClose}>
    <form onSubmit={submit} onChange={() => setDirty(true)} className="ac-form">
      <fieldset disabled={mutation.busy}>{children}</fieldset>
      {mutation.error && <div className="ac-error" role="alert">{mutation.error}</div>}
      {mutation.stale && <button type="button" onClick={async () => { try { const state = await onRefresh() as { scope: { version: number } }; setDraftVersion(state.scope.version); mutation.rebase() } catch (e) { mutation.setError(errorText(e)) } }}><RefreshCw size={16} />Перечитать, сохранив ввод</button>}
      <footer className="ac-actions"><button className="ac-primary" type="submit" disabled={mutation.busy || mutation.stale}><Save size={16} />{mutation.busy ? 'Сохранение…' : 'Сохранить'}</button><span className="ac-muted">{dirty ? 'Есть несохранённые изменения' : ''}</span></footer>
    </form>
  </CalendarModal>
}
