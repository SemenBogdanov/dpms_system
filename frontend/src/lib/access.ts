import type { User } from '@/api/types'

export function hasTaskWorkspaceAccess(user: User | null | undefined) {
  return user?.role === 'admin' || Boolean(user?.task_workspace_enabled)
}

export function hasDevelopmentAccess(user: User | null | undefined) {
  return user?.role === 'admin' || Boolean(user?.competency_development_enabled) || Boolean(user?.competency_constructor_enabled)
}

export function hasFeedbackAccess(user: User | null | undefined) {
  return Boolean(user?.feedback_enabled)
}

export function firstAvailablePath(user: User | null | undefined) {
  if (!user) return '/login'
  if (hasTaskWorkspaceAccess(user)) return user.role === 'executor' ? '/my-tasks' : '/'
  if (hasDevelopmentAccess(user)) return '/competencies'
  if (hasFeedbackAccess(user)) return '/feedback'
  if (user.role === 'admin') return '/admin/users'
  return '/no-access'
}
