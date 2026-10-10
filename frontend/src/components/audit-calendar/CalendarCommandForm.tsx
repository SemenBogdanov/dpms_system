import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { auditCalendar, type CalendarCommand, type CalendarState } from '@/api/auditCalendar'
import { useCalendarMutation } from '@/lib/auditCalendarHooks'
import { errorText } from '@/lib/auditCalendar'
import { CalendarModal } from './CalendarModal'

export function CalendarCommandForm({ title, version, initialVersion, onRefresh, onClose, children, command, validate, reconcile, initialDirty = false }: {
  title: string; version: number; initialVersion?: number; onRefresh: () => Promise<unknown>; onClose: () => void; children: ReactNode; command: () => CalendarCommand; validate?: () => string; initialDirty?: boolean; reconcile?: (state: CalendarState, resolve: () => void) => ReactNode
}) {
  const mutation = useCalendarMutation()
  const [dirty, setDirty] = useState(initialDirty)
  const [confirmed, setConfirmed] = useState(false)
  const [draftVersion, setDraftVersion] = useState(initialVersion ?? version)
  const [fresh, setFresh] = useState<CalendarState | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const flight = useRef(false)
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  async function reload() {
    if (flight.current) return
    flight.current = true; setRefreshing(true); setFresh(null)
    try {
      const state = await onRefresh() as CalendarState
      if (live.current) setFresh(state)
    } catch (e) { if (live.current) mutation.setError(errorText(e)) }
    finally { if (live.current) { flight.current = false; setRefreshing(false) } }
  }
  function resolve() {
    if (!fresh || refreshing || fresh.scope.version !== version) return
    setDraftVersion(fresh.scope.version); setFresh(null); mutation.rebase('Изменения согласованы. Проверьте форму перед сохранением.')
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (flight.current || mutation.busy || mutation.stale) return
    const body = command()
    // An identical uncertain attempt confirms its original receipt, not a new plan.
    const error = mutation.isReplay(body, draftVersion) ? '' : validate?.()
    if (error) { mutation.setError(error); return }
    flight.current = true
    const result = await mutation.run(body, draftVersion, (id, expected) => auditCalendar.command(body, id, expected))
    flight.current = false
    if (!result || !live.current) return
    setConfirmed(true)
    onClose()
    await onRefresh().catch(() => undefined)
  }
  return <CalendarModal title={title} dirty={dirty && !confirmed} busy={mutation.busy || refreshing} onClose={onClose}>
    <form onSubmit={submit} onChange={() => setDirty(true)} className="ac-form">
      <div className="ac-form-body">
      <fieldset disabled={mutation.busy || refreshing || !!fresh}>{children}</fieldset>
      {mutation.error && <div className="ac-error" role="alert">{mutation.error}</div>}
      {mutation.stale && <button type="button" disabled={refreshing} onClick={() => void reload()}><RefreshCw size={16} />{refreshing ? 'Перечитывание…' : 'Перечитать, сохранив ввод'}</button>}
      {fresh && (fresh.scope.version !== version ? <p className="ac-warning">Календарь снова изменился. Перечитайте данные ещё раз.</p> : reconcile ? reconcile(fresh, resolve) : <div className="ac-warning"><p>Серверная версия изменилась. Ввод сохранён; сверьте его с актуальными данными перед повтором команды.</p><details><summary tabIndex={0}>Актуальные данные контура</summary><pre>{JSON.stringify(fresh, null, 2)}</pre></details><button type="button" onClick={resolve}>Подтверждаю повтор команды после сверки</button></div>)}
      {fresh && <button type="button" onClick={() => setFresh(null)}>Вернуться к вводу</button>}
      </div>
      <footer className="ac-actions"><button className="ac-primary" type="submit" disabled={mutation.busy || mutation.stale || refreshing}><Save size={16} />{mutation.busy ? 'Сохранение…' : 'Сохранить'}</button><span className="ac-muted">{dirty ? 'Есть несохранённые изменения' : ''}</span></footer>
    </form>
  </CalendarModal>
}
