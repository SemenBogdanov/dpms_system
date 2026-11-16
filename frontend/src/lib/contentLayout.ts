import type { User } from '@/api/types'
import { hasTaskWorkspaceAccess } from '@/lib/access'
import { sidebarNav, visibleSidebarNav } from '@/lib/sidebarNavigation'

export type ContentLayoutPreference = {
  fullWidth: boolean
  marginPercent: number
}

export type ContentLayoutPreferences = Partial<Record<string, ContentLayoutPreference>>

export type ContentLayoutSection = {
  id: string
  pathname: string
  label: string
  minWidth: number
}

export const DEFAULT_CONTENT_LAYOUT_PREFERENCE: ContentLayoutPreference = Object.freeze({
  fullWidth: true,
  marginPercent: 10,
})

export const MAX_CONTENT_MARGIN = 40
const MAX_STORAGE_LENGTH = 16_384
const minWidths: Record<string, number> = {
  queue: 1440,
  reports: 1440,
  'work-entities': 1440,
  audit: 1440,
  'admin-users': 1440,
  'audit-calendar': 1440,
  calculator: 1120,
  knowledge: 1100,
  competencies: 1100,
}

const extraSections: ContentLayoutSection[] = [
  { id: 'profile', pathname: '/profile', label: '\u041f\u0440\u043e\u0444\u0438\u043b\u044c', minWidth: 960 },
  { id: 'admin-integrations', pathname: '/admin/integrations', label: '\u0418\u043d\u0442\u0435\u0433\u0440\u0430\u0446\u0438\u0438', minWidth: 960 },
  { id: 'admin-usage', pathname: '/admin/usage', label: '\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u044f', minWidth: 960 },
]

export const contentLayoutSections: ContentLayoutSection[] = [
  ...sidebarNav.map((item) => ({
    id: item.id,
    pathname: item.to,
    label: item.label,
    minWidth: minWidths[item.id] ?? 960,
  })),
  ...extraSections,
]

const sectionsByPath = [...contentLayoutSections].sort((a, b) => b.pathname.length - a.pathname.length)

export function getContentLayoutSections(user: User | null): ContentLayoutSection[] {
  const visibleIds = new Set(visibleSidebarNav(user).map((item) => item.id))
  if (hasTaskWorkspaceAccess(user)) visibleIds.add('profile')
  if (user?.role === 'admin') {
    visibleIds.add('admin-integrations')
    visibleIds.add('admin-usage')
  }
  return contentLayoutSections.filter((section) => visibleIds.has(section.id))
}

export function getSectionForPath(pathname: string): ContentLayoutSection | undefined {
  const path = pathname.split(/[?#]/, 1)[0]
  return sectionsByPath.find((section) => path === section.pathname || path.startsWith(`${section.pathname}/`))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function normalizeContentLayoutPreference(value: unknown): ContentLayoutPreference | undefined {
  if (!isRecord(value)
    || !Object.prototype.hasOwnProperty.call(value, 'fullWidth')
    || !Object.prototype.hasOwnProperty.call(value, 'marginPercent')
    || typeof value.fullWidth !== 'boolean'
    || typeof value.marginPercent !== 'number'
    || !Number.isFinite(value.marginPercent)) return undefined

  return {
    fullWidth: value.fullWidth,
    marginPercent: Math.round(Math.min(MAX_CONTENT_MARGIN, Math.max(0, value.marginPercent)) * 10) / 10,
  }
}

export function normalizeContentLayoutPreferences(value: unknown): ContentLayoutPreferences {
  const preferences: ContentLayoutPreferences = {}
  if (!isRecord(value)) return preferences
  for (const { id } of contentLayoutSections) {
    if (!Object.prototype.hasOwnProperty.call(value, id)) continue
    const preference = normalizeContentLayoutPreference(value[id])
    if (preference) preferences[id] = preference
  }
  return preferences
}

export function parseContentLayoutPreferences(raw: string | null | undefined): ContentLayoutPreferences {
  if (typeof raw !== 'string' || raw.length > MAX_STORAGE_LENGTH) return {}
  try {
    const value: unknown = JSON.parse(raw)
    if (!isRecord(value) || value.version !== 1) return {}
    return normalizeContentLayoutPreferences(value.sections)
  } catch {
    return {}
  }
}

export function serializeContentLayoutPreferences(preferences: ContentLayoutPreferences): string {
  return JSON.stringify({ version: 1, sections: normalizeContentLayoutPreferences(preferences) })
}

export function contentLayoutStorageKey(userId: string, sectionId?: string): string {
  const base = `dpms.contentLayout.v1:${userId}`
  return sectionId === undefined ? base : `${base}:${sectionId}`
}
