import { expect, test, type Page } from '@playwright/test'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'
import { calendarDailyTarget, periodError, validDate } from '../src/lib/auditCalendar'

const visibleCreate = (page: Page) => page.locator('button[aria-label="Создать план 2026-09-14 12:00"]:visible')
async function fillPlan(page: Page) {
  await visibleCreate(page).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeFocused()
  await dialog.getByRole('combobox', { name: 'Группа', exact: true }).selectOption(ids.g)
  await dialog.getByLabel('Активность', { exact: true }).fill('Тестовая комиссия')
  await dialog.getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption(ids.s)
  await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Тестовая комиссия')
  return dialog
}

test('date bounds and effective daily targets are exact', () => {
  expect(validDate('2026-13-01')).toBe(false)
  expect(validDate('2026-02-30')).toBe(false)
  expect(validDate('2100-12-31')).toBe(true)
  expect(periodError('2026-01-01', '2027-01-02')).toContain('366')
  const state = fixtureState()
  state.norms.push({ ...state.norms[0], id: 'later', effective_from: '2026-09-15', value: 4 })
  expect(calendarDailyTarget(state, '2026-09-14')).toBe(6)
  expect(calendarDailyTarget(state, '2026-09-15')).toBe(4)
  expect(calendarDailyTarget(state, '2026-09-19')).toBe(0)
  expect(calendarDailyTarget(state, '2026-09-14', ids.g)).toBe(0.3)
  expect(calendarDailyTarget(state, '2026-09-14', 'unknown-group')).toBe(0)
})

test('all views, server KPI and direct calendar help', async ({ page }, testInfo) => {
  const { commands } = await mountCalendar(page)
  await expect(page.locator('.ac-kpi-target strong')).toHaveText('30')
  await expect(page.locator('.ac-kpis > div')).toHaveCount(4)
  for (const name of ['Доступное время', 'Датасет', 'Справочники', 'Управление', 'Журнал', 'Импорт', 'Справка']) {
    await page.getByRole('navigation', { name: 'Представления календаря' }).getByRole('link', { name, exact: true }).click()
    await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
    await expect(page.locator('.ac-content h2').first()).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`view-${name}.png`), fullPage: true, animations: 'disabled' })
  }
  expect(commands).toHaveLength(0)
})

test('dirty modal survives Escape backdrop native Back and Forward and restores focus', async ({ page }) => {
  await mountCalendar(page)
  await page.getByRole('link', { name: 'Датасет', exact: true }).click()
  await page.getByRole('link', { name: 'График встреч', exact: true }).click()
  await page.getByRole('link', { name: 'Справочники', exact: true }).click()
  await page.goBack()
  await expect(visibleCreate(page)).toBeVisible()
  const dialog = await fillPlan(page)
  await page.keyboard.press('Escape')
  await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
  const url = page.url()
  await page.goBack()
  await expect(page).toHaveURL(url)
  await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Тестовая комиссия')
  await page.goForward()
  await expect(page).toHaveURL(url)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(visibleCreate(page)).toBeFocused()
})

test('network retry keeps UUID and only confirmed save closes; busy discard blocked', async ({ page }) => {
  let calls = 0
  let release: (() => void) | undefined
  const { commands } = await mountCalendar(page, { command: async route => {
    calls++
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: 'Синтетическая сетевая ошибка' } })
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: { version: 2, result: {} } })
  } })
  const dialog = await fillPlan(page)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Синтетическая')
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Удалить черновик', exact: true })).toBeDisabled()
  await expect.poll(() => commands.length).toBe(2)
  expect(commands[0].request_id).toBe(commands[1].request_id)
  release?.()
  await expect(dialog).not.toBeVisible()
})

test('CAS preserves draft until explicit rebase', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, command: async route => {
    state.scope.version = 2
    return route.fulfill({ status: 409, json: { detail: 'Scope version changed' } })
  } })
  const dialog = await fillPlan(page)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Конфликт версии')
  await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Тестовая комиссия')
  await dialog.getByRole('button', { name: 'Перечитать, сохранив ввод', exact: true }).click()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(2)
  expect(commands[0].expected_version).toBe(1)
  expect(commands[1].expected_version).toBe(2)
  expect(commands[0].request_id).not.toBe(commands[1].request_id)
})

test('whole-day and ownership are server-scoped, no optimistic partial writes', async ({ page }) => {
  const { commands } = await mountCalendar(page, { view: 'availability', helper: false })
  await page.getByRole('button', { name: '2026-09-14: Свободен, весь день 00:00–24:00', exact: true }).filter({ visible: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].payload).toEqual({ user_id: ids.a, patches: [{ date: '2026-09-14', start: 0, end: 1440, value: true }],
    expected: Array.from({ length: 48 }, (_, i) => ({ date: '2026-09-14', start: i * 30, end: i * 30 + 30, value: null })) })
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  await page.getByRole('region', { name: 'Доступное время', exact: true }).getByRole('combobox', { name: 'Участник', exact: true }).selectOption(ids.t)
  await expect(page.getByRole('button', { name: '2026-09-14: Свободен, весь день 00:00–24:00', exact: true }).filter({ visible: true })).toBeDisabled()
  await expect(page.getByRole('link', { name: 'Управление', exact: true })).toHaveCount(0)
})

test('pointercancel and blur discard unsent drag, pointerup sends one batch', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Mouse drag uses desktop Chromium; WebKit has touch alternative coverage.')
  const { commands } = await mountCalendar(page, { view: 'availability' })
  const first = page.locator('[data-ac-slot][data-date="2026-09-14"][data-start="600"]:visible')
  const last = page.locator('[data-ac-slot][data-date="2026-09-14"][data-start="720"]:visible')
  const a = (await first.boundingBox())!; const b = (await last.boundingBox())!
  for (const cancel of ['pointercancel', 'blur']) {
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down()
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 3 })
    await page.evaluate(type => window.dispatchEvent(new Event(type)), cancel)
    await page.mouse.up()
    expect(commands).toHaveLength(0)
  }
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 3 }); await page.mouse.up()
  await expect.poll(() => commands.length).toBe(1)
  expect((commands[0].payload as { patches: unknown[] }).patches.length).toBeGreaterThan(1)
})

test('norm editor reads effective history and accepts zero', async ({ page }) => {
  const state = fixtureState(); state.norms[0].value = 4; state.norms[1].value = 7
  const { commands } = await mountCalendar(page, { state, view: 'management' })
  await page.getByRole('button', { name: 'Изменить норму', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Встреч на будний день', { exact: true })).toHaveValue('4')
  await dialog.getByRole('combobox', { name: 'Область нормы', exact: true }).selectOption(ids.g)
  await expect(dialog.getByLabel('Встреч на 10 будней', { exact: true })).toHaveValue('7')
  await dialog.getByLabel('Встреч на 10 будней', { exact: true }).fill('0')
  await dialog.getByLabel('Основание').fill('Тестовая нулевая норма')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].payload).toMatchObject({ group_id: ids.g, value: 0, effective_from: '2026-09-14' })
})

test('admin panel uses existing membership endpoint without calendar state', async ({ page }) => {
  const { commands } = await mountCalendar(page, { admin: true })
  await page.getByRole('button', { name: 'Изменить участие Тестовый аудитор', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Помощник управления расписанием').uncheck()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ user_id: ids.a, can_manage: false, expected_version: 1 })
})

for (const active of [true, false]) for (const revoked of ['grant', 'account']) {
  test(`admin edits saved membership without silently changing it: active=${active}, revoked=${revoked}`, async ({ page }) => {
    const { state, commands } = await mountCalendar(page, { admin: true })
    await page.route('**/api/audit-calendar/admin', route => route.fulfill({ json: {
      scope: { ...state.scope, version: 99 }, members: state.members.map(m => ({ ...m, active })),
      users: state.members.map(m => ({ id: m.user_id, full_name: m.full_name,
        email: 'synthetic@example.invalid', audit_calendar_enabled: revoked !== 'grant', is_active: revoked !== 'account' })),
    } }))
    await page.getByRole('button', { name: 'Обновить участников календаря', exact: true }).click()
    await expect(page.getByText('Синтетический тестовый контур · Europe/Moscow · версия 99', { exact: true })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: 'Тестовый аудитор' })).toContainText(active ? 'Активно' : 'Отключено')
    await page.getByRole('button', { name: 'Изменить участие Тестовый аудитор', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(active ? 'Участие сохранено, но доступ к календарю закрыт' : 'Перед активацией участия нужны допуск')
    await expect(dialog.getByLabel('Активное участие')).toBeChecked({ checked: active })
    await dialog.getByLabel('Код', { exact: true }).fill('EDIT')
    if (!active) await dialog.getByLabel('Активное участие').check()
    await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
    if (active) {
      await expect.poll(() => commands.length).toBe(1)
      expect(commands[0]).toMatchObject({ user_id: ids.a, code: 'EDIT', active: true })
    } else {
      await expect(dialog.getByRole('alert')).toContainText('Сначала выдайте активному пользователю допуск')
      expect(commands).toHaveLength(0)
    }
  })
}

test('period date edge and malformed URL never produce 2101 or crash', async ({ page }) => {
  await mountCalendar(page)
  await page.goto('/audit-calendar?from=2026-13-01&to=2026-13-02')
  await expect(page.getByRole('alert')).toContainText('2000–2100')
  await page.getByLabel('С', { exact: true }).fill('2100-12-31')
  await page.getByLabel('По', { exact: true }).fill('2100-12-31')
  await page.getByRole('button', { name: 'Применить', exact: true }).click()
  await page.getByRole('button', { name: '14 дней', exact: true }).click()
  await expect(page).toHaveURL(/to=2100-12-31/)
})

test('responsive themes show nonblank fit without page overflow', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  await mountCalendar(page)
  for (const [width, height] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => document.documentElement.dataset.theme = value, theme)
      await expect(page.getByRole('heading', { name: 'Сетевой план-график', exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      if (width >= 1440) { await expect(page.locator('.ac-desktop-graph')).toBeVisible(); await expect(page.locator('.ac-graph-heading > div > span')).toHaveCount(16) }
      await page.screenshot({ path: testInfo.outputPath(`${width}-${theme}-graph.png`), animations: 'disabled' })
    }
  }
})

test('central modal fits every viewport and theme without losing draft', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  await page.setViewportSize({ width: 1440, height: 900 })
  await mountCalendar(page)
  const dialog = await fillPlan(page)
  for (const [width, height] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      await expect(dialog).toBeVisible()
      const box = (await dialog.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.y).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width + 1)
      expect(box.y + box.height).toBeLessThanOrEqual(height + 1)
      expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
      const selectHeights = await dialog.locator('select').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height))
      expect(selectHeights.every(height => height >= (width <= 700 ? 44 : 36))).toBe(true)
      await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Тестовая комиссия')
      await page.screenshot({ path: testInfo.outputPath(`${width}-${theme}-modal.png`), animations: 'disabled' })
    }
  }
})

test('old-period availability is inert until matching state arrives', async ({ page }) => {
  const { state, commands } = await mountCalendar(page, { view: 'availability' })
  let release: (() => void) | undefined
  await page.route('**/api/audit-calendar/state?**', async route => {
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: state })
  })
  await page.getByRole('button', { name: 'Следующий период', exact: true }).click()
  await expect(page.locator('.ac-bound-content')).toHaveAttribute('inert')
  expect(commands).toHaveLength(0)
  await expect.poll(() => !!release).toBe(true)
  release?.()
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
})

test('background refresh cannot silently advance the form CAS version', async ({ page }) => {
  const { state, commands } = await mountCalendar(page)
  const dialog = await fillPlan(page)
  state.scope.version = 7
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).evaluate((button: HTMLButtonElement) => button.click())
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].expected_version).toBe(1)
})

test('revoked API access clears sensitive state and an open modal', async ({ page }) => {
  await mountCalendar(page, { command: route => route.fulfill({ status: 403, json: { detail: 'Доступ отозван' } }) })
  const dialog = await fillPlan(page)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Нет доступа')
  await expect(page.locator('.ac-meeting')).toHaveCount(0)
  await expect(page.getByText('Синтетический тестовый контур', { exact: false })).toHaveCount(0)
})

test('immutable fact summary participates in modal keyboard cycle', async ({ page }) => {
  const state = fixtureState()
  state.facts.push({ id: 'fact-synthetic', plan_id: ids.p, date: '2026-09-14', start: 600, duration: 90, group_id: ids.g, activity: 'И43', speaker_id: ids.s, outcome: 'completed', reason: 'Тест', evidence: 'Синтетический протокол', recorded_by_id: ids.a, recorded_at: state.scope.now, participant_snapshot: [], planned_snapshot: { activity: 'И43' }, composition_unknown: true, origin: 'native' })
  await mountCalendar(page, { state })
  await page.locator('.ac-fact:visible').first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(dialog.locator('summary')).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog.locator('details')).toHaveAttribute('open')
  await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toHaveCount(0)
})

test('outside hours use 48 rows with one meeting and continuations', async ({ page }) => {
  const state = fixtureState(); state.plans[0].start = 480
  await mountCalendar(page, { state })
  await expect(page.locator('.ac-day-graph')).toBeVisible()
  await expect(page.locator('.ac-vertical-row')).toHaveCount(48)
  await expect(page.locator('.ac-day-graph .ac-meeting')).toHaveCount(1)
  await expect(page.locator('.ac-day-graph .ac-continuation')).toHaveCount(2)
})

test('delayed initial modal focus does not interrupt an already focused field', async ({ page }) => {
  await mountCalendar(page)
  await page.locator('.ac-plan:visible').first().click()
  const reason = page.getByRole('dialog').locator('textarea')
  await reason.fill('Ввод до начального кадра фокуса')
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(reason).toBeFocused()
  await expect(reason).toHaveValue('Ввод до начального кадра фокуса')
})

test('source working revision is explicit and uses plan.revise', async ({ page }) => {
  const state = fixtureState(); state.plans[0].source_id = '00000000-0000-4000-8000-000000000080'; state.plans[0].origin = 'source'
  const { commands } = await mountCalendar(page, { state })
  await page.locator('.ac-plan:visible').first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание', { exact: true }).fill('Рабочая редакция тестового источника')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('явно выберите рабочую редакцию')
  expect(commands).toHaveLength(0)
  await dialog.getByLabel('Создать рабочую редакцию источника').check()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].operation).toBe('plan.revise')
})

test('import bootstrap and group mapping require explicit preview and apply', async ({ page }) => {
  const state = fixtureState(); state.plans = []; state.groups = []
  const { commands } = await mountCalendar(page, { state, view: 'imports', command: async route => {
    if (route.request().url().endsWith('/preview')) return route.fulfill({ json: { id: 'synthetic-batch', version: 2, status: 'ready', summary: { rows: 0 }, issues: [], mapping_required: [], rows: [], source_sha256: 'synthetic-digest' } })
    return route.fulfill({ json: { version: 3, result: {} } })
  } })
  await page.getByLabel('JSON V5').setInputFiles({ name: 'synthetic.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ application: 'audit-meeting-constructor', version: 1, data: { plans: [], facts: [], availability: [] } })) })
  expect(commands).toHaveLength(0)
  await page.getByLabel('Первичное восстановление истории в пустом контуре').check()
  await page.getByRole('button', { name: 'Состав группы', exact: true }).click()
  await page.getByLabel('Код группы', { exact: true }).fill('G1')
  await page.getByRole('combobox', { name: 'Аудитор группы', exact: true }).selectOption(ids.a)
  await page.getByRole('combobox', { name: 'Техспециалист группы', exact: true }).selectOption(ids.t)
  await page.getByRole('button', { name: 'Предварительный просмотр', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ bootstrap_history: true, group_mapping: { G1: { auditor_id: ids.a, tech_id: ids.t } } })
  await expect(page.getByRole('button', { name: 'Применить импорт', exact: true })).toBeDisabled()
  await page.getByLabel('Основание переноса').fill('Подтверждён только синтетический источник')
  await page.getByLabel('Подтверждаю источник, горизонт истории и сопоставление').check()
  await page.getByRole('button', { name: 'Применить импорт', exact: true }).click()
  await expect.poll(() => commands.length).toBe(2)
  expect(commands[1]).toMatchObject({ confirm: true, expected_version: 2 })
})

test('initial Today is canonical server today despite device clock', async ({ page }) => {
  const state = fixtureState(); state.scope.today = '2100-12-31'
  await mountCalendar(page, { state })
  await page.goto('/audit-calendar')
  await expect(page).toHaveURL(/from=2100-12-31&to=2100-12-31/)
})

test('import preview stale rebase adopts refreshed version and preserves source', async ({ page }) => {
  let attempts = 0
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'imports', command: async route => {
    attempts++
    if (attempts === 1) { state.scope.version = 8; return route.fulfill({ status: 409, json: { detail: 'Scope advanced' } }) }
    return route.fulfill({ json: { id: 'synthetic-preview', version: 9, status: 'ready', summary: {}, issues: [], mapping_required: [], rows: [], source_sha256: 'synthetic' } })
  } })
  await page.getByLabel('JSON V5').setInputFiles({ name: 'synthetic.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ application: 'audit-meeting-constructor', version: 1, data: { plans: [], facts: [], availability: [] } })) })
  await page.getByRole('button', { name: 'Предварительный просмотр', exact: true }).click()
  await page.getByRole('button', { name: 'Перечитать данные и повторить preview', exact: true }).click()
  await page.getByRole('button', { name: 'Предварительный просмотр', exact: true }).click()
  await expect.poll(() => commands.length).toBe(2)
  expect(commands[0].expected_version).toBe(1)
  expect(commands[1].expected_version).toBe(8)
  expect(commands[0].source).toEqual(commands[1].source)
  expect(commands[0].request_id).not.toBe(commands[1].request_id)
})
