import { cn } from '@/lib/utils'
import type { League } from '@/api/types'

const styles: Record<League, string> = {
  C: 'bg-emerald-100 text-emerald-800',
  B: 'bg-blue-100 text-blue-800',
  A: 'bg-violet-100 text-violet-800',
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
        'inline-flex whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium',
        styles[l] ?? 'bg-slate-100 text-slate-600',
        className
      )}
    >
      Лига {league}
    </span>
  )
}
