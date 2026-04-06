import { cn } from '@/lib/utils'

interface QBadgeProps {
  q: number
  className?: string
}

export function QBadge({ q, className }: QBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-accent-lighter text-accent-dark whitespace-nowrap',
        className
      )}
    >
      {q} Q
    </span>
  )
}
