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
  canManage?: boolean
}

export function WorkEntityBacklinks(props: WorkEntityBacklinksProps) {
  return <BacklinksSession key={`${props.targetType}:${props.targetId}`} {...props} />
}

function BacklinksSession({
  targetType,
  targetId,
  className,
  canManage = true,
}: WorkEntityBacklinksProps) {
  const [links, setLinks] = useState<WorkEntityReverseLink[]>([])
  const [entities, setEntities] = useState<WorkEntity[]>([])
  const [selectedEntityId, setSelectedEntityId] = useState('')
  const [relationType, setRelationType] = useState<WorkEntityRelationType>('contains')
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [linksError, setLinksError] = useState<string | null>(null)
  const [entitiesError, setEntitiesError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const requestRef = useRef(0)
  const pendingRef = useRef(false)
  const activeRef = useRef(true)

  const load = useCallback(async () => {
    const requestId = ++requestRef.current
    setLoading(true)
    const params = new URLSearchParams({ target_type: targetType, target_id: targetId })
    await Promise.all([
      api.get<WorkEntityReverseLink[]>(`/api/work-entities/links/by-target?${params.toString()}`)
        .then((data) => {
          if (requestId !== requestRef.current) return
          setLinks(data)
          setLinksError(null)
          setSaved(false)
        }).catch(() => {
          if (requestId === requestRef.current) setLinksError('Не удалось обновить связи')
        }),
      api.get<WorkEntity[]>('/api/work-entities?include_archived=false')
        .then((data) => {
          if (requestId !== requestRef.current) return
          setEntities(data)
          setEntitiesError(null)
        }).catch(() => {
          if (requestId === requestRef.current) setEntitiesError('Не удалось загрузить проекты для добавления связи')
        }),
    ])
    if (requestId === requestRef.current) setLoading(false)
  }, [targetId, targetType])

  useEffect(() => {
    activeRef.current = true
    setLoading(true)
    void load()
    return () => {
      activeRef.current = false
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
    if (!selectedEntityId || pendingRef.current || loading || linksError || entitiesError) return
    pendingRef.current = true
    setBusy(true)
    try {
      await api.post(`/api/work-entities/${selectedEntityId}/links`, {
        target_type: targetType,
        target_id: targetId,
        relation_type: relationType,
      })
      if (!activeRef.current) return
      setSaved(true)
      setSelectedEntityId('')
      setEditing(false)
      toast.success('Связь добавлена')
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось добавить связь')
    } finally {
      pendingRef.current = false
      setBusy(false)
    }
  }

  const removeLink = async (link: WorkEntityReverseLink) => {
    if (pendingRef.current || loading || linksError) return
    pendingRef.current = true
    setBusy(true)
    try {
      await api.delete(`/api/work-entities/${link.entity_id}/links/${link.link_id}`)
      if (!activeRef.current) return
      setSaved(true)
      toast.success('Связь удалена')
      await load()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось удалить связь')
    } finally {
      pendingRef.current = false
      setBusy(false)
    }
  }

  return (
    <section className={cn('rounded-lg border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-700 dark:bg-slate-900/60', className)}>
      <div className="flex min-h-10 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Network className="h-4 w-4 shrink-0 text-primary" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Проекты и цели</h3>
          {!loading && !linksError && (
            <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-200">
              {links.length}
            </span>
          )}
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:border-primary/40 hover:text-primary disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
            title={editing ? 'Закрыть добавление связи' : 'Добавить в проект или цель'}
            aria-label={editing ? 'Закрыть добавление связи' : 'Добавить в проект или цель'}
            disabled={loading || busy || Boolean(linksError || entitiesError)}
          >
            {editing ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          </button>
        )}
      </div>

      {(linksError || entitiesError) && <div role="alert" className="py-2 text-sm text-red-700">
        {saved && 'Изменение сохранено. '}{linksError || entitiesError}. {linksError && links.length > 0 && 'Показаны последние загруженные связи.'}
        <button type="button" disabled={loading} onClick={() => void load()} className="ml-2 underline">Повторить загрузку связей</button>
      </div>}
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
              className="flex max-w-full items-center gap-1 rounded-md border border-slate-200 bg-white pl-2 dark:border-slate-700 dark:bg-slate-950"
            >
              <Link
                to={`/work-entities?entity=${link.entity_id}`}
                className="flex min-w-0 items-center gap-1.5 py-1.5 text-xs font-medium text-slate-700 hover:text-primary dark:text-slate-200"
                title={`${relationLabels[link.relation_type]}: ${link.entity_title}`}
              >
                <Link2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span className="truncate">{link.entity_title}</span>
              </Link>
              {canManage && (link.access_role === 'owner' || link.access_role === 'editor') && (
                <button
                  type="button"
                  onClick={() => void removeLink(link)}
                  disabled={busy || Boolean(linksError)}
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
      ) : !linksError ? (
        <p className="py-1 text-xs text-slate-500 dark:text-slate-400">Объект пока не связан с проектами или целями.</p>
      ) : null}

      {canManage && editing && (
        <div className="mt-3 grid gap-2 border-t border-slate-200 pt-3 sm:grid-cols-[minmax(0,1fr)_150px_auto] dark:border-slate-700">
          <label className="min-w-0">
            <span className="sr-only">Проект или цель</span>
            <select
              value={selectedEntityId}
              onChange={(event) => setSelectedEntityId(event.target.value)}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
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
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
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
            disabled={!selectedEntityId || busy || loading || Boolean(linksError || entitiesError)}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Добавить
          </button>
          {availableEntities.length === 0 && (
            <p className="text-xs text-slate-500 sm:col-span-3 dark:text-slate-400">
              Нет доступных для редактирования сущностей. Создайте проект или цель в разделе «Управление».
            </p>
          )}
        </div>
      )}
    </section>
  )
}
