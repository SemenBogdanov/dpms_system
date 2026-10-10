import { useContext, useLayoutEffect, useRef } from 'react'
import { UNSAFE_NavigationContext, useLocation } from 'react-router-dom'
import { protectPersonalTaskPop } from '@/components/PersonalTaskFormNavigation'

// Reuse the listener installed before BrowserRouter; a later popstate listener
// cannot prevent the router from unmounting the draft before cancellation.
export function useAuditNavigationGuard(dirty: boolean, pending: boolean) {
  const { navigator } = useContext(UNSAFE_NavigationContext)
  const location = useLocation()
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  const active = dirty || pending

  useLayoutEffect(() => {
    if (!active) return
    const entry = { state: window.history.state, href: window.location.href }
    const index: unknown = entry.state?.idx
    const push = navigator.push
    const replace = navigator.replace
    let restoringDelta = 0
    let leaving = false
    const allowLeave = () => !pendingRef.current
      && window.confirm('Изменения аудита не сохранены. Уйти и потерять несохраненные правки?')
    const guardedPush: typeof push = (...args) => {
      if (!restoringDelta && allowLeave()) push(...args)
    }
    const guardedReplace: typeof replace = (...args) => {
      if (!restoringDelta && allowLeave()) replace(...args)
    }
    const release = protectPersonalTaskPop((event) => {
      // Synthetic popstate is not a browser traversal (used by lifecycle tests).
      if (!event.isTrusted || leaving) return
      event.stopImmediatePropagation()
      if (restoringDelta) {
        const delta = restoringDelta
        restoringDelta = 0
        if (allowLeave()) {
          leaving = true
          window.history.go(delta)
        }
        return
      }
      const nextIndex: unknown = event.state?.idx
      if (typeof index === 'number' && typeof nextIndex === 'number' && index !== nextIndex) {
        restoringDelta = nextIndex - index
        window.history.go(-restoringDelta)
      } else {
        // Unknown history entries cannot be replayed safely; keep the draft.
        window.history.replaceState(entry.state, '', entry.href)
      }
    })
    navigator.push = guardedPush
    navigator.replace = guardedReplace
    return () => {
      if (navigator.push === guardedPush) navigator.push = push
      if (navigator.replace === guardedReplace) navigator.replace = replace
      release()
    }
  }, [active, location.key, navigator])
}
