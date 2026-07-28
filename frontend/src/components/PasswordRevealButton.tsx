import { Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'

interface PasswordRevealButtonProps {
  revealed: boolean
  onRevealChange: (revealed: boolean) => void
  className?: string
}

export function PasswordRevealButton({
  revealed,
  onRevealChange,
  className,
}: PasswordRevealButtonProps) {
  const hide = () => onRevealChange(false)

  return (
    <button
      type="button"
      className={cn(
        'absolute right-2 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center text-slate-400 transition-colors hover:text-slate-600',
        className
      )}
      aria-label="Удерживайте, чтобы показать пароль"
      title="Удерживайте, чтобы показать пароль"
      onPointerDown={(event) => {
        event.preventDefault()
        event.currentTarget.setPointerCapture(event.pointerId)
        onRevealChange(true)
      }}
      onPointerUp={hide}
      onPointerCancel={hide}
      onLostPointerCapture={hide}
      onPointerLeave={hide}
      onBlur={hide}
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {
          event.preventDefault()
          onRevealChange(true)
        }
      }}
      onKeyUp={(event) => {
        if (event.key === ' ' || event.key === 'Enter') {
          event.preventDefault()
          hide()
        }
      }}
    >
      {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
    </button>
  )
}
