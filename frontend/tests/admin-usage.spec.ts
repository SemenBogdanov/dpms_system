import { expect, test, type Page, type TestInfo } from '@playwright/test'

// The main session integrates /admin/usage and prepares the canonical local candidate.
// Run without starting a server: playwright test --config=playwright.usage.config.ts admin-usage.spec.ts --workers=1
test.use({
  baseURL: 'http://localhost:55177',
  timezoneId: 'America/Los_Angeles',
  serviceWorkers: 'block',
})
test.setTimeout(30_000)

const ORIGIN = 'http://localhost:55177'
// September 28 in Moscow, September 27 in the browser's timezone.
const now = '2026-09-27T21:30:00Z'
const alice = '11111111-1111-4111-8111-111111111111'
const bob = '22222222-2222-4222-8222-222222222222'
const admin = {
  id: alice, full_name: 'Тестовый администратор', email: 'admin@example.invalid', role: 'admin',
  league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, needs_password_change: false,
  task_workspace_enabled: false, can_link_queue_tasks_to_projects: false,
  feedback_enabled: false, audit_enabled: false, audit_calendar_enabled: false,
  competency_development_enabled: false, competency_constructor_enabled: false,
  plan_started_at: null, onboarding_started_at: null, onboarding_until: null,
  sidebar_menu_order: null, created_at: now, updated_at: now,
}
type Theme = 'light' | 'dark' | 'rose'
type UsageFetchProbe = { id: number; url: string; hasSignal: boolean; aborted: boolean }

declare global {
  interface Window {
    __adminUsageFetches: UsageFetchProbe[]
  }
}

function payload(count = 27) {
  return {
    start_date: '2026-09-22', end_date: '2026-09-28', timezone: 'Europe/Moscow',
    login_count: count, login_users: count ? 2 : 0,
    section_view_count: count ? 40 : 0, section_users: count ? 2 : 0,
    first_login_at: '2026-09-01T08:00:00Z' as string | null,
    first_section_view_at: '2026-09-25T21:00:00Z' as string | null,
    sections: count ? [
      { section: 'notes', label: 'Заметки', views: 10, users: 1 },
      { section: 'graphs', label: 'Графы', views: 30, users: 2 },
    ] : [],
    users: count ? [
      { id: alice, name: 'Анна Тестовая', email: 'anna@example.invalid', logins: count - 1 },
      { id: bob, name: 'Борис Тестовый', email: 'boris@example.invalid', logins: 1 },
    ] : [],
    daily: [
      { date: '2026-09-22', logins: 0, section_views: 0 },
      { date: '2026-09-28', logins: count, section_views: count ? 40 : 0 },
    ],
    logins: {
      total: count,
      items: Array.from({ length: count }, (_, index) => ({
        id: `login-${index}`, user_id: index === count - 1 ? bob : alice,
        name: index === count - 1 ? 'Борис Тестовый' : 'Анна Тестовая',
        email: index === count - 1 ? 'boris@example.invalid' : 'anna@example.invalid',
        occurred_at: now, device: 'desktop' as string | null,
        browser: 'Chrome' as string | null, os: 'macOS' as string | null,
      })),
    },
  }
}

async function fixture(page: Page, options: { theme?: Theme; data?: ReturnType<typeof payload>; status?: number; observeUsageAborts?: boolean } = {}) {
  const control = {
    data: options.data ?? payload(), status: options.status ?? 200,
    requests: [] as URL[], completed: [] as string[], methods: [] as string[], pageErrors: [] as string[],
    beforeReply: null as null | ((url: URL) => Promise<void>),
  }
  page.on('pageerror', (error) => control.pageErrors.push(error.message))
  await page.clock.setFixedTime(new Date(now))
  await page.addInitScript((theme) => {
    // Fresh disposable context with a synthetic marker; never read saved browser sessions.
    window.localStorage.setItem('dpms_token', 'admin-usage-fixture-only')
    window.localStorage.setItem('dpms-theme', theme)
  }, options.theme ?? 'light')
  if (options.observeUsageAborts) {
    await page.addInitScript(() => {
      const originalFetch = window.fetch
      window.__adminUsageFetches = []
      window.fetch = function (input, init) {
        const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
        if (url.origin === window.location.origin && url.pathname === '/api/admin/usage') {
          const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
          const probe: UsageFetchProbe = {
            id: window.__adminUsageFetches.length, url: url.href,
            hasSignal: !!signal, aborted: signal?.aborted ?? false,
          }
          window.__adminUsageFetches.push(probe)
          // Observe the actual fetch signal without changing transport or cancellation.
          signal?.addEventListener('abort', () => { probe.aborted = true }, { once: true })
        }
        return originalFetch.call(this, input, init)
      }
    })
  }
  await page.routeWebSocket('**/*', (socket) => {
    socket.onMessage(() => socket.send(JSON.stringify({ type: 'ready' })))
  })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== ORIGIN) return route.abort()
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/admin/usage') {
      control.requests.push(url)
      control.methods.push(request.method())
      const status = control.status
      const data = structuredClone(control.data)
      const start = url.searchParams.get('start_date')!
      const end = url.searchParams.get('end_date')!
      const offset = Number(url.searchParams.get('offset'))
      const selected = url.searchParams.get('user_id')
      const items = data.logins.items.filter((item) => {
        const time = Date.parse(item.occurred_at)
        return time >= Date.parse(`${start}T00:00:00+03:00`) && time <= Date.parse(`${end}T23:59:59.999+03:00`)
      })
      const filtered = items.filter((item) => !selected || item.user_id === selected)
      await control.beforeReply?.(url)
      await route.fulfill({ status, json: status === 200 ? {
        ...data, start_date: start, end_date: end,
        login_count: items.length,
        logins: { total: filtered.length, items: filtered.slice(offset, offset + 25) },
      } : { detail: 'INTERNAL_DETAIL_MUST_NOT_APPEAR' } }).catch(() => {
        // A deliberately cancelled request may already be gone.
      })
      control.completed.push(start)
      return
    }
    // Every API call is mocked, including writes from unrelated shell features.
    let json: unknown = []
    if (url.pathname === '/api/auth/me') json = admin
    if (url.pathname === '/api/users/admin') json = [admin]
    if (url.pathname === '/api/messages/summary') json = { direct_count: 0, important_count: 0, revision: 0 }
    await route.fulfill({ status: 200, json })
  })
  return control
}

function panel(page: Page) {
  return page.getByRole('region', { name: 'Обзор использования', exact: true })
}

function metrics(page: Page) {
  return panel(page).getByRole('definition')
}

async function open(page: Page, query = '') {
  await page.goto(`${ORIGIN}/admin/usage${query}`)
  await expect(panel(page)).toBeVisible()
  await expect(panel(page).getByText('Загрузка статистики…', { exact: true })).toBeHidden()
}

async function journal(page: Page) {
  const details = panel(page).locator('details').filter({ has: page.locator('summary', { hasText: 'Журнал входов' }) })
  if (await details.getAttribute('open') === null) await details.locator('summary').click()
  return details
}

function queryOf(url: URL | undefined) {
  return Object.fromEntries(url?.searchParams ?? [])
}

async function evidence(page: Page, info: TestInfo, name: string) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(await panel(page).evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await page.getByRole('main').evaluate((element) => element.scrollTo({ top: 0, left: 0, behavior: 'instant' }))
  const screenshotPath = info.outputPath(`${name}-top.png`)
  await page.screenshot({ path: screenshotPath, fullPage: false, animations: 'disabled' })
  await info.attach(`${name}-top`, { path: screenshotPath, contentType: 'image/png' })
  // Capture actual viewports within the shell, never a tall element outside its scrollport.
  for (const [suffix, target] of [
    ['sections', panel(page).getByRole('table', { name: 'Популярные разделы' })],
    ['login-row', panel(page).getByRole('table', { name: 'Журнал успешных входов' }).locator('tbody tr').first()],
  ] as const) {
    if (!await target.isVisible()) continue
    await target.scrollIntoViewIfNeeded()
    const detailPath = info.outputPath(`${name}-${suffix}.png`)
    await page.screenshot({ path: detailPath, fullPage: false, animations: 'disabled' })
    await info.attach(`${name}-${suffix}`, { path: detailPath, contentType: 'image/png' })
  }
}

test('default Moscow period, lifetime first records, section ranking and login details', async ({ page }) => {
  const control = await fixture(page)
  await open(page)
  expect(queryOf(control.requests.at(-1))).toEqual({ start_date: '2026-09-22', end_date: '2026-09-28', limit: '25', offset: '0' })
  await expect(metrics(page)).toHaveText(['27', '2', '40', '2'])
  await expect(panel(page)).toContainText('Первый записанный вход: 01.09.2026, 11:00:00')
  await expect(panel(page)).toContainText('Первое записанное посещение раздела: 26.09.2026, 00:00:00')
  await expect(panel(page)).toContainText('Историческая полнота не гарантируется')
  await expect(panel(page).getByRole('table', { name: 'Популярные разделы' }).locator('tbody tr').first()).toContainText('Графы')
  await expect(panel(page).getByRole('table', { name: 'Журнал успешных входов' })).toBeHidden()
  const log = await journal(page)
  await expect(log.getByRole('table').locator('tbody tr')).toHaveCount(25)
  await expect(log.getByRole('table').locator('tbody tr').first()).toContainText('Анна Тестоваяanna@example.invalid')
  await expect(log.getByRole('table').locator('tbody tr').first()).toContainText('28.09.2026, 00:30:00')
  await expect(log.getByRole('table').locator('tbody tr').first()).toContainText('desktop')
  await expect(log.getByRole('table').locator('tbody tr').first()).toContainText('ChromemacOS')
  await expect(log.getByText('1–25 из 27', { exact: true })).toBeVisible()
  expect(control.methods.every((method) => method === 'GET')).toBe(true)
  expect(control.pageErrors).toEqual([])
})

test('quick and custom periods require Apply, retain unrelated URL state and survive back/reload', async ({ page }) => {
  const control = await fixture(page)
  await open(page, '?view=usage&keep=untouched')
  for (const [days, start] of [[3, '2026-09-26'], [30, '2026-08-30'], [7, '2026-09-22']] as const) {
    const count = control.requests.length
    await panel(page).getByRole('button', { name: `${days} ${days === 3 ? 'дня' : 'дней'}`, exact: true }).click()
    await expect(panel(page).getByLabel('С даты', { exact: true })).toHaveValue(start)
    expect(control.requests).toHaveLength(count)
    await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
    await expect.poll(() => queryOf(control.requests.at(-1)).start_date).toBe(start)
    await expect(metrics(page)).toHaveCount(4)
  }
  await panel(page).getByLabel('С даты', { exact: true }).fill('2026-09-28')
  await panel(page).getByLabel('По дату', { exact: true }).fill('2026-09-28')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  await expect.poll(() => queryOf(control.requests.at(-1)).start_date).toBe('2026-09-28')
  await expect(metrics(page).first()).toHaveText('27')
  expect(new URL(page.url()).searchParams.get('view')).toBe('usage')
  expect(new URL(page.url()).searchParams.get('keep')).toBe('untouched')
  await page.reload()
  await expect(panel(page).getByLabel('С даты', { exact: true })).toHaveValue('2026-09-28')
  await page.goBack()
  await expect(panel(page).getByLabel('С даты', { exact: true })).toHaveValue('2026-09-22')
  await expect.poll(() => queryOf(control.requests.at(-1)).start_date).toBe('2026-09-22')
})

test('login-only user filter, page resets and recovery when a page disappears', async ({ page }) => {
  const control = await fixture(page)
  await open(page)
  const log = await journal(page)
  await expect(log.getByRole('button', { name: 'Предыдущие входы' })).toBeDisabled()
  await log.getByRole('button', { name: 'Следующие входы' }).click()
  await expect(log.getByText('26–27 из 27', { exact: true })).toBeVisible()
  await expect(log.getByRole('button', { name: 'Следующие входы' })).toBeDisabled()
  await log.getByLabel('Сотрудник в журнале').selectOption(bob)
  await expect(log.getByText('1–1 из 1', { exact: true })).toBeVisible()
  expect(queryOf(control.requests.at(-1))).toMatchObject({ user_id: bob, offset: '0' })
  await expect(metrics(page)).toHaveText(['27', '2', '40', '2'])
  await expect(log.getByRole('table')).toContainText('Борис Тестовый')
  await expect(log.getByLabel('Сотрудник в журнале').locator('option')).toHaveCount(3)
  await log.getByLabel('Сотрудник в журнале').selectOption('')
  await expect(log.getByText('1–25 из 27', { exact: true })).toBeVisible()
  await log.getByRole('button', { name: 'Следующие входы' }).click()
  await expect(log.getByText('26–27 из 27', { exact: true })).toBeVisible()
  control.data = payload(2)
  await panel(page).getByRole('button', { name: 'Обновить статистику' }).click()
  await expect(log.getByText('1–2 из 2', { exact: true })).toBeVisible()
  expect(queryOf(control.requests.at(-1)).offset).toBe('0')
  expect(queryOf(control.requests.at(-1))).not.toHaveProperty('user_id')
})

test('invalid dates are local errors and malformed URL dates use the default range', async ({ page }) => {
  const control = await fixture(page)
  await open(page, '?usage_start=2026-02-30&usage_end=2026-09-28&usage_offset=-25')
  expect(queryOf(control.requests.at(-1))).toMatchObject({ start_date: '2026-09-22', offset: '0' })
  const count = control.requests.length
  await panel(page).getByLabel('С даты', { exact: true }).fill('2026-09-30')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(panel(page).getByRole('alert')).toContainText('начало периода не должно быть позже окончания')
  await expect(panel(page).getByLabel('С даты', { exact: true })).toBeFocused()
  expect(control.requests).toHaveLength(count)
  await panel(page).getByLabel('С даты', { exact: true }).fill('')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  expect(control.requests).toHaveLength(count)
  await panel(page).getByLabel('С даты', { exact: true }).fill('2025-09-27')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(panel(page).getByRole('alert')).toContainText('Период не должен превышать 366 дней.')
  await expect(panel(page).getByLabel('По дату', { exact: true })).toBeFocused()
  expect(control.requests).toHaveLength(count)
  await panel(page).getByLabel('С даты', { exact: true }).fill('2025-09-28')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  await expect.poll(() => queryOf(control.requests.at(-1)).start_date).toBe('2025-09-28')
  await open(page, '?usage_start=2020-01-01&usage_end=2026-09-28&usage_offset=100025')
  expect(queryOf(control.requests.at(-1))).toMatchObject({ start_date: '2026-09-22', offset: '0' })
})

test('safe failure, retry and 403 erase report data without rendering raw errors', async ({ page }) => {
  const control = await fixture(page, { status: 503 })
  await open(page)
  await expect(panel(page).getByRole('alert')).toContainText('Не удалось загрузить статистику.')
  control.status = 200
  await panel(page).getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(metrics(page)).toHaveCount(4)
  await journal(page)
  control.status = 403
  await panel(page).getByRole('button', { name: 'Обновить статистику' }).click()
  await expect(panel(page).getByRole('alert')).toContainText('Просмотр доступен только администратору.')
  await expect(panel(page).getByRole('table')).toHaveCount(0)
  await expect(metrics(page)).toHaveCount(0)
  await expect(panel(page)).not.toContainText('INTERNAL_DETAIL_MUST_NOT_APPEAR')
  await expect(panel(page)).not.toContainText('anna@example.invalid')
})

test('unknown history is distinct from zero recorded events, including daily rows', async ({ page }) => {
  const data = payload(0)
  data.first_login_at = null
  data.first_section_view_at = null
  const control = await fixture(page, { data })
  await open(page)
  await expect(metrics(page)).toHaveText(['Нет данных', 'Нет данных', 'Нет данных', 'Нет данных'])
  await expect(panel(page)).toContainText('Первый записанный вход: нет записей')
  await expect(panel(page)).toContainText('За выбранный период событий не записано.')
  control.data = payload(0)
  await panel(page).getByRole('button', { name: 'Обновить статистику' }).click()
  await expect(metrics(page)).toHaveText(['0', '0', '0', '0'])
  await panel(page).locator('summary', { hasText: 'По дням' }).click()
  const daily = panel(page).getByRole('table', { name: 'События по дням' })
  await expect(daily.getByRole('row').filter({ hasText: '22.09.2026' }).getByRole('cell').last()).toHaveText('Нет данных')
  await panel(page).getByLabel('С даты', { exact: true }).fill('2026-09-22')
  await panel(page).getByLabel('По дату', { exact: true }).fill('2026-09-24')
  await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(metrics(page)).toHaveText(['0', '0', 'Нет данных', 'Нет данных'])
})

test('replacement and unmount cancel pending requests and ignore late responses', async ({ page }, info) => {
  const control = await fixture(page, { observeUsageAborts: true })
  let release!: () => void
  const pending = new Promise<void>((resolve) => { release = resolve })
  control.beforeReply = (url) => url.searchParams.get('start_date') === '2026-09-22' ? pending : Promise.resolve()
  try {
    await page.goto(`${ORIGIN}/admin/usage`)
    await expect(panel(page).getByText('Загрузка статистики…', { exact: true })).toBeVisible()
    await expect.poll(() => control.requests.length).toBeGreaterThan(0)
    await evidence(page, info, 'loading')
    const replaced = await page.evaluate(() => window.__adminUsageFetches.at(-1)!)
    expect(replaced).toMatchObject({ hasSignal: true, aborted: false })
    expect(new URL(replaced.url).searchParams.get('start_date')).toBe('2026-09-22')
    control.data = payload(2)
    control.data.sections[1].label = 'Текущие графы'
    await panel(page).getByRole('button', { name: '3 дня', exact: true }).click()
    await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
    await expect(metrics(page)).toHaveText(['2', '2', '40', '2'])
    await expect.poll(() => page.evaluate((id) => window.__adminUsageFetches.find((item) => item.id === id)?.aborted, replaced.id)).toBe(true)
  } finally {
    release()
  }
  await expect.poll(() => control.completed.includes('2026-09-22')).toBe(true)
  await expect(panel(page)).toContainText('Период: 26.09.2026 – 28.09.2026')
  await expect(panel(page).getByLabel('С даты', { exact: true })).toHaveValue('2026-09-26')
  await expect(metrics(page)).toHaveText(['2', '2', '40', '2'])
  await expect(panel(page).getByRole('table', { name: 'Популярные разделы' }).locator('tbody tr').first()).toContainText('Текущие графы')
  let finish!: () => void
  control.beforeReply = () => new Promise<void>((resolve) => { finish = resolve })
  await panel(page).getByRole('button', { name: 'Обновить статистику' }).click()
  await expect.poll(() => typeof finish).toBe('function')
  const unmounted = await page.evaluate(() => window.__adminUsageFetches.at(-1)!)
  expect(unmounted).toMatchObject({ hasSignal: true, aborted: false })
  expect(new URL(unmounted.url).searchParams.get('start_date')).toBe('2026-09-26')
  const completedBeforeUnmount = control.completed.length
  try {
    // A router Link unmounts React; full-document navigation only tears down the browser page.
    await page.getByRole('navigation', { name: 'Разделы администрирования' }).getByRole('link', { name: 'Сотрудники', exact: true }).click()
    await expect(page).toHaveURL(`${ORIGIN}/admin/users`)
    await expect(panel(page)).toHaveCount(0)
    await expect.poll(() => page.evaluate((id) => window.__adminUsageFetches.find((item) => item.id === id)?.aborted, unmounted.id)).toBe(true)
  } finally {
    finish()
  }
  await expect.poll(() => control.completed.length).toBeGreaterThan(completedBeforeUnmount)
  await expect(page).toHaveURL(`${ORIGIN}/admin/users`)
  await expect(panel(page)).toHaveCount(0)
})

test('no report polling', async ({ page }) => {
  await page.clock.install({ time: new Date(now) })
  const control = await fixture(page)
  await open(page)
  const count = control.requests.length
  await page.clock.runFor(120_000)
  expect(control.requests).toHaveLength(count)
})

for (const theme of ['light', 'dark', 'rose'] as const) {
  test(`${theme}: bounded desktop/mobile overflow and long-content evidence`, async ({ page }, info) => {
    const data = payload(2)
    data.logins.items[0].name = 'ОченьДлинноеИмяБезПробелов'.repeat(4)
    data.logins.items[0].email = `${'long-email-'.repeat(9)}@example.invalid`
    data.logins.items[0].device = null
    data.logins.items[0].browser = null
    data.logins.items[0].os = null
    const control = await fixture(page, { theme, data })
    await open(page)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await journal(page)
    await expect(panel(page)).toContainText('Неизвестный браузер')
    for (const viewport of [
      { width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 1024, height: 768 },
      { width: 390, height: 844 }, { width: 320, height: 700 },
    ]) {
      await page.setViewportSize(viewport)
      const sections = panel(page).getByRole('table', { name: 'Популярные разделы' })
      for (const [full, compact] of [['Посещения', 'Визиты'], ['Сотрудники', 'Люди']]) {
        const header = sections.getByRole('columnheader', { name: full, exact: true })
        await expect(header.getByText(viewport.width < 640 ? compact : full, { exact: true })).toBeVisible()
        expect(await header.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
        await expect(header).toHaveCSS('white-space', 'nowrap')
      }
      await evidence(page, info, `${theme}-${viewport.width}`)
    }
    expect(control.pageErrors).toEqual([])
  })
}

test.describe('Mobile controls', () => {
  test('date controls, disclosure and mobile login table', async ({ page }, info) => {
    const control = await fixture(page, { data: payload(2) })
    await open(page)
    await page.setViewportSize({ width: 390, height: 844 })
    await panel(page).getByRole('button', { name: '3 дня', exact: true }).click()
    await panel(page).getByRole('button', { name: 'Применить', exact: true }).click()
    await expect.poll(() => queryOf(control.requests.at(-1)).start_date).toBe('2026-09-26')
    const log = await journal(page)
    await expect(log.getByRole('table').locator('tbody tr')).toHaveCount(2)
    await evidence(page, info, 'mobile-390')
    expect(control.pageErrors).toEqual([])
  })
})
