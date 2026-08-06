import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  Archive,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock3,
  FolderKanban,
  PauseCircle,
  Search,
} from 'lucide-react'
import type { WorkEntity, WorkEntityStatus } from '@/api/types'
import { cn } from '@/lib/utils'
import { getWorkEntityHealth, type WorkEntityHealth } from '@/lib/workEntityHealth'

type PortfolioFilter = 'all' | 'attention' | 'escalation' | WorkEntityStatus

const statusLabels: Record<WorkEntityStatus, string> = {
  draft: 'Черновик',
  active: 'Активно',
  paused: 'Пауза',
  done: 'Завершено',
  archived: 'Архив',
}

const entityTypeLabels: Record<WorkEntity['entity_type'], string> = {
  project: 'Проект',
  initiative: 'Инициатива',
  goal: 'Цель',
  system: 'Система',
  kpi: 'KPI-контекст',
  other: 'Другое',
}

const statusStyles: Record<WorkEntityStatus, string> = {
  draft: 'border-slate-200 bg-slate-100 text-slate-700',
  active: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  paused: 'border-amber-200 bg-amber-50 text-amber-800',
  done: 'border-sky-200 bg-sky-50 text-sky-700',
  archived: 'border-slate-300 bg-slate-50 text-slate-500',
}

const healthStyles: Record<WorkEntityHealth['tone'], string> = {
  good: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  watch: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-red-200 bg-red-50 text-red-700',
  neutral: 'border-slate-200 bg-slate-50 text-slate-600',
}

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})

function dateValue(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatDate(value: string | null | undefined) {
  const date = dateValue(value)
  return date ? dateFormatter.format(date) : 'не задан'
}

function HealthIcon({ health }: { health: WorkEntityHealth }) {
  if (health.key === 'escalation' || health.key === 'overdue') {
    return <AlertTriangle className="h-3.5 w-3.5" />
  }
  if (health.key === 'paused') return <PauseCircle className="h-3.5 w-3.5" />
  if (health.key === 'draft') return <CircleDashed className="h-3.5 w-3.5" />
  if (health.key === 'archived') return <Archive className="h-3.5 w-3.5" />
  if (health.key === 'watch') return <Clock3 className="h-3.5 w-3.5" />
  return <CheckCircle2 className="h-3.5 w-3.5" />
}

export function WorkEntityStatusBadge({ status }: { status: WorkEntityStatus }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 shrink-0 items-center rounded-md border px-2 text-xs font-semibold',
        statusStyles[status],
      )}
    >
      {statusLabels[status]}
    </span>
  )
}

export function WorkEntityHealthBadge({ health }: { health: WorkEntityHealth }) {
  return (
    <span
      className={cn(
        'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 text-xs font-semibold',
        healthStyles[health.tone],
      )}
      title={health.detail}
    >
      <HealthIcon health={health} />
      {health.label}
    </span>
  )
}

type WorkEntityPortfolioProps = {
  entities: WorkEntity[]
  loading: boolean
  onSelect: (entityId: string) => void
}

export function WorkEntityPortfolio({ entities, loading, onSelect }: WorkEntityPortfolioProps) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<PortfolioFilter>('all')

  const rows = useMemo(
    () =>
      entities.map((entity) => ({
        entity,
        health: getWorkEntityHealth(entity),
      })),
    [entities],
  )

  const counters = useMemo(
    () => ({
      active: entities.filter((entity) => entity.status === 'active').length,
      escalation: rows.filter(({ health }) => health.key === 'escalation').length,
      draft: entities.filter((entity) => entity.status === 'draft').length,
      archived: entities.filter((entity) => entity.status === 'archived').length,
    }),
    [entities, rows],
  )

  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('ru')
    return rows.filter(({ entity, health }) => {
      const matchesFilter =
        filter === 'all' ||
        (filter === 'attention' &&
          ['escalation', 'overdue', 'paused', 'watch'].includes(health.key)) ||
        (filter === 'escalation' && health.key === 'escalation') ||
        entity.status === filter
      if (!matchesFilter) return false
      if (!normalizedQuery) return true
      return [entity.title, entity.owner_name, entity.description, entity.outcome_statement]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase('ru').includes(normalizedQuery))
    })
  }, [filter, query, rows])

  const metrics: Array<{
    label: string
    value: number
    filter: PortfolioFilter
    tone: string
  }> = [
    { label: 'Активные', value: counters.active, filter: 'active', tone: 'text-emerald-700' },
    {
      label: 'Нужна эскалация',
      value: counters.escalation,
      filter: 'escalation',
      tone: 'text-red-700',
    },
    { label: 'Черновики', value: counters.draft, filter: 'draft', tone: 'text-slate-700' },
    { label: 'В архиве', value: counters.archived, filter: 'archived', tone: 'text-slate-500' },
  ]

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="Обзор проектов и целей">
      <div className="grid grid-cols-2 border-b border-slate-200 sm:grid-cols-4">
        {metrics.map((metric, index) => (
          <button
            key={metric.filter}
            type="button"
            onClick={() => setFilter((current) => (current === metric.filter ? 'all' : metric.filter))}
            className={cn(
              'min-h-20 px-4 py-3 text-left transition hover:bg-slate-50 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
              index % 2 !== 0 && 'border-l border-slate-200',
              index >= 2 && 'border-t border-slate-200 sm:border-t-0',
              index > 0 && 'sm:border-l sm:border-slate-200',
              filter === metric.filter && 'bg-slate-50 shadow-[inset_0_-2px_0_hsl(var(--primary))]',
            )}
            aria-pressed={filter === metric.filter}
          >
            <span className={cn('block text-2xl font-semibold tabular-nums', metric.tone)}>
              {metric.value}
            </span>
            <span className="mt-1 block text-xs font-medium text-slate-500">{metric.label}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3 border-b border-slate-200 px-3 py-3 sm:flex-row sm:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Поиск по проектам и целям</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Название, владелец или результат"
            className="h-10 w-full rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-primary focus:ring-2 focus:ring-primary/15"
          />
        </label>
        <select
          value={filter}
          onChange={(event) => setFilter(event.target.value as PortfolioFilter)}
          className="h-10 min-w-44 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
          aria-label="Фильтр статуса проекта"
        >
          <option value="all">Все статусы</option>
          <option value="attention">Требуют внимания</option>
          <option value="escalation">Нужна эскалация</option>
          <option value="active">Активные</option>
          <option value="draft">Черновики</option>
          <option value="paused">На паузе</option>
          <option value="done">Завершенные</option>
          <option value="archived">Архив</option>
        </select>
      </div>

      <div className="hidden grid-cols-[minmax(240px,1.4fr)_120px_170px_minmax(140px,0.7fr)_180px_140px_20px] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-2 text-[11px] font-semibold uppercase text-slate-500 lg:grid">
        <span>Проект или цель</span>
        <span>Статус</span>
        <span>Сигнал</span>
        <span>Владелец</span>
        <span>Сроки</span>
        <span>Состав</span>
        <span />
      </div>

      {loading ? (
        <div className="flex min-h-52 items-center justify-center gap-2 text-sm text-slate-500">
          <CircleDashed className="h-4 w-4 animate-spin" />
          Загрузка
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center">
          <FolderKanban className="h-7 w-7 text-slate-300" />
          <p className="mt-3 text-sm font-medium text-slate-700">
            {entities.length === 0 ? 'Проектов пока нет' : 'По заданным условиям ничего не найдено'}
          </p>
          {(query || filter !== 'all') && (
            <button
              type="button"
              onClick={() => {
                setQuery('')
                setFilter('all')
              }}
              className="mt-3 text-sm font-medium text-primary hover:underline"
            >
              Сбросить фильтр
            </button>
          )}
        </div>
      ) : (
        <div className="divide-y divide-slate-200">
          {filteredRows.map(({ entity, health }) => {
            const targetDate = entity.target_due_at || entity.due_at
            const forecastDate = entity.forecast_due_at || targetDate
            const forecastShifted =
              Boolean(targetDate && forecastDate) &&
              new Date(forecastDate || 0).getTime() > new Date(targetDate || 0).getTime()
            return (
              <button
                key={entity.id}
                type="button"
                onClick={() => onSelect(entity.id)}
                className="group grid w-full min-w-0 grid-cols-2 gap-3 px-4 py-4 text-left transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary lg:grid-cols-[minmax(240px,1.4fr)_120px_170px_minmax(140px,0.7fr)_180px_140px_20px] lg:items-center"
                aria-label={`Открыть ${entityTypeLabels[entity.entity_type].toLocaleLowerCase('ru')} ${entity.title}. Статус: ${statusLabels[entity.status]}. Сигнал: ${health.label}`}
              >
                <span className="col-span-2 min-w-0 lg:col-span-1">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {entity.title}
                  </span>
                  <span className="mt-1 block truncate text-xs text-slate-500">
                    {entityTypeLabels[entity.entity_type]}
                    {entity.outcome_statement ? ` · ${entity.outcome_statement}` : ''}
                  </span>
                </span>

                <span className="flex min-w-0 items-center lg:block">
                  <WorkEntityStatusBadge status={entity.status} />
                </span>

                <span className="flex min-w-0 items-center justify-end lg:justify-start">
                  <WorkEntityHealthBadge health={health} />
                </span>

                <span className="min-w-0 text-xs text-slate-600">
                  <span className="block truncate">{entity.owner_name}</span>
                  <span className="mt-0.5 block text-[11px] text-slate-400">
                    {entity.members_count} участников
                  </span>
                </span>

                <span className="min-w-0 text-xs tabular-nums text-slate-600">
                  <span className="flex items-center gap-1.5">
                    <CalendarDays className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    цель: {formatDate(targetDate)}
                  </span>
                  {forecastShifted && (
                    <span className="mt-1 block pl-5 font-medium text-red-700">
                      прогноз: {formatDate(forecastDate)}
                    </span>
                  )}
                </span>

                <span className="col-span-2 flex gap-3 text-xs text-slate-600 lg:col-span-1 lg:block">
                  <span className="block">{entity.tasks_count} операций</span>
                  <span className="block text-[11px] text-slate-400 lg:mt-0.5">
                    {entity.milestones_count} проверок
                  </span>
                </span>

                <ChevronRight className="hidden h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-primary lg:block" />
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
