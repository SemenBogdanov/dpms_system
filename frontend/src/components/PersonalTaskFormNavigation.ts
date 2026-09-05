type PopGuard = (event: PopStateEvent) => void

let activeGuard: PopGuard | null = null

// Import this module in main.tsx before BrowserRouter mounts. Window target
// listeners run in registration order, even when a later listener uses capture.
window.addEventListener('popstate', (event) => activeGuard?.(event))

export function protectPersonalTaskPop(guard: PopGuard) {
  activeGuard = guard
  return () => {
    if (activeGuard === guard) activeGuard = null
  }
}
