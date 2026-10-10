import { expect, type Locator, type Page, type Route } from '@playwright/test'

export const stamp = '2026-10-03T08:00:00Z'
export const admin = {
  id: '11111111-1111-4111-8111-111111111109', full_name: 'Администратор проверки', email: 'admin@example.test',
  role: 'admin', league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, needs_password_change: false, task_workspace_enabled: true,
  can_link_queue_tasks_to_projects: true, feedback_enabled: true, audit_enabled: true, audit_calendar_enabled: true,
  competency_development_enabled: true, competency_constructor_enabled: true, sidebar_menu_order: null,
  created_at: stamp, updated_at: stamp,
}
export const staff = ['A', 'B'].map((suffix, index) => ({
  ...admin, id: `22222222-2222-4222-8222-22222222220${index}`, role: 'executor',
  full_name: `Сотрудник ${suffix}`, email: `${suffix.toLowerCase()}@example.test`,
}))
export const providers = ['A', 'B'].map((suffix, index) => ({
  id: `profile-${suffix.toLowerCase()}`, display_name: `Профиль ${suffix}`, model_name: `model-${suffix.toLowerCase()}`,
  base_url: 'https://provider.example.test/v1', provider_kind: 'openai_compatible', enabled: true, configured: true,
  api_key_configured: true, config_version: index + 3, last_test_status: null, last_tested_at: null,
  last_verified_config_version: null, ready_for_use: false, last_error_code: null,
  allowed_origins_configured: true, encryption_key_configured: true, updated_at: stamp,
}))
export const quotaRequests = staff.map((user, index) => ({
  id: `quota-${index}`, user_id: user.id, user_name: user.full_name, user_email: user.email,
  status: 'pending', current_limit_bytes: 1048576, requested_limit_bytes: 3145728,
  used_bytes: 0, reserved_bytes: 0, reason: 'Причина'.repeat(120), created_at: stamp,
}))
export const period = {
  period: '2026-08', status: 'closed', mode: 'manual', closed_at: stamp, cancelled_at: null,
  users_count: 2, total_main_reset: 10, total_karma_burned: 0,
}
export const periodResult = { ...period, users_processed: 2 }

export function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

export function historyFor(userId: string, name: string) {
  return { user_id: userId, total: 1, items: [{
    id: `event-${userId}`, action: 'updated', actor_name: 'Администратор проверки', occurred_at: stamp,
    changes: [{ field: 'full_name', before: 'Прежнее имя', after: name }],
  }] }
}

export async function adminFixture(page: Page, handler: (route: Route, url: URL) => Promise<boolean> = async () => false) {
  const writes: Array<{ path: string; method: string }> = []
  const unexpected: string[] = []
  await page.routeWebSocket('**/*', () => {})
  await page.addInitScript(() => {
    const storage = (initial: Array<[string, string]>) => {
      const values = new Map(initial)
      return {
        getItem: (name: string) => values.get(name) ?? null,
        setItem: (name: string, value: string) => { values.set(name, String(value)) },
        removeItem: (name: string) => { values.delete(name) }, clear: () => values.clear(),
        key: (index: number) => [...values.keys()][index] ?? null, get length() { return values.size },
      }
    }
    Object.defineProperty(window, 'localStorage', { configurable: true, value: storage([
      ['dpms_token', 'synthetic-worker-nine'], ['dpms-theme', 'light'], ['dpms.sidebarPinned', 'true'],
    ]) })
    Object.defineProperty(window, 'sessionStorage', { configurable: true, value: storage([]) })
  })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== 'http://localhost:55177') return route.abort()
    if (!url.pathname.startsWith('/api/')) {
      return ['GET', 'HEAD'].includes(request.method()) ? route.continue() : route.abort()
    }
    if (request.method() !== 'GET') writes.push({ path: url.pathname, method: request.method() })
    if (await handler(route, url)) return
    const path = url.pathname
    if (path.startsWith('/api/usage/') || path.startsWith('/api/client-events')) return route.fulfill({ json: {} })
    if (request.method() !== 'GET') {
      unexpected.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 405, json: { detail: 'Unexpected synthetic mutation' } })
    }
    if (path === '/api/auth/me') return route.fulfill({ json: admin })
    if (path === '/api/users' || path === '/api/users/admin') return route.fulfill({ json: [admin, ...staff] })
    if (path === '/api/messages/summary') return route.fulfill({ json: { direct_count: 0, important_count: 0, revision: 0 } })
    if (path === '/api/web-push/config') return route.fulfill({ json: { available: false } })
    if (path === '/api/admin/period-history') return route.fulfill({ json: [period] })
    if (path === '/api/storage-quota/admin/requests') return route.fulfill({ json: quotaRequests })
    if (path === '/api/admin/server-boots') return route.fulfill({ json: {
      period_days: 0, total: 0, all_time_count: 0, last_7_days_count: 0, first_imported_at: stamp, items: [],
      import_status: { state: 'ok', last_attempt_at: stamp, last_success_at: stamp, invalid_files: 0, conflicting_files: 0, checked_files: 0, error_code: null },
    } })
    if (path === '/api/admin/integrations/ai/providers') return route.fulfill({ json: {
      items: providers, allowed_origins_configured: true, encryption_key_configured: true,
    } })
    if (path === '/api/admin/integrations/ai/skills') return route.fulfill({ json: { items: [] } })
    if (path === '/api/audit/synology/connections') return route.fulfill({ json: {
      items: [], allowed_origins_configured: true, encryption_key_configured: true,
    } })
    if (path.endsWith('/admin-history')) return route.fulfill({ json: historyFor(path.split('/')[3], 'Новое имя') })
    return route.fulfill({ json: [] })
  })
  return { writes, unexpected }
}

export async function aiForm(page: Page) {
  await page.goto('/admin/integrations')
  await page.getByRole('tab', { name: /ИИ/ }).click()
  const form = page.locator('form').filter({ has: page.getByLabel('Название', { exact: true }) })
  await expect(form.getByLabel('Название', { exact: true })).toHaveValue('Профиль A')
  return form
}

export async function doubleActivate(button: Locator) {
  await button.evaluate((element: HTMLButtonElement) => { element.click(); element.click() })
}

export async function releaseResponse(page: Page, path: string, release: () => void) {
  const response = page.waitForResponse((result) => new URL(result.url()).pathname === path)
  release()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

export async function assertModalGeometry(dialog: Locator) {
  const geometry = await dialog.evaluate((element) => {
    const panel = element.getBoundingClientRect()
    const header = element.querySelector('header')!.getBoundingClientRect()
    const footer = element.querySelector('footer')!.getBoundingClientRect()
    return {
      top: panel.top, bottom: panel.bottom, left: panel.left, right: panel.right,
      headerTop: header.top, footerBottom: footer.bottom,
      height: innerHeight, width: innerWidth,
      focused: element.contains(document.activeElement),
    }
  })
  expect(geometry.top).toBeGreaterThanOrEqual(0)
  expect(geometry.headerTop).toBeGreaterThanOrEqual(geometry.top)
  expect(geometry.footerBottom).toBeLessThanOrEqual(geometry.height)
  expect(geometry.bottom).toBeLessThanOrEqual(geometry.height)
  expect(geometry.left).toBeGreaterThanOrEqual(0)
  expect(geometry.right).toBeLessThanOrEqual(geometry.width)
}
