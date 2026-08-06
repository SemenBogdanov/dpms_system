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
  can_link_queue_tasks_to_projects: true,
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

async function installApiMock(
  page: Page,
  authAvailable = true,
  responses: Record<string, unknown> = {},
) {
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
    if (Object.prototype.hasOwnProperty.call(responses, pathname)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(responses[pathname]),
      })
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

const portfolioProjectId = '22222222-2222-4222-8222-222222222222'

function portfolioEntity(overrides: Record<string, unknown>) {
  return {
    id: portfolioProjectId,
    owner_id: testUser.id,
    owner_name: 'Мобильный тест',
    owner_email: testUser.email,
    entity_type: 'project',
    title: 'Миграция клиентского сервиса',
    description: 'Перенос сервиса без остановки клиентских операций.',
    outcome_statement: 'Сервис переведен на новую инфраструктуру',
    success_criteria: 'Миграция завершена без потери данных',
    constraints: null,
    baseline_outcome_statement: 'Сервис переведен на новую инфраструктуру',
    baseline_success_criteria: 'Миграция завершена без потери данных',
    baseline_constraints: null,
    status: 'active',
    visibility: 'private',
    starts_at: '2026-08-01T00:00:00Z',
    due_at: '2026-08-10T23:59:59Z',
    target_due_at: '2026-08-10T23:59:59Z',
    forecast_starts_at: '2026-08-01T00:00:00Z',
    forecast_due_at: '2026-08-15T23:59:59Z',
    actual_starts_at: null,
    actual_due_at: null,
    planning_mode: 'guided',
    methodology_title: null,
    methodology_version: null,
    methodology_snapshot: null,
    baseline_locked_at: '2026-08-01T08:00:00Z',
    baseline_locked_by_id: testUser.id,
    schedule_revision: 1,
    tags: [],
    details_json: null,
    archived_at: null,
    access_role: 'owner',
    members_count: 3,
    links_count: 1,
    stages_count: 2,
    tasks_count: 7,
    milestones_count: 3,
    artifacts_count: 2,
    created_at: '2026-08-01T08:00:00Z',
    updated_at: '2026-08-05T08:00:00Z',
    ...overrides,
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

test('admin user modal only protects the page while it is open', async ({ page }) => {
  await installApiMock(page)
  await page.goto('/admin/users')
  await expect(page.getByRole('heading', { name: 'Сотрудники' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('')

  await page.getByRole('button', { name: 'Добавить сотрудника' }).click()
  const dialog = page.getByRole('dialog', { name: 'Добавить сотрудника' })
  await expect(dialog).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('hidden')

  await dialog.getByLabel('ФИО *').fill('Проверка защищенной модалки')
  await dialog.click({ position: { x: 2, y: 2 } })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('ФИО *')).toHaveValue('Проверка защищенной модалки')

  await dialog.getByRole('button', { name: 'Отмена' }).click()
  await expect(dialog).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe('')
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

test('project portfolio exposes lifecycle and escalation status before opening a project', async ({ page }) => {
  const activeProject = portfolioEntity({})
  const draftProject = portfolioEntity({
    id: '33333333-3333-4333-8333-333333333333',
    title: 'Новая продуктовая инициатива',
    status: 'draft',
    baseline_locked_at: null,
    forecast_due_at: '2026-09-20T23:59:59Z',
    target_due_at: '2026-09-20T23:59:59Z',
  })
  const archivedProject = portfolioEntity({
    id: '44444444-4444-4444-8444-444444444444',
    title: 'Завершенная программа',
    status: 'archived',
    archived_at: '2026-07-01T08:00:00Z',
  })
  await installApiMock(page, true, {
    '/api/contacts': [],
    '/api/work-entities': [activeProject, draftProject, archivedProject],
    [`/api/work-entities/${portfolioProjectId}/links`]: [],
    [`/api/work-entities/${portfolioProjectId}/summary`]: {
      entity_id: portfolioProjectId,
      accessible_links: 0,
      restricted_links: 0,
      native_tasks: 7,
      artifacts: 2,
      work_items_total: 10,
      work_items_done: 3,
      overdue_items: 1,
      next_due_at: '2026-08-10T23:59:59Z',
      counts_by_type: {},
      counts_by_status: {},
    },
    [`/api/work-entities/${portfolioProjectId}/readiness`]: {
      entity_id: portfolioProjectId,
      can_activate: false,
      blocking_count: 0,
      warning_count: 0,
      issues: [],
    },
    [`/api/work-entities/${portfolioProjectId}/members`]: [],
    [`/api/work-entities/${portfolioProjectId}/events`]: [],
    [`/api/work-entities/${portfolioProjectId}/workspace`]: {
      entity_id: portfolioProjectId,
      current_access_role: 'owner',
      participants: [],
      stages: [],
      tasks: [],
      milestones: [],
      dependencies: [],
      artifacts: [],
    },
  })

  await page.goto('/work-entities')
  await expect(page.getByRole('heading', { name: 'Проекты и цели' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Обзор проектов и целей' })).toBeVisible()
  await expect(page.getByText('Миграция клиентского сервиса', { exact: true })).toBeVisible()
  const activeProjectRow = page.getByRole('button', {
    name: /Открыть проект Миграция клиентского сервиса/,
  })
  await expect(activeProjectRow).toContainText('Нужна эскалация')
  await expect(page.getByText('Новая продуктовая инициатива', { exact: true })).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await activeProjectRow.click()
  await expect(page).toHaveURL(new RegExp(`work-entities\\?entity=${portfolioProjectId}`))
  const status = page.getByLabel('Статус выбранного проекта')
  await expect(status.getByText('Активно', { exact: true })).toBeVisible()
  await expect(status.getByText('Нужна эскалация', { exact: true })).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await page.goBack()
  await expect(page.getByRole('region', { name: 'Обзор проектов и целей' })).toBeVisible()
})
