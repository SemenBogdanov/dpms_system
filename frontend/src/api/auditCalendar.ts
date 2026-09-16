import { api } from './client'

export type CalendarRole = 'auditor' | 'tech' | 'speaker' | 'observer'
export type CalendarScope = { id: string; name: string; timezone: string; baseline: string; version: number; today: string; now: string; archived: boolean; history_complete: boolean }
export type CalendarMember = { user_id: string; full_name: string; code: string; role: CalendarRole; can_manage: boolean; active: boolean }
export type CalendarGroup = { id: string; code: string; label: string; legacy: boolean; archived: boolean; versions: { id: string; effective_from: string; auditor_id: string | null; tech_id: string | null }[] }
export type CalendarIssue = { code: string; message: string; user_id?: string; participant_code?: string; participant_name?: string; role?: CalendarRole; record_id?: string }
export type CalendarMeetingOptions = { version: number; date: string; start: number; duration: number; groups: { id: string; code: string; label: string; eligible: boolean; issues: CalendarIssue[]; warnings: CalendarIssue[] }[] }
export type CalendarMeetingWindowCell = { date: string; start: number; status: 'available' | 'warning' | 'unavailable' | 'expired'; confirmed: number; uncertain: number }
export type CalendarMeetingWindowQuery = { date: string; start: number; duration: number; group_id: string | null; speaker_id: string | null }
export type CalendarMeetingWindowOption = { group_id: string; group_version_id: string; auditor_id: string; tech_id: string; speaker_id: string; status: 'available' | 'warning'; warnings: CalendarIssue[] }
export type CalendarMeetingWindows = {
  version: number; now: string
  period: { from: string; to: string; duration: number; group_id: string | null; speaker_id: string | null; full_day: boolean }
  cells: CalendarMeetingWindowCell[]
}
export type CalendarMeetingWindowOptions = { version: number; now: string; query: CalendarMeetingWindowQuery; options: CalendarMeetingWindowOption[] }
export type CalendarMeetingWindowPrefill = { duration: number; group_id: string; speaker_id: string; version: number; server_now?: string; clock_started?: { wall: number; monotonic: number } }
export type CalendarWorkload = {
  version: number; period: { from: string; to: string; group_id: string | null }; working_days: number
  working_window: { start: number; end: number; slot_minutes: number }
  members: (CalendarMember & { filled_days: number; partial_days: number; unfilled_days: number; absence_days: number
    free_slots: number; free_minutes: number; planned_meetings: number; planned_minutes: number; planned_work_minutes: number
    outside_work_minutes: number; target: number; power_percent: number | null; norm_percent: number | null })[]
}
export type CalendarPlan = { id: string; date: string; start: number; duration: number; group_id: string; group_version_id: string | null; activity: string; speaker_id: string | null; status: 'draft' | 'planned' | 'cancelled'; fact_outcome?: 'completed' | 'cancelled' | null; version: number; origin: string; source_id: string | null; issues: CalendarIssue[]; warnings: CalendarIssue[] }
export type CalendarFact = { id: string; plan_id: string | null; date: string; start: number; duration: number; group_id: string | null; activity: string; speaker_id: string | null; outcome: 'completed' | 'cancelled'; reason: string; evidence: string; recorded_by_id: string; recorded_at: string; participant_snapshot: unknown[]; planned_snapshot: unknown; composition_unknown: boolean; origin: string }
export type CalendarAvailability = { user_id: string; date: string; start: number; end: number; available: boolean }
export type CalendarAvailabilityLock = { id: string; user_id: string; date: string; locked: boolean; locked_at: string; locked_by_id: string; snapshot: unknown[] }
export type CalendarChangeRequest = { id: string; user_id: string; date: string; reason: string; status: 'pending' | 'approved' | 'closed' | 'rejected'; requested_at: string; requested_by_id: string; opened_at: string | null; opened_by_id: string | null; closed_at: string | null; closed_by_id: string | null; resolution: string; before: unknown[]; after: unknown[] | null }
export type CalendarReadiness = {
  scope_version: number; from: string; to: string; duration: number; working_start: number; working_end: number
  employees: { user_id: string; full_name: string; code: string; role: CalendarRole; days: { date: string; status: 'missing' | 'partial' | 'filled' | 'absent'; free_minutes: number; locked: boolean }[]; filled_days: number; total_days: number }[]
  groups: { group_id: string; code: string; label: string; days: { date: string; member_ids: string[]; missing_user_ids: string[]; status: 'no_composition' | 'missing' | 'absent' | 'no_overlap' | 'booked' | 'available'; common_windows: { start: number; end: number }[]; free_windows: { start: number; end: number }[]; slots: { start: number; end: number }[]; plans: { id: string; start: number; duration: number; activity: string; status: string }[]; last_notified_at: string | null }[] }[]
}
export type CalendarAbsence = { id: string; user_id: string; start_date: string; end_date: string; reason: string; version: number; status: 'active' | 'cancelled' }
export type CalendarTimelineMeeting = { id: string; kind: 'plan' | 'fact'; start: number; duration: number; activity: string; status: string; group_code: string; participants: { user_id: string; role: CalendarRole }[] }
export type CalendarTimeline = { version: number; date: string; members: CalendarMember[]; availability: CalendarAvailability[]; absences: CalendarAbsence[]; locks: CalendarAvailabilityLock[]; meetings: CalendarTimelineMeeting[] }
export type CalendarNorm = { id: string; group_id: string | null; effective_from: string; value: number; reason: string; recorded_at: string; recorded_by_id: string }
export type CalendarNotice = { id: string; plan_id: string; user_id: string; reported_at: string; reason: string }
export type CalendarTotals = { target: number; completed: number; balance: number; backlog: number }
export type CalendarStats = { plan: number; fact: number; attention: number; target: number; backlog: number; through: string | null; target_scope: 'team' | 'group'; groups: ({ group_id: string; code: string } & CalendarTotals)[]; fortnights: ({ from: string; to: string; cumulative_backlog: number } & CalendarTotals)[] }
export type CalendarState = { scope: CalendarScope; actor: { user_id: string; can_manage: boolean; can_archive: boolean }; members: CalendarMember[]; groups: CalendarGroup[]; plans: CalendarPlan[]; facts: CalendarFact[]; availability: CalendarAvailability[]; availability_locks: CalendarAvailabilityLock[]; change_requests: CalendarChangeRequest[]; absences: CalendarAbsence[]; norms: CalendarNorm[]; notices: CalendarNotice[]; stats: CalendarStats }
export type AvailabilityPatch = { date: string; start: number; end: number; value: boolean | null }
export type CalendarCommandMap = {
  'group.save': { id?: string; code: string; label: string; legacy?: false; archived?: boolean; effective_from: string; auditor_id?: string; tech_id?: string; reason: string }
  'plan.save': { id?: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; status: CalendarPlan['status']; reason?: string }
  'plan.revise': { id: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; status: CalendarPlan['status']; reason: string }
  'fact.record': { plan_id: string; date: string; start: number; duration: number; group_id: string; activity: string; speaker_id: string | null; outcome: CalendarFact['outcome']; reason: string; evidence: string; auditor_absent_minutes: number }
  'fact.restore': { source_row_id: string; date: string; start: number; duration: number; activity: string; speaker_id: string | null; outcome: CalendarFact['outcome']; reason: string; evidence: string; composition_unknown: boolean; participants: { user_id: string; role: CalendarRole }[]; confirm: true }
  'notice.record': { plan_id: string; user_id: string; reported_at: string; reason: string }
  'availability.paint': { user_id: string; patches: AvailabilityPatch[]; expected?: AvailabilityPatch[] }
  'availability.lock': { user_id: string; date: string; reason: string }
  'availability.request': { user_id: string; date: string; reason: string }
  'availability.resolve': { id: string; action: 'approve' | 'close' | 'reject'; reason: string }
  'availability.notify': { group_id: string; date: string; reason: string; duration?: number }
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
  readiness: (params: { from: string; to: string; duration: number }, signal?: AbortSignal) => api.get<CalendarReadiness>(`${root}/readiness`, { ...params, duration: String(params.duration) }, { signal }),
  timeline: (date: string, signal?: AbortSignal) => api.get<CalendarTimeline>(`${root}/availability-timeline`, { date }, { signal }),
  meetingOptions: (params: { date: string; start: number; duration: number; speaker_id?: string; plan_id?: string }, signal?: AbortSignal) => api.get<CalendarMeetingOptions>(`${root}/meeting-options`, { ...params, start: String(params.start), duration: String(params.duration) }, { signal }),
  meetingWindows: (params: { from: string; to: string; duration: number; group?: string; speaker_id?: string; full_day: boolean }, signal?: AbortSignal) => api.get<CalendarMeetingWindows>(`${root}/meeting-windows`, { ...params, duration: String(params.duration), full_day: String(params.full_day) }, { signal }),
  meetingWindowOptions: (params: { date: string; start: number; duration: number; group?: string; speaker_id?: string }, signal?: AbortSignal) => api.get<CalendarMeetingWindowOptions>(`${root}/meeting-window-options`, { ...params, start: String(params.start), duration: String(params.duration) }, { signal }),
  workload: (params: { from: string; to: string; group?: string }, signal?: AbortSignal) => api.get<CalendarWorkload>(`${root}/workload`, params, { signal }),
  command: (command: CalendarCommand, request_id: string, expected_version: number) => api.post<CalendarMutation>(`${root}/commands`, { request_id, expected_version, ...command }),
  admin: () => api.get<CalendarAdminState>(`${root}/admin`),
  setup: (body: { request_id: string; name: string; baseline: string }) => api.post<CalendarMutation>(`${root}/admin/setup`, body),
  member: (body: { request_id: string; expected_version: number; user_id: string; code: string; role: CalendarRole; can_manage: boolean; active: boolean }) => api.post<CalendarMutation>(`${root}/admin/members`, body),
  history: (limit = 100) => api.get<CalendarHistory>(`${root}/history`, { limit: String(limit) }),
  imports: () => api.get<CalendarImport[] | { items: CalendarImport[] }>(`${root}/imports`),
  preview: (body: { request_id: string; expected_version: number; source: unknown; mapping: Record<string, string>; bootstrap_history?: boolean; group_mapping?: Record<string, { auditor_id: string; tech_id: string }> }) => api.post<CalendarImport>(`${root}/imports/preview`, body),
  applyImport: (id: string, body: { request_id: string; expected_version: number; confirm: true; reason: string }) => api.post<CalendarMutation>(`${root}/imports/${encodeURIComponent(id)}/apply`, body),
}
