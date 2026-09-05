import { expect, test, type Page } from '@playwright/test'
import type { DeadlineTracker } from '../src/api/types'
import { newTrackerForm, trackerFormPayload, validateTrackerForm } from '../src/components/deadline-trackers/trackerForm'

const id = (n: number) => `11111111-1111-4111-8111-${String(n).padStart(12, '0')}`
const pageErrors = new WeakMap<Page, string[]>()
test.afterEach(async ({ page }) => { expect(pageErrors.get(page) || []).toEqual([]) })
const user = {
  id: id(1), full_name: 'Проверка трекеров', email: 'trackers@example.com', role: 'executor', league: 'A',
  mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100, is_active: true,
  is_new_employee: false, task_workspace_enabled: true, needs_password_change: false,
  can_link_queue_tasks_to_projects: false, feedback_enabled: false, audit_enabled: false,
  competency_development_enabled: false, competency_constructor_enabled: false,
  sidebar_menu_order: null, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
}

function tracker(number: number, patch: Partial<DeadlineTracker> = {}): DeadlineTracker {
  return {
    id: id(number), owner_id: user.id, title: `Трекер ${number}`, description: null, tracker_type: 'other', status: 'active',
    starts_at: '2026-09-01T09:00:00Z', due_at: '2027-01-01T09:00:00Z', pause_started_at: null,
    paused_seconds: 0, shifted_due_at: '2027-01-01T09:00:00Z', total_pause_seconds: 0, next_action: null,
    responsible: 'Старое свободное поле', tags: [], personal_task_id: null, linked_task_id: null,
    personal_task_key: null, personal_task_title: null, completed_at: null,
    created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
    group_id: id(10), category_id: id(20), url: null, recurrence: null, reminders: [], source: 'standalone', source_available: true,
    ...patch,
  }
}

const series = () => tracker(102, {
  title: 'Ежемесячная проверка', group_id: null,
  recurrence: { frequency: 'month', interval: 1, timezone: 'Europe/Moscow', end_type: 'count', count: 12 },
  current_occurrence: { id: id(202), sequence: 1, due_at: '2027-01-01T09:00:00Z', status: 'pending', completed_at: null },
})

async function mockApi(page: Page, options: { rows?: DeadlineTracker[]; archivedGroup?: boolean; exclude?: string; slowSearch?: boolean } = {}) {
  pageErrors.set(page, [])
  page.on('pageerror', (error) => pageErrors.get(page)?.push(error.message))
  await page.routeWebSocket(/.*/, () => {})
  const state = {
    rows: options.rows || [tracker(101), series()],
    groups: [{ id: id(10), name: 'Работа', color: '#0284c7', sort_order: 0, is_archived: Boolean(options.archivedGroup), is_collapsed: Boolean(options.archivedGroup) }],
    categories: [{ id: id(20), name: 'Оплата', color: null as string | null, sort_order: 0, is_archived: false, legacy_type: null as string | null }],
    calls: [] as Array<{ method: string; path: string; body: Record<string, unknown> }>,
    failNextWrite: 0,
    abortNextWrite: false,
    nextId: 1000,
  }
  await page.addInitScript(() => {
    localStorage.setItem('dpms_token', 'tracker-fixture-only')
    window.addEventListener('dpms:attention-refresh', () => document.documentElement.dataset.trackerAttentionRefreshed = 'true')
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const body = request.postData() ? request.postDataJSON() as Record<string, unknown> : {}
    state.calls.push({ method, path, body })
    const respond = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (path === '/api/auth/me') return respond(user)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/storage-quota/me') return respond({ quota_bytes: 50000000, used_bytes: 0, usage_percent: 0, warning_level: 'normal', pending_request: null })
    if (path === '/api/personal-tasks') return respond([{
      id: id(30), title: 'Задача-источник', task_key: 'PT-30', description: 'Контекст источника', responsible: 'Анна',
      status: 'planned', start_at: '2026-09-01T09:00:00Z', due_at: '2027-02-01T09:00:00Z',
    }])
    if (!path.startsWith('/api/deadline-trackers')) return respond([])
    if (method !== 'GET' && state.abortNextWrite) { state.abortNextWrite = false; return route.abort('failed') }
    if (method !== 'GET' && state.failNextWrite) { const status = state.failNextWrite; state.failNextWrite = 0; return respond({ detail: 'Проверьте название трекера' }, status) }
    const parts = path.slice('/api/deadline-trackers'.length).split('/').filter(Boolean)
    if (parts[0] === 'groups' || parts[0] === 'categories') {
      const kind = parts[0]
      const collection = state[kind]
      if (method === 'GET') return respond(collection)
      if (parts[1] === 'reorder') {
        for (const [index, identity] of (body.ids as string[]).entries()) { const row = collection.find((item) => item.id === identity); if (row) row.sort_order = index }
        return respond(collection)
      }
      if (parts.length === 1) {
        const row = { id: id(state.nextId++), name: String(body.name), color: body.color as string | null, sort_order: Number(body.sort_order || 0), is_archived: false, is_collapsed: false, legacy_type: null }
        collection.push(row)
        return respond(row)
      }
      const row = collection.find((item) => item.id === parts[1])
      if (!row) return respond({ detail: 'Запись недоступна' }, 404)
      if (method === 'PATCH') { Object.assign(row, body); return respond(row) }
      if (method === 'DELETE') {
        collection.splice(collection.indexOf(row), 1)
        for (const item of state.rows) {
          if (kind === 'groups' && item.group_id === row.id) item.group_id = null
          if (kind === 'categories' && item.category_id === row.id) item.category_id = null
        }
        return respond({ status: 'deleted' })
      }
    }
    if (!parts.length) {
      if (method === 'POST') {
        const row = tracker(state.nextId++, body as Partial<DeadlineTracker>)
        state.rows.push(row)
        await new Promise((resolve) => setTimeout(resolve, 150))
        return respond(row)
      }
      const query = url.searchParams.get('search')
      const rows = state.rows.filter((row) => row.id !== options.exclude
        && (!url.searchParams.get('status') || row.status === url.searchParams.get('status'))
        && (!url.searchParams.get('category_id') || row.category_id === url.searchParams.get('category_id'))
        && (!query || row.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())))
      const offset = Number(url.searchParams.get('offset') || 0)
      const snapshot = JSON.parse(JSON.stringify(rows.slice(offset, offset + 300)))
      if (options.slowSearch && query === 'Старый') await new Promise((resolve) => setTimeout(resolve, 1000))
      return respond(snapshot).catch(() => undefined)
    }
    const row = state.rows.find((item) => item.id === parts[0])
    if (!row) return respond({ detail: 'Трекер недоступен или удален' }, 404)
    if (parts[1] === 'alerts' && parts[2] === 'read') return respond({ marked: 1 })
    if (parts[1] === 'occurrences' && parts[3] === 'complete') {
      row.current_occurrence = { id: id(203), sequence: 2, status: 'pending', due_at: '2027-02-01T09:00:00Z', completed_at: null }
      row.updated_at = '2026-09-05T12:00:00Z'
      return respond(row)
    }
    if (parts[1] === 'finish-series') { row.status = 'done'; row.current_occurrence = null; return respond(row) }
    if (parts[1] === 'occurrences') return respond(row.current_occurrence ? [row.current_occurrence] : [])
    if (parts[1] === 'history') return respond([{ id: id(400), event_type: 'created', details: {}, created_at: '2026-09-01T00:00:00Z' }])
    if (parts[1] === 'alerts') return respond([{ id: id(500), occurrence_id: id(202), reminder_id: id(600), scheduled_for: '2026-09-01T09:00:00Z', status: 'sent', delivered_at: '2026-09-01T09:00:00Z', notification_id: id(700), is_read: true }])
    if (method === 'PATCH') { Object.assign(row, body); row.updated_at = new Date().toISOString(); return respond(row) }
    if (method === 'DELETE') { state.rows.splice(state.rows.indexOf(row), 1); return respond({ status: 'deleted' }) }
    return respond(row)
  })
  return state
}

async function assertNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1)
  const dialog = page.getByRole('dialog')
  if (await dialog.count()) expect(await dialog.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1)
}

test('form validation bounds recurrence and deduplicates equivalent reminder offsets', () => {
  const form = { ...newTrackerForm(), title: 'Проверка', startsAt: '2026-09-01T12:00', dueAt: '2027-01-31T12:00', mode: 'recurring' as const }
  expect(validateTrackerForm(form, false)).toEqual({})
  expect(validateTrackerForm({ ...form, interval: '1001', timezone: 'not/a-zone', end: 'count', count: '0' }, false)).toMatchObject({ interval: expect.any(String), timezone: expect.any(String), count: expect.any(String) })
  expect(validateTrackerForm({ ...form, reminders: [{ value: '1', unit: 'day' }, { value: '24', unit: 'hour' }] }, false)).toHaveProperty('reminder-1')
  expect(validateTrackerForm({ ...form, reminders: [{ value: '367', unit: 'day' }] }, false)).toHaveProperty('reminder-0')
  expect(validateTrackerForm({ ...form, url: 'javascript:alert(1)' }, false)).toHaveProperty('url')
  const payload = trackerFormPayload({ ...form, end: 'count', count: '12', reminders: [{ value: '1', unit: 'day' }] })
  expect(payload.recurrence).toEqual({ frequency: 'month', interval: 1, timezone: form.timezone, end_type: 'count', count: 12 })
  expect(payload).not.toHaveProperty('responsible')
  expect(payload).not.toHaveProperty('status')
})

test('protected recurring editor has field errors, max10 reminders and one submitted request', async ({ page }, testInfo) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Новый трекер', exact: true }).click()
  let dialog = page.getByRole('dialog', { name: 'Новый трекер срока' })
  await dialog.getByRole('button', { name: 'Создать трекер' }).click()
  await expect(dialog.getByText('Укажите название', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Название', { exact: true })).toBeFocused()
  await dialog.getByLabel('Название', { exact: true }).fill('Новая серия')
  await dialog.getByLabel('Старт периода', { exact: true }).fill('2026-09-01T12:00')
  await dialog.getByRole('button', { name: 'Периодический', exact: true }).click()
  await dialog.getByLabel('Первый срок', { exact: true }).fill('2027-01-31T12:00')
  await dialog.getByLabel('Окончание', { exact: true }).selectOption('count')
  await dialog.getByLabel('Число повторений', { exact: true }).fill('12')
  await dialog.getByRole('button', { name: 'Добавить напоминание' }).click()
  await dialog.getByRole('button', { name: 'Добавить напоминание' }).click()
  await dialog.getByRole('button', { name: 'Создать трекер' }).click()
  await expect(dialog.getByText('Эта точка уже добавлена')).toBeVisible()
  await dialog.getByLabel('Напоминание 2: единица').selectOption('hour')
  for (let index = 2; index < 10; index++) await dialog.getByRole('button', { name: 'Добавить напоминание' }).click()
  await expect(dialog.getByRole('button', { name: 'Добавить напоминание' })).toBeDisabled()
  for (let index = 10; index > 2; index--) await dialog.getByRole('button', { name: `Удалить напоминание ${index}`, exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await page.mouse.click(1, 1)
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Новая серия')
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  const discard = page.getByRole('alertdialog', { name: 'Несохраненные изменения трекера' })
  await expect(discard).toBeVisible()
  await discard.getByRole('button', { name: 'Продолжить редактирование' }).click()
  dialog = page.getByRole('dialog', { name: 'Новый трекер срока' })
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Новая серия')
  await expect(dialog.getByLabel('Ответственный', { exact: true })).toHaveCount(0)
  await assertNoOverflow(page)
  await page.screenshot({ path: testInfo.outputPath('recurring-editor.png'), animations: 'disabled' })
  await dialog.locator('form').evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit() })
  await expect(dialog).toHaveCount(0)
  const writes = state.calls.filter((call) => call.method === 'POST' && call.path === '/api/deadline-trackers')
  expect(writes).toHaveLength(1)
  expect(writes[0].body.recurrence).toMatchObject({ frequency: 'month', end_type: 'count', count: 12 })
  expect(writes[0].body.reminders).toEqual([{ value: 1, unit: 'day' }, { value: 1, unit: 'hour' }])
})

test('group CRUD, rename, reorder, collapse and archive-delete preserve trackers', async ({ page }, testInfo) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Группы', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Группы трекеров' })
  await dialog.getByLabel('Новая группа', { exact: true }).fill('Личные')
  await dialog.getByRole('button', { name: 'Зеленый', exact: true }).click()
  await dialog.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Переименовать Личные', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Переименовать Работа', exact: true }).click()
  await dialog.getByLabel('Новое название').fill('Рабочие сроки')
  await dialog.getByRole('button', { name: 'Сохранить название и цвет' }).click()
  await expect(dialog.getByRole('button', { name: 'Переименовать Рабочие сроки' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('group-manager.png'), animations: 'disabled' })
  const down = dialog.getByRole('button', { name: 'Ниже: Личные' })
  if (await down.isEnabled()) await down.click()
  else await dialog.getByRole('button', { name: 'Выше: Личные' }).click()
  await expect.poll(() => state.calls.some((call) => call.path.endsWith('/groups/reorder'))).toBe(true)
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await page.getByRole('button', { name: 'Свернуть Рабочие сроки' }).click()
  await expect(page.getByRole('button', { name: 'Развернуть Рабочие сроки' })).toBeVisible()
  await expect(page.locator('#deadline-tracker-' + id(101))).toHaveCount(0)
  await page.getByRole('button', { name: 'Развернуть Рабочие сроки' }).click()
  await expect(page.locator('#deadline-tracker-' + id(101))).toBeVisible()
  await page.getByRole('button', { name: 'Группы', exact: true }).click()
  page.once('dialog', (prompt) => prompt.accept())
  await dialog.getByRole('button', { name: 'Архивировать Рабочие сроки' }).click()
  await dialog.getByLabel('Показать архив').check()
  page.once('dialog', (prompt) => prompt.accept())
  await dialog.getByRole('button', { name: 'Удалить Рабочие сроки' }).click()
  await expect(dialog.getByRole('button', { name: 'Удалить Рабочие сроки' })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Без группы', exact: true }).locator('#deadline-tracker-' + id(101))).toBeVisible()
  expect(state.rows.some((row) => row.id === id(101))).toBe(true)
  expect(state.calls.some((call) => call.method === 'DELETE' && call.path === '/api/deadline-trackers/' + id(101))).toBe(false)
})

test('categories can be created renamed archived filtered and deleted without deleting trackers', async ({ page }) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Категории', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Категории трекеров' })
  await dialog.getByLabel('Новая категория').fill('Документы')
  await dialog.getByRole('button', { name: 'Создать', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Переименовать Документы' })).toBeVisible()
  await dialog.getByRole('button', { name: 'Переименовать Оплата' }).click()
  await dialog.getByLabel('Новое название').fill('Платежи')
  await dialog.getByRole('button', { name: 'Сохранить название и цвет' }).click()
  await expect(dialog.getByRole('button', { name: 'Архивировать Платежи' })).toBeVisible()
  page.once('dialog', (prompt) => prompt.accept())
  await dialog.getByRole('button', { name: 'Архивировать Платежи' }).click()
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  await page.getByLabel('Фильтр по категории').selectOption(id(20))
  await expect(page.locator('#deadline-tracker-' + id(101))).toContainText('Платежи')
  await expect(page.getByLabel('Фильтр по категории').locator('option:checked')).toHaveText('Платежи (архив)')
  expect(state.rows[0].category_id).toBe(id(20))
  await page.getByLabel('Фильтр по категории').selectOption('all')
  await page.getByRole('button', { name: 'Категории', exact: true }).click()
  await dialog.getByLabel('Показать архив').check()
  page.once('dialog', (prompt) => prompt.accept())
  await dialog.getByRole('button', { name: 'Удалить Платежи' }).click()
  await expect(dialog.getByRole('button', { name: 'Удалить Платежи' })).toHaveCount(0)
  expect(state.rows[0].category_id).toBeNull()
  expect(state.rows).toHaveLength(2)
})

test('linked source is read-only and update does not overwrite source dates or lifecycle', async ({ page }) => {
  const state = await mockApi(page, { rows: [tracker(101, { personal_task_id: id(30), personal_task_key: 'PT-30', source: 'personal_task', source_title: 'Задача-источник', source_responsible: 'Анна' })] })
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Редактировать трекер', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Редактирование трекера' })
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveAttribute('readonly', '')
  await expect(dialog.getByLabel('Старт периода', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Периодический', exact: true })).toBeDisabled()
  await expect(dialog.getByText('Исполнитель: Анна')).toBeVisible()
  await dialog.getByLabel('Группа', { exact: true }).selectOption('')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  const write = state.calls.find((call) => call.method === 'PATCH' && call.path.endsWith(id(101)))
  expect(write?.body).toEqual({ group_id: null })
})

test('recurrence completion leaves series active and finish-series is a distinct guarded call', async ({ page }) => {
  const state = await mockApi(page, { rows: [series()] })
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Завершить повторение', exact: true }).click()
  await expect(page.locator('#deadline-tracker-' + id(102))).toContainText('01.02.27')
  expect(state.rows[0].status).toBe('active')
  expect(state.calls.filter((call) => call.method === 'PATCH' && call.body.status === 'done')).toHaveLength(0)
  await page.getByRole('button', { name: 'История трекера', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Ежемесячная проверка' })
  await expect(dialog.getByRole('region', { name: 'История повторений' })).toContainText('#2')
  page.once('dialog', (prompt) => prompt.accept())
  await dialog.getByRole('button', { name: 'Завершить серию', exact: true }).click()
  await expect.poll(() => state.rows[0].status).toBe('done')
  expect(state.calls.filter((call) => call.path.endsWith('/finish-series'))).toHaveLength(1)
})

for (const exhausted of [true, undefined]) {
  test(`series without a pending occurrence is neutral: exhausted=${String(exhausted)}`, async ({ page }) => {
    const row = tracker(102, {
      title: 'Серия без текущего повторения', starts_at: '2024-01-01T09:00:00Z', due_at: '2025-01-01T09:00:00Z',
      recurrence: { frequency: 'year', interval: 1, timezone: 'Europe/Moscow', end_type: 'count', count: 1 },
      series_exhausted: exhausted,
      current_occurrence: exhausted ? null : { id: id(202), sequence: 1, due_at: '2025-01-01T09:00:00Z', status: 'completed', completed_at: '2025-01-01T09:00:00Z' },
    })
    const state = await mockApi(page, { rows: [row] })
    await page.goto('/deadline-trackers')
    const article = page.locator('#deadline-tracker-' + row.id)
    const expected = exhausted ? 'Повторения завершены' : 'Нет текущего повторения'
    for (const view of ['compact', 'full']) {
      if (view === 'full') await page.getByRole('button', { name: 'Полный вид', exact: true }).click()
      await expect(article.getByText(expected, { exact: true })).toBeVisible()
      await expect(article.getByText('срок', { exact: true })).toHaveCount(0)
      await expect(article.getByText(/просрочено на|осталось|Ближайший срок|01\.01\.25/)).toHaveCount(0)
      await expect(article.getByRole('button', { name: 'Завершить повторение', exact: true })).toHaveCount(0)
      await expect(article.getByRole('button', { name: 'Завершить серию', exact: true })).toBeVisible()
      await expect(page.getByText('просрочено', { exact: true }).locator('..').getByText('0', { exact: true })).toBeVisible()
    }
    await article.getByRole('button', { name: 'История трекера', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: row.title })
    await expect(dialog.getByText(expected, { exact: true })).toBeVisible()
    await expect(dialog.getByText('Ближайший срок', { exact: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Завершить повторение', exact: true })).toHaveCount(0)
    expect(state.rows[0].status).toBe('active')
    page.once('dialog', (prompt) => prompt.accept())
    await dialog.getByRole('button', { name: 'Завершить серию', exact: true }).click()
    await expect.poll(() => state.rows[0].status).toBe('done')
    expect(state.calls.filter((call) => call.path.endsWith('/finish-series'))).toHaveLength(1)
  })
}

test('annual series uses the pending frontier rather than the past anchor deadline', async ({ page }) => {
  const row = tracker(102, {
    title: 'Годовая проверка', starts_at: '2024-01-01T09:00:00Z', due_at: '2025-01-01T09:00:00Z',
    recurrence: { frequency: 'year', interval: 1, timezone: 'Europe/Moscow', end_type: 'never' }, series_exhausted: false,
    current_occurrence: { id: id(203), sequence: 4, due_at: '2028-01-01T09:00:00Z', status: 'pending', completed_at: null },
  })
  await mockApi(page, { rows: [row] })
  await page.goto('/deadline-trackers')
  const article = page.locator('#deadline-tracker-' + row.id)
  await expect(article.getByText(/Ближайший срок: 01\.01\.28/)).toBeVisible()
  await expect(article.getByText(/просрочено на|01\.01\.25/)).toHaveCount(0)
  await expect(article.getByRole('button', { name: 'Завершить повторение', exact: true })).toBeVisible()
  await expect(page.getByText('просрочено', { exact: true }).locator('..').getByText('0', { exact: true })).toBeVisible()
})

test('deep link independently loads an excluded tracker and reveals archived collapsed group before specific read', async ({ page }) => {
  const hidden = tracker(999, { title: 'Архивная цель', status: 'archived' })
  const state = await mockApi(page, { rows: [tracker(101), hidden], archivedGroup: true, exclude: hidden.id })
  await page.goto(`/deadline-trackers?tracker=${hidden.id}&status=active&category=${id(21)}`)
  await expect(page.getByRole('dialog', { name: 'Архивная цель' })).toBeVisible()
  await expect(page.locator('#deadline-tracker-' + hidden.id)).toBeAttached()
  await expect.poll(() => state.calls.filter((call) => call.method === 'POST' && call.path.endsWith('/alerts/read')).map((call) => call.path)).toEqual([`/api/deadline-trackers/${hidden.id}/alerts/read`])
  await expect(page.locator('html')).toHaveAttribute('data-tracker-attention-refreshed', 'true')
  expect(state.calls.some((call) => call.method === 'GET' && call.path === '/api/deadline-trackers/' + hidden.id)).toBe(true)
})

test('inaccessible deep link never marks alerts read', async ({ page }) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers?tracker=' + id(9999))
  await expect(page.getByRole('alert')).toContainText('Трекер недоступен или удален')
  expect(state.calls.some((call) => call.path.endsWith('/alerts/read'))).toBe(false)
})

test('deep link beyond the 300-row boundary loads the requested record', async ({ page }) => {
  const rows = Array.from({ length: 301 }, (_, index) => tracker(2000 + index, { group_id: null }))
  const target = rows[300]
  const state = await mockApi(page, { rows })
  await page.goto('/deadline-trackers?tracker=' + target.id)
  await expect(page.getByRole('dialog', { name: target.title, exact: true })).toBeVisible()
  await expect(page.locator('#deadline-tracker-' + target.id)).toBeAttached()
  expect(state.calls.some((call) => call.path === '/api/deadline-trackers/' + target.id)).toBe(true)
})

test('browser back cannot discard a dirty tracker editor', async ({ page }) => {
  await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Все', exact: true }).click()
  await page.getByRole('button', { name: 'Новый трекер', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый трекер срока' })
  await dialog.getByLabel('Название', { exact: true }).fill('Сохранить черновик при возврате')
  await page.evaluate(() => window.history.back())
  const discard = page.getByRole('alertdialog', { name: 'Несохраненные изменения трекера' })
  await expect(discard).toBeVisible()
  await expect(page).toHaveURL(/status=all/)
  await discard.getByRole('button', { name: 'Продолжить редактирование' }).click()
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Сохранить черновик при возврате')
})

test('stale editor refuses to overwrite a changed tracker', async ({ page }) => {
  const state = await mockApi(page, { rows: [tracker(101)] })
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Редактировать трекер', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Редактирование трекера' })
  await dialog.getByLabel('Название', { exact: true }).fill('Мой черновик')
  state.rows[0].updated_at = '2026-09-05T13:00:00Z'
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Трекер изменился после открытия формы')
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Мой черновик')
  expect(state.calls.some((call) => call.method === 'PATCH')).toBe(false)
})

test('personal source selection uses accessible task data without manual UUID fields', async ({ page }) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Новый трекер', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый трекер срока' })
  await dialog.locator('summary').click()
  await dialog.getByLabel('Личная задача', { exact: true }).selectOption(id(30))
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Задача-источник')
  await expect(dialog.getByRole('button', { name: 'Периодический', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Создать трекер' }).click()
  await expect(dialog).toHaveCount(0)
  const write = state.calls.find((call) => call.method === 'POST' && call.path === '/api/deadline-trackers')
  expect(write?.body).toMatchObject({ personal_task_id: id(30), starts_at: '2026-09-01T09:00:00.000Z', due_at: '2027-02-01T09:00:00.000Z', recurrence: null })
  expect(write?.body).not.toHaveProperty('linked_task_id')
  expect(write?.body).not.toHaveProperty('responsible')
})

test('stale search responses cannot overwrite a newer result', async ({ page }) => {
  await mockApi(page, { slowSearch: true, rows: [tracker(101, { title: 'Старый результат' }), tracker(102, { title: 'Новый результат' })] })
  await page.goto('/deadline-trackers')
  await expect(page.locator('#deadline-tracker-' + id(101))).toBeVisible()
  const oldRequest = page.waitForRequest((request) => new URL(request.url()).searchParams.get('search') === 'Старый')
  await page.getByLabel('Поиск по трекерам').fill('Старый')
  await oldRequest
  await page.getByLabel('Поиск по трекерам').fill('Новый')
  await expect(page.locator('#deadline-tracker-' + id(102))).toBeVisible()
  await expect(page.locator('#deadline-tracker-' + id(101))).toHaveCount(0)
  await page.waitForTimeout(1100)
  await expect(page.locator('#deadline-tracker-' + id(102))).toBeVisible()
  await expect(page.locator('#deadline-tracker-' + id(101))).toHaveCount(0)
})

test('ambiguous network write keeps draft and disables unsafe create replay', async ({ page }) => {
  const state = await mockApi(page)
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Новый трекер', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Новый трекер срока' })
  await dialog.getByLabel('Название', { exact: true }).fill('Неопределенный результат')
  await dialog.getByLabel('Дедлайн', { exact: true }).fill('2027-01-31T12:00')
  state.abortNextWrite = true
  await dialog.getByRole('button', { name: 'Создать трекер' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Изменения могли сохраниться')
  await expect(dialog.getByRole('button', { name: 'Создать трекер' })).toBeDisabled()
  await expect(dialog.getByLabel('Название', { exact: true })).toHaveValue('Неопределенный результат')
  expect(state.calls.filter((call) => call.method === 'POST' && call.path === '/api/deadline-trackers')).toHaveLength(1)
})

test('compact/full pause-shift labels, backlinks, mobile targets and themes stay usable', async ({ page }, testInfo) => {
  await mockApi(page, { rows: [tracker(101, { title: 'Проверка очень длинного русского названия срока и сохранения полосы смещения', status: 'paused', total_pause_seconds: 172800, paused_seconds: 172800, shifted_due_at: '2027-01-03T09:00:00Z', pause_started_at: '2026-09-01T09:00:00Z' })] })
  await page.goto('/deadline-trackers?status=all')
  const article = page.locator('#deadline-tracker-' + id(101))
  await expect(article.getByText('сдвиг', { exact: true })).toBeVisible()
  await expect(article.getByRole('button', { name: 'Снять паузу', exact: true })).toBeVisible()
  await expect(article.getByRole('button', { name: 'Проекты и цели', exact: true })).toBeVisible()
  if ((testInfo.project.use.viewport?.width || 390) < 1000) {
    const box = await article.getByRole('button', { name: 'Редактировать трекер', exact: true }).boundingBox()
    expect(box?.width).toBeGreaterThanOrEqual(44)
    expect(box?.height).toBeGreaterThanOrEqual(44)
  }
  await assertNoOverflow(page)
  await article.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('compact.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: 'Полный вид', exact: true }).click()
  await expect(article.getByText('сдвиг', { exact: true })).toBeVisible()
  const widths = (testInfo.project.use.viewport?.width || 390) >= 1000 ? [1920, 1024] : [320]
  for (const width of widths) {
    await page.setViewportSize({ width, height: width === 320 ? 700 : 900 })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate((theme) => document.documentElement.dataset.theme = theme, theme)
      await assertNoOverflow(page)
      await article.scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath(`full-${width}-${theme}.png`), fullPage: true, animations: 'disabled' })
    }
  }
  await article.getByRole('button', { name: 'Проекты и цели', exact: true }).click()
  await expect(page.getByRole('dialog', { name: /Проекты и цели:/ })).toBeVisible()
  await assertNoOverflow(page)
})
