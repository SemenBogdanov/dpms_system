import { expect, type Page, type Route } from '@playwright/test'
import type { CalendarCommand, CalendarImport } from '../src/api/auditCalendar'
import { fixtureReadiness, fixtureState, fixtureTimeline, ids } from './audit-calendar.fixtures'

export { ids }
export const origin = 'http://localhost:55177'
export type Command = CalendarCommand & { expected_version: number; request_id: string }
export function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}
export function batch(version = 1): CalendarImport {
  return { id: `synthetic-batch-${version}`, version, status: 'preview', source_sha256: 'a'.repeat(64), summary: { rows: 1 }, issues: [], rows: [], mapping_required: [] }
}

export async function calendarFixture(page: Page) {
  const state = fixtureState()
  const control = {
    state, commands: [] as Command[], writes: [] as string[], errors: [] as string[], stateReads: 0,
    handlers: new Map<string, (route: Route) => Promise<void>>(),
  }
  const user = {
    id: ids.a, full_name: 'Календарный тест', email: 'calendar@example.invalid', role: 'admin',
    league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
    is_active: true, is_new_employee: false, needs_password_change: false,
    task_workspace_enabled: false, can_link_queue_tasks_to_projects: false,
    feedback_enabled: false, audit_enabled: false, audit_calendar_enabled: true,
    competency_development_enabled: false, competency_constructor_enabled: false,
    plan_started_at: null, onboarding_started_at: null, onboarding_until: null, sidebar_menu_order: null,
    created_at: state.scope.now, updated_at: state.scope.now,
  }
  page.on('pageerror', error => control.errors.push(error.message))
  await page.clock.setFixedTime(new Date(state.scope.now))
  await page.addInitScript(() => {
    // Only a synthetic marker in a fresh disposable Playwright context.
    localStorage.setItem('dpms_token', 'review-calendar-synthetic-only')
    localStorage.setItem('dpms-theme', 'light')
  })
  await page.routeWebSocket('**/*', socket => { socket.onMessage(() => undefined) })
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== origin) return route.abort()
    if (!url.pathname.startsWith('/api/')) return request.method() === 'GET' ? route.continue() : route.abort()
    if (request.method() !== 'GET') control.writes.push(url.pathname)
    if (url.pathname.endsWith('/commands')) control.commands.push(request.postDataJSON() as Command)
    if (url.pathname.endsWith('/state')) control.stateReads++
    const handler = control.handlers.get(url.pathname)
    if (handler) return handler(route)
    let json: unknown = []
    if (url.pathname === '/api/auth/me') json = user
    else if (url.pathname === '/api/web-push/config') json = { available: false }
    else if (url.pathname.startsWith('/api/usage/') || url.pathname.startsWith('/api/client-events')) json = {}
    else if (url.pathname === '/api/messages/summary') json = { direct_count: 0, important_count: 0, revision: 0 }
    else if (url.pathname === '/api/users/admin') json = [user]
    else if (url.pathname === '/api/audit-calendar/state') json = state
    else if (url.pathname === '/api/audit-calendar/imports/preview') json = batch(state.scope.version)
    else if (url.pathname === '/api/audit-calendar/availability-timeline') json = fixtureTimeline(state, url.searchParams.get('date')!)
    else if (url.pathname === '/api/audit-calendar/readiness') json = fixtureReadiness(state, url.searchParams.get('from')!, url.searchParams.get('to')!, Number(url.searchParams.get('duration')))
    else if (url.pathname === '/api/audit-calendar/meeting-options') json = {
      version: state.scope.version, date: url.searchParams.get('date'), start: Number(url.searchParams.get('start')), duration: Number(url.searchParams.get('duration')),
      groups: state.groups.map(g => ({ id: g.id, code: g.code, label: g.label, eligible: !g.archived && !g.legacy, issues: [], warnings: g.archived ? [{ code: 'ARCHIVED', message: 'Группа архивирована' }] : [] })),
    }
    else if (url.pathname.startsWith('/api/audit-calendar/') && request.method() !== 'GET') {
      return route.fulfill({ status: 409, json: { detail: 'Синтетический конфликт версии' } })
    }
    // Unknown shell API calls, including analytics, are fulfilled here, never forwarded.
    return route.fulfill({ json })
  })
  return control
}

export async function openCalendar(page: Page, view = 'imports', query = '') {
  await page.goto(`/audit-calendar?from=2026-09-14&to=2026-09-20&view=${view}${query}`)
  await expect(page.getByRole('heading', { name: 'Календарь аудита', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Обновить календарь', exact: true })).toBeEnabled()
}

export const sourceFile = (name = 'source.json', content = '{"version":5}') => ({ name, mimeType: 'application/json', buffer: Buffer.from(content) })

export async function editMeeting(page: Page) {
  const trigger = page.getByRole('region', { name: 'Датасет', exact: true }).getByRole('button', { name: /G1 · И43/ })
  // Touch activation need not focus a button in WebKit. Establish a focus owner.
  await trigger.focus()
  await trigger.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Редакция плана', exact: true })
  await expect(dialog.getByRole('combobox', { name: 'Группа', exact: true })).toBeEnabled()
  return dialog
}
