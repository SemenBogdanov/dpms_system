import { expect, test, type Page, type TestInfo } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

type Theme = 'light' | 'dark' | 'rose'
type ImportState = 'waiting' | 'ok' | 'degraded' | 'stale'
const now = '2026-09-25T08:00:00Z'
const admin = {
  id: '11111111-1111-4111-8111-111111111111',
  full_name: 'Тестовый администратор', email: 'admin@example.invalid', role: 'admin',
  league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: false, can_link_queue_tasks_to_projects: false,
  feedback_enabled: false, audit_enabled: false, audit_calendar_enabled: false,
  competency_development_enabled: false, competency_constructor_enabled: false,
  plan_started_at: null, onboarding_started_at: null, onboarding_until: null,
  sidebar_menu_order: null, created_at: now, updated_at: now,
}

function records(count = 2) {
  return Array.from({ length: count }, (_, index) => ({
    source_id: 'PRIVATE_SOURCE_DO_NOT_RENDER', event_id: `boot-${index}`,
    boot_time: new Date(Date.parse(now) - index * 86_400_000).toISOString(),
    recorded_at: new Date(Date.parse(now) - index * 86_400_000 + 45_000).toISOString(),
    imported_at: '2026-09-25T08:01:00Z', uptime_seconds: 45,
    reason: 'unknown', clock: 'system_clock_not_independently_verified',
  }))
}

function payload(count = 2, state: ImportState = 'ok') {
  return {
    period_days: 0, total: count, all_time_count: count, last_7_days_count: Math.min(count, 7),
    first_imported_at: count ? '2026-09-25T08:01:00Z' : null,
    items: records(count),
    import_status: {
      state,
      last_attempt_at: state === 'waiting' ? null : '2026-09-25T08:02:00Z',
      last_success_at: state === 'waiting' ? null : '2026-09-25T08:01:00Z',
      invalid_files: state === 'degraded' ? 2 : 0,
      conflicting_files: state === 'degraded' ? 1 : 0,
      checked_files: state === 'waiting' ? 0 : count + (state === 'degraded' ? 3 : 0),
      error_code: state === 'degraded' ? 'INTERNAL_DETAIL_MUST_NOT_APPEAR' : null,
    },
  }
}

async function fixture(page: Page, options: { theme?: Theme; role?: string; data?: ReturnType<typeof payload>; status?: number } = {}) {
  const control = {
    data: options.data ?? payload(), status: options.status ?? 200,
    requests: [] as Array<{ days: string | null; limit: string | null; offset: string | null }>,
    completed: [] as number[],
    writes: [] as string[],
    pageErrors: [] as string[],
    beforeReply: null as null | ((url: URL) => Promise<void>),
  }
  page.on('pageerror', (error) => control.pageErrors.push(error.message))
  await page.addInitScript((theme) => {
    // Disposable browser context, synthetic marker only; never load a saved session.
    window.localStorage.setItem('dpms_token', 'server-boot-fixture-only')
    window.localStorage.setItem('dpms-theme', theme)
  }, options.theme ?? 'light')
  await page.route('**/*', async (route) => {
    if (new URL(route.request().url()).origin !== 'http://localhost:55177') {
      await route.abort()
      return
    }
    await route.continue()
  })
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' })))
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') {
      control.writes.push(`${request.method()} ${url.pathname}`)
      await route.fulfill({ status: 405, json: { detail: 'Read-only fixture' } })
      return
    }
    if (url.pathname === '/api/admin/server-boots') {
      control.requests.push({ days: url.searchParams.get('days'), limit: url.searchParams.get('limit'), offset: url.searchParams.get('offset') })
      const status = control.status
      const data = structuredClone(control.data)
      const days = Number(url.searchParams.get('days'))
      const offset = Number(url.searchParams.get('offset'))
      const items = data.items.filter((item) => !days || Date.parse(item.boot_time) > Date.parse(now) - days * 86_400_000)
      await control.beforeReply?.(url)
      await route.fulfill({
        status,
        json: status === 200
          ? { ...data, period_days: days, total: items.length, items: items.slice(offset, offset + 25) }
          : { detail: 'INTERNAL_DETAIL_MUST_NOT_APPEAR' },
      }).catch(() => { /* An intentionally aborted fixture request may already be gone. */ })
      control.completed.push(days)
      return
    }
    let json: unknown = []
    if (url.pathname === '/api/auth/me') json = { ...admin, role: options.role ?? 'admin' }
    if (url.pathname === '/api/users/admin') json = [admin]
    if (url.pathname === '/api/messages/summary') json = { direct_count: 0, important_count: 0, revision: 0 }
    await route.fulfill({ status: 200, json })
  })
  return control
}

function panel(page: Page) {
  return page.getByRole('region', { name: 'Загрузки сервера', exact: true })
}

async function open(page: Page) {
  await page.goto('/admin/users')
  await expect(panel(page)).toBeVisible()
  await expect(panel(page).getByText('Загрузка записей…')).toBeHidden()
}

async function screenshot(page: Page, info: TestInfo, name: string) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(await panel(page).evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await test.step('visual evidence', async () => {
    if (name.endsWith('-ok')) {
      const directory = path.resolve('../docs/stability/screenshots')
      await mkdir(directory, { recursive: true })
      const prefix = path.join(directory, `${info.project.name}-${name}`)
      await page.screenshot({ path: `${prefix}-page.png`, animations: 'disabled' })
      await panel(page).screenshot({ path: `${prefix}-panel.png`, animations: 'disabled' })
    }
    await info.attach(`${name}-page`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' })
    await info.attach(`${name}-panel`, { body: await panel(page).screenshot({ animations: 'disabled' }), contentType: 'image/png' })
  })
}

for (const theme of ['light', 'dark', 'rose'] as const) {
  for (const state of ['ok', 'empty', 'waiting', 'error', 'degraded', 'stale'] as const) {
    test(`${theme}: ${state} screenshot and state`, async ({ page }, info) => {
      const control = await fixture(page, {
        theme, status: state === 'error' ? 503 : 200,
        data: payload(state === 'empty' || state === 'waiting' ? 0 : 2, state === 'empty' || state === 'error' ? 'ok' : state),
      })
      await open(page)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const expected = {
        ok: 'Импорт при последнем запросе: Синхронизирован', empty: 'События загрузки не найдены.',
        waiting: 'Импорт ещё не выполнен.', error: 'Не удалось загрузить записи. Повторите запрос.',
        degraded: 'Импорт при последнем запросе: Импорт с ошибками', stale: 'Импорт при последнем запросе: Проверка устарела',
      }
      await expect(panel(page).getByText(expected[state], { exact: true })).toBeVisible()
      await expect(panel(page).getByText('МСК (Europe/Moscow, UTC+3)')).toBeVisible()
      await expect(panel(page)).not.toContainText('INTERNAL_DETAIL_MUST_NOT_APPEAR')
      await expect(panel(page)).not.toContainText('PRIVATE_SOURCE_DO_NOT_RENDER')
      if (state === 'degraded') {
        await expect(panel(page)).toContainText('Некорректных: 2. Конфликтующих: 1.')
        await expect(panel(page)).toContainText('Последняя успешная проверка:')
      }
      if (state === 'waiting') {
        await expect(panel(page)).toContainText('Синхронизация ещё не запускалась')
        await expect(panel(page)).toContainText('Последняя проверка: нет данных')
      }
      await screenshot(page, info, `${theme}-${state}`)
      expect(control.writes).toEqual([])
      expect(control.pageErrors).toEqual([])
    })
  }
}

test('default query, Moscow dates, admin placement and existing controls', async ({ page }) => {
  const control = await fixture(page)
  await open(page)
  expect(control.requests.at(-1)).toEqual({ days: '0', limit: '25', offset: '0' })
  await expect(panel(page).getByLabel('Период')).toHaveValue('0')
  await expect(panel(page).locator('dl')).toContainText('Всего2За 7 дней2')
  await expect(panel(page).getByRole('table').getByRole('row')).toHaveCount(3)
  await expect(panel(page).locator('tbody tr').first()).toContainText('25.09.2026, 11:00:00')
  await expect(panel(page).locator('tbody tr').first()).toContainText('25.09.2026, 11:00:45')
  await expect(panel(page).locator('tbody tr').first()).toContainText('25.09.2026, 11:01:00')
  await expect(panel(page)).toContainText('Неизвестна')
  await expect(panel(page)).toContainText('Последняя проверка: 25.09.2026, 11:02:00')
  await expect(panel(page).getByRole('button', { name: 'Обновить записи загрузок' })).toHaveAttribute('title', 'Обновить записи загрузок')
  await expect(page.getByRole('button', { name: 'Быстро добавить', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Добавить сотрудника', exact: true })).toBeVisible()
  expect(await panel(page).evaluate((element) => ({
    afterHeader: element.previousElementSibling?.tagName === 'HEADER',
    beforeUsers: element.nextElementSibling?.textContent?.includes('Управление сотрудниками'),
  }))).toEqual({ afterHeader: true, beforeUsers: true })
})

test('periods, pagination, reset on filter, refresh and no polling', async ({ page }) => {
  await page.clock.install()
  const control = await fixture(page, { data: payload(27) })
  await open(page)
  await expect(panel(page).getByText('1–25 из 27', { exact: true })).toBeVisible()
  await expect(panel(page).getByRole('button', { name: 'Предыдущие записи' })).toBeDisabled()
  await panel(page).getByRole('button', { name: 'Следующие записи' }).click()
  await expect(panel(page).getByText('26–27 из 27', { exact: true })).toBeVisible()
  await expect(panel(page).getByRole('button', { name: 'Следующие записи' })).toBeDisabled()
  await panel(page).getByRole('button', { name: 'Предыдущие записи' }).click()
  await expect(panel(page).getByText('1–25 из 27', { exact: true })).toBeVisible()
  await panel(page).getByRole('button', { name: 'Следующие записи' }).click()
  await expect(panel(page).getByText('26–27 из 27', { exact: true })).toBeVisible()
  for (const days of ['7', '30', '90', '366', '0']) {
    await panel(page).getByLabel('Период').selectOption(days)
    await expect(panel(page).getByText('Загрузка записей…')).toBeHidden()
    await expect.poll(() => control.requests.at(-1)).toEqual({ days, limit: '25', offset: '0' })
    await expect(panel(page).getByRole('button', { name: 'Предыдущие записи' })).toBeDisabled()
  }
  const count = control.requests.length
  await page.clock.runFor(120_000)
  expect(control.requests).toHaveLength(count)
  await panel(page).getByRole('button', { name: 'Обновить записи загрузок' }).click()
  await expect.poll(() => control.requests.length).toBe(count + 1)
  expect(control.writes).toEqual([])
})

test('empty filtered period is not confused with no import', async ({ page }) => {
  const data = payload(1)
  data.items[0].boot_time = '2025-01-01T00:00:00Z'
  const control = await fixture(page, { data })
  await open(page)
  await panel(page).getByLabel('Период').selectOption('7')
  await expect(panel(page).getByText('За выбранный период загрузок нет.')).toBeVisible()
  await expect(panel(page)).not.toContainText('Импорт ещё не выполнен.')
  await expect(panel(page).getByText('0 записей', { exact: true })).toBeVisible()
  expect(control.requests.at(-1)?.days).toBe('7')
})

test('failed initial import remains distinct from a successful empty scan', async ({ page }) => {
  const data = payload(0, 'degraded')
  data.import_status.last_success_at = null
  await fixture(page, { data })
  await open(page)
  await expect(panel(page)).toContainText('Импорт с ошибками')
  await expect(panel(page)).toContainText('Импорт ещё не выполнен.')
})

test('safe error recovery and forbidden response', async ({ page }) => {
  const control = await fixture(page, { status: 503 })
  await open(page)
  await expect(panel(page).getByRole('alert')).toContainText('Не удалось загрузить записи.')
  control.status = 200
  await panel(page).getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(panel(page)).toContainText('Синхронизирован')
  control.status = 403
  await panel(page).getByRole('button', { name: 'Обновить записи загрузок' }).click()
  await expect(panel(page).getByRole('alert')).toContainText('Просмотр доступен только администратору.')
  await expect(panel(page).getByRole('table')).toHaveCount(0)
  await expect(panel(page)).not.toContainText('INTERNAL_DETAIL_MUST_NOT_APPEAR')
})

test('aborts replaced requests and never renders their late responses', async ({ page }, info) => {
  const control = await fixture(page, { data: payload(27) })
  let release!: () => void
  const pending = new Promise<void>((resolve) => { release = resolve })
  control.beforeReply = (url) => Number(url.searchParams.get('days')) === 0 ? pending : Promise.resolve()
  const aborted: string[] = []
  page.on('requestfailed', (request) => {
    if (request.url().includes('/api/admin/server-boots')) aborted.push(request.url())
  })
  await page.goto('/admin/users')
  await expect(panel(page).getByText('Загрузка записей…')).toBeVisible()
  await expect.poll(() => control.requests.length).toBeGreaterThan(0)
  await expect(panel(page).getByRole('button', { name: 'Обновить записи загрузок' })).toBeDisabled()
  await screenshot(page, info, 'loading')
  try {
    await panel(page).getByLabel('Период').selectOption('7')
    await expect(panel(page).getByText('1–7 из 7', { exact: true })).toBeVisible()
    await expect.poll(() => aborted.length).toBeGreaterThan(0)
  } finally {
    release()
  }
  await expect.poll(() => control.completed.includes(0)).toBe(true)
  await expect(panel(page).getByLabel('Период')).toHaveValue('7')
  await expect(panel(page).getByText('1–7 из 7', { exact: true })).toBeVisible()
  await expect(panel(page).locator('tbody tr')).toHaveCount(7)
})

test('refresh recovers when the current page disappears', async ({ page }) => {
  const control = await fixture(page, { data: payload(27) })
  await open(page)
  await panel(page).getByRole('button', { name: 'Следующие записи' }).click()
  await expect(panel(page).getByText('26–27 из 27', { exact: true })).toBeVisible()
  control.data = payload(2)
  await panel(page).getByRole('button', { name: 'Обновить записи загрузок' }).click()
  await expect(panel(page).getByText('1–2 из 2', { exact: true })).toBeVisible()
  expect(control.requests.at(-1)?.offset).toBe('0')
})

test('non-admin never mounts or requests the panel', async ({ page }) => {
  const control = await fixture(page, { role: 'executor' })
  await page.goto('/admin/users')
  await expect(page.locator('.app-shell')).toBeVisible()
  await expect(panel(page)).toHaveCount(0)
  expect(control.requests).toEqual([])
})

test('narrow and wide viewports keep the panel within the page', async ({ page }, info) => {
  await fixture(page)
  await open(page)
  for (const viewport of [{ width: 320, height: 700 }, { width: 1024, height: 768 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport)
    await screenshot(page, info, `viewport-${viewport.width}`)
  }
})
