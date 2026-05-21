import type { FC } from 'react'
import type { TaskStatus } from '@/api/types'

interface DeadlineBadgeProps {
  dueDate: string | null
  zone: 'green' | 'yellow' | 'red' | null
  status?: TaskStatus | string | null
  showDate?: boolean
  showLabel?: boolean
}

export const DeadlineBadge: FC<DeadlineBadgeProps> = ({ dueDate, zone, status, showDate = true, showLabel = true }) => {
  if (!dueDate || !zone) return null

  const date = new Date(dueDate)
  const dateStr = `${date.toLocaleDateString('ru')} ${date.toLocaleTimeString('ru', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
  const text = (label: string) => {
    if (!showLabel) return dateStr
    return showDate ? `${label}: ${dateStr}` : label
  }

  const isClosed = status === 'done' || status === 'cancelled'
  if (isClosed) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500" title={`Срок: ${dateStr}`}>
        {text('Срок')}
      </span>
    )
  }

  if (zone === 'green') {
    return (
      <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-500" title={`Срок: ${dateStr}`}>
        {text('Срок')}
      </span>
    )
  }

  if (zone === 'yellow') {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-500" title={`Скоро: ${dateStr}`}>
        {text('Скоро')}
      </span>
    )
  }

  return (
    <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-500" title={`Просрочено: ${dateStr}`}>
      {text('Просрочено')}
    </span>
  )
}
