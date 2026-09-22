import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

const userId = '11111111-1111-4111-8111-111111111111'
const testUser = {
  id: userId,
  full_name: 'Проверка графов',
  email: 'graphs-test@example.com',
  league: 'A',
  role: 'executor',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 100,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false,
  feedback_enabled: false,
  audit_enabled: false,
  audit_calendar_enabled: false,
  competency_development_enabled: false,
  competency_constructor_enabled: false,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
}

async function installApiMock(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('dpms_token', 'graphs-smoke-token')
  })
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage((message) => {
      try {
        const event = JSON.parse(String(message)) as { type?: string }
        socket.send(JSON.stringify({ type: event.type === 'ping' ? 'pong' : 'ready' }))
      } catch {
        socket.close({ code: 1003, reason: 'Malformed synthetic message' })
      }
    })
  })
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(testUser) })
      return
    }
    if (pathname === '/api/messages/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ direct_count: 0, important_count: 0, revision: 0 }),
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
}

test('Graphs open as a DPMS section without losing the standalone workspace', async ({ page }, testInfo) => {
  const runtimeErrors: string[] = []
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })

  await installApiMock(page)
  await page.goto('/graphs')

  const frameElement = page.getByTitle('Рабочее пространство графов')
  await expect(frameElement).toBeVisible()
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await expect(frame.locator('.app')).toBeVisible()
  await expect(frame.locator('.graph-node')).toHaveCount(4)
  await expect(page.getByRole('status')).toBeHidden()
  await expect(page.locator('header.app-header')).toBeHidden()

  const viewport = page.viewportSize()
  const workspaceBox = await frameElement.boundingBox()
  expect(workspaceBox).not.toBeNull()
  expect(viewport).not.toBeNull()
  const reservedMobileNavigation = viewport!.width < 1024 ? 70 : 2
  expect(workspaceBox!.height).toBeGreaterThanOrEqual(viewport!.height - reservedMobileNavigation)
  expect(workspaceBox!.height).toBeLessThanOrEqual(viewport!.height + 1)

  if (viewport && viewport.width < 1024) {
    const menuButton = page.getByRole('button', { name: 'Меню' })
    await expect(menuButton).toBeVisible()
    const menuBox = await menuButton.boundingBox()
    const brandBox = await frame.locator('.brand').boundingBox()
    expect(menuBox).not.toBeNull()
    expect(brandBox).not.toBeNull()
    expect(brandBox!.x).toBeGreaterThanOrEqual(menuBox!.x + menuBox!.width + 4)
    await menuButton.click()
  }

  await expect(page.getByRole('link', { name: 'Графы', exact: true })).toBeVisible()

  if (viewport && viewport.width < 1024) {
    const menuButton = page.getByRole('button', { name: 'Меню' })
    await menuButton.click()
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false')
    await expect.poll(async () => {
      const box = await page.locator('.app-sidebar').boundingBox()
      return box ? box.x + box.width : 0
    }).toBeLessThanOrEqual(1)
  }

  await expect.poll(async () => page.evaluate((id) => (
    window.localStorage.getItem(`dpms-graphs-workspace-v2:${id}`) !== null
  ), userId)).toBe(true)

  const frameSource = await frameElement.getAttribute('src')
  expect(frameSource).toContain(`owner=${encodeURIComponent(userId)}`)

  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1)

  mkdirSync('test-results/graphs', { recursive: true })
  await page.screenshot({
    path: `test-results/graphs/${testInfo.project.name}.png`,
    fullPage: false,
  })
  expect(runtimeErrors).toEqual([])
})
