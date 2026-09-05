import { api } from './client'
import type { DeadlineTracker, DeadlineTrackerCreate, DeadlineTrackerUpdate } from './types'

export interface TrackerGroup {
  id: string
  name: string
  color: string | null
  sort_order: number
  is_archived: boolean
  is_collapsed: boolean
}

export interface TrackerCategory {
  id: string
  name: string
  color: string | null
  sort_order: number
  is_archived: boolean
  legacy_type: string | null
}

export type TrackerOrganizationKind = 'groups' | 'categories'
export type TrackerOrganizationUpdate = Partial<Pick<TrackerGroup, 'name' | 'color' | 'sort_order' | 'is_archived' | 'is_collapsed'>>
export type TrackerOccurrence = NonNullable<DeadlineTracker['current_occurrence']>
export interface TrackerEvent { id: string; event_type: string; details: Record<string, unknown>; created_at: string }
export interface TrackerAlert {
  id: string
  occurrence_id: string
  reminder_id: string
  scheduled_for: string
  status: 'pending' | 'sent' | 'suppressed' | 'cancelled'
  delivered_at: string | null
  notification_id: string | null
  is_read?: boolean | null
}

const root = '/api/deadline-trackers'
const itemPath = (id: string) => `${root}/${encodeURIComponent(id)}`

export const deadlineTrackers = {
  list: (params: Record<string, string>, signal?: AbortSignal) => api.get<DeadlineTracker[]>(root, params, { signal }),
  get: (id: string, signal?: AbortSignal) => api.get<DeadlineTracker>(itemPath(id), undefined, { signal }),
  create: (payload: DeadlineTrackerCreate) => api.post<DeadlineTracker>(root, payload),
  update: (id: string, payload: DeadlineTrackerUpdate) => api.patch<DeadlineTracker>(itemPath(id), payload),
  remove: (id: string) => api.delete<{ status: string }>(itemPath(id)),
  organizations: async (signal?: AbortSignal) => {
    const [groups, categories] = await Promise.all([
      api.get<TrackerGroup[]>(`${root}/groups`, { include_archived: 'true' }, { signal }),
      api.get<TrackerCategory[]>(`${root}/categories`, { include_archived: 'true' }, { signal }),
    ])
    return { groups, categories }
  },
  createOrganization: (kind: TrackerOrganizationKind, payload: { name: string; color: string | null; sort_order?: number }) =>
    api.post<TrackerGroup | TrackerCategory>(`${root}/${kind}`, payload),
  patchOrganization: (kind: TrackerOrganizationKind, id: string, payload: TrackerOrganizationUpdate) =>
    api.patch<TrackerGroup | TrackerCategory>(`${root}/${kind}/${encodeURIComponent(id)}`, payload),
  deleteOrganization: (kind: TrackerOrganizationKind, id: string) =>
    api.delete<{ status: 'deleted' | 'archived' }>(`${root}/${kind}/${encodeURIComponent(id)}`),
  reorderGroups: (ids: string[]) => api.post<TrackerGroup[]>(`${root}/groups/reorder`, { ids }),
  completeOccurrence: (id: string, occurrenceId: string) =>
    api.post<DeadlineTracker>(`${itemPath(id)}/occurrences/${encodeURIComponent(occurrenceId)}/complete`, {}),
  finishSeries: (id: string) => api.post<DeadlineTracker>(`${itemPath(id)}/finish-series`, {}),
  markRead: (id: string) => api.post<{ marked: number }>(`${itemPath(id)}/alerts/read`, {}),
  history: async (id: string, signal: AbortSignal, offset = 0) => {
    const params = { limit: '100', offset: String(offset) }
    const [occurrences, events, alerts] = await Promise.all([
      api.get<TrackerOccurrence[]>(`${itemPath(id)}/occurrences`, params, { signal }),
      api.get<TrackerEvent[]>(`${itemPath(id)}/history`, params, { signal }),
      api.get<TrackerAlert[]>(`${itemPath(id)}/alerts`, params, { signal }),
    ])
    return { occurrences, events, alerts }
  },
}
