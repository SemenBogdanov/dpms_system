import type { FC } from 'react'

interface DeadlineBadgeProps {
  dueDate: string | null
  zone: 'green' | 'yellow' | 'red' | null
}

export const DeadlineBadge: FC<DeadlineBadgeProps> = ({ dueDate, zone }) => {
  if (!dueDate || !zone) return null

  const date = new Date(dueDate)
  const dateStr = `${date.toLocaleDateString('ru')} ${date.toLocaleTimeString('ru', {
    hour: '2-digit',
    minute: '2-digit',
  })}`

  if (zone === 'green') {
    return (
      <span className="inline-flex items-center rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-500">
        Срок: {dateStr}
      </span>
    )
  }

  if (zone === 'yellow') {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-500">
        Скоро: {dateStr}
      </span>
    )
  }

  return (
    <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-500">
      Просрочено
    </span>
  )
}
