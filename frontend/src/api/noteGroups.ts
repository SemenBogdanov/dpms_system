import { api } from './client'
import type { QuickNote } from './types'

export type GroupedQuickNote = QuickNote & { group_id?: string | null }
export type NoteGroup = { id: string; title: string; position: number; collapsed: boolean; archived: boolean; revision: number; note_count: number }
export type NoteTargetType = 'entity' | 'personal_task'
export type NoteTarget = { target_type: NoteTargetType; target_id: string; title: string }
export type NoteContextLink = NoteTarget & { id: string; inherited: boolean; origin: 'direct' | 'group' | 'source' | 'legacy'; can_remove: boolean }
export type NoteBacklinks = { notes: { id: string; title: string }[]; groups: { id: string; title: string; archived: boolean }[] }
export type NoteRecipient = { id: string; name: string }
export type NoteShareSelection = { note_ids?: string[]; group_id?: string; recipient_ids: string[]; project_id?: string }
export type NoteSharePreview = {
  id: string; expires_at: string; policy: 'accepted_contacts'; existing_share_count: number; new_share_count: number
  notes: { id: string; title: string; revision: number; excerpt: string; comment_count: number; files: { id: string; name: string; size: number }[] }[]
  recipients: NoteRecipient[]
}

const root = '/api/note-groups'
const source = (type: 'group' | 'note', id: string) => `${root}/sources/${type}/${id}/links`
export const noteGroupsApi = {
  list: () => api.get<NoteGroup[]>(root),
  create: (title: string) => api.post<NoteGroup>(root, { title }),
  update: (group: NoteGroup, changes: Partial<Pick<NoteGroup, 'title' | 'collapsed' | 'archived'>>) => api.patch<NoteGroup>(`${root}/${group.id}`, { ...changes, base_revision: group.revision }),
  remove: (group: NoteGroup) => api.delete(`${root}/${group.id}?base_revision=${group.revision}`),
  order: (groups: NoteGroup[]) => api.post<NoteGroup[]>(`${root}/order`, { groups: groups.map(group => ({ id: group.id, base_revision: group.revision })) }),
  move: (note_ids: string[], group_id: string | null) => api.post(`${root}/move`, { note_ids, group_id }),
  targets: () => api.get<NoteTarget[]>(`${root}/targets`),
  links: (type: 'group' | 'note', id: string) => api.get<NoteContextLink[]>(source(type, id)),
  addLink: (type: 'group' | 'note', id: string, target: NoteTarget) => api.post<NoteContextLink[]>(source(type, id), { target_type: target.target_type, target_id: target.target_id }),
  removeLink: (type: 'group' | 'note', id: string, link: NoteContextLink) => link.origin === 'legacy'
    ? api.delete(`/api/work-entities/${link.target_id}/links/${link.id}`)
    : api.delete(`${source(type, id)}/${link.id}`),
  backlinks: (target_type: NoteTargetType, target_id: string) => api.get<NoteBacklinks>(`${root}/backlinks`, { target_type, target_id }),
  recipients: (project_id?: string) => api.get<NoteRecipient[]>(`${root}/share/recipients`, project_id ? { project_id } : undefined),
  preview: (selection: NoteShareSelection) => api.post<NoteSharePreview>(`${root}/share/preview`, selection),
  apply: (id: string) => api.post<{ changed_share_count: number }>(`${root}/share/${id}/apply`, {}),
}
