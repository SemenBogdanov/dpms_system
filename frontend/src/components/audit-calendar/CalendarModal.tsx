import { useId, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { preventBackdropDismiss, useProtectedModal } from '@/hooks/useProtectedModal'
import { useCalendarDraftGuard } from '@/lib/auditCalendarHooks'

export function CalendarModal({ title, children, dirty = false, busy = false, onClose }: { title: string; children: ReactNode; dirty?: boolean; busy?: boolean; onClose: () => void }) {
  const panel = useProtectedModal<HTMLDivElement>()
  const id = useId()
  const [discard, setDiscard] = useState(false)
  useCalendarDraftGuard(true)
  return <div className="ac-overlay" onPointerDown={preventBackdropDismiss}>
    <div className="ac ac-modal" ref={panel} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}>
      <header className="ac-modal-head"><h2 id={id}>{title}</h2><button type="button" className="ac-icon" aria-label="Закрыть" title="Закрыть" disabled={busy} onClick={() => dirty ? setDiscard(true) : onClose()}><X size={18} /></button></header>
      {discard && <div className="ac-warning" role="alert"><p>Есть несохранённые изменения. Удалить черновик?</p><div className="ac-actions"><button type="button" disabled={busy} onClick={() => setDiscard(false)}>Продолжить ввод</button><button type="button" disabled={busy} className="ac-danger" onClick={onClose}>Удалить черновик</button></div></div>}
      {children}
    </div>
  </div>
}
