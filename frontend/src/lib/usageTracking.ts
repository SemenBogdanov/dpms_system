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
const memory = new Map<string, Visit>()
const inflight = new Set<string>()

function readVisit(userId: string): Visit | undefined {
  if (memory.has(userId)) return memory.get(userId)
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(`dpms:usage:last-section:${userId}`) || 'null')
    if (saved && typeof saved === 'object' && 'section' in saved && typeof saved.section === 'string'
      && 'event_id' in saved && typeof saved.event_id === 'string' && /^[0-9a-f-]{36}$/i.test(saved.event_id)
      && 'sent' in saved && typeof saved.sent === 'boolean') {
      const visit = saved as Visit
      memory.set(userId, visit)
      return visit
    }
  } catch { /* Navigation must also work when storage is unavailable. */ }
  return undefined
}

function storeVisit(userId: string, visit: Visit) {
  memory.set(userId, visit)
  try { sessionStorage.setItem(`dpms:usage:last-section:${userId}`, JSON.stringify(visit)) } catch { /* Best effort. */ }
}

export async function recordSectionVisit(userId: string, section: string) {
  const previous = readVisit(userId)
  const visit = previous?.section === section ? previous : { section, event_id: crypto.randomUUID(), sent: false }
  if (visit.sent || inflight.has(visit.event_id)) return
  storeVisit(userId, visit)
  inflight.add(visit.event_id)
  try {
    // Telemetry failures must never terminate the user's working session.
    await api.post('/api/usage/section-views', { event_id: visit.event_id, section }, { redirectOnUnauthorized: false })
    if (memory.get(userId)?.event_id === visit.event_id) storeVisit(userId, { ...visit, sent: true })
  } catch { /* Keep the same id for a later foreground/reload retry; no polling. */ }
  finally { inflight.delete(visit.event_id) }
}
