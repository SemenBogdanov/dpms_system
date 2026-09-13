import type { Page, Route } from '@playwright/test'
import type { CalendarState } from '../src/api/auditCalendar'

export const ids = { a: '00000000-0000-4000-8000-000000000001', t: '00000000-0000-4000-8000-000000000002', s: '00000000-0000-4000-8000-000000000003', g: '00000000-0000-4000-8000-000000000004', p: '00000000-0000-4000-8000-000000000005' }
export function fixtureState(helper = true): CalendarState {
  return {
    scope: { id: '00000000-0000-4000-8000-000000000099', name: 'Синтетический тестовый контур', timezone: 'Europe/Moscow', baseline: '2026-09-01', version: 1, today: '2026-09-14', now: '2026-09-14T06:00:00Z', archived: false, history_complete: false },
    actor: { user_id: ids.a, can_manage: helper },
    members: [
      { user_id: ids.a, full_name: 'Тестовый аудитор', code: 'ТА', role: 'auditor', can_manage: helper, active: true },
      { user_id: ids.t, full_name: 'Тестовый технический специалист с длинным именем', code: 'ТТ', role: 'tech', can_manage: false, active: true },
      { user_id: ids.s, full_name: 'Тестовый докладчик', code: 'ТД', role: 'speaker', can_manage: false, active: true },
    ],
    groups: [{ id: ids.g, code: 'G1', label: 'Тестовая группа', legacy: false, archived: false, versions: [{ id: '00000000-0000-4000-8000-000000000006', effective_from: '2026-09-01', auditor_id: ids.a, tech_id: ids.t }] }],
    plans: [{ id: ids.p, date: '2026-09-14', start: 600, duration: 90, group_id: ids.g, group_version_id: null, activity: 'И43', speaker_id: ids.s, status: 'planned', version: 1, origin: 'native', source_id: null, issues: [], warnings: [{ code: 'UNKNOWN_AVAILABILITY', message: 'Время участника не указано' }] }],
    facts: [], availability: [], absences: [], notices: [],
    norms: [{ id: 'norm-team', group_id: null, effective_from: '2026-09-01', value: 6, reason: 'Синтетическая норма', recorded_at: '2026-09-01T06:00:00Z', recorded_by_id: ids.a }, { id: 'norm-group', group_id: ids.g, effective_from: '2026-09-01', value: 3, reason: 'Синтетическая норма группы', recorded_at: '2026-09-01T06:00:00Z', recorded_by_id: ids.a }],
    stats: { plan: 1, fact: 0, attention: 1, target: 30, backlog: 12, through: '2026-09-13', target_scope: 'team', groups: [{ group_id: ids.g, code: 'G1', target: 3, completed: 1, balance: 2, backlog: 2 }], fortnights: [{ from: '2026-09-01', to: '2026-09-13', target: 12, completed: 0, balance: 12, backlog: 12, cumulative_backlog: 12 }] },
  }
}
const harness = `<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Calendar isolated fixture</title></head><body><div id="root"></div><script type="module" src="/tests/audit-calendar.harness.ts"></script></body></html>`

export async function mountCalendar(page: Page, options: { helper?: boolean; state?: CalendarState; view?: string; admin?: boolean; command?: (route: Route, body: Record<string, unknown>) => Promise<void> } = {}) {
  await page.routeWebSocket('ws://127.0.0.1:4198/**', () => undefined)
  page.on('pageerror', error => console.error('Calendar fixture browser error:', error.message))
  page.on('console', message => { if (message.type() === 'error') console.error('Calendar fixture console:', message.text()) })
  const state = options.state || fixtureState(options.helper)
  const commands: Record<string, unknown>[] = []
  await page.clock.setFixedTime(new Date('2026-09-14T06:00:00Z'))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (!path.startsWith('/api/')) return route.fallback()
    if (path.endsWith('/state')) return route.fulfill({ json: state })
    if (path.endsWith('/admin')) return route.fulfill({ json: { scope: state.scope, members: state.members, users: state.members.map(m => ({ id: m.user_id, full_name: m.full_name, email: 'synthetic@example.invalid', audit_calendar_enabled: true, is_active: true })) } })
    if (path.endsWith('/history')) return route.fulfill({ json: { items: [{ id: 'event-test', action: 'plan.save', actor_name: 'Тестовый аудитор', occurred_at: state.scope.now, detail: { reason: 'Тест' } }], total: 1 } })
    if (path.endsWith('/imports') && request.method() === 'GET') return route.fulfill({ json: [] })
    if (request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>; commands.push(body)
      if (options.command) return options.command(route, body)
      state.scope.version++
      return route.fulfill({ json: { version: state.scope.version, result: {} } })
    }
    return route.fulfill({ status: 403, json: { detail: 'Only synthetic calendar API is available' } })
  })
  await page.route('**/*', route => route.request().isNavigationRequest() ? route.fulfill({ contentType: 'text/html', body: harness }) : route.fallback())
  await page.goto(options.admin ? '/calendar-admin' : `/audit-calendar?from=2026-09-14&to=2026-09-20&view=${options.view || 'graph'}`)
  await page.getByRole('heading', { name: options.admin ? 'Календарь аудита' : 'Сетевой план-график', exact: true }).waitFor()
  await page.getByRole('button', { name: options.admin ? 'Участник контура' : 'Обновить календарь', exact: true }).waitFor()
  return { state, commands }
}
