import { expect, test, type Page } from '@playwright/test'

const user = {
  id: '91111111-1111-4111-8111-111111111111', full_name: 'Тест навигации', email: 'usage@example.invalid',
  role: 'executor', league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0,
  quality_score: 100, is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: false, audit_enabled: false, audit_calendar_enabled: false,
  feedback_enabled: false, competency_development_enabled: false, competency_constructor_enabled: false,
  sidebar_menu_order: null, created_at: '2026-09-27T00:00:00Z', updated_at: '2026-09-27T00:00:00Z',
}

async function fixture(page: Page) {
  const control = { requests: [] as Array<{ event_id: string; section: string }>, status: 204 }
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-usage-only'))
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' })))
  })
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/usage/section-views') {
      control.requests.push(route.request().postDataJSON())
      await route.fulfill({ status: control.status, ...(control.status === 204 ? {} : { json: { detail: 'synthetic failure' } }) })
      return
    }
    let json: unknown = []
    if (pathname === '/api/auth/me') json = user
    if (pathname === '/api/messages/summary') json = { direct_count: 0, important_count: 0, revision: 0 }
    await route.fulfill({ status: 200, json })
  })
  return control
}

async function navigate(page: Page, pathname: string) {
  await page.evaluate((path) => {
    window.history.pushState(null, '', path)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, pathname)
}

test('navigation emits section only; reload, filters and foreground do not add visits', async ({ page }) => {
  const control = await fixture(page)
  await page.goto('/settings')
  await expect.poll(() => control.requests.length).toBe(1)
  expect(control.requests[0].section).toBe('settings')
  expect(Object.keys(control.requests[0]).sort()).toEqual(['event_id', 'section'])
  await navigate(page, '/settings?private=DO_NOT_COLLECT#private-anchor')
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Настройки', exact: true })).toBeVisible()
  expect(control.requests).toHaveLength(1)
  await navigate(page, '/graphs?graph=PRIVATE_GRAPH_ID')
  await expect.poll(() => control.requests.length).toBe(2)
  expect(control.requests[1].section).toBe('graphs')
  await navigate(page, '/settings')
  await expect.poll(() => control.requests.length).toBe(3)
  expect(new Set(control.requests.map((item) => item.event_id)).size).toBe(3)
  expect(JSON.stringify(control.requests)).not.toContain('PRIVATE')
})

test('background opening is deferred; foreground retry reuses id and failure cannot log out', async ({ page }) => {
  const control = await fixture(page)
  control.status = 401
  await page.addInitScript(() => Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }))
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Настройки', exact: true })).toBeVisible()
  expect(control.requests).toHaveLength(0)
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect.poll(() => control.requests.length).toBe(1)
  await expect(page).toHaveURL(/\/settings$/)
  control.status = 204
  await expect(async () => {
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(control.requests.length).toBe(2)
  }).toPass()
  expect(control.requests[1].event_id).toBe(control.requests[0].event_id)
  await page.reload()
  await expect(page).toHaveURL(/\/settings$/)
})

test('denied admin route emits no admin usage and cannot show the report', async ({ page }) => {
  const control = await fixture(page)
  await page.goto('/admin/usage')
  await expect(page).toHaveURL(/\/messages$/)
  expect(control.requests.every((request) => request.section === 'messages')).toBe(true)
  await expect(page.getByRole('heading', { name: 'Использование системы' })).toHaveCount(0)
})
