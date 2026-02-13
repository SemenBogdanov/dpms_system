import { cn } from '@/lib/utils'

interface ProgressBarProps {
  /** 0–100 */
  percent: number
  /** Цвет полоски по проценту: <50 red, 50–80 yellow, >80 green */
  variant?: 'default' | 'risk'
  className?: string
}

/** Мини прогресс-бар для таблиц (колонка %). */
export function ProgressBar({
  percent,
  variant = 'default',
  className,
}: ProgressBarProps) {
  const p = Math.min(100, Math.max(0, percent))
  const color =
    variant === 'risk'
      ? p < 50
        ? 'bg-red-500'
        : p < 80
          ? 'bg-amber-500'
          : 'bg-emerald-500'
      : 'bg-primary'

  return (
    <div
      className={cn(
        'h-2 w-full min-w-[60px] overflow-hidden rounded-full bg-slate-200',
        className
      )}
    >
      <div
        className={cn('h-full rounded-full transition-all', color)}
        style={{ width: `${p}%` }}
      />
    </div>
  )
}
