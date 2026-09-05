import { readFile } from 'node:fs/promises'
import { expect, test, type Page, type Route } from '@playwright/test'

const user = {
  id: '11111111-1111-4111-8111-111111111111',
  full_name: 'Проверка ID 64A',
  email: 'id64a@example.com',
  league: 'A',
  role: 'executor',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 100,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: true,
  can_link_queue_tasks_to_projects: false,
  feedback_enabled: false,
  audit_enabled: false,
  competency_development_enabled: false,
  competency_constructor_enabled: false,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: {
    version: 7,
    groups: [{ id: 'tasks', label: 'Работа', item_ids: ['personal-tasks', 'quick-notes'] }],
    items: { tasks: ['personal-tasks', 'quick-notes'] },
    item_labels: {},
  },
  needs_password_change: false,
  created_at: '2026-09-03T00:00:00Z',
  updated_at: '2026-09-03T00:00:00Z',
}

const knowledgeArticles = [
  {
    id: '22222222-2222-4222-8222-222222222222',
    slug: 'start-id64a',
    title: 'Работа с системой',
    summary: 'Краткая проверка изменяемой области чтения.',
    section: 'start',
    body: '## Первый раздел\n\nТекст статьи для проверки области чтения.',
    status: 'published',
    sort_order: 1,
    created_by_id: user.id,
    updated_by_id: user.id,
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  },
]

async function installApiMock(page: Page, mockUser = user) {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'id64a-token'))
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (path === '/api/auth/me') return respond(mockUser)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/messages/threads') return respond([])
    if (path === '/api/messages/attention') return respond([])
    if (path === '/api/users') return respond([])
    if (path === '/api/knowledge') return respond(knowledgeArticles)
    if (path === '/api/storage-quota/me') {
      return respond({
        quota_bytes: 50 * 1024 * 1024,
        used_bytes: 0,
        reserved_bytes: 0,
        available_bytes: 50 * 1024 * 1024,
        usage_percent: 0,
        warning_level: 'normal',
        warning_message: 'Свободного места достаточно.',
        pending_request: null,
      })
    }
    if (path === '/api/auth/me/sidebar-menu/import-preview' && request.method() === 'POST') {
      return respond({
        sidebar_menu_order: {
          version: 8,
          groups: [{ id: 'custom-work', label: 'Моя работа', item_ids: ['quick-notes', 'messages'] }],
          items: { 'custom-work': ['quick-notes', 'messages'] },
          item_labels: { 'quick-notes': 'Мои записи' },
        },
        referenced_item_count: 3,
        imported_count: 1,
        skipped_inaccessible_count: 1,
        skipped_unknown_count: 1,
        skipped_duplicate_count: 0,
        required_added_count: 1,
      })
    }
    if (path === '/api/auth/me/sidebar-menu' && request.method() === 'PATCH') {
      const payload = request.postDataJSON() as { sidebar_menu_order: unknown }
      return respond({ ...mockUser, sidebar_menu_order: payload.sidebar_menu_order })
    }
    return respond(request.method() === 'GET' ? [] : {})
  })
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1)
}

for (const role of ['executor', 'teamlead', 'admin']) {
  test(`authenticated ${role} root opens Messages for every viewport`, async ({ page }) => {
    await installApiMock(page, {
      ...user,
      role,
      task_workspace_enabled: role !== 'executor',
    })
    await page.goto('/')
    await expect(page).toHaveURL(/\/messages$/)
    await expect(page.getByRole('heading', { name: 'Сообщения' })).toBeVisible()
    await assertNoHorizontalOverflow(page)
  })
}

test('menu settings export a portable v8 file and import a server-filtered draft', async ({ page }, testInfo) => {
  test.skip((testInfo.project.use.viewport?.width ?? 0) < 1000, 'Desktop settings evidence')
  await installApiMock(page)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Экспорт' }).click()
  const download = await downloadPromise
  const downloadPath = await download.path()
  expect(downloadPath).not.toBeNull()
  const exported = JSON.parse(await readFile(downloadPath as string, 'utf8')) as {
    format: string
    version: number
    layout: { version: number; groups: Array<{ item_ids: string[] }> }
  }
  expect(exported.format).toBe('dpms-sidebar-menu')
  expect(exported.version).toBe(1)
  expect(exported.layout.version).toBe(8)
  expect(exported.layout.groups.flatMap((group) => group.item_ids)).toContain('messages')

  await page.getByLabel('Выбрать файл настроек меню').setInputFiles({
    name: 'menu.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({
      format: 'dpms-sidebar-menu',
      version: 1,
      layout: {
        version: 8,
        groups: [{ id: 'custom-work', label: 'Моя работа', item_ids: ['quick-notes', 'audit', 'unknown'] }],
      },
    })),
  })

  await expect(page.getByText('Загружено разделов: 1')).toBeVisible()
  await expect(page.getByText('Без доступа: 1')).toBeVisible()
  await expect(page.getByText('Неизвестных: 1')).toBeVisible()
  await expect(page.locator('input[value="Моя работа"]')).toBeVisible()
  await expect(page.getByText('Мои записи', { exact: true }).first()).toBeVisible()
  await expect(page.getByLabel('Системный раздел')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Сохранить' })).toBeEnabled()

  const saveRequestPromise = page.waitForRequest((request) =>
    new URL(request.url()).pathname === '/api/auth/me/sidebar-menu' && request.method() === 'PATCH'
  )
  await page.getByRole('button', { name: 'Сохранить' }).click()
  const saveRequest = await saveRequestPromise
  const savedLayout = saveRequest.postDataJSON() as {
    sidebar_menu_order: { version: number; groups: Array<{ item_ids: string[] }> }
  }
  expect(savedLayout.sidebar_menu_order.version).toBe(8)
  expect(savedLayout.sidebar_menu_order.groups.flatMap((group) => group.item_ids)).toEqual([
    'quick-notes',
    'messages',
  ])
  await expect(page.getByText('Меню сохранено')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('menu-import-preview.png'), fullPage: true })
})

test('menu import remains usable without horizontal overflow on mobile', async ({ page }, testInfo) => {
  test.skip((testInfo.project.use.viewport?.width ?? 0) >= 1000, 'Mobile settings evidence')
  await installApiMock(page)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()

  await page.getByLabel('Выбрать файл настроек меню').setInputFiles({
    name: 'menu-mobile.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({
      format: 'dpms-sidebar-menu',
      version: 1,
      layout: {
        version: 8,
        groups: [{ id: 'mobile', label: 'Мобильное меню', item_ids: ['quick-notes', 'audit'] }],
      },
    })),
  })

  await expect(page.getByText('Загружено разделов: 1', { exact: true })).toBeVisible()
  await expect(page.locator('input[value="Моя работа"]')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Сохранить' })).toBeEnabled()
  await assertNoHorizontalOverflow(page)
})

test('Knowledge Base splitter resizes on desktop and stays stacked on mobile', async ({ page }, testInfo) => {
  await installApiMock(page)
  await page.goto('/knowledge')
  await expect(page.getByRole('heading', { name: 'База знаний' })).toBeVisible()
  const splitter = page.getByRole('separator', { name: 'Изменить ширину списка статей' })
  const isDesktop = (testInfo.project.use.viewport?.width ?? 0) >= 1280

  if (!isDesktop) {
    await expect(splitter).toBeHidden()
    await assertNoHorizontalOverflow(page)
    await page.screenshot({ path: testInfo.outputPath('knowledge-mobile.png'), fullPage: true })
    return
  }

  await expect(splitter).toBeVisible()
  await expect(splitter).toHaveAttribute('aria-valuenow', '360')
  await splitter.press('ArrowRight')
  await expect(splitter).toHaveAttribute('aria-valuenow', '384')

  const box = await splitter.boundingBox()
  expect(box).not.toBeNull()
  await page.mouse.move((box?.x ?? 0) + (box?.width ?? 0) / 2, (box?.y ?? 0) + 60)
  await page.mouse.down()
  await page.mouse.move((box?.x ?? 0) + 72, (box?.y ?? 0) + 60)
  await page.mouse.up()
  await expect.poll(async () => Number(await splitter.getAttribute('aria-valuenow'))).toBeGreaterThan(384)

  const persisted = await splitter.getAttribute('aria-valuenow')
  await page.reload()
  await expect(page.getByRole('separator', { name: 'Изменить ширину списка статей' })).toHaveAttribute(
    'aria-valuenow',
    persisted as string
  )
  await page.screenshot({ path: testInfo.outputPath('knowledge-desktop.png'), fullPage: true })
})
