import { expect, test, type BrowserContext, type Page } from '@playwright/test'

const user = {
  id: '10000000-0000-4000-8000-000000000011',
  full_name: 'Проверка визуализации',
  email: 'layout-test@example.com',
  league: 'A', role: 'admin', mpw: 0, wip_limit: 5,
  wallet_main: 0, wallet_karma: 0, quality_score: 1,
  is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: true, feedback_enabled: true, audit_enabled: true,
  audit_calendar_enabled: true, competency_development_enabled: true,
  competency_constructor_enabled: true, sidebar_menu_order: null,
  created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
}
const preferenceKey = `dpms.contentLayout.v1:${user.id}`
type Preferences = Record<string, { fullWidth: boolean; marginPercent: number }>

async function installFixture(context: BrowserContext, options: {
  preferences?: Preferences; restricted?: boolean; denyStorage?: boolean; theme?: string
} = {}) {
  const actor = options.restricted
    ? { ...user, role: 'executor', task_workspace_enabled: false, feedback_enabled: false,
      audit_enabled: false, audit_calendar_enabled: false, competency_constructor_enabled: false }
    : user
  await context.addInitScript(({ preferences, denyStorage, theme, key }) => {
    localStorage.setItem('dpms_token', 'content-layout-synthetic-fixture')
    for (const [section, preference] of Object.entries(preferences ?? {})) {
      localStorage.setItem(`${key}:${section}`, JSON.stringify({ version: 1, sections: { [section]: preference } }))
    }
    if (theme) localStorage.setItem('dpms_theme', theme)
    if (denyStorage) {
      const original = Storage.prototype.setItem
      Storage.prototype.setItem = function (name: string, value: string) {
        if (name.startsWith('dpms.contentLayout.')) throw new DOMException('Fixture storage denial', 'QuotaExceededError')
        original.call(this, name, value)
      }
    }
  }, { ...options, key: preferenceKey })
  await context.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' })))
  })
  await context.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/me' ? actor
      : path === '/api/storage-quota/me' ? {
        quota_bytes: 52428800, used_bytes: 0, reserved_bytes: 0, available_bytes: 52428800,
        usage_percent: 0, warning_level: 'normal', warning_message: 'Место доступно.', pending_request: null,
      }
        : path === '/api/messages/summary' ? { direct_count: 0, important_count: 0, revision: 0 }
        : path === '/api/note-groups/backlinks' ? { notes: [], groups: [] }
          : route.request().method() === 'GET' ? [] : {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

const settingsPanel = (page: Page) => page.getByRole('region', { name: 'Визуализация', exact: true })
const row = (page: Page, name: string) => settingsPanel(page).getByRole('group', { name, exact: true })

async function openSettings(page: Page) {
  await page.goto('/settings')
  await expect(settingsPanel(page)).toBeVisible()
}

async function storedPreferences(page: Page) {
  return page.evaluate((key) => Object.assign({}, ...Object.keys(localStorage)
    .filter((name) => name.startsWith(`${key}:`))
    .map((name) => JSON.parse(localStorage.getItem(name)!).sections)), preferenceKey)
}

async function enableMargins(page: Page, name: string) {
  const checkbox = row(page, name).getByRole('checkbox')
  if (await checkbox.evaluate((el) => (el as HTMLInputElement).indeterminate)) await checkbox.check()
  await checkbox.uncheck()
}

async function frameGeometry(page: Page) {
  return page.locator('.app-content-frame').evaluate((frame) => {
    const main = frame.parentElement!
    const rect = frame.getBoundingClientRect()
    const mainRect = main.getBoundingClientRect()
    const style = getComputedStyle(main)
    const left = parseFloat(style.paddingLeft)
    const right = parseFloat(style.paddingRight)
    return {
      width: rect.width, height: rect.height,
      available: main.clientWidth - left - right,
      left: rect.left - mainRect.left - left,
      right: mainRect.right - right - rect.right,
      mainWidth: main.clientWidth, mainScrollWidth: main.scrollWidth,
    }
  })
}

async function noOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth, document: document.documentElement.scrollWidth,
    main: document.querySelector('main')!.clientWidth,
    mainScroll: document.querySelector('main')!.scrollWidth,
    overflow: Array.from(document.querySelectorAll('main *')).filter((el) => el.getBoundingClientRect().right > innerWidth)
      .map((el) => `${el.tagName}.${el.className}: ${Math.round(el.getBoundingClientRect().right)}`).slice(0, 10),
  }))
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1)
  expect(dimensions.mainScroll, JSON.stringify(dimensions.overflow)).toBeLessThanOrEqual(dimensions.main + 1)
}

test('controls persist, validate, restore defaults and keep legacy widths until edited', async ({ page, context }, testInfo) => {
  await installFixture(context)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await openSettings(page)
  await expect(settingsPanel(page).getByRole('group')).toHaveCount(26)
  const settings = row(page, 'Настройки')
  const checkbox = settings.getByRole('checkbox')
  const margin = settings.getByRole('spinbutton')
  await expect(checkbox).toHaveJSProperty('indeterminate', true)
  await expect(checkbox).not.toBeChecked()
  await expect(margin).toBeDisabled()
  await expect(margin).toHaveValue('10')
  await expect(page.locator('[data-content-section="settings"]')).toHaveAttribute('data-layout-custom', 'false')
  expect(await storedPreferences(page)).toEqual({})
  const originalWidth = await page.locator('.app-content-frame > div').evaluate((el) => el.getBoundingClientRect().width)

  await enableMargins(page, 'Настройки')
  await expect(checkbox).toHaveJSProperty('indeterminate', false)
  await expect(margin).toBeEnabled()
  expect((await storedPreferences(page)).settings).toEqual({ fullWidth: false, marginPercent: 10 })
  await margin.fill('12.5')
  await margin.press('Enter')
  expect((await storedPreferences(page)).settings.marginPercent).toBe(12.5)
  const geometry = await frameGeometry(page)
  const expectedWidth = testInfo.project.name.includes('mobile')
    ? geometry.available : Math.max(Math.min(geometry.available, 960), geometry.available * 0.75)
  expect(geometry.width).toBeCloseTo(expectedWidth, 0)
  expect(geometry.left).toBeCloseTo(geometry.right, 0)

  await margin.fill('50')
  await margin.press('Tab')
  await expect(margin).toHaveValue('40')
  await expect(settings.getByRole('status')).toContainText('40%')
  await margin.fill('')
  await margin.press('Enter')
  await expect(margin).toHaveAttribute('aria-invalid', 'true')
  await expect(settings.getByRole('alert')).toBeVisible()
  expect((await storedPreferences(page)).settings.marginPercent).toBe(40)
  await margin.fill('9.86')
  await margin.press('Enter')
  await expect(margin).toHaveValue('9.9')
  await page.reload()
  await expect(margin).toHaveValue('9.9')
  await expect(checkbox).not.toBeChecked()

  await checkbox.check()
  await expect(margin).toBeDisabled()
  const full = await frameGeometry(page)
  expect(full.width).toBeCloseTo(full.available, 0)
  await settings.getByRole('button', { name: 'Сбросить настройки раздела: Настройки', exact: true }).click()
  await expect(page.locator('[data-content-section="settings"]')).toHaveAttribute('data-layout-custom', 'false')
  await expect(settings.getByRole('button')).toBeDisabled()
  await expect(checkbox).toHaveJSProperty('indeterminate', true)
  const resetWidth = await page.locator('.app-content-frame > div').evaluate((el) => el.getBoundingClientRect().width)
  expect(resetWidth).toBeCloseTo(originalWidth, 0)
  expect(await storedPreferences(page)).toEqual({})
  expect(errors).toEqual([])
})

test('accessible sections only, with settings retained for development-only users', async ({ page, context }) => {
  await installFixture(context, { restricted: true })
  await openSettings(page)
  for (const label of ['Настройки', 'Развитие', 'Графы', 'Сообщения']) await expect(row(page, label)).toBeVisible()
  for (const label of ['Очередь', 'Аудит', 'Админ', 'Профиль', 'Интеграции', 'Аналитика использования']) {
    await expect(row(page, label)).toHaveCount(0)
  }
})

test('storage failures are explicitly memory-only and still affect the layout', async ({ page, context }) => {
  await installFixture(context, { denyStorage: true })
  await openSettings(page)
  const settings = row(page, 'Настройки')
  await enableMargins(page, 'Настройки')
  await expect(settings.getByRole('status')).toHaveText('Применено только в этой вкладке')
  await expect(page.locator('[data-content-section="settings"]')).toHaveAttribute('data-layout-custom', 'true')
  expect(await storedPreferences(page)).toEqual({})
})

test('cross-tab updates are immediate and drafts survive unrelated row changes', async ({ page, context }) => {
  await installFixture(context)
  await openSettings(page)
  const other = await context.newPage()
  await openSettings(other)
  await enableMargins(page, 'Графы')
  await expect(row(other, 'Графы').getByRole('checkbox')).not.toBeChecked()
  const draft = row(other, 'Графы').getByRole('spinbutton')
  await draft.fill('17')
  await enableMargins(page, 'Настройки')
  await expect(row(other, 'Настройки').getByRole('checkbox')).not.toBeChecked()
  await expect(draft).toHaveValue('17')
  await draft.press('Enter')
  await expect(row(page, 'Графы').getByRole('spinbutton')).toHaveValue('17')
  await other.close()
})

test('desktop and mobile layout stays usable in all themes', async ({ page, context }, testInfo) => {
  await installFixture(context, { preferences: { settings: { fullWidth: false, marginPercent: 40 } } })
  await openSettings(page)
  for (const [width, height] of [[1920, 1080], [1440, 900], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate((theme) => {
        document.documentElement.dataset.theme = theme
        document.documentElement.classList.toggle('dark', theme === 'dark')
      }, theme)
      const first = row(page, 'Личные задачи')
      await settingsPanel(page).evaluate((el) => {
        const main = el.closest('main')!
        document.scrollingElement!.scrollTop = 0
        main.scrollTop += el.getBoundingClientRect().top - main.getBoundingClientRect().top - 12
      })
      await noOverflow(page)
      const sizes = await first.evaluate((el) => Array.from(el.querySelectorAll('button, input[type="number"], label:has(input[type="checkbox"])')).map((control) => {
        const rect = control.getBoundingClientRect()
        return { width: rect.width, height: rect.height, left: rect.left, right: rect.right }
      }))
      for (const size of sizes) {
        expect(size.width).toBeGreaterThanOrEqual(44)
        expect(size.height).toBeGreaterThanOrEqual(44)
        expect(size.left).toBeGreaterThanOrEqual(0)
        expect(size.right).toBeLessThanOrEqual(width)
      }
      if ((width === 1920 && theme === 'light') || (width === 390 && theme !== 'light') || (width === 320 && theme === 'light')) {
        await page.screenshot({ path: testInfo.outputPath(`settings-${width}-${theme}.png`) })
      }
    }
  }
})

test('per-section margins apply across routes while graph canvas keeps its height', async ({ page, context }) => {
  await installFixture(context, { preferences: {
    settings: { fullWidth: false, marginPercent: 10 },
    'personal-tasks': { fullWidth: false, marginPercent: 12 },
    graphs: { fullWidth: false, marginPercent: 15 },
    queue: { fullWidth: false, marginPercent: 40 },
  } })
  await page.setViewportSize({ width: 1920, height: 1080 })
  for (const [path, id, margin, minWidth] of [
    ['/settings', 'settings', 10, 960], ['/personal-tasks', 'personal-tasks', 12, 960],
    ['/queue', 'queue', 40, 1440], ['/graphs', 'graphs', 15, 960],
  ] as const) {
    await page.goto(path)
    const frame = page.locator(`[data-content-section="${id}"]`)
    await expect(frame).toHaveAttribute('data-layout-custom', 'true')
    const geometry = await frameGeometry(page)
    expect(geometry.width).toBeCloseTo(Math.max(Math.min(geometry.available, minWidth), geometry.available * (1 - margin / 50)), 0)
    expect(geometry.left).toBeCloseTo(geometry.right, 0)
    if (id === 'graphs') {
      expect(geometry.height).toBeGreaterThan(700)
      await expect(page.locator('iframe')).toBeVisible()
      const iframe = await page.locator('iframe').boundingBox()
      expect(iframe!.height).toBeGreaterThan(650)
    }
  }
})
