import { expect, test, type Page, type Route } from '@playwright/test'
import type { CalendarMeetingOptions, CalendarState } from '../src/api/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const otherGroup = '00000000-0000-4000-8000-000000000070'
const warning = { code: 'UNKNOWN_AVAILABILITY', message: 'Тестовый аудитор: Время участника не указано' }
const busy = { code: 'BUSY', message: 'Тестовый аудитор: Участник занят в выбранное время' }
const groupSelect = (page: Page) => page.getByRole('dialog').getByRole('combobox', { name: 'Группа', exact: true })
const save = (page: Page) => page.getByRole('dialog').getByRole('button', { name: 'Сохранить', exact: true })

function planningState() {
  const state = fixtureState()
  state.groups.push({ ...state.groups[0], id: otherGroup, code: 'G2', label: 'Вторая тестовая группа' })
  return state
}

function responseFor(route: Route, state: CalendarState): CalendarMeetingOptions {
  const query = new URL(route.request().url()).searchParams
  return {
    version: state.scope.version, date: query.get('date')!, start: Number(query.get('start')), duration: Number(query.get('duration')),
    groups: state.groups.map(g => ({ id: g.id, code: g.code, label: g.label, eligible: true, issues: [], warnings: [] })),
  }
}

async function mountPlanning(page: Page, state = planningState(), handler?: (route: Route, response: CalendarMeetingOptions) => Promise<void>) {
  const fixture = await mountCalendar(page, { state })
  const queries: URLSearchParams[] = []
  await page.route('**/api/audit-calendar/meeting-options?**', async route => {
    expect(route.request().method()).toBe('GET')
    queries.push(new URL(route.request().url()).searchParams)
    const response = responseFor(route, state)
    if (handler) return handler(route, response)
    return route.fulfill({ json: response })
  })
  return { ...fixture, queries }
}

async function openNew(page: Page) {
  await page.locator('button[aria-label="Создать план 2026-09-14 12:00"]:visible').click()
  return page.getByRole('dialog')
}

async function openSaved(page: Page) {
  await page.locator('.ac-plan:visible').first().click()
  return page.getByRole('dialog')
}

for (const view of ['directories', 'management']) {
  test(`group norm is discoverable on ${view} row and opens preselected without changing history`, async ({ page }) => {
    const state = fixtureState()
    state.norms.push({ ...state.norms[1], id: 'future-group-norm', effective_from: '2026-10-01', value: 9 })
    const originalNorms = structuredClone(state.norms)
    const { commands } = await mountCalendar(page, { state, view })
    const button = page.getByRole('button', { name: 'Изменить норму G1', exact: true })
    await expect(button.locator('xpath=ancestor::tr')).toContainText('3 / 10 будней')
    await button.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('combobox', { name: 'Область нормы', exact: true })).toHaveValue(ids.g)
    await expect(dialog.getByLabel('Встреч на 10 будней', { exact: true })).toHaveValue('3')
    await dialog.getByLabel('Встреч на 10 будней', { exact: true }).fill('0')
    await dialog.getByLabel('Действует с', { exact: true }).fill('2026-09-15')
    await dialog.getByLabel('Основание', { exact: true }).fill('  Пересмотр групповой квоты  ')
    await save(page).click()
    await expect.poll(() => commands.length).toBe(1)
    expect(commands[0]).toMatchObject({ operation: 'norm.set', expected_version: 1, payload: { group_id: ids.g, effective_from: '2026-09-15', value: 0, reason: 'Пересмотр групповой квоты' } })
    expect(state.norms).toEqual(originalNorms)
  })
}

test('global norm flow, reason and effective-date protections remain intact', async ({ page }) => {
  const { commands } = await mountCalendar(page, { view: 'management' })
  await page.getByRole('button', { name: 'Изменить норму', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('combobox', { name: 'Область нормы', exact: true })).toHaveValue('')
  await expect(dialog.getByLabel('Встреч на будний день', { exact: true })).toHaveValue('6')
  await dialog.getByLabel('Основание', { exact: true }).fill('   ')
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('Укажите основание')
  await dialog.getByLabel('Основание', { exact: true }).fill('Изменение команды')
  await dialog.getByLabel('Действует с', { exact: true }).fill('2026-09-13')
  await dialog.locator('form').dispatchEvent('submit')
  await expect(dialog.getByRole('alert')).toContainText('прошлые даты')
  expect(commands).toHaveLength(0)
  await dialog.getByLabel('Действует с', { exact: true }).fill('2026-09-15')
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'norm.set', payload: { group_id: null, value: 6 } })
})

test('group norm respects future baseline and cannot be saved after helper permission is revoked', async ({ page }) => {
  const state = fixtureState()
  state.scope.baseline = '2026-09-16'
  const { commands } = await mountCalendar(page, { state, view: 'directories' })
  await page.getByRole('button', { name: 'Изменить норму G1', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Действует с', { exact: true })).toHaveAttribute('min', state.scope.baseline)
  await expect(dialog.getByLabel('Действует с', { exact: true })).toHaveValue(state.scope.baseline)
  await dialog.getByLabel('Основание', { exact: true }).fill('Изменение нормы')
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).evaluate((button: HTMLButtonElement) => button.click())
  await expect(page.getByRole('button', { name: 'Изменить норму G1', exact: true })).toHaveCount(0)
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('только помощнику')
  expect(commands).toHaveLength(0)
})

for (const actor of ['employee', 'admin-only', 'archived']) {
  test(`${actor} sees the group norm but has no edit action`, async ({ page }) => {
    const state = fixtureState(actor === 'archived')
    state.actor.can_archive = actor === 'admin-only'
    state.scope.archived = actor === 'archived'
    await mountCalendar(page, { state, view: 'directories' })
    await expect(page.getByRole('table').first().getByText('3 / 10 будней', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /Изменить норму/ })).toHaveCount(0)
  })
}

test('archived and legacy groups have no norm action; unset is not displayed as zero', async ({ page }) => {
  const state = planningState()
  state.groups[0].archived = true
  state.groups[1].legacy = true
  await mountCalendar(page, { state, view: 'directories' })
  await expect(page.getByRole('button', { name: /Изменить норму/ })).toHaveCount(0)
  await expect(page.getByText('Не задана', { exact: true })).toBeVisible()
})

test('only eligible groups can be selected, unknown availability remains a warning and saves', async ({ page }) => {
  const { commands, queries } = await mountPlanning(page, planningState(), (route, response) => {
    response.groups[0].warnings = [warning]
    response.groups[1] = { ...response.groups[1], eligible: false, issues: [busy] }
    return route.fulfill({ json: response })
  })
  const dialog = await openNew(page)
  await expect(groupSelect(page)).toBeEnabled()
  await expect(groupSelect(page).locator('option')).toHaveCount(2)
  await expect(groupSelect(page).locator(`option[value="${otherGroup}"]`)).toHaveCount(0)
  await groupSelect(page).selectOption(ids.g)
  await dialog.getByLabel('Активность', { exact: true }).fill('Новая комиссия')
  await dialog.getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption(ids.s)
  await expect(groupSelect(page)).toBeEnabled()
  await expect(dialog.getByText(warning.message, { exact: true })).toHaveCount(1)
  await expect(dialog.getByLabel('Основание', { exact: true })).toHaveCount(0)
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'plan.save', payload: { date: '2026-09-14', start: 720, duration: 30, group_id: ids.g, speaker_id: ids.s } })
  expect(queries.at(-1)?.get('speaker_id')).toBe(ids.s)
  expect(queries[0].has('plan_id')).toBe(false)
})

test('saved selected group stays disabled and attributed issues are not double-prefixed', async ({ page }) => {
  const state = planningState()
  state.plans[0].issues = [busy]
  state.plans[0].warnings = [{ code: 'SOURCE_NOTE', message: 'Тестовая заметка сохранённого плана' }]
  const { commands, queries } = await mountPlanning(page, state, (route, response) => {
    response.groups[0] = { ...response.groups[0], eligible: false, issues: [busy, busy] }
    return route.fulfill({ json: response })
  })
  const dialog = await openSaved(page)
  await expect(groupSelect(page)).toBeEnabled()
  await expect(groupSelect(page)).toHaveValue(ids.g)
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveJSProperty('disabled', true)
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toContainText('недоступна')
  await expect(dialog.getByText(busy.message, { exact: true })).toHaveCount(1)
  await expect(dialog.getByText('Тестовая заметка сохранённого плана', { exact: true })).toBeVisible()
  await dialog.getByLabel('Основание', { exact: true }).fill('Проверка конфликта')
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('Выберите доступную группу')
  expect(commands).toHaveLength(0)
  expect(queries[0].get('plan_id')).toBe(ids.p)
  await groupSelect(page).selectOption(otherGroup)
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ payload: { id: ids.p, group_id: otherGroup } })
})

test('date start duration and speaker refetch without resetting the rest of the draft', async ({ page }) => {
  const { queries } = await mountPlanning(page, planningState(), (route, response) => {
    if (response.duration === 60) response.groups[0] = { ...response.groups[0], eligible: false, issues: [busy] }
    return route.fulfill({ json: response })
  })
  const dialog = await openNew(page)
  await groupSelect(page).selectOption(ids.g)
  await dialog.getByLabel('Активность', { exact: true }).fill('Сохранённая активность')
  await dialog.getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption(ids.s)
  await expect(groupSelect(page)).toBeEnabled()
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await dialog.getByLabel('Дата', { exact: true }).fill('2026-09-15')
  await expect.poll(() => queries.at(-1)?.get('date')).toBe('2026-09-15')
  await dialog.getByRole('combobox', { name: 'Начало', exact: true }).selectOption('750')
  await expect.poll(() => queries.at(-1)?.get('start')).toBe('750')
  await dialog.getByLabel('Длительность, мин', { exact: true }).fill('60')
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toContainText('недоступна')
  await expect(groupSelect(page)).toHaveValue(ids.g)
  await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Сохранённая активность')
  await expect(dialog.getByLabel('Основание', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue(ids.s)
  expect(Object.fromEntries(queries.at(-1)!)).toEqual({ date: '2026-09-15', start: '750', duration: '60', speaker_id: ids.s })
})

test('pending and out-of-order responses cannot submit or replace current choices', async ({ page }) => {
  let releaseOld: (() => void) | undefined
  let oldFinished = false
  const { commands, queries } = await mountPlanning(page, planningState(), async (route, response) => {
    if (response.date === '2026-09-14') {
      await new Promise<void>(resolve => { releaseOld = resolve })
      response.groups = [response.groups[0]]
      await route.fulfill({ json: response })
      oldFinished = true
      return
    }
    response.groups = [response.groups[1]]
    return route.fulfill({ json: response })
  })
  const dialog = await openSaved(page)
  await expect.poll(() => !!releaseOld).toBe(true)
  await expect(groupSelect(page)).toBeDisabled()
  await dialog.getByLabel('Основание', { exact: true }).fill('Проверка ожидания')
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('Дождитесь проверки')
  expect(commands).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await dialog.getByLabel('Дата', { exact: true }).fill('2026-09-15')
  await expect(groupSelect(page)).toBeEnabled()
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveJSProperty('disabled', true)
  await groupSelect(page).selectOption(otherGroup)
  releaseOld?.()
  await expect.poll(() => oldFinished).toBe(true)
  await expect(groupSelect(page)).toHaveValue(otherGroup)
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveCount(0)
  expect(queries).toHaveLength(2)
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ payload: { date: '2026-09-15', group_id: otherGroup } })
})

test('failed query can be retried, a mismatched tuple is rejected, and empty choices do not select a group', async ({ page }) => {
  let calls = 0
  const { commands } = await mountPlanning(page, planningState(), (route, response) => {
    calls++
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: 'Синтетический сбой проверки групп' } })
    if (calls === 2) return route.fulfill({ json: { ...response, duration: response.duration + 30 } })
    return route.fulfill({ json: { ...response, groups: [] } })
  })
  const dialog = await openSaved(page)
  await expect(dialog.getByText('Синтетический сбой проверки групп', { exact: true })).toBeVisible()
  await dialog.getByLabel('Основание', { exact: true }).fill('Проверка повтора')
  await save(page).click()
  expect(commands).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Повторить проверку групп', exact: true }).click()
  await expect(dialog.getByText('Получен устаревший список групп. Повторите проверку.', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Повторить проверку групп', exact: true }).click()
  await expect(dialog.getByText('Нет доступных групп для выбранного времени.', { exact: true })).toBeVisible()
  await expect(groupSelect(page)).toHaveValue(ids.g)
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveJSProperty('disabled', true)
  await save(page).click()
  expect(commands).toHaveLength(0)
})

test('returning to an earlier time waits for a new matching response', async ({ page }) => {
  let release: (() => void) | undefined
  let firstDateCalls = 0
  const { commands } = await mountPlanning(page, planningState(), async (route, response) => {
    if (response.date === '2026-09-14' && ++firstDateCalls > 1) {
      await new Promise<void>(resolve => { release = resolve })
      response.groups[0] = { ...response.groups[0], eligible: false, issues: [busy] }
    }
    return route.fulfill({ json: response })
  })
  const dialog = await openSaved(page)
  await expect(groupSelect(page)).toBeEnabled()
  await dialog.getByLabel('Основание', { exact: true }).fill('Возврат к исходной дате')
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await dialog.getByLabel('Дата', { exact: true }).fill('2026-09-15')
  await expect(groupSelect(page)).toBeEnabled()
  await dialog.getByLabel('Дата', { exact: true }).fill('2026-09-14')
  await expect.poll(() => !!release).toBe(true)
  await expect(groupSelect(page)).toBeDisabled()
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('Дождитесь проверки')
  expect(commands).toHaveLength(0)
  release?.()
  await expect(groupSelect(page)).toBeEnabled()
  await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveJSProperty('disabled', true)
})

test('calendar version refresh invalidates options without changing the draft or form CAS version', async ({ page }) => {
  const state = planningState()
  let release: (() => void) | undefined
  const { commands } = await mountPlanning(page, state, async (route, response) => {
    if (response.version === 2) await new Promise<void>(resolve => { release = resolve })
    return route.fulfill({ json: response })
  })
  const dialog = await openSaved(page)
  await expect(groupSelect(page)).toBeEnabled()
  await dialog.getByLabel('Активность', { exact: true }).fill('Сохранить при обновлении')
  await dialog.getByLabel('Основание', { exact: true }).fill('Проверка версии')
  state.scope.version = 2
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).evaluate((button: HTMLButtonElement) => button.click())
  await expect.poll(() => !!release).toBe(true)
  await expect(groupSelect(page)).toBeDisabled()
  await save(page).click()
  await expect(dialog.getByRole('alert')).toContainText('Дождитесь проверки')
  expect(commands).toHaveLength(0)
  release?.()
  await expect(groupSelect(page)).toBeEnabled()
  await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Сохранить при обновлении')
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].expected_version).toBe(1)
})

test('server can still reject an eligible plan without closing or losing its fields', async ({ page }) => {
  await mountPlanning(page)
  await page.route('**/api/audit-calendar/commands', route => route.fulfill({ status: 422, json: { detail: busy.message } }))
  const dialog = await openSaved(page)
  await expect(groupSelect(page)).toBeEnabled()
  await dialog.getByLabel('Основание', { exact: true }).fill('Проверка серверного решения')
  await save(page).click()
  await expect(dialog.getByRole('alert')).toHaveText(busy.message)
  await expect(dialog).toBeVisible()
  await expect(groupSelect(page)).toHaveValue(ids.g)
  await expect(dialog.getByRole('textbox', { name: 'Основание', exact: true })).toHaveValue('Проверка серверного решения')
})

for (const mode of ['fact', 'notice', 'cancel']) {
  test(`${mode} submission is not blocked by unavailable meeting options`, async ({ page }) => {
    const { commands } = await mountPlanning(page, planningState(), route => route.fulfill({ status: 503, json: { detail: 'Нет сервиса вариантов' } }))
    const dialog = await openSaved(page)
    if (mode === 'cancel') {
      await dialog.getByRole('combobox', { name: 'Статус', exact: true }).selectOption('cancelled')
    } else {
      await dialog.getByRole('button', { name: mode === 'fact' ? 'Факт' : 'Уведомление', exact: true }).click()
      if (mode === 'fact') await dialog.getByLabel('Подтверждение', { exact: true }).fill('Тестовый протокол')
      else await dialog.getByRole('combobox', { name: 'Участник', exact: true }).selectOption(ids.a)
    }
    await dialog.getByLabel('Основание', { exact: true }).fill('Основание тестового действия')
    await save(page).click()
    await expect.poll(() => commands.length).toBe(1)
    expect(commands[0].operation).toBe(mode === 'fact' ? 'fact.record' : mode === 'notice' ? 'notice.record' : 'plan.save')
    await expect(dialog).not.toBeVisible()
  })
}

test('read-only plan shows attributed API issues without querying meeting options', async ({ page }) => {
  const state = fixtureState(false)
  state.plans[0].issues = [busy]
  const { queries } = await mountPlanning(page, state)
  const dialog = await openSaved(page)
  await expect(dialog.getByText(busy.message, { exact: true })).toHaveCount(1)
  await expect(save(page)).toHaveCount(0)
  expect(queries).toHaveLength(0)
})

for (const optionsState of ['ineligible', 'error', 'pending']) {
  test(`draft can preserve its selected group with ${optionsState} options`, async ({ page }) => {
    let release: (() => void) | undefined
    const { commands } = await mountPlanning(page, planningState(), async (route, response) => {
      if (optionsState === 'error') return route.fulfill({ status: 503, json: { detail: 'Нет сервиса вариантов' } })
      if (optionsState === 'pending') await new Promise<void>(resolve => { release = resolve })
      response.groups[0] = { ...response.groups[0], eligible: false, issues: [busy] }
      return route.fulfill({ json: response })
    })
    const dialog = await openSaved(page)
    if (optionsState === 'ineligible') await expect(groupSelect(page).locator(`option[value="${ids.g}"]`)).toHaveJSProperty('disabled', true)
    if (optionsState === 'pending') await expect.poll(() => !!release).toBe(true)
    if (optionsState === 'error') await expect(dialog.getByText('Нет сервиса вариантов', { exact: true })).toBeVisible()
    await dialog.getByRole('combobox', { name: 'Статус', exact: true }).selectOption('draft')
    await dialog.getByLabel('Основание', { exact: true }).fill('Вернуться к выбору времени позже')
    await save(page).click()
    await expect.poll(() => commands.length).toBe(1)
    expect(commands[0]).toMatchObject({ operation: 'plan.save', payload: { group_id: ids.g, status: 'draft' } })
    release?.()
    await expect(dialog).not.toBeVisible()
  })
}

test('group norm and meeting choices fit desktop and mobile widths', async ({ page }, testInfo) => {
  await mountPlanning(page)
  const dialog = await openNew(page)
  await groupSelect(page).selectOption(ids.g)
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(dialog).toBeVisible()
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`planning-${width}.png`), animations: 'disabled' })
  }
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
  await page.getByRole('link', { name: 'Справочники', exact: true }).click()
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole('button', { name: 'Изменить норму G1', exact: true })).toBeVisible()
    const geometry = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > innerWidth + 1)
        .map(e => `${e.tagName}.${e.className}`).slice(0, 20) }))
    expect(geometry.scroll, JSON.stringify(geometry)).toBeLessThanOrEqual(width + 1)
    await page.screenshot({ path: testInfo.outputPath(`norms-${width}.png`), animations: 'disabled' })
  }
})
