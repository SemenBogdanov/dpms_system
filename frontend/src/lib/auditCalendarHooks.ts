import { useCallback, useContext, useEffect, useRef, useState } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'
import { ApiError } from '@/api/client'
import { errorText } from './auditCalendar'
import { holdAuditCalendarNavigation } from './auditCalendarNavigation'

// BrowserRouter has no data-router blocker. Guard its navigator and native unload
// while the protected surface owns a draft; no draft is persisted to storage.
export function useCalendarDraftGuard(active: boolean) {
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
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const click = (event: MouseEvent) => {
      if ((event.target as Element)?.closest?.('a[href]')) { event.preventDefault(); event.stopPropagation() }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', click, true)
    return () => {
      navigator.push = push; navigator.replace = replace; navigator.go = go
      window.removeEventListener('beforeunload', unload)
      release()
      document.removeEventListener('click', click, true)
    }
  }, [active, navigator])
}

export function useCalendarMutation() {
  const flight = useRef(false)
  const attempt = useRef<{ signature: string; id: string; version: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const run = useCallback(async <T,>(body: unknown, version: number, send: (id: string, expected: number) => Promise<T>): Promise<{ value: T } | null> => {
    if (flight.current) return null
    const signature = JSON.stringify(body)
    if (!attempt.current || attempt.current.signature !== signature) attempt.current = { signature, id: crypto.randomUUID(), version }
    const current = attempt.current
    flight.current = true; setBusy(true); setError(''); setStale(false)
    try {
      const value = await send(current.id, current.version)
      attempt.current = null
      return { value }
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) window.dispatchEvent(new Event('audit-calendar:access-revoked'))
      const conflict = e instanceof ApiError && e.status === 409
      setStale(conflict)
      setError(conflict ? `Конфликт версии. Ввод сохранён. ${errorText(e)}` : errorText(e))
      return null
    } finally { flight.current = false; setBusy(false) }
  }, [])
  const rebase = () => { attempt.current = null; setStale(false); setError('Данные перечитаны. Проверьте ввод и повторите сохранение.') }
  return { busy, error, stale, run, rebase, setError }
}
