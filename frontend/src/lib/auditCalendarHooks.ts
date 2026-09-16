import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { errorText } from './auditCalendar'
import { holdAuditCalendarNavigation } from './auditCalendarNavigation'

// BrowserRouter has no data-router blocker. Guard its navigator and native unload
// while the protected surface owns a draft; no draft is persisted to storage.
export function useCalendarDraftGuard(active: boolean, { protectPeriod = false }: { protectPeriod?: boolean } = {}) {
  const { navigator } = useContext(UNSAFE_NavigationContext)
  useEffect(() => {
    if (!active) return
    const push = navigator.push
    const replace = navigator.replace
    const go = navigator.go
    navigator.push = () => undefined
    navigator.replace = () => undefined
    navigator.go = () => undefined
    const release = holdAuditCalendarNavigation()
    // Period controls update local inputs before navigating, so blocking only
    // the navigator would leave dates that no longer describe the visible draft.
    const periodControls = protectPeriod ? Array.from(document.querySelectorAll<HTMLInputElement | HTMLButtonElement>('.ac-period-panel input, .ac-period-panel button'), element => ({ element, disabled: element.disabled })) : []
    periodControls.forEach(({ element }) => { element.disabled = true })
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const click = (event: MouseEvent) => {
      if ((event.target as Element)?.closest?.('a[href]')) { event.preventDefault(); event.stopPropagation() }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', click, true)
    return () => {
      navigator.push = push; navigator.replace = replace; navigator.go = go
      periodControls.forEach(({ element, disabled }) => { element.disabled = disabled })
      window.removeEventListener('beforeunload', unload)
      release()
      document.removeEventListener('click', click, true)
    }
  }, [active, navigator, protectPeriod])
}

export function useCalendarMutation() {
  const flight = useRef(false)
  const attempt = useRef<{ signature: string; id: string; version: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const run = useCallback(async <T,>(body: unknown, version: number, send: (id: string, expected: number) => Promise<T>, options?: { conflictCode: string; conflictMessage: string }): Promise<{ value: T } | null> => {
    if (flight.current) return null
    const signature = JSON.stringify(body)
    if (!attempt.current || attempt.current.signature !== signature) attempt.current = { signature, id: crypto.randomUUID(), version }
    const current = attempt.current
    flight.current = true; setBusy(true); setError(''); setStale(false); setUncertain(false)
    try {
      const value = await send(current.id, current.version)
      attempt.current = null
      return { value }
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) window.dispatchEvent(new Event('audit-calendar:access-revoked'))
      const conflict = e instanceof ApiError && e.status === 409 && (!options || e.code === options.conflictCode)
      setStale(conflict)
      setUncertain(!(e instanceof ApiError) || e.status >= 500 || e.status === 408)
      setError(conflict ? options?.conflictMessage ?? `Конфликт версии. Ввод сохранён. ${errorText(e)}` : errorText(e))
      return null
    } finally { flight.current = false; setBusy(false) }
  }, [])
  const rebase = (message = 'Данные перечитаны. Проверьте ввод и повторите сохранение.') => { attempt.current = null; setStale(false); setUncertain(false); setError(message) }
  const isReplay = (body: unknown, version: number) => uncertain && attempt.current?.signature === JSON.stringify(body) && attempt.current.version === version
  return { busy, error, stale, uncertain, run, rebase, setError, isReplay }
}
