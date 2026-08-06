import type { WorkEntity } from '@/api/types'

type WorkEntityHealthTone = 'good' | 'watch' | 'danger' | 'neutral'

export type WorkEntityHealth = {
  key:
    | 'on_track'
    | 'watch'
    | 'overdue'
    | 'escalation'
    | 'draft'
    | 'paused'
    | 'done'
    | 'archived'
  label: string
  detail: string
  tone: WorkEntityHealthTone
}

function dateValue(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function daysUntil(value: string | null | undefined, now: Date) {
  const date = dateValue(value)
  if (!date) return null
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.ceil((target - today) / 86_400_000)
}

export function getWorkEntityHealth(
  entity: WorkEntity,
  overdueItems = 0,
  now = new Date(),
): WorkEntityHealth {
  if (entity.status === 'archived') {
    return {
      key: 'archived',
      label: 'Изменения закрыты',
      detail: 'Проект находится в архиве.',
      tone: 'neutral',
    }
  }
  if (entity.status === 'done') {
    return {
      key: 'done',
      label: 'Результат принят',
      detail: 'Проект завершен.',
      tone: 'good',
    }
  }
  if (entity.status === 'paused') {
    return {
      key: 'paused',
      label: 'Требует решения',
      detail: 'Исполнение проекта приостановлено.',
      tone: 'watch',
    }
  }
  if (entity.status === 'draft') {
    return {
      key: 'draft',
      label: 'Не запущен',
      detail: 'Базовый план еще не зафиксирован.',
      tone: 'neutral',
    }
  }

  const targetDate = entity.target_due_at || entity.due_at
  const forecastDate = entity.forecast_due_at || targetDate
  const target = dateValue(targetDate)
  const forecast = dateValue(forecastDate)
  const remainingDays = daysUntil(targetDate, now)
  const forecastLate = Boolean(target && forecast && forecast.getTime() > target.getTime())

  if (forecastLate || (remainingDays !== null && remainingDays < 0)) {
    const reasons = []
    if (forecastLate) reasons.push('прогноз позже целевого срока')
    if (!forecastLate && remainingDays !== null && remainingDays < 0) reasons.push('целевой срок истек')
    return {
      key: 'escalation',
      label: 'Нужна эскалация',
      detail: reasons.join('; '),
      tone: 'danger',
    }
  }

  if (overdueItems > 0) {
    return {
      key: 'overdue',
      label: 'Есть просрочка',
      detail: `Просрочено операций или связанных сроков: ${overdueItems}.`,
      tone: 'danger',
    }
  }

  if (remainingDays === null) {
    return {
      key: 'watch',
      label: 'Срок не задан',
      detail: 'Нужно определить целевую дату.',
      tone: 'watch',
    }
  }

  if (remainingDays <= 7) {
    return {
      key: 'watch',
      label: 'Контроль срока',
      detail: remainingDays === 0 ? 'Целевой срок сегодня.' : `До целевого срока: ${remainingDays} дн.`,
      tone: 'watch',
    }
  }

  return {
    key: 'on_track',
    label: 'В срок',
    detail: 'Прогноз находится в пределах целевой даты.',
    tone: 'good',
  }
}
