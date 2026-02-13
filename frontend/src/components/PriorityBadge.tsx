import { cn } from '@/lib/utils'
import type { TaskPriority } from '@/api/types'

const styles: Record<TaskPriority, string> = {
  critical: 'bg-red-100 text-red-800',
  high: 'bg-orange-100 text-orange-800',
  medium: 'bg-amber-100 text-amber-800',
  low: 'bg-slate-100 text-slate-600',
}

const labels: Record<TaskPriority, string> = {
  critical: 'Критичный',
  high: 'Высокий',
  medium: 'Средний',
  low: 'Низкий',
}

interface PriorityBadgeProps {
  priority: TaskPriority | string
  className?: string
}

export function PriorityBadge({ priority, className }: PriorityBadgeProps) {
  const p = priority as TaskPriority
  return (
    <span
      className={cn(
        'inline-flex rounded px-2 py-0.5 text-xs font-medium',
        styles[p] ?? 'bg-slate-100 text-slate-600',
        className
      )}
    >
      {labels[p] ?? priority}
    </span>
  )
}
