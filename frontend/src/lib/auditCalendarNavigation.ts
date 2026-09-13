type Entry = { href: string; state: unknown; index: number | null }
const owners = new Map<symbol, Entry>()
let installed = false
let restoring = false

/** Call once before BrowserRouter/createRoot. Never persists form or server data. */
export function installAuditCalendarNavigationGuard() {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('popstate', event => {
    const entry = [...owners.values()][0]
    if (!entry && !restoring) return
    event.stopImmediatePropagation()
    if (restoring) { restoring = false; return }
    if (!entry) return
    const index = typeof event.state?.idx === 'number' ? event.state.idx : null
    if (index !== null && entry.index !== null && index !== entry.index) {
      restoring = true
      window.history.go(entry.index - index)
    } else {
      window.history.replaceState(entry.state, '', entry.href)
    }
  }, true)
}

export function holdAuditCalendarNavigation() {
  installAuditCalendarNavigationGuard()
  const owner = Symbol('audit-calendar-draft')
  const state = window.history.state
  owners.set(owner, { href: window.location.href, state, index: typeof state?.idx === 'number' ? state.idx : null })
  return () => { owners.delete(owner) }
}
