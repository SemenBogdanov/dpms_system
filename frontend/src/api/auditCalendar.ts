import { api } from './client'

export type CalendarRole = 'auditor' | 'tech' | 'speaker' | 'observer'
export type CalendarScope = { id: string; name: string; timezone: string; baseline: string; version: number; today: string; now: string; archived: boolean; history_complete: boolean }
export type CalendarMember = { user_id: string; full_name: string; code: string; role: CalendarRole; can_manage: boolean; active: boolean }
export type CalendarGroup = { id: string; code: string; label: string; legacy: boolean; archived: boolean; versions: { id: string; effective_from: string; auditor_id: string | null; tech_id: string | null }[] }
export type CalendarIssue = { code: string; message: string }
export type CalendarPlan = { id: string; date: string; start: number; duration: number; group_id: string; group_version_id: string | null; activity: string; speaker_id: string | null; status: 'draft' | 'planned' | 'cancelled'; version: number; origin: string; source_id: string | null; issues: CalendarIssue[]; warnings: CalendarIssue[] }
export type CalendarFact = { id: string; plan_id: string | null; date: string; start: number; duration: number; group_id: string | null; activity: string; speaker_id: string | null; outcome: 'completed' | 'cancelled'; reason: string; evidence: string; recorded_by_id: string; recorded_at: string; participant_snapshot: unknown[]; planned_snapshot: unknown; composition_unknown: boolean; origin: string }
export type CalendarAvailability = { user_id: string; date: string; start: number; end: number; available: boolean }
export type CalendarAbsence = { id: string; user_id: string; start_date: string; end_date: string; reason: string; version: number; status: 'active' | 'cancelled' }
export type CalendarNorm = { id: string; group_id: string | null; effective_from: string; value: number; reason: string; recorded_at: string; recorded_by_id: string }
export type CalendarNotice = { id: string; plan_id: string; user_id: string; reported_at: string; reason: string }
export type CalendarTotals = { target: number; completed: number; balance: number; backlog: number }
export type CalendarStats = { plan: number; fact: number; attention: number; target: number; backlog: number; through: string | null; target_scope: 'team' | 'group'; groups: ({ group_id: string; code: string } & CalendarTotals)[]; fortnights: ({ from: string; to: string; cumulative_backlog: number } & CalendarTotals)[] }
export type CalendarState = { scope: CalendarScope; actor: { user_id: string; can_manage: boolean }; members: CalendarMember[]; groups: CalendarGroup[]; plans: CalendarPlan[]; facts: CalendarFact[]; availability: CalendarAvailability[]; absences: CalendarAbsence[]; norms: CalendarNorm[]; notices: CalendarNotice[]; stats: CalendarStats }
export type AvailabilityPatch = { date: string; start: number; end: number; value: boolean | null }
export type CalendarCommandMap = {
  'group.save': { id?: string; code: string; label: string; legacy?: false; archived?: boolean; effective_from: string; auditor_id?: string; tech_id?: string; reason: string }
  'plan.save': { id?: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; status: CalendarPlan['status']; reason?: string }
  'plan.revise': { id: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; status: CalendarPlan['status']; reason: string }
  'fact.record': { plan_id: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; outcome: CalendarFact['outcome']; reason: string; evidence: string; auditor_absent_minutes: number }
  'fact.restore': { source_row_id: string; date: string; start: number; duration: number; activity: string; speaker_id: string | null; outcome: CalendarFact['outcome']; reason: string; evidence: string; composition_unknown: boolean; participants: { user_id: string; role: CalendarRole }[]; confirm: true }
  'notice.record': { plan_id: string; user_id: string; reported_at: string; reason: string }
  'availability.paint': { user_id: string; patches: AvailabilityPatch[] }
  'absence.add': { user_id: string; start_date: string; end_date: string; reason: string }
  'absence.end': { id: string; reason: string }
  'norm.set': { group_id: string | null; effective_from: string; value: number; reason: string }
  'scope.archive': { archived: boolean; reason: string }
}
export type CalendarCommand = { [K in keyof CalendarCommandMap]: { operation: K; payload: CalendarCommandMap[K] } }[keyof CalendarCommandMap]
export type CalendarMutation = { version: number; result: unknown }
export type CalendarAdminState = { scope: CalendarScope | null; members: CalendarMember[]; users: { id: string; full_name: string; email: string; audit_calendar_enabled: boolean; is_active: boolean }[] }
export type CalendarHistory = { items: { id: string; action: string; actor_name: string; occurred_at: string; detail: unknown }[]; total: number }
export type CalendarImport = { id: string; version: number; status: string; summary: unknown; issues: unknown[]; rows: unknown[]; mapping_required: unknown[]; source_sha256: string }
const root = '/api/audit-calendar'
export const auditCalendar = {
  state: (params: Record<string, string>, signal?: AbortSignal) => api.get<CalendarState>(`${root}/state`, params, { signal }),
  command: (command: CalendarCommand, request_id: string, expected_version: number) => api.post<CalendarMutation>(`${root}/commands`, { request_id, expected_version, ...command }),
  admin: () => api.get<CalendarAdminState>(`${root}/admin`),
  setup: (body: { request_id: string; name: string; baseline: string }) => api.post<CalendarMutation>(`${root}/admin/setup`, body),
  member: (body: { request_id: string; expected_version: number; user_id: string; code: string; role: CalendarRole; can_manage: boolean; active: boolean }) => api.post<CalendarMutation>(`${root}/admin/members`, body),
  history: (limit = 100) => api.get<CalendarHistory>(`${root}/history`, { limit: String(limit) }),
  imports: () => api.get<CalendarImport[] | { items: CalendarImport[] }>(`${root}/imports`),
  preview: (body: { request_id: string; expected_version: number; source: unknown; mapping: Record<string, string>; bootstrap_history?: boolean; group_mapping?: Record<string, { auditor_id: string; tech_id: string }> }) => api.post<CalendarImport>(`${root}/imports/preview`, body),
  applyImport: (id: string, body: { request_id: string; expected_version: number; confirm: true; reason: string }) => api.post<CalendarMutation>(`${root}/imports/${encodeURIComponent(id)}/apply`, body),
}
