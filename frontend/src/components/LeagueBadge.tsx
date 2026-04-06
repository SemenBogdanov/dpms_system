import { cn } from '@/lib/utils'
import type { League } from '@/api/types'

const styles: Record<League, string> = {
  C: 'bg-gray-50 text-gray-400 ring-1 ring-gray-100',
  B: 'bg-accent-lighter text-accent-dark',
  A: 'bg-accent text-white',
}

interface LeagueBadgeProps {
  league: League | string
  className?: string
}

export function LeagueBadge({ league, className }: LeagueBadgeProps) {
  const l = league as League
  return (
    <span
      className={cn(
        'inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium',
        styles[l] ?? 'bg-gray-50 text-gray-400',
        className
      )}
    >
      Лига {league}
    </span>
  )
}
