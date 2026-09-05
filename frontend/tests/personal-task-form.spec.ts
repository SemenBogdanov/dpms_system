import { expect, test, type Page } from '@playwright/test'

const user = {
  id: '11111111-1111-4111-8111-111111111166', full_name: 'Тест формы ID 66', email: 'id66@example.com',
  role: 'executor', league: 'A', is_active: true, is_new_employee: false, task_workspace_enabled: true,
  needs_password_change: false, sidebar_menu_order: null, wallet_main: 0, wallet_karma: 0,
  quality_score: 100, mpw: 0, wip_limit: 5,
}
const noteId = '22222222-2222-4222-8222-222222222266'
const task = {
  id: '33333333-3333-4333-8333-333333333366', task_key: 'PT-66', task_number: 66, owner_id: user.id,
  title: 'Подготовить материалы', description: 'Полное описание', notes: 'Рабочие записи',
  status: 'waiting', priority: 'high', category: 'research', project: 'Проект 66', context: 'Совещание',
  responsible: 'Владелец', tags: ['проверка', 'документы'], acceptance_criteria: 'Материалы приняты',
  next_step: 'Получить согласование', next_step_at: '2026-09-10T09:00:00.000Z',
  start_at: '2026-09-01T09:00:00.000Z', due_at: '2026-09-30T09:00:00.000Z',
  waiting_for: 'Ответ коллеги', blocked_reason: null, impact: 4, effort: 2,
  source_quick_note_id: noteId, promoted_task_id: null, linked_task_id: null, promoted_at: null,
  promoted_task: null, execution_task: null, created_at: '2026-09-01T09:00:00.000Z', updated_at: '2026-09-01T09:00:00.000Z',
}

type Write = { method: string; body: Record<string, unknown> }
type Reply = { status: number; body: unknown }

async function mockApi(page: Page, options: { edit?: boolean; reply?: Reply; hold?: Promise<void>; abort?: boolean } = {}) {
  const writes: Write[] = []
  await page.routeWebSocket('**/api/**', () => {})
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'id66-test-fixture'))
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path === '/api/auth/me') return respond(user)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/note-groups/backlinks') return respond({ notes: [{ id: noteId, title: 'Связанная заметка ID66' }], groups: [] })
    if (path === '/api/quick-notes') return respond(options.edit ? [] : [{ id: noteId, title: 'Источник '.repeat(40), status: 'draft' }])
    if (path === '/api/personal-tasks' || path === `/api/personal-tasks/${task.id}`) {
      if (request.method() !== 'GET') {
        writes.push({ method: request.method(), body: request.postDataJSON() })
        await options.hold
        if (options.abort) return route.abort('connectionfailed')
        if (options.reply) return respond(options.reply.body, options.reply.status)
        return respond({ ...task, ...request.postDataJSON() })
      }
      return respond(options.edit ? [task] : [])
    }
    return respond(request.method() === 'GET' ? [] : {})
  })
  return writes
}

async function openCreate(page: Page) {
  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: 'Новая задача', exact: true }).click()
  return page.getByRole('dialog', { name: 'Новая личная задача' })
}

test.beforeEach(async ({ page }, testInfo) => {
  const theme = testInfo.project.name.includes('dark') ? 'dark' : testInfo.project.name.includes('rose') ? 'rose' : 'light'
  await page.addInitScript((value) => localStorage.setItem('dpms-theme', value), theme)
})

test('lost write response preserves the draft and blocks ambiguous retry', async ({ page }) => {
  const writes = await mockApi(page, { abort: true })
  const dialog = await openCreate(page)
  await dialog.getByLabel('Название', { exact: true }).fill('Проверить неизвестный результат')
  const submit = dialog.getByRole('button', { name: 'Создать задачу', exact: true })
  await submit.click()
  await expect(dialog.getByText(/Изменения могли сохраниться/)).toBeVisible()
  await expect(submit).toBeDisabled()
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Проверить неизвестный результат')
  await dialog.getByLabel('Название', { exact: true }).fill('Уточненный черновик')
  await expect(dialog.getByText(/Изменения могли сохраниться/)).toBeVisible()
  await expect(submit).toBeDisabled()
  await dialog.locator('form').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  expect(writes).toHaveLength(1)
})

test('compact core, full details, Inbox-only create, long text and responsive framing', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const writes = await mockApi(page)
  const dialog = await openCreate(page)
  await expect(dialog.getByLabel('Название', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Следующий шаг', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Срок', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Статус', { exact: true })).toHaveCount(0)
  await expect(dialog.getByLabel('Проект / поток')).not.toBeVisible()
  await expect(dialog.getByLabel('Кого / чего ждем')).toHaveCount(0)
  await expect(dialog.getByLabel('Причина блокировки')).toHaveCount(0)
  await dialog.getByLabel('Название', { exact: true }).fill('Подготовить подробный комплект '.repeat(5))
  await dialog.getByLabel('Следующий шаг', { exact: true }).fill('Согласовать'.repeat(35))
  await dialog.getByLabel('Срок', { exact: true }).fill('2027-01-20T18:00')
  const frame = await dialog.boundingBox()
  const viewport = page.viewportSize()!
  expect(frame!.width).toBeLessThanOrEqual(viewport.width < 640 ? viewport.width : 576)
  expect(Math.abs(frame!.x + frame!.width - viewport.width)).toBeLessThanOrEqual(1)
  expect(Math.abs(frame!.height - viewport.height)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: testInfo.outputPath('core.png') })
  await dialog.getByText('Дополнительно', { exact: true }).click()
  await dialog.getByLabel('Проект / поток').fill('Проект '.repeat(20))
  await dialog.getByLabel('Описание', { exact: true }).fill('Длинныйтекст'.repeat(200))
  await dialog.getByLabel('Источник: заметка').selectOption(noteId)
  await expect(dialog.getByLabel('Источник: заметка')).toHaveValue(noteId)
  const dimensions = await dialog.evaluate((element) => ({
    page: document.documentElement.scrollWidth,
    viewport: innerWidth,
    body: element.querySelector('fieldset')!.scrollWidth,
    width: element.querySelector('fieldset')!.clientWidth,
    inputSize: getComputedStyle(element.querySelector('input')!).fontSize,
  }))
  expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport + 1)
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.width + 1)
  if (viewport.width < 640) expect(parseFloat(dimensions.inputSize)).toBeGreaterThanOrEqual(16)
  await page.screenshot({ path: testInfo.outputPath('details.png') })
  await dialog.getByRole('button', { name: 'Создать задачу' }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toMatchObject({ status: 'inbox', waiting_for: null, blocked_reason: null, source_quick_note_id: noteId })
  expect(writes[0].body).not.toHaveProperty('linked_task_id')
  expect(errors).toEqual([])
})

test('dirty backdrop, Escape, Tab trap, explicit discard and focus restoration', async ({ page }) => {
  await mockApi(page)
  const dialog = await openCreate(page)
  await dialog.getByLabel('Название', { exact: true }).fill('Не потерять черновик')
  await page.keyboard.press('Escape')
  await page.getByTestId('personal-form-backdrop').dispatchEvent('pointerdown')
  await page.getByTestId('personal-form-backdrop').dispatchEvent('click')
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Не потерять черновик')
  await dialog.getByLabel('Срок', { exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.locator('summary')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog.getByLabel('Проект / поток')).toBeVisible()
  await dialog.getByRole('button', { name: 'Создать задачу' }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Закрыть форму' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Закрыть форму' }).click()
  const discard = page.getByRole('alertdialog', { name: 'Отменить изменения?' })
  await discard.getByRole('button', { name: 'Продолжить заполнение' }).click()
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await discard.getByRole('button', { name: 'Отменить изменения', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Новая задача', exact: true })).toBeFocused()
})

test('dirty router navigation, browser Back and reload keep the draft on cancellation', async ({ page }) => {
  await mockApi(page)
  await page.goto('/messages')
  const taskLink = page.locator('a[href="/personal-tasks"]').first()
  await taskLink.waitFor({ state: 'attached' })
  await taskLink.evaluate((element: HTMLAnchorElement) => element.click())
  await page.getByRole('button', { name: 'Новая задача', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новая личная задача' })
  await dialog.getByLabel('Название', { exact: true }).fill('Сохранить при навигации')
  const index = await page.evaluate(() => history.state.idx)
  const messageLink = page.locator('a[href="/messages"]').first()
  await messageLink.evaluate((element: HTMLAnchorElement) => element.click())
  const discard = page.getByRole('alertdialog', { name: 'Отменить изменения?' })
  await discard.getByRole('button', { name: 'Продолжить заполнение' }).click()
  await expect(page).toHaveURL(/\/personal-tasks$/)
  await page.evaluate(() => history.back())
  await discard.getByRole('button', { name: 'Продолжить заполнение' }).click()
  await expect.poll(() => page.evaluate(() => history.state.idx)).toBe(index)
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Сохранить при навигации')
  const unloadBlocked = await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
  expect(unloadBlocked).toBe(true)
  await page.evaluate(() => history.back())
  await discard.getByRole('button', { name: 'Отменить изменения', exact: true }).click()
  await expect(page).toHaveURL(/\/messages$/)
  await expect(dialog).toHaveCount(0)
})

test('synchronous duplicate submit is locked and pending writes cannot be dismissed', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>((resolve) => { release = resolve })
  const writes = await mockApi(page, { hold })
  const dialog = await openCreate(page)
  await dialog.getByLabel('Название', { exact: true }).fill('Только один запрос')
  await dialog.locator('form').evaluate((element) => {
    element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
  await expect.poll(() => writes.length).toBe(1)
  await expect(dialog.getByRole('button', { name: 'Создать задачу' })).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Закрыть форму' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  release()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(1)
})

test('edit preserves every field and a source absent from draft notes; status context is conditional', async ({ page }) => {
  const writes = await mockApi(page, { edit: true })
  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: task.title, exact: true }).click()
  await expect(page.getByRole('region', { name: 'Связанные заметки' }).getByRole('link', { name: 'Связанная заметка ID66' })).toHaveAttribute('href', `/quick-notes/${noteId}`)
  await page.getByRole('button', { name: 'Редактировать задачу', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Редактирование PT-66' })
  await expect(dialog.getByLabel('Кого / чего ждем')).toHaveValue(task.waiting_for)
  await expect(dialog.getByLabel('Причина блокировки')).toHaveCount(0)
  await dialog.getByLabel('Статус', { exact: true }).selectOption('blocked')
  await expect(dialog.getByLabel('Кого / чего ждем')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByLabel('Причина блокировки')).toBeFocused()
  expect(writes).toHaveLength(0)
  await dialog.getByLabel('Статус', { exact: true }).selectOption('waiting')
  await expect(dialog.getByLabel('Кого / чего ждем')).toHaveValue(task.waiting_for)
  await dialog.getByText('Дополнительно', { exact: true }).click()
  await expect(dialog.getByLabel('Источник: заметка')).toHaveValue(noteId)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(1)
  expect(writes[0].method).toBe('PATCH')
  await expect(page.getByRole('button', { name: 'Редактировать задачу', exact: true })).toBeFocused()
  for (const [name, value] of Object.entries(writes[0].body)) {
    expect(value, name).toEqual(task[name as keyof typeof task])
  }
  expect(Object.keys(writes[0].body)).toHaveLength(20)
  expect(writes[0].body).not.toHaveProperty('linked_task_id')
  await expect(page.getByRole('button', { name: 'Добавить этап контроля', exact: true })).toBeVisible()
})

test('local validation and flattened 422 appear at fields and reveal hidden details', async ({ page }) => {
  const writes = await mockApi(page, { reply: { status: 422, body: { detail: [
    { loc: ['body', 'project'], msg: 'Проект больше не доступен' },
    { loc: ['body', 'context'], msg: 'Проверьте контекст' },
  ] } } })
  const dialog = await openCreate(page)
  await dialog.getByRole('button', { name: 'Создать задачу' }).click()
  await expect(dialog.getByLabel('Название', { exact: true })).toBeFocused()
  await expect(dialog.getByText('Укажите название', { exact: true })).toBeVisible()
  expect(writes).toHaveLength(0)
  await dialog.getByLabel('Название', { exact: true }).fill('Поправить поля')
  await dialog.getByLabel('Срок', { exact: true }).fill('2020-01-01T09:00')
  await dialog.getByRole('button', { name: 'Создать задачу' }).click()
  await expect(dialog.getByLabel('Срок', { exact: true })).toBeFocused()
  expect(writes).toHaveLength(0)
  await dialog.getByLabel('Срок', { exact: true }).fill('')
  await dialog.getByRole('button', { name: 'Создать задачу' }).click()
  await expect(dialog.getByLabel('Проект / поток')).toBeFocused()
  await expect(dialog.getByText('Проект больше не доступен', { exact: true })).toBeVisible()
  await dialog.getByLabel('Проект / поток').pressSequentially('Проект')
  await expect(dialog.getByLabel('Проект / поток')).toBeFocused()
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Поправить поля')
})

test('409 Q handoff error is adjacent to status without losing edit values', async ({ page }) => {
  await mockApi(page, { edit: true, reply: { status: 409, body: { detail: 'Связанная задача Q недоступна для проверки. Локальный старт заблокирован, чтобы не создать двойное выполнение.' } } })
  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: task.title, exact: true }).click()
  await page.getByRole('button', { name: 'Редактировать задачу', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Редактирование PT-66' })
  await dialog.getByLabel('Статус', { exact: true }).selectOption('in_progress')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByLabel('Статус', { exact: true })).toBeFocused()
  await expect(dialog.getByLabel('Статус', { exact: true })).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.getByText(/Связанная задача Q недоступна/)).toBeVisible()
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue(task.title)
})
