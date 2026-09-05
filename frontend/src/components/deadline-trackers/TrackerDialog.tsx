import { useContext, useEffect, useState, type ReactNode } from 'react'
import { UNSAFE_NavigationContext } from 'react-router-dom'
import { Loader2, X, type LucideIcon } from 'lucide-react'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { cn } from '@/lib/utils'

export const trackerInput = 'min-h-11 w-full min-w-0 rounded-md border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 sm:text-sm [&:is(select)]:h-11'
export const trackerButton = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-wait disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800'

export function TrackerIconButton({ label, icon: Icon, onClick, disabled, tone, pressed }: {
  label: string; icon: LucideIcon; onClick: () => void; disabled?: boolean
  tone?: 'danger' | 'success' | 'warning'; pressed?: boolean
}) {
  return <button type="button" aria-label={label} title={label} aria-pressed={pressed} disabled={disabled} onClick={onClick}
    className={cn(trackerButton, 'h-11 w-11 shrink-0 p-0 lg:h-8 lg:min-h-8 lg:w-8',
      tone === 'danger' && 'border-rose-200 bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300',
      tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300',
      tone === 'warning' && 'border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300')}>
    <Icon className="h-4 w-4" aria-hidden="true" />
  </button>
}

export function TrackerField({ label, name, error, children }: { label: string; name: string; error?: string; children: ReactNode }) {
  return <div className="min-w-0 space-y-1">
    <label htmlFor={`tracker-${name}`} className="block text-sm font-medium text-slate-700 dark:text-slate-200">{label}</label>
    {children}
    {error && <p id={`tracker-${name}-error`} role="alert" className="text-sm text-rose-700 dark:text-rose-300">{error}</p>}
  </div>
}

export function TrackerDialog({ title, dirty = false, busy = false, onClose, children, footer }: {
  title: string; dirty?: boolean; busy?: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode
}) {
  const [discard, setDiscard] = useState(false)
  const panelRef = useProtectedModal<HTMLDivElement>()
  const { navigator } = useContext(UNSAFE_NavigationContext)

  useEffect(() => {
    if (!dirty && !busy) return
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protect)
    const currentIndex = window.history.state?.idx as number | undefined
    let restoring = false
    const protectHistory = (event: PopStateEvent) => {
      event.stopImmediatePropagation()
      if (restoring) { restoring = false; return }
      const nextIndex = event.state?.idx as number | undefined
      if (currentIndex !== undefined && nextIndex !== undefined && currentIndex !== nextIndex) {
        restoring = true
        window.history.go(currentIndex - nextIndex)
      }
      if (!busy) setDiscard(true)
    }
    window.addEventListener('popstate', protectHistory, true)
    // BrowserRouter has no data-router blocker. Keep SPA navigation on this mounted draft.
    const push = navigator.push
    const replace = navigator.replace
    const go = navigator.go
    const blocked = () => { if (!busy) setDiscard(true) }
    navigator.push = blocked
    navigator.replace = blocked
    navigator.go = blocked
    return () => {
      window.removeEventListener('beforeunload', protect)
      window.removeEventListener('popstate', protectHistory, true)
      navigator.push = push
      navigator.replace = replace
      navigator.go = go
    }
  }, [busy, dirty, navigator])

  useEffect(() => {
    if (discard) panelRef.current?.querySelector<HTMLButtonElement>('[data-continue-editing]')?.focus()
  }, [discard, panelRef])

  const close = () => {
    if (busy) return
    if (dirty) setDiscard(true)
    else onClose()
  }

  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center sm:p-4" onPointerDown={preventBackdropDismiss}>
    <div ref={panelRef} role={discard ? 'alertdialog' : 'dialog'} aria-modal="true" aria-label={discard ? 'Несохраненные изменения трекера' : title} aria-busy={busy} tabIndex={-1}
      className="flex max-h-[94dvh] w-full min-w-0 flex-col overflow-hidden rounded-t-lg bg-white text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100 sm:max-w-2xl sm:rounded-lg">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 p-4 dark:border-slate-700">
        <h2 className="min-w-0 break-words text-base font-semibold">{title}</h2>
        <TrackerIconButton label="Закрыть" icon={X} disabled={busy} onClick={close} />
      </header>
      {discard ? <div className="space-y-4 p-4">
        <p>Закрыть без сохранения? Введенные изменения будут потеряны.</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" data-continue-editing className={trackerButton} onClick={() => setDiscard(false)}>Продолжить редактирование</button>
          <button type="button" className={cn(trackerButton, 'text-rose-700')} onClick={onClose}>Закрыть без сохранения</button>
        </div>
      </div> : <>
        <div className="min-h-0 overflow-y-auto overscroll-contain p-4">{children}</div>
        <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-slate-200 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] dark:border-slate-700">
          {footer}
          <button type="button" className={trackerButton} disabled={busy} onClick={close}>Отмена</button>
          {busy && <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-label="Сохранение" />}
        </footer>
      </>}
    </div>
  </div>
}
