import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Link2, Loader2, Network, Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '@/api/client'
import type {
  WorkEntity,
  WorkEntityRelationType,
  WorkEntityReverseLink,
  WorkEntityTargetType,
} from '@/api/types'
import { cn } from '@/lib/utils'

const relationLabels: Record<WorkEntityRelationType, string> = {
  contains: 'В составе',
  contributes_to: 'Вносит вклад',
  depends_on: 'Зависит от',
  measures: 'Измеряет',
  related: 'Связано',
}

type WorkEntityBacklinksProps = {
  targetType: Exclude<WorkEntityTargetType, 'entity'>
  targetId: string
  className?: string
}

export function WorkEntityBacklinks({
  targetType,
  targetId,
  className,
}: WorkEntityBacklinksProps) {
  const [links, setLinks] = useState<WorkEntityReverseLink[]>([])
  const [entities, setEntities] = useState<WorkEntity[]>([])
  const [selectedEntityId, setSelectedEntityId] = useState('')
  const [relationType, setRelationType] = useState<WorkEntityRelationType>('contains')
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const requestRef = useRef(0)

  const load = useCallback(async () => {
    const requestId = ++requestRef.current
    try {
      const params = new URLSearchParams({ target_type: targetType, target_id: targetId })
      const [reverseLinks, entityList] = await Promise.all([
        api.get<WorkEntityReverseLink[]>(`/api/work-entities/links/by-target?${params.toString()}`),
        api.get<WorkEntity[]>('/api/work-entities?include_archived=false'),
      ])
      if (requestId !== requestRef.current) return
      setLinks(reverseLinks)
      setEntities(entityList)
      setUnavailable(false)
    } catch {
      if (requestId !== requestRef.current) return
      setUnavailable(true)
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [targetId, targetType])

  useEffect(() => {
    setLoading(true)
    void load()
    return () => {
      requestRef.current += 1
    }
  }, [load])

  const availableEntities = useMemo(() => {
    const linkedIds = new Set(links.map((link) => link.entity_id))
    return entities.filter(
      (entity) =>
        entity.status !== 'archived' &&
        (entity.access_role === 'owner' || entity.access_role === 'editor') &&
        !linkedIds.has(entity.id),
    )
  }, [entities, links])

  const addLink = async () => {
    if (!selectedEntityId) return
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${selectedEntityId}/links`, {
        target_type: targetType,
        target_id: targetId,
        relation_type: relationType,
      })
      await load()
      setSelectedEntityId('')
      setEditing(false)
      toast.success('Связь добавлена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить связь')
    } finally {
      setBusy(false)
    }
  }

  const removeLink = async (link: WorkEntityReverseLink) => {
    setBusy(true)
    try {
      await api.delete(`/api/work-entities/${link.entity_id}/links/${link.link_id}`)
      await load()
      toast.success('Связь удалена')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить связь')
    } finally {
      setBusy(false)
    }
  }

  if (unavailable) return null

  return (
    <section className={cn('rounded-lg border border-slate-200 bg-slate-50/60 p-3', className)}>
      <div className="flex min-h-10 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Network className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="text-sm font-semibold text-slate-800">Проекты и цели</h3>
          {!loading && (
            <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-medium text-slate-600">
              {links.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:border-primary/40 hover:text-primary disabled:opacity-50"
          title={editing ? 'Закрыть добавление связи' : 'Добавить в проект или цель'}
          aria-label={editing ? 'Закрыть добавление связи' : 'Добавить в проект или цель'}
          disabled={loading}
        >
          {editing ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-2 text-xs text-slate-400">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Загрузка связей
        </div>
      ) : links.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {links.map((link) => (
            <div
              key={link.link_id}
              className="flex max-w-full items-center gap-1 rounded-md border border-slate-200 bg-white pl-2"
            >
              <Link
                to={`/work-entities?entity=${link.entity_id}`}
                className="flex min-w-0 items-center gap-1.5 py-1.5 text-xs font-medium text-slate-700 hover:text-primary"
                title={`${relationLabels[link.relation_type]}: ${link.entity_title}`}
              >
                <Link2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span className="truncate">{link.entity_title}</span>
              </Link>
              {(link.access_role === 'owner' || link.access_role === 'editor') && (
                <button
                  type="button"
                  onClick={() => void removeLink(link)}
                  disabled={busy}
                  className="inline-flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-red-600 disabled:opacity-50"
                  title="Убрать связь"
                  aria-label={`Убрать связь с ${link.entity_title}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="py-1 text-xs text-slate-500">Объект пока не связан с проектами или целями.</p>
      )}

      {editing && (
        <div className="mt-3 grid gap-2 border-t border-slate-200 pt-3 sm:grid-cols-[minmax(0,1fr)_150px_auto]">
          <label className="min-w-0">
            <span className="sr-only">Проект или цель</span>
            <select
              value={selectedEntityId}
              onChange={(event) => setSelectedEntityId(event.target.value)}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              <option value="">Выберите сущность</option>
              {availableEntities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Тип связи</span>
            <select
              value={relationType}
              onChange={(event) => setRelationType(event.target.value as WorkEntityRelationType)}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              {Object.entries(relationLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void addLink()}
            disabled={!selectedEntityId || busy}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Добавить
          </button>
          {availableEntities.length === 0 && (
            <p className="text-xs text-slate-500 sm:col-span-3">
              Нет доступных для редактирования сущностей. Создайте проект или цель в разделе «Управление».
            </p>
          )}
        </div>
      )}
    </section>
  )
}
