import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'

export const noteControl = 'inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-md border border-slate-200 px-2 text-sm hover:border-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50 dark:border-slate-700'
export const noteInput = 'min-h-11 w-full min-w-0 rounded-md border border-slate-300 bg-white px-3 text-base text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100'

export function NoteGroupDialog({ title, dirty = false, busy = false, onClose, children }: {
  title: string; dirty?: boolean; busy?: boolean; onClose: () => void; children: ReactNode
}) {
  const panel = useProtectedModal<HTMLDivElement>()
  useEffect(() => {
    if (!dirty) return
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  const close = () => {
    if (!busy && (!dirty || window.confirm('Закрыть без сохранения изменений?'))) onClose()
  }
  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onPointerDown={preventBackdropDismiss}>
    <div ref={panel} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
      onClickCapture={event => {
        const link = (event.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null
        if (dirty && link && link.target !== '_blank' && !window.confirm('Перейти без сохранения изменений?')) {
          event.preventDefault(); event.stopPropagation()
        }
      }}
      className="max-h-[100dvh] w-full min-w-0 overflow-y-auto overscroll-contain bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-slate-900 sm:max-h-[90dvh] sm:max-w-xl sm:rounded-lg dark:bg-slate-950 dark:text-slate-100">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="min-w-0 break-words text-lg font-semibold">{title}</h2>
        <button type="button" onClick={close} disabled={busy} className={noteControl} aria-label="Закрыть" title="Закрыть"><X className="h-4 w-4" /></button>
      </div>
      {children}
    </div>
  </div>
}
