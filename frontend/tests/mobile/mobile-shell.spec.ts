import { expect, test, type Page, type Route } from '@playwright/test'

const testUser = {
  id: '11111111-1111-4111-8111-111111111111',
  full_name: 'Мобильный тест',
  email: 'mobile-test@example.com',
  league: 'A',
  role: 'admin',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 1,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: true,
  feedback_enabled: true,
  competency_development_enabled: true,
  competency_constructor_enabled: true,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-07-30T00:00:00Z',
  updated_at: '2026-07-30T00:00:00Z',
}

async function assertNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1)
}

async function installApiMock(page: Page, authAvailable = true) {
  let available = authAvailable
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'mobile-smoke-token'))
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/api/auth/me') {
      if (!available) {
        await route.abort('connectionfailed')
        return
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(testUser) })
      return
    }
    const body = request.method() === 'GET' ? [] : {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return {
    restore: () => {
      available = true
    },
  }
}

test('login remains usable without horizontal overflow', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Загрузка системы' })).toHaveCount(0)
  await expect(page.getByLabel('Email')).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Пароль' })).toBeVisible()
  await page.getByLabel('Email').fill('mobile@example.com')
  await page.getByRole('textbox', { name: 'Пароль' }).fill('demo-password')
  await assertNoHorizontalOverflow(page)
})

test('auth bootstrap shows recovery and reconnects without deleting the session', async ({ page }) => {
  const api = await installApiMock(page, false)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Нет связи с системой' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Повторить подключение' })).toBeVisible()

  api.restore()
  await page.getByRole('button', { name: 'Повторить подключение' }).click()
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('dpms_token'))).toBe('mobile-smoke-token')
})

test('mobile drawer exposes every required section', async ({ page }) => {
  await installApiMock(page)
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible()

  await page.getByRole('button', { name: 'Меню', exact: true }).click()
  const sidebar = page.locator('aside')
  await expect(sidebar).toBeVisible()
  await sidebar.getByRole('button', { name: /Задачи/ }).click()
  await sidebar.getByRole('button', { name: /Управление/ }).click()

  const requiredLabels = [
    'Личные задачи',
    'Q-план',
    'Очередь',
    'Калькулятор',
    'Каталог операций',
    'База знаний',
    'Магазин',
    'Трекер сроков',
    'Заметки',
    'Контакты',
    'Дашборд',
    'Отчёты',
    'Калибровка',
    'Отсутствия',
    'Проекты и цели',
    'Развитие',
    'Обратная связь',
    'Настройки',
    'Админ',
  ]
  for (const label of requiredLabels) {
    await expect(sidebar.getByText(label, { exact: true }).first()).toBeVisible()
  }
})

test('core mobile routes load through lazy chunks while the shell stays visible', async ({ page }) => {
  await installApiMock(page)
  await page.route('**/assets/QuickNotesPage-*.js', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.continue()
  })
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/settings')
  const bottomNavigation = page.locator('nav.fixed')
  await bottomNavigation.getByRole('link', { name: 'Заметки' }).click()
  await expect(page.getByRole('heading', { name: 'Заметки' })).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await bottomNavigation.getByRole('link', { name: 'Личные' }).click()
  await expect(page.getByRole('heading', { name: 'Личные задачи' })).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await bottomNavigation.getByRole('link', { name: 'Сроки' }).click()
  await expect(page.getByRole('heading', { name: 'Трекер сроков' })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  expect(pageErrors).toEqual([])
})
