import type { Page, Route } from '@playwright/test'
import type { CalendarReadiness, CalendarState, CalendarTimeline } from '../src/api/auditCalendar'
import { allSlots, dateRange, isWorkingDay, workSlots } from '../src/lib/auditCalendar'

export const ids = { a: '00000000-0000-4000-8000-000000000001', t: '00000000-0000-4000-8000-000000000002', s: '00000000-0000-4000-8000-000000000003', g: '00000000-0000-4000-8000-000000000004', p: '00000000-0000-4000-8000-000000000005' }
export function fixtureState(helper = true): CalendarState {
  return {
    scope: { id: '00000000-0000-4000-8000-000000000099', name: 'Синтетический тестовый контур', timezone: 'Europe/Moscow', baseline: '2026-09-01', version: 1, today: '2026-09-14', now: '2026-09-14T06:00:00Z', archived: false, history_complete: false },
    actor: { user_id: ids.a, can_manage: helper, can_archive: false },
    members: [
      { user_id: ids.a, full_name: 'Тестовый аудитор', code: 'ТА', role: 'auditor', can_manage: helper, active: true },
      { user_id: ids.t, full_name: 'Тестовый технический специалист с длинным именем', code: 'ТТ', role: 'tech', can_manage: false, active: true },
      { user_id: ids.s, full_name: 'Тестовый докладчик', code: 'ТД', role: 'speaker', can_manage: false, active: true },
    ],
    groups: [{ id: ids.g, code: 'G1', label: 'Тестовая группа', legacy: false, archived: false, versions: [{ id: '00000000-0000-4000-8000-000000000006', effective_from: '2026-09-01', auditor_id: ids.a, tech_id: ids.t }] }],
    plans: [{ id: ids.p, date: '2026-09-14', start: 600, duration: 90, group_id: ids.g, group_version_id: null, activity: 'И43', speaker_id: ids.s, status: 'planned', version: 1, origin: 'native', source_id: null, issues: [], warnings: [{ code: 'UNKNOWN_AVAILABILITY', message: 'Время участника не указано' }] }],
    facts: [], availability: [], availability_locks: [], change_requests: [], absences: [], notices: [],
    norms: [{ id: 'norm-team', group_id: null, effective_from: '2026-09-01', value: 6, reason: 'Синтетическая норма', recorded_at: '2026-09-01T06:00:00Z', recorded_by_id: ids.a }, { id: 'norm-group', group_id: ids.g, effective_from: '2026-09-01', value: 3, reason: 'Синтетическая норма группы', recorded_at: '2026-09-01T06:00:00Z', recorded_by_id: ids.a }],
    stats: { plan: 1, fact: 0, attention: 1, target: 30, backlog: 12, through: '2026-09-13', target_scope: 'team', groups: [{ group_id: ids.g, code: 'G1', target: 3, completed: 1, balance: 2, backlog: 2 }], fortnights: [{ from: '2026-09-01', to: '2026-09-13', target: 12, completed: 0, balance: 12, backlog: 12, cumulative_backlog: 12 }] },
  }
}
const harness = `<!doctype html><html lang="ru"><head><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Calendar isolated fixture</title></head><body><div id="root"></div><script type="module" src="/tests/audit-calendar.harness.ts"></script></body></html>`

export function fixtureReadiness(state: CalendarState, from = '2026-09-14', to = '2026-09-20', duration = 30): CalendarReadiness {
  const dates = dateRange(from, to).filter(isWorkingDay)
  return { scope_version: state.scope.version, from, to, duration, working_start: 600, working_end: 1080,
    employees: state.members.map(m => ({ ...m, days: dates.map(date => ({ date, status: 'missing', free_minutes: 0, locked: state.availability_locks.some(l => l.user_id === m.user_id && l.date === date && l.locked) })), filled_days: 0, total_days: dates.length })),
    groups: state.groups.map(g => ({ group_id: g.id, code: g.code, label: g.label, days: dates.map(date => ({ date, member_ids: [ids.a, ids.t], missing_user_ids: [ids.a, ids.t], status: 'missing', common_windows: [], free_windows: [], slots: [], plans: [], last_notified_at: null })) })),
  }
}

export function fixtureTimeline(state: CalendarState, date = state.scope.today): CalendarTimeline {
  return { version: state.scope.version, date, members: state.members, availability: state.availability.filter(a => a.date === date), absences: state.absences.filter(a => a.start_date <= date && a.end_date >= date), locks: state.availability_locks.filter(a => a.date === date), meetings: [] }
}

export async function mountCalendar(page: Page, options: { helper?: boolean; state?: CalendarState; view?: string; admin?: boolean; readiness?: (from: string, to: string, duration: number) => CalendarReadiness; command?: (route: Route, body: Record<string, unknown>) => Promise<void> } = {}) {
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
    if (path.endsWith('/availability-timeline')) return route.fulfill({ json: fixtureTimeline(state, new URL(request.url()).searchParams.get('date')!) })
    if (path.endsWith('/meeting-windows')) {
      const query = new URL(request.url()).searchParams
      return route.fulfill({ json: { version: state.scope.version, now: state.scope.now,
        period: { from: query.get('from'), to: query.get('to'), duration: Number(query.get('duration') || 30),
          group_id: query.get('group'), speaker_id: query.get('speaker_id'), full_day: query.get('full_day') === 'true' },
        cells: dateRange(query.get('from')!, query.get('to')!).flatMap(date =>
          (query.get('full_day') === 'true' ? allSlots : workSlots).map(start => ({ date, start, status: 'unavailable', confirmed: 0, uncertain: 0 }))) } })
    }
    if (path.endsWith('/meeting-window-options')) {
      const query = new URL(request.url()).searchParams
      return route.fulfill({ json: { version: state.scope.version, now: state.scope.now,
        query: { date: query.get('date'), start: Number(query.get('start')), duration: Number(query.get('duration') || 30),
          group_id: query.get('group'), speaker_id: query.get('speaker_id') }, options: [] } })
    }
    if (path.endsWith('/meeting-options')) {
      const query = new URL(request.url()).searchParams
      return route.fulfill({ json: { version: state.scope.version, date: query.get('date'), start: Number(query.get('start')),
        duration: Number(query.get('duration')), groups: state.groups.map(g => ({ id: g.id, code: g.code, label: g.label,
          eligible: !g.archived && !g.legacy, issues: [], warnings: [] })) } })
    }
    if (path.endsWith('/readiness')) {
      const params = new URL(request.url()).searchParams
      const args: [string, string, number] = [params.get('from')!, params.get('to')!, Number(params.get('duration'))]
      return route.fulfill({ json: options.readiness ? options.readiness(...args) : fixtureReadiness(state, ...args) })
    }
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
  await page.getByRole('heading', { name: 'Календарь аудита', exact: true, ...(!options.admin && { level: 1 }) }).waitFor()
  await page.getByRole('button', { name: options.admin ? 'Участник контура' : 'Обновить календарь', exact: true }).waitFor()
  return { state, commands }
}
