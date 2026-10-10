import { test as base, expect, type Route } from '@playwright/test'

export const reviewer = {
  id: '88888888-8888-4888-8888-888888888888', full_name: 'Проверка команды', email: 'worker8@example.invalid',
  role: 'admin', league: 'A', mpw: 10, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 95,
  is_active: true, needs_password_change: false, task_workspace_enabled: true, audit_enabled: true,
  audit_calendar_enabled: true, sidebar_menu_order: null,
}

export const operation = (id = 'operation-a', name = 'Операция А') => ({
  id, name, category: 'widget', complexity: 'M', base_cost_q: 2, description: '', min_league: 'C',
  sort_order: 1, is_active: true, created_at: '2026-10-03T08:00:00Z',
})
export const estimate = { total_q: 4, min_league: 'C', breakdown: [] }
export const longName = 'ОченьДлинноеНазваниеБезПробелов'.repeat(12)
export const member = {
  ...reviewer, effective_mpw: 10, earned: 5, percent: 50, karma: 0, in_progress_q: 2,
  is_at_risk: false, has_overdue: false, is_new_employee: false, onboarding_active: false,
  onboarding_until: null, absence_working_days: 0, absent_today: false, adjustment_reasons: [],
}
export const focus = [{
  user_id: reviewer.id, full_name: 'Сотрудник в фокусе', league: 'A', status: 'focused',
  focused_task_id: 'task-focus', focused_task_title: 'Работа над отчётом', focus_duration_minutes: 15,
}]
export const overdue = [{ id: 'overdue-task', task_number: 8, title: 'Просроченная работа', status: 'in_progress', assignee_id: reviewer.id }]
export const periodReport = (period: string) => ({
  period, generated_at: '2026-10-03T08:00:00Z', total_capacity: 10, total_earned: 5, utilization_percent: 50,
  team_members: [{ full_name: longName, league: 'A', percent: 50, tasks_completed: 1 }],
  top_performers: [], underperformers: [],
  tasks_overview: { total_created: 1, total_completed: 1, avg_time_hours: 2, by_category: { widget: 1 } },
  shop_activity: { total_purchases: 0, total_karma_spent: 0 },
  calibration_summary: { accurate_count: 1, overestimated_count: 0, underestimated_count: 0 },
})
export const calibration = (title = longName) => ({
  period: '2026-10', total_tasks_analyzed: 1, overall_accuracy_pct: 90, avg_deviation_pct: 10,
  total_tasks_with_breakdown: 1,
  task_calibrations: [{ task_id: 'calibration-task', title, task_type: 'widget', complexity: 'M', estimated_q: 2,
    actual_hours: 2, deviation_pct: 10, assignee_name: longName, estimator_name: longName, tags: ['Последняя колонка'] }],
  estimator_calibrations: [{ estimator_name: longName, tasks_count: 1, avg_deviation_pct: 10,
    accuracy_pct: 90, bias: 'точно', overestimates: 0, underestimates: 0 }],
  widget_popularity: [{ name: longName, tasks_count: 1, usage_percent: 100 }],
})

export async function reply(route: Route, json: unknown, status = 200) {
  await route.fulfill({ status, json })
  return true
}

interface ApiMock {
  handle: (route: Route, url: URL) => Promise<boolean>
}

export const test = base.extend<{ mockApi: ApiMock }>({
  mockApi: [async ({ page }, use) => {
    const unexpectedWrites: string[] = []
    const mock: ApiMock = { handle: async () => false }
    await page.addInitScript(() => {
      localStorage.setItem('dpms_token', 'synthetic-worker8-review')
      localStorage.setItem('dpms-theme', 'light')
    })
    await page.routeWebSocket('**', (socket) => { socket.onMessage(() => {}) })
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://localhost:55177') return route.abort()
      if (!url.pathname.startsWith('/api/')) {
        if (route.request().method() !== 'GET') return route.abort()
        return route.continue()
      }
      if (await mock.handle(route, url)) return
      const path = url.pathname
      if (path.startsWith('/api/usage/') || path.startsWith('/api/client-events')) return reply(route, {})
      if (route.request().method() !== 'GET') {
        unexpectedWrites.push(`${route.request().method()} ${path}`)
        return reply(route, { detail: 'Unexpected synthetic mutation' }, 405)
      }
      if (path === '/api/auth/me') return reply(route, reviewer)
      if (path === '/api/users') return reply(route, [reviewer])
      if (path === '/api/messages/summary') return reply(route, { direct_count: 0, important_count: 0, revision: 0 })
      if (path === '/api/web-push/config') return reply(route, { available: false })
      if (path === '/api/catalog') return reply(route, [operation(), operation('operation-b', 'Операция Б')])
      if (path === '/api/admin/period-history') return reply(route, [{ period: '2026-01' }, { period: '2026-02' }])
      if (path === '/api/dashboard/capacity') return reply(route, { load: 5, capacity: 10, utilization: 50, status: 'green' })
      if (path === '/api/dashboard/team-summary') return reply(route, { by_league: { A: [member] }, total_capacity: 10, total_load: 5, total_earned: 5, utilization: 50 })
      if (path === '/api/dashboard/burndown') return reply(route, { points: [], period: '2026-10', total_capacity: 10, working_days: 22 })
      if (path === '/api/dashboard/capacity-history') return reply(route, { weeks: [] })
      if (path === '/api/dashboard/focus-status') return reply(route, focus)
      if (path === '/api/tasks' && url.searchParams.has('is_overdue')) return reply(route, overdue)
      return reply(route, [])
    })
    await use(mock)
    expect(unexpectedWrites, 'All writes must be explicitly intercepted synthetic requests').toEqual([])
  }, { auto: true }],
})

export { expect }
