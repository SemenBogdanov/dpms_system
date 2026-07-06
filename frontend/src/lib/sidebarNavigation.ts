import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  BookOpenCheck,
  Calculator,
  CalendarClock,
  CalendarDays,
  ClipboardList,
  Contact,
  LayoutDashboard,
  Library,
  ListChecks,
  ListTodo,
  MessageSquare,
  Scale,
  Settings,
  ShoppingBag,
  StickyNote,
  Users,
} from 'lucide-react'
import type { User } from '@/api/types'
import { hasDevelopmentAccess, hasFeedbackAccess, hasTaskWorkspaceAccess } from '@/lib/access'

export type SidebarGroupKey = 'tasks' | 'management' | 'development' | 'feedback' | 'settings' | 'admin'
export type SidebarSection = 'task' | 'feedback' | 'development' | 'personal' | 'settings' | 'admin'
export type SidebarRole = 'executor' | 'teamlead' | 'admin'

export type SidebarNavItem = {
  id: string
  to: string
  label: string
  icon: LucideIcon
  section: SidebarSection
  group: SidebarGroupKey
  roles?: readonly SidebarRole[]
}

export type SidebarGroupDefinition = {
  key: SidebarGroupKey
  label: string
  icon: LucideIcon
  placement: 'main' | 'bottom'
  expandable?: boolean
}

export type SidebarMenuButton = {
  id: string
  label: string
  itemIds: string[]
}

export type SidebarOrder = {
  groups: SidebarMenuButton[]
  items: Record<string, string[]>
  itemLabels: Record<string, string>
}

type SidebarMenuButtonInput =
  | string
  | {
      id?: unknown
      key?: unknown
      label?: unknown
      item_ids?: unknown
      itemIds?: unknown
    }

export type SidebarOrderInput = {
  version?: unknown
  groups?: SidebarMenuButtonInput[]
  items?: Record<string, string[] | undefined>
  item_labels?: Record<string, unknown>
  itemLabels?: Record<string, unknown>
} | null | undefined

export const sidebarGroups: SidebarGroupDefinition[] = [
  { key: 'tasks', label: 'Задачи', icon: ListChecks, placement: 'main', expandable: true },
  { key: 'management', label: 'Управление', icon: LayoutDashboard, placement: 'main', expandable: true },
  { key: 'development', label: 'Развитие', icon: BookOpenCheck, placement: 'main' },
  { key: 'feedback', label: 'Обратная связь', icon: MessageSquare, placement: 'main' },
  { key: 'settings', label: 'Настройки', icon: Settings, placement: 'bottom' },
  { key: 'admin', label: 'Админ', icon: Users, placement: 'bottom' },
]

export const sidebarNav: SidebarNavItem[] = [
  { id: 'personal-tasks', to: '/personal-tasks', label: 'Личные задачи', icon: ListChecks, section: 'personal', group: 'tasks' },
  { id: 'my-tasks', to: '/my-tasks', label: 'Q-план', icon: ClipboardList, section: 'task', group: 'tasks' },
  { id: 'queue', to: '/queue', label: 'Очередь', icon: ListTodo, section: 'task', group: 'tasks' },
  { id: 'calculator', to: '/calculator', label: 'Калькулятор', icon: Calculator, section: 'task', group: 'tasks', roles: ['teamlead', 'admin'] },
  { id: 'catalog', to: '/catalog', label: 'Каталог операций', icon: Library, section: 'task', group: 'tasks' },
  { id: 'shop', to: '/shop', label: 'Магазин', icon: ShoppingBag, section: 'task', group: 'tasks' },
  { id: 'deadline-trackers', to: '/deadline-trackers', label: 'Трекер сроков', icon: CalendarClock, section: 'personal', group: 'tasks' },
  { id: 'quick-notes', to: '/quick-notes', label: 'Заметки', icon: StickyNote, section: 'personal', group: 'tasks' },
  { id: 'contacts', to: '/contacts', label: 'Контакты', icon: Contact, section: 'personal', group: 'tasks' },
  { id: 'dashboard', to: '/', label: 'Дашборд', icon: LayoutDashboard, section: 'task', group: 'management', roles: ['teamlead', 'admin'] },
  { id: 'reports', to: '/reports', label: 'Отчёты', icon: BarChart3, section: 'task', group: 'management', roles: ['teamlead', 'admin'] },
  { id: 'calibration', to: '/calibration', label: 'Калибровка', icon: Scale, section: 'task', group: 'management', roles: ['admin'] },
  { id: 'absences', to: '/absences', label: 'Отсутствия', icon: CalendarDays, section: 'task', group: 'management', roles: ['teamlead', 'admin'] },
  { id: 'competencies', to: '/competencies', label: 'Развитие', icon: BookOpenCheck, section: 'development', group: 'development' },
  { id: 'feedback', to: '/feedback', label: 'Обратная связь', icon: MessageSquare, section: 'feedback', group: 'feedback' },
  { id: 'settings', to: '/settings', label: 'Настройки', icon: Settings, section: 'settings', group: 'settings' },
  { id: 'admin-users', to: '/admin/users', label: 'Админ', icon: Users, section: 'admin', group: 'admin', roles: ['admin'] },
]

export const defaultSidebarOrder: SidebarOrder = {
  groups: sidebarGroups
    .filter((group) => group.placement === 'main')
    .map((group) => ({
      id: group.key,
      label: group.label,
      itemIds: sidebarNav.filter((item) => item.group === group.key).map((item) => item.id),
    })),
  items: {
    tasks: sidebarNav.filter((item) => item.group === 'tasks').map((item) => item.id),
    management: sidebarNav.filter((item) => item.group === 'management').map((item) => item.id),
    development: sidebarNav.filter((item) => item.group === 'development').map((item) => item.id),
    feedback: sidebarNav.filter((item) => item.group === 'feedback').map((item) => item.id),
  },
  itemLabels: {},
}

const builtinGroupByKey = new Map<string, SidebarGroupDefinition>(sidebarGroups.map((group) => [group.key, group]))
const navById = new Map(sidebarNav.map((item) => [item.id, item]))

function cleanId(value: unknown, fallback: string) {
  const id = typeof value === 'string' ? value.trim() : ''
  return (id || fallback).slice(0, 64)
}

function cleanLabel(value: unknown, fallback: string) {
  const label = typeof value === 'string' ? value : ''
  return (label.trim() ? label : fallback).slice(0, 80)
}

function cleanItemIds(value: unknown, fallback: string[]) {
  if (!Array.isArray(value)) return fallback
  const seen = new Set<string>()
  return value
    .filter((itemId): itemId is string => typeof itemId === 'string' && navById.has(itemId))
    .filter((itemId) => {
      if (seen.has(itemId)) return false
      seen.add(itemId)
      return true
    })
}

function cleanItemLabels(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.fromEntries(
    Object.entries(value)
      .filter(([itemId, label]) => navById.has(itemId) && typeof label === 'string')
      .map(([itemId, label]) => [itemId.slice(0, 64), (label as string).slice(0, 80)])
  )
}

function normalizeButton(
  input: SidebarMenuButtonInput,
  items: Record<string, string[] | undefined> | undefined,
  index: number
) {
  if (typeof input === 'string') {
    const builtin = builtinGroupByKey.get(input)
    const defaults = defaultSidebarOrder.items[input] || []
    return {
      id: input,
      label: builtin?.label || input,
      itemIds: cleanItemIds(items?.[input], defaults),
    }
  }

  const rawId = input?.id ?? input?.key
  const id = cleanId(rawId, `custom-${index + 1}`)
  const builtin = builtinGroupByKey.get(id)
  const fallbackItems = builtin
    ? defaultSidebarOrder.items[id] || []
    : []
  const itemIds = cleanItemIds(input?.item_ids ?? input?.itemIds ?? items?.[id], fallbackItems)
  return {
    id,
    label: cleanLabel(input?.label, builtin?.label || `Кнопка ${index + 1}`),
    itemIds,
  }
}

export function normalizeSidebarOrder(order?: SidebarOrderInput): SidebarOrder {
  const rawGroups = Array.isArray(order?.groups) ? order.groups : []
  const normalizedGroups = rawGroups
    .map((group, index) => normalizeButton(group, order?.items, index))

  const groups = normalizedGroups.length ? normalizedGroups : defaultSidebarOrder.groups
  const usedIds = new Set<string>()
  const uniqueGroups = groups.map((group, index) => {
    const id = usedIds.has(group.id) ? `${group.id}-${index + 1}` : group.id
    usedIds.add(id)
    return { ...group, id }
  })
  const version = typeof order?.version === 'number' ? order.version : 1
  const shouldBackfillMissingDefaults = rawGroups.length > 0 && version < 2
  const assignedItemIds = new Set(uniqueGroups.flatMap((group) => group.itemIds))
  const mergedGroups = shouldBackfillMissingDefaults
    ? uniqueGroups.map((group) => {
        const defaults = defaultSidebarOrder.items[group.id] ?? []
        const missingDefaults = defaults.filter((itemId) => !assignedItemIds.has(itemId))
        if (missingDefaults.length === 0) return group
        missingDefaults.forEach((itemId) => assignedItemIds.add(itemId))
        return { ...group, itemIds: [...group.itemIds, ...missingDefaults] }
      })
    : uniqueGroups

  return {
    groups: mergedGroups,
    items: Object.fromEntries(mergedGroups.map((group) => [group.id, group.itemIds])),
    itemLabels: cleanItemLabels(order?.item_labels ?? order?.itemLabels),
  }
}

export function sidebarOrderPayload(order: SidebarOrder) {
  const normalized = normalizeSidebarOrder(order)
  const itemLabels = Object.fromEntries(
    Object.entries(normalized.itemLabels)
      .map(([itemId, label]) => [itemId, label.trim()])
      .filter(([itemId, label]) => navById.has(itemId) && Boolean(label))
  )
  return {
    version: 2,
    groups: normalized.groups.map((group) => ({
      id: group.id,
      label: group.label.trim() || 'Кнопка',
      item_ids: group.itemIds,
    })),
    items: normalized.items,
    item_labels: itemLabels,
  }
}

export function applySidebarItemLabels(items: SidebarNavItem[], order: SidebarOrder) {
  return items.map((item) => {
    const label = order.itemLabels[item.id]
    return label?.trim() ? { ...item, label } : item
  })
}

export function visibleItemsForButton(button: SidebarMenuButton, visibleItems: SidebarNavItem[]) {
  const visibleById = new Map(visibleItems.map((item) => [item.id, item]))
  return button.itemIds.map((itemId) => visibleById.get(itemId)).filter((item): item is SidebarNavItem => Boolean(item))
}

export function iconForMenuButton(button: SidebarMenuButton, items: SidebarNavItem[]) {
  const builtin = builtinGroupByKey.get(button.id)
  return builtin?.icon || items[0]?.icon || ListChecks
}

export function visibleSidebarNav(user: User | null) {
  return sidebarNav.filter((item) => {
    if (item.section === 'task' && !hasTaskWorkspaceAccess(user)) return false
    if (item.section === 'feedback' && !hasFeedbackAccess(user)) return false
    if (item.section === 'development' && !hasDevelopmentAccess(user)) return false
    if (item.section === 'personal') return true
    if (item.section === 'settings') return true
    if (item.section === 'admin' && user?.role !== 'admin') return false
    if (!item.roles) return true
    return user && item.roles.includes(user.role)
  })
}
