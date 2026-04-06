import { cn } from '@/lib/utils'
import type { TaskPriority } from '@/api/types'

const styles: Record<TaskPriority, string> = {
  critical: 'bg-red-50 text-red-600 ring-1 ring-red-100',
  high: 'bg-orange-50 text-orange-600 ring-1 ring-orange-100',
  medium: 'bg-accent-lighter text-accent-dark',
  low: 'bg-gray-50 text-gray-400 ring-1 ring-gray-100',
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
        'inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium',
        styles[p] ?? 'bg-gray-50 text-gray-400',
        className
      )}
    >
      {labels[p] ?? priority}
    </span>
  )
}
