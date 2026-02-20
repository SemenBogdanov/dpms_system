import { cn } from '@/lib/utils'

interface QBadgeProps {
  q: number
  className?: string
}

/** Бейдж с ценой задачи в Квантах (Q). */
export function QBadge({ q, className }: QBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-800 whitespace-nowrap',
        className
      )}
    >
      {q} Q
    </span>
  )
}
