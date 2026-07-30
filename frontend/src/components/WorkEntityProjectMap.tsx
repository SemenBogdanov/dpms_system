import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Check,
  CircleDot,
  FileText,
  GitBranch,
  Link2,
  Loader2,
  Milestone,
  RefreshCw,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type { WorkEntity, WorkEntityMap, WorkEntityMapNode } from '@/api/types'
import { cn } from '@/lib/utils'

const DAY = 86_400_000
const ROW_HEIGHT = 64
const LABEL_WIDTH = 220

type NodeGeometry = {
  baselineStartX: number
  baselineEndX: number
  forecastStartX: number
  forecastEndX: number
  forecastWidth: number
  y: number
}

const milestoneStatusLabels: Record<string, string> = {
  planned: 'запланирована',
  rescheduled: 'перенесена',
  overdue: 'просрочена',
  achieved: 'пройдена',
  cancelled: 'отменена',
}

const criticalityLabels: Record<string, string> = {
  control: 'контрольная',
  key: 'ключевая',
  critical: 'критическая',
}

function formatDate(value: string | null): string {
  if (!value) return 'не задано'
  return new Date(value).toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function nodeIcon(node: WorkEntityMapNode) {
  if (node.node_type === 'milestone') return <Milestone className="h-3.5 w-3.5" />
  if (node.node_type === 'artifact') return <FileText className="h-3.5 w-3.5" />
  if (node.node_type === 'linked_object') return <Link2 className="h-3.5 w-3.5" />
  return <CircleDot className="h-3.5 w-3.5" />
}

function milestoneColor(status: string | null): string {
  if (status === 'achieved') return 'bg-emerald-500'
  if (status === 'overdue') return 'bg-red-500'
  if (status === 'rescheduled') return 'bg-amber-500'
  if (status === 'cancelled') return 'bg-slate-400'
  return 'bg-sky-500'
}

function milestoneSize(criticality: string | null): string {
  if (criticality === 'critical') return 'h-5 w-5 border-[3px]'
  if (criticality === 'key') return 'h-[18px] w-[18px] border-2'
  return 'h-4 w-4 border'
}

function taskColor(status: string | null): string {
  if (status === 'done') return 'bg-emerald-500'
  if (status === 'blocked') return 'bg-red-500'
  if (status === 'waiting') return 'bg-amber-500'
  if (status === 'review') return 'bg-violet-500'
  if (status === 'cancelled') return 'bg-slate-400'
  return 'bg-primary'
}

function milestoneTitle(node: WorkEntityMapNode): string {
  const status = milestoneStatusLabels[node.status ?? ''] ?? node.status ?? 'без статуса'
  const criticality =
    criticalityLabels[node.criticality ?? ''] ?? node.criticality ?? 'без критичности'
  return [
    node.ref,
    node.title,
    `статус: ${status}`,
    `критичность: ${criticality}`,
    `база: ${formatDate(node.baseline_due_at)}`,
    `прогноз: ${formatDate(node.forecast_due_at)}`,
    node.actual_at ? `факт: ${formatDate(node.actual_at)}` : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function WorkEntityProjectMap({ entity }: { entity: WorkEntity }) {
  const [map, setMap] = useState<WorkEntityMap | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setMap(await api.get<WorkEntityMap>(`/api/work-entities/${entity.id}/map`))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось построить график проекта')
    } finally {
      setLoading(false)
    }
  }, [entity.id])

  useEffect(() => {
    setMap(null)
    void load()
  }, [load])

  const layout = useMemo(() => {
    if (!map) return null
    const rangeStart = new Date(map.range_start).getTime()
    const rangeEnd = new Date(map.range_end).getTime()
    const duration = Math.max(DAY, rangeEnd - rangeStart)
    const durationDays = Math.max(1, Math.ceil(duration / DAY))
    const timelineWidth = Math.max(560, Math.min(2800, durationDays * 11))
    const rows = map.nodes
      .filter((node) => node.node_type === 'task' || node.node_type === 'milestone')
      .sort((left, right) => {
        const stageOrder =
          (left.stage_position ?? Number.MAX_SAFE_INTEGER) -
          (right.stage_position ?? Number.MAX_SAFE_INTEGER)
        if (stageOrder !== 0) return stageOrder
        const leftDate =
          left.baseline_starts_at ||
          left.baseline_due_at ||
          left.forecast_starts_at ||
          left.forecast_due_at ||
          left.occurred_at
        const rightDate =
          right.baseline_starts_at ||
          right.baseline_due_at ||
          right.forecast_starts_at ||
          right.forecast_due_at ||
          right.occurred_at
        return new Date(leftDate || 0).getTime() - new Date(rightDate || 0).getTime()
      })
    const x = (value: string | null | undefined) => {
      if (!value) return 0
      return Math.max(
        0,
        Math.min(
          timelineWidth,
          ((new Date(value).getTime() - rangeStart) / duration) * timelineWidth,
        ),
      )
    }
    const geometry = new Map<string, NodeGeometry>(
      rows.map((node, index) => {
        const baselineStart =
          node.baseline_starts_at || node.baseline_due_at || node.forecast_starts_at || map.range_start
        const baselineEnd =
          node.baseline_due_at || node.baseline_starts_at || node.forecast_due_at || map.range_start
        const forecastStart =
          node.forecast_starts_at || node.forecast_due_at || baselineStart
        const forecastEnd =
          node.forecast_due_at || node.forecast_starts_at || baselineEnd
        const baselineStartX = x(baselineStart)
        const baselineEndX = x(baselineEnd)
        const forecastStartX = x(forecastStart)
        const forecastEndX = x(forecastEnd)
        return [
          node.id,
          {
            baselineStartX,
            baselineEndX,
            forecastStartX,
            forecastEndX,
            forecastWidth: Math.max(
              node.node_type === 'task' ? 30 : 12,
              forecastEndX - forecastStartX,
            ),
            y: index * ROW_HEIGHT + ROW_HEIGHT / 2,
          },
        ]
      }),
    )

    const monthTicks: Array<{ x: number; label: string }> = []
    const cursor = new Date(rangeStart)
    cursor.setDate(1)
    cursor.setHours(0, 0, 0, 0)
    if (cursor.getTime() <= rangeStart) cursor.setMonth(cursor.getMonth() + 1)
    while (cursor.getTime() < rangeEnd) {
      const tickX = x(cursor.toISOString())
      if (tickX >= 90 && tickX <= timelineWidth - 90) {
        monthTicks.push({
          x: tickX,
          label: cursor.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }),
        })
      }
      cursor.setMonth(cursor.getMonth() + 1)
    }

    return {
      rows,
      geometry,
      timelineWidth,
      height: Math.max(ROW_HEIGHT, rows.length * ROW_HEIGHT),
      monthTicks,
      x,
    }
  }, [map])

  if ((loading && !map) || (map && map.entity_id !== entity.id)) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Построение графика
      </div>
    )
  }

  if (!map || !layout) return null

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">График проекта</h3>
          <p className="mt-1 text-xs text-slate-500">
            Базовый план сохраняется для сравнения, цвет показывает состояние, размер точки — критичность.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:border-primary/40 hover:text-primary disabled:opacity-50"
          title="Обновить график"
          aria-label="Обновить график"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
        </button>
      </header>

      <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-6 rounded border border-dashed border-slate-500 bg-slate-100" />
          базовый план
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-6 rounded bg-primary" />
          текущий прогноз задачи
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3.5 w-3.5 rotate-45 border border-white bg-sky-500 ring-1 ring-sky-500" />
          контрольная
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-4 w-4 rotate-45 border-2 border-white bg-sky-500 ring-1 ring-sky-500" />
          ключевая
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-[18px] w-[18px] rotate-45 border-[3px] border-white bg-sky-500 ring-1 ring-sky-500" />
          критическая
        </span>
        <span className="inline-flex items-center gap-1.5">
          <GitBranch className="h-3.5 w-3.5" />
          зависимость
        </span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-2 border-y border-slate-200 py-2 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-sky-500" /> запланирована</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-amber-500" /> перенесена</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-red-500" /> просрочена</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-emerald-500" /> пройдена</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rotate-45 bg-slate-400" /> отменена</span>
      </div>

      {layout.rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 px-4 py-12 text-center text-sm text-slate-500">
          Добавьте задачи или контрольные точки, чтобы построить график.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <div style={{ width: LABEL_WIDTH + layout.timelineWidth }} className="relative">
            <div
              className="sticky left-0 z-30 flex h-12 items-end border-r border-slate-200 bg-white px-3 pb-2 text-xs font-semibold text-slate-500"
              style={{ width: LABEL_WIDTH }}
            >
              Элемент проекта
            </div>
            <div
              className="absolute top-0 h-12 border-b border-slate-200"
              style={{ left: LABEL_WIDTH, width: layout.timelineWidth }}
            >
              <span className="absolute bottom-2 left-2 text-[11px] text-slate-500">
                {formatDate(map.range_start)}
              </span>
              {layout.monthTicks.map((tick) => (
                <span
                  key={`${tick.x}-${tick.label}`}
                  className="absolute bottom-2 -translate-x-1/2 text-[11px] text-slate-500"
                  style={{ left: tick.x }}
                >
                  {tick.label}
                </span>
              ))}
              <span className="absolute bottom-2 right-2 text-[11px] text-slate-500">
                {formatDate(map.range_end)}
              </span>
            </div>

            <div className="relative" style={{ height: layout.height }}>
              <div
                className="sticky left-0 z-20 border-r border-slate-200 bg-white"
                style={{ width: LABEL_WIDTH, height: layout.height }}
              >
                {layout.rows.map((node) => (
                  <div
                    key={node.id}
                    className="flex items-center gap-2 border-b border-slate-100 px-3"
                    style={{ height: ROW_HEIGHT }}
                  >
                    <span className={cn('shrink-0', node.accessible ? 'text-slate-500' : 'text-slate-300')}>
                      {nodeIcon(node)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-slate-800" title={node.title}>
                        {node.ref && <span className="mr-1 font-semibold text-slate-500">{node.ref}</span>}
                        {node.title}
                      </span>
                      <span className="block truncate text-[10px] text-slate-600">
                        {node.node_type === 'milestone'
                          ? [
                              node.stage_title,
                              milestoneStatusLabels[node.status ?? ''] ?? node.status ?? 'без статуса',
                              criticalityLabels[node.criticality ?? ''] ?? 'контрольная',
                            ]
                              .filter(Boolean)
                              .join(' · ')
                          : [node.stage_title, node.assignee_name || node.status || 'без статуса']
                              .filter(Boolean)
                              .join(' · ')}
                      </span>
                    </span>
                  </div>
                ))}
              </div>

              <div
                className="absolute top-0 overflow-hidden"
                style={{
                  left: LABEL_WIDTH,
                  width: layout.timelineWidth,
                  height: layout.height,
                }}
              >
                {layout.rows.map((node, index) => (
                  <div
                    key={node.id}
                    className="absolute left-0 w-full border-b border-slate-100"
                    style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
                  />
                ))}
                {layout.monthTicks.map((tick) => (
                  <div
                    key={`grid-${tick.x}`}
                    className="absolute top-0 border-l border-dashed border-slate-200"
                    style={{ left: tick.x, height: layout.height }}
                  />
                ))}

                <svg
                  className="absolute inset-0 z-0 overflow-visible"
                  width={layout.timelineWidth}
                  height={layout.height}
                  aria-label="Зависимости проекта"
                >
                  <defs>
                    <marker
                      id="work-entity-arrow"
                      markerWidth="7"
                      markerHeight="7"
                      refX="6"
                      refY="3.5"
                      orient="auto"
                    >
                      <path d="M0,0 L7,3.5 L0,7 Z" fill="currentColor" />
                    </marker>
                  </defs>
                  {map.edges
                    .filter((edge) => edge.edge_type === 'dependency')
                    .map((edge) => {
                      const from = layout.geometry.get(edge.from_node_id)
                      const to = layout.geometry.get(edge.to_node_id)
                      if (!from || !to) return null
                      const startX = from.forecastEndX
                      const endX = to.forecastStartX
                      const bendX =
                        endX > startX + 24
                          ? (startX + endX) / 2
                          : Math.max(startX, endX) + 18
                      return (
                        <path
                          key={edge.id}
                          d={`M ${startX} ${from.y} H ${bendX} V ${to.y} H ${endX}`}
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          className="text-slate-400"
                          markerEnd="url(#work-entity-arrow)"
                        />
                      )
                    })}
                </svg>

                {layout.rows.map((node) => {
                  const item = layout.geometry.get(node.id)
                  if (!item) return null

                  if (node.node_type === 'milestone') {
                    const shifted =
                      Boolean(node.baseline_due_at && node.forecast_due_at) &&
                      node.baseline_due_at !== node.forecast_due_at
                    const actualX = node.actual_at ? layout.x(node.actual_at) : null
                    return (
                      <div key={node.id}>
                        {shifted && (
                          <div
                            className="absolute z-[2] h-px bg-amber-400"
                            style={{
                              left: Math.min(item.baselineEndX, item.forecastEndX),
                              top: item.y,
                              width: Math.max(1, Math.abs(item.forecastEndX - item.baselineEndX)),
                            }}
                            aria-hidden="true"
                          />
                        )}
                        <div
                          className="absolute z-[3] h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-dashed border-slate-500 bg-slate-100"
                          style={{ left: item.baselineEndX, top: item.y }}
                          title={`Базовая дата: ${formatDate(node.baseline_due_at)}`}
                        />
                        <div
                          className={cn(
                            'absolute z-10 -translate-x-1/2 -translate-y-1/2 rotate-45 border-white shadow-sm ring-1 ring-current',
                            milestoneSize(node.criticality),
                            milestoneColor(node.status),
                            node.status === 'cancelled' && 'opacity-60',
                          )}
                          style={{ left: item.forecastEndX, top: item.y }}
                          title={milestoneTitle(node)}
                        >
                          {node.status === 'achieved' && (
                            <Check className="h-full w-full -rotate-45 p-0.5 text-white" strokeWidth={3} />
                          )}
                        </div>
                        {actualX !== null && node.status !== 'achieved' && (
                          <div
                            className="absolute z-10 h-5 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-emerald-600"
                            style={{ left: actualX, top: item.y }}
                            title={`Фактическая дата: ${formatDate(node.actual_at)}`}
                          />
                        )}
                      </div>
                    )
                  }

                  const baselineWidth = Math.max(30, item.baselineEndX - item.baselineStartX)
                  const actualX = node.actual_at ? layout.x(node.actual_at) : null
                  return (
                    <div key={node.id}>
                      <div
                        className="absolute z-[2] h-3 -translate-y-1/2 rounded border border-dashed border-slate-500 bg-slate-100"
                        style={{
                          left: item.baselineStartX,
                          top: item.y,
                          width: baselineWidth,
                        }}
                        title={`Базовый план: ${formatDate(node.baseline_starts_at)} — ${formatDate(node.baseline_due_at)}`}
                      />
                      <div
                        className={cn(
                          'absolute z-10 h-4 -translate-y-1/2 rounded border border-white/70 shadow-sm',
                          taskColor(node.status),
                        )}
                        style={{
                          left: item.forecastStartX,
                          top: item.y,
                          width: item.forecastWidth,
                        }}
                        title={[
                          node.ref,
                          node.title,
                          node.assignee_name || 'без исполнителя',
                          `прогноз: ${formatDate(node.forecast_starts_at)} — ${formatDate(node.forecast_due_at)}`,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      />
                      {actualX !== null && (
                        <div
                          className="absolute z-20 h-6 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-emerald-700"
                          style={{ left: actualX, top: item.y }}
                          title={`Факт: ${formatDate(node.actual_at)}`}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
