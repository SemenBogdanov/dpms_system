import { api } from '@/api/client'
import type { User } from '@/api/types'
import { hasAuditAccess, hasAuditCalendarAccess, hasDevelopmentAccess, hasFeedbackAccess, hasTaskWorkspaceAccess } from './access'

const personal = new Set(['messages', 'quick-notes', 'personal-tasks', 'deadline-trackers', 'graphs', 'contacts', 'settings'])
const workspace = new Set(['my-tasks', 'queue', 'catalog', 'knowledge', 'shop', 'work-entities', 'profile'])
const management = new Set(['dashboard', 'reports', 'calculator', 'absences'])

export function usageSection(pathname: string, user: User): string | null {
  const part = pathname.split('/')[1]
  if (personal.has(part)) return part
  if (workspace.has(part) && hasTaskWorkspaceAccess(user)) return part
  if (management.has(part) && hasTaskWorkspaceAccess(user) && ['admin', 'teamlead'].includes(user.role)) return part
  if (part === 'calibration' && user.role === 'admin') return part
  if (part === 'audit' && hasAuditAccess(user)) return part
  if (part === 'audit-calendar' && hasAuditCalendarAccess(user)) return part
  if (part === 'competencies' && hasDevelopmentAccess(user)) return part
  if (part === 'feedback' && hasFeedbackAccess(user)) return part
  if (part === 'admin' && user.role === 'admin') {
    if (pathname === '/admin/integrations') return 'admin-integrations'
    if (pathname === '/admin/users' || pathname === '/admin/usage') return 'admin-users'
  }
  return null
}

type Visit = { section: string; event_id: string; sent: boolean }
type VisitState = { last: Visit | null; pending: Visit[] }
const memory = new Map<string, VisitState>()
const inflight = new Set<string>()
const MAX_PENDING = 100

function isVisit(value: unknown): value is Visit {
  return !!value && typeof value === 'object' && 'section' in value && typeof value.section === 'string'
    && 'event_id' in value && typeof value.event_id === 'string' && /^[0-9a-f-]{36}$/i.test(value.event_id)
    && 'sent' in value && typeof value.sent === 'boolean'
}

function readVisits(userId: string): VisitState {
  const cached = memory.get(userId)
  if (cached) return cached
  let state: VisitState = { last: null, pending: [] }
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(`dpms:usage:last-section:${userId}`) || 'null')
    if (isVisit(saved)) {
      state = { last: saved, pending: saved.sent ? [] : [saved] }
    } else if (saved && typeof saved === 'object' && 'last' in saved && 'pending' in saved && Array.isArray(saved.pending)) {
      state = { last: isVisit(saved.last) ? saved.last : null, pending: saved.pending.filter(isVisit).filter((visit) => !visit.sent).slice(-MAX_PENDING) }
    }
  } catch { /* Navigation must also work when storage is unavailable. */ }
  memory.set(userId, state)
  return state
}

function storeVisits(userId: string, state: VisitState) {
  memory.set(userId, state)
  try { sessionStorage.setItem(`dpms:usage:last-section:${userId}`, JSON.stringify(state)) } catch { /* Best effort. */ }
}

export async function recordSectionVisit(userId: string, section: string, isCurrent = () => true) {
  const previous = readVisits(userId)
  if (previous.last?.section !== section) {
    const visit = { section, event_id: crypto.randomUUID(), sent: false }
    storeVisits(userId, { last: visit, pending: [...previous.pending, visit].slice(-MAX_PENDING) })
  }
  // Keep unacknowledged IDs across navigation; telemetry stays bounded and best effort.
  for (const visit of [...readVisits(userId).pending]) {
    if (!isCurrent()) return
    if (inflight.has(visit.event_id)) continue
    inflight.add(visit.event_id)
    try {
      await api.post('/api/usage/section-views', { event_id: visit.event_id, section: visit.section }, { redirectOnUnauthorized: false })
      const current = readVisits(userId)
      storeVisits(userId, {
        last: current.last?.event_id === visit.event_id ? { ...visit, sent: true } : current.last,
        pending: current.pending.filter((item) => item.event_id !== visit.event_id),
      })
    } catch { /* Retry the same ID on a later foreground/reload; no polling. */ }
    finally { inflight.delete(visit.event_id) }
  }
}
