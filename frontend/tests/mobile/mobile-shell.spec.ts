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
  responses: Record<string, unknown | ((route: Route) => Promise<void>)> = {},
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
    if (pathname === '/api/storage-quota/me') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          quota_bytes: 50 * 1024 * 1024,
          used_bytes: 0,
          reserved_bytes: 0,
          available_bytes: 50 * 1024 * 1024,
          usage_percent: 0,
          warning_level: 'normal',
          warning_message: 'Свободного места достаточно.',
          pending_request: null,
        }),
      })
      return
    }
    if (Object.prototype.hasOwnProperty.call(responses, pathname)) {
      const response = responses[pathname]
      if (typeof response === 'function') {
        await response(route)
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(response),
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
const personalTaskId = '55555555-5555-4555-8555-555555555555'

const personalTask = {
  id: personalTaskId,
  task_number: 1058,
  task_key: 'PT-1058',
  owner_id: testUser.id,
  title: 'Подготовить комплект материалов',
  description: 'Собрать документы и итоговый результат.',
  notes: null,
  status: 'in_progress',
  priority: 'high',
  category: 'work',
  project: 'Демонстрация ID 58',
  context: null,
  responsible: 'Мобильный тест',
  tags: ['demo'],
  acceptance_criteria: 'Комплект доступен в задаче и имеет историю версий.',
  next_step: 'Добавить итоговую презентацию',
  next_step_at: '2026-08-12T09:00:00Z',
  start_at: '2026-08-10T09:00:00Z',
  due_at: '2026-08-14T18:00:00Z',
  waiting_for: null,
  blocked_reason: null,
  impact: 4,
  effort: 2,
  linked_task_id: null,
  source_quick_note_id: null,
  promoted_task_id: null,
  promoted_at: null,
  promoted_task: null,
  execution_task: null,
  created_at: '2026-08-10T09:00:00Z',
  updated_at: '2026-08-10T09:00:00Z',
}

const acceptanceTaskId = '88888888-8888-4888-8888-888888888888'
const acceptanceCriterionId = '99999999-9999-4999-8999-999999999999'
const delegatedPersonalTaskId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const delegatedQueueTaskId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const delegatedExecutorId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'

const acceptanceTask = {
  id: acceptanceTaskId,
  task_number: 2042,
  title: 'Проверить защиту черновика приемки',
  description: 'Сценарий безопасной сдачи результата по критериям.',
  task_type: 'docs',
  complexity: 'S',
  estimated_q: 3,
  priority: 'medium',
  status: 'in_progress',
  min_league: 'C',
  assignee_id: testUser.id,
  estimator_id: testUser.id,
  acceptance_owner_id: testUser.id,
  acceptance_mode: 'criteria',
  acceptance_state: 'none',
  acceptance_revision: 1,
  acceptance_total_count: 1,
  acceptance_required_count: 1,
  acceptance_accepted_count: 0,
  acceptance_required_accepted_count: 0,
  acceptance_submitted_count: 0,
  acceptance_returned_count: 0,
  validator_id: null,
  estimation_details: null,
  result_url: null,
  result_comment: null,
  brief_rating: null,
  brief_feedback: null,
  rejection_comment: null,
  started_at: '2026-08-11T08:00:00Z',
  completed_at: null,
  validated_at: null,
  due_date: '2026-08-15T18:00:00Z',
  sla_hours: null,
  is_overdue: false,
  parent_task_id: null,
  deadline_zone: 'green',
  tags: ['ux-safety'],
  rejection_count: 0,
  created_at: '2026-08-11T08:00:00Z',
  updated_at: '2026-08-11T08:00:00Z',
  focus_started_at: null,
  active_seconds: 0,
  active_hours: 0,
  is_focused: false,
}

const acceptancePlan = {
  task_id: acceptanceTaskId,
  mode: 'criteria',
  state: 'none',
  revision: 1,
  owner_id: testUser.id,
  owner_name: testUser.full_name,
  locked: true,
  can_manage_plan: false,
  can_submit: true,
  can_review: false,
  criteria: [
    {
      id: acceptanceCriterionId,
      task_id: acceptanceTaskId,
      position: 1,
      title: 'Приложен проверяемый результат',
      description: null,
      kind: 'required',
      status: 'pending',
      evidence_comment: null,
      evidence_url: null,
      reviewer_comment: null,
      submitted_at: null,
      reviewed_at: null,
      baseline_revision: 1,
      return_count: 0,
      decision_change_count: 0,
      events: [],
    },
  ],
}

const delegatedQueueTask = {
  ...acceptanceTask,
  id: delegatedQueueTaskId,
  task_number: 3042,
  title: 'Исполнить делегированный результат',
  acceptance_mode: 'full',
  acceptance_total_count: 0,
  acceptance_required_count: 0,
  assignee_id: delegatedExecutorId,
}

const delegatedPersonalTask = {
  ...personalTask,
  id: delegatedPersonalTaskId,
  task_number: 1059,
  task_key: 'PT-1059',
  title: 'Контролировать делегированный результат',
  status: 'planned',
  linked_task_id: delegatedQueueTaskId,
  promoted_task_id: delegatedQueueTaskId,
  promoted_at: '2026-08-11T09:00:00Z',
  promoted_task: {
    id: delegatedQueueTaskId,
    task_number: 3042,
    status: 'in_progress',
    assignee_id: delegatedExecutorId,
    assignee_name: 'Другой исполнитель',
    started_at: '2026-08-11T09:00:00Z',
    due_date: '2026-08-15T18:00:00Z',
  },
  execution_task: {
    id: delegatedQueueTaskId,
    task_number: 3042,
    status: 'in_progress',
    assignee_id: delegatedExecutorId,
    assignee_name: 'Другой исполнитель',
    started_at: '2026-08-11T09:00:00Z',
    due_date: '2026-08-15T18:00:00Z',
  },
}

function acceptanceResponses() {
  return {
    '/api/tasks': [acceptanceTask],
    '/api/users': [testUser],
    [`/api/users/${testUser.id}/run-rate`]: null,
    [`/api/users/${testUser.id}/progress`]: null,
    '/api/deadline-trackers': [],
    '/api/shop/approvals': [],
    [`/api/tasks/${acceptanceTaskId}/attachments`]: [],
    [`/api/tasks/${acceptanceTaskId}/review-events`]: [],
    [`/api/tasks/${acceptanceTaskId}/acceptance`]: acceptancePlan,
    [`/api/tasks/${acceptanceTaskId}`]: acceptanceTask,
  }
}

const personalTaskArtifact = {
  id: '66666666-6666-4666-8666-666666666666',
  task_id: personalTaskId,
  artifact_type: 'document',
  title: 'Паспорт проекта',
  description: 'Согласованная рабочая версия',
  status: 'active',
  current_version: 1,
  created_by_id: testUser.id,
  updated_by_id: testUser.id,
  archived_at: null,
  created_at: '2026-08-10T10:00:00Z',
  updated_at: '2026-08-10T10:00:00Z',
  can_edit: true,
  versions: [
    {
      id: '77777777-7777-4777-8777-777777777777',
      artifact_id: '66666666-6666-4666-8666-666666666666',
      version_number: 1,
      source_kind: 'file',
      url: null,
      original_filename: 'passport.pdf',
      content_type: 'application/pdf',
      size_bytes: 8192,
      sha256: 'a'.repeat(64),
      change_note: 'Первая версия',
      created_by_id: testUser.id,
      created_at: '2026-08-10T10:00:00Z',
    },
  ],
}

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
    'Сообщения',
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

test('personal task materials remain usable and protected on mobile', async ({ page }) => {
  await installApiMock(page, true, {
    '/api/personal-tasks': [personalTask],
    '/api/personal-tasks/deadlines': [],
    '/api/deadline-trackers': [],
    [`/api/personal-tasks/${personalTaskId}/events`]: [],
    [`/api/personal-tasks/${personalTaskId}/checkpoints`]: [],
    [`/api/personal-tasks/${personalTaskId}/artifacts`]: [personalTaskArtifact],
  })

  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: personalTask.title }).click()
  const materialsHeading = page.getByRole('heading', { name: 'Материалы' })
  await expect(materialsHeading).toBeVisible()
  await expect(page.getByText('Паспорт проекта', { exact: true })).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await page.getByRole('button', { name: 'Добавить материал' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Новый материал' })).toBeVisible()
  await dialog.getByLabel('Тип').selectOption('result')
  await dialog.getByRole('button', { name: 'Ссылка' }).click()
  await dialog.getByLabel('Название').fill('Ссылка на итоговый результат')
  const urlInput = dialog.getByRole('textbox', { name: 'URL' })
  await urlInput.fill('https://example.com/result')

  await dialog.click({ position: { x: 2, y: 2 } })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('Название')).toHaveValue('Ссылка на итоговый результат')
  await expect(urlInput).toHaveValue('https://example.com/result')
  await assertNoHorizontalOverflow(page)

  await dialog.getByRole('button', { name: 'Отмена' }).click()
  await expect(dialog).toHaveCount(0)
})

test('delegated Q execution has no parallel-start override', async ({ page }) => {
  const personalTaskPatches: unknown[] = []
  page.on('request', (request) => {
    if (
      request.method() === 'PATCH'
      && new URL(request.url()).pathname === `/api/personal-tasks/${delegatedPersonalTaskId}`
    ) {
      personalTaskPatches.push(request.postDataJSON())
    }
  })
  await installApiMock(page, true, {
    '/api/personal-tasks': [delegatedPersonalTask],
    '/api/personal-tasks/deadlines': [],
    '/api/deadline-trackers': [],
    [`/api/personal-tasks/${delegatedPersonalTaskId}`]: delegatedPersonalTask,
    [`/api/personal-tasks/${delegatedPersonalTaskId}/events`]: [],
    [`/api/personal-tasks/${delegatedPersonalTaskId}/checkpoints`]: [],
    [`/api/personal-tasks/${delegatedPersonalTaskId}/artifacts`]: [],
    '/api/queue': [],
    '/api/tasks': [delegatedQueueTask],
    [`/api/tasks/${delegatedQueueTaskId}`]: delegatedQueueTask,
    [`/api/tasks/${delegatedQueueTaskId}/attachments`]: [],
    [`/api/tasks/${delegatedQueueTaskId}/review-events`]: [],
    '/api/users': [testUser],
  })

  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: 'Начать работу над задачей' }).click()

  await expect(page.getByText('Выполнение этой работы уже передано в Q-задачу.')).toBeVisible()
  await expect(page.getByText('Другой исполнитель · В работе.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Все равно начать' })).toHaveCount(0)
  const openQueueButton = page.getByRole('button', { name: 'Открыть Q #3042' })
  await expect(openQueueButton).toBeVisible()
  await assertNoHorizontalOverflow(page)
  expect(personalTaskPatches).toEqual([])

  await openQueueButton.click()
  await expect(page).toHaveURL(new RegExp(`/queue\\?task=${delegatedQueueTaskId}`))
})

test('delegated Q execution handoff blocks local start while waiting in_queue', async ({ page }) => {
  const queuedPersonalTaskId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
  const queuedQueueTaskId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
  const queuedQueueTaskNumber = 5077
  const queuedPersonalTask = {
    ...personalTask,
    id: queuedPersonalTaskId,
    task_number: queuedQueueTaskNumber,
    task_key: `PT-${queuedQueueTaskNumber}`,
    title: 'Ожидает вывода результата через глобальную очередь',
    status: 'planned',
    linked_task_id: queuedQueueTaskId,
    promoted_task_id: queuedQueueTaskId,
    promoted_at: '2026-08-11T09:00:00Z',
    promoted_task: {
      id: queuedQueueTaskId,
      task_number: queuedQueueTaskNumber,
      status: 'in_queue',
      assignee_id: null,
      assignee_name: null,
      started_at: null,
      due_date: '2026-08-15T18:00:00Z',
    },
    execution_task: {
      id: queuedQueueTaskId,
      task_number: queuedQueueTaskNumber,
      status: 'in_queue',
      assignee_id: null,
      assignee_name: null,
      started_at: null,
      due_date: '2026-08-15T18:00:00Z',
    },
  }
  const queuedQueueTask = {
    ...delegatedQueueTask,
    id: queuedQueueTaskId,
    task_number: queuedQueueTaskNumber,
    title: 'Ожидает исполнителя в очереди',
    status: 'in_queue',
    assignee_id: null,
  }

  const personalTaskPatches: unknown[] = []
  page.on('request', (request) => {
    if (
      request.method() === 'PATCH'
      && new URL(request.url()).pathname === `/api/personal-tasks/${queuedPersonalTaskId}`
    ) {
      personalTaskPatches.push(request.postDataJSON())
    }
  })
  await installApiMock(page, true, {
    '/api/personal-tasks': [queuedPersonalTask],
    '/api/personal-tasks/deadlines': [],
    '/api/deadline-trackers': [],
    [`/api/personal-tasks/${queuedPersonalTaskId}`]: queuedPersonalTask,
    [`/api/personal-tasks/${queuedPersonalTaskId}/events`]: [],
    [`/api/personal-tasks/${queuedPersonalTaskId}/checkpoints`]: [],
    [`/api/personal-tasks/${queuedPersonalTaskId}/artifacts`]: [],
    '/api/queue': [],
    '/api/tasks': [queuedQueueTask],
    [`/api/tasks/${queuedQueueTaskId}`]: queuedQueueTask,
    [`/api/tasks/${queuedQueueTaskId}/attachments`]: [],
    [`/api/tasks/${queuedQueueTaskId}/review-events`]: [],
    '/api/users': [testUser],
  })

  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: 'Начать работу над задачей' }).click()

  await expect(page.getByText('Личная задача уже опубликована в Q-очереди.')).toBeVisible()
  await expect(page.getByText('Исполнитель не указан · В глобальной очереди.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Все равно начать' })).toHaveCount(0)
  const openQueueButton = page.getByRole('button', { name: `Открыть Q #${queuedQueueTaskNumber}` })
  await expect(openQueueButton).toBeVisible()
  await assertNoHorizontalOverflow(page)
  expect(personalTaskPatches).toEqual([])
})

test('acceptance draft survives navigation and requires explicit discard', async ({ page }) => {
  await installApiMock(page, true, acceptanceResponses())

  await page.goto('/my-tasks')
  const restoredTaskTrigger = page.getByRole('button', { name: acceptanceTask.title }).first()
  await restoredTaskTrigger.click()
  const criterion = page.getByRole('checkbox', { name: `Выбрать критерий: ${acceptancePlan.criteria[0].title}` })
  await criterion.check()
  const comment = page.getByLabel(`Комментарий к результату: ${acceptancePlan.criteria[0].title}`)
  await comment.fill('Проверяемый результат приложен к задаче')
  await expect.poll(() => page.evaluate(
    (taskId) => window.sessionStorage.getItem(`dpms:acceptance-draft:${taskId}`),
    acceptanceTaskId,
  )).not.toBeNull()

  await page.goto('/my-tasks?draft_roundtrip=1')
  await page.getByRole('button', { name: acceptanceTask.title }).first().click()
  const restoredCriterion = page.getByRole('checkbox', { name: `Выбрать критерий: ${acceptancePlan.criteria[0].title}` })
  await expect(restoredCriterion).toBeChecked()
  const restoredComment = page.getByLabel(`Комментарий к результату: ${acceptancePlan.criteria[0].title}`)
  await expect(restoredComment).toHaveValue('Проверяемый результат приложен к задаче')
  await assertNoHorizontalOverflow(page)

  await page.keyboard.press('Escape')
  const discardDialog = page.getByRole('alertdialog', { name: 'Есть несохраненные данные приемки' })
  await expect(discardDialog).toBeVisible()
  const continueButton = discardDialog.getByRole('button', { name: 'Продолжить редактирование' })
  const discardButton = discardDialog.getByRole('button', { name: 'Удалить черновик и закрыть' })
  await expect(continueButton).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(discardButton).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(continueButton).toBeFocused()
  await continueButton.click()
  await expect(restoredComment).toBeFocused()
  await expect(restoredComment).toHaveValue('Проверяемый результат приложен к задаче')

  await page.getByRole('button', { name: 'Закрыть' }).first().click()
  await expect(discardDialog).toBeVisible()
  await discardDialog.getByRole('button', { name: 'Удалить черновик и закрыть' }).click()
  await expect(page.getByRole('heading', { name: acceptanceTask.title })).toHaveCount(0)
  await expect(restoredTaskTrigger).toBeFocused()
  await expect.poll(() => page.evaluate(
    (taskId) => window.sessionStorage.getItem(`dpms:acceptance-draft:${taskId}`),
    acceptanceTaskId,
  )).toBeNull()
})

test('acceptance loading failure is visible and retryable', async ({ page }) => {
  let attempts = 0
  await installApiMock(page, true, {
    ...acceptanceResponses(),
    [`/api/tasks/${acceptanceTaskId}/acceptance`]: async (route: Route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Временная ошибка загрузки приемки' }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(acceptancePlan),
      })
    },
  })

  await page.goto('/my-tasks')
  await page.getByRole('button', { name: acceptanceTask.title }).first().click()
  await expect(page.getByText('Критерии приемки не загрузились')).toBeVisible()
  await expect(page.getByText('Временная ошибка загрузки приемки')).toBeVisible()
  await page.getByRole('button', { name: 'Повторить загрузку' }).click()
  await expect(page.getByText(acceptancePlan.criteria[0].title, { exact: true })).toBeVisible()
  await assertNoHorizontalOverflow(page)
  expect(attempts).toBe(2)
})

test('acceptance revision change preserves the previous draft', async ({ page }) => {
  await installApiMock(page, true, acceptanceResponses())
  await page.addInitScript(
    ({ taskId, criterionId, criterionTitle, savedAt }) => {
      window.sessionStorage.setItem(`dpms:acceptance-draft:${taskId}`, JSON.stringify({
        savedAt,
        acceptanceRevision: 0,
        selected: [criterionId],
        evidence: {
          [criterionId]: { comment: 'Черновик для предыдущей версии', url: '' },
        },
        reviewComments: {},
        revisionCriterionId: null,
        revisionComments: {},
        criterionTitles: { [criterionId]: criterionTitle },
      }))
    },
    {
      taskId: acceptanceTaskId,
      criterionId: acceptanceCriterionId,
      criterionTitle: acceptancePlan.criteria[0].title,
      savedAt: Date.now(),
    },
  )

  await page.goto('/my-tasks')
  await page.getByRole('button', { name: acceptanceTask.title }).first().click()
  await expect(page.getByText('Критерии изменились после создания черновика')).toBeVisible()
  await expect(page.getByLabel(`Комментарий к результату: ${acceptancePlan.criteria[0].title}`)).toHaveValue(
    'Черновик для предыдущей версии',
  )
  await expect(page.getByRole('button', { name: 'Отправить выбранные' })).toBeDisabled()
  await assertNoHorizontalOverflow(page)

  await page.keyboard.press('Escape')
  const discardDialog = page.getByRole('alertdialog', { name: 'Есть несохраненные данные приемки' })
  await expect(discardDialog).toBeVisible()
  await discardDialog.getByRole('button', { name: 'Удалить черновик и закрыть' }).click()
})

test('acceptance stale refresh blocks duplicate submit and remains retryable', async ({ page }) => {
  let loadAttempts = 0
  let submitAttempts = 0
  await installApiMock(page, true, {
    ...acceptanceResponses(),
    [`/api/tasks/${acceptanceTaskId}/acceptance`]: async (route: Route) => {
      loadAttempts += 1
      if (loadAttempts === 2) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Не удалось обновить состояние после записи' }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(acceptancePlan),
      })
    },
    [`/api/tasks/${acceptanceTaskId}/acceptance/submit`]: async (route: Route) => {
      submitAttempts += 1
      await new Promise((resolve) => setTimeout(resolve, 250))
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    },
  })

  await page.goto('/my-tasks')
  await page.getByRole('button', { name: acceptanceTask.title }).first().click()
  await page.getByRole('checkbox', { name: `Выбрать критерий: ${acceptancePlan.criteria[0].title}` }).check()
  await page.getByLabel(`Комментарий к результату: ${acceptancePlan.criteria[0].title}`).fill('Готово к проверке')
  const submitButton = page.getByRole('button', { name: 'Отправить выбранные' })
  await submitButton.evaluate((element) => {
    element.click()
    element.click()
  })

  await page.keyboard.press('Escape')
  await expect(page.getByRole('alertdialog', { name: 'Есть несохраненные данные приемки' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: acceptanceTask.title })).toBeVisible()

  await expect(page.getByText('Не удалось обновить приемку')).toBeVisible()
  await expect(page.getByText(/Показаны данные от/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Отправить выбранные' })).toBeDisabled()
  expect(submitAttempts).toBe(1)

  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByText('Не удалось обновить приемку')).toHaveCount(0)
  expect(loadAttempts).toBe(3)
  expect(submitAttempts).toBe(1)
  await assertNoHorizontalOverflow(page)
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
