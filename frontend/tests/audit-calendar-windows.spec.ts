import { expect, test, type Page, type Route } from '@playwright/test'
import type { CalendarMeetingWindowOption, CalendarMeetingWindowOptions, CalendarMeetingWindows, CalendarState } from '../src/api/auditCalendar'
import { allSlots, dateRange, workSlots } from '../src/lib/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const extra = { a: '00000000-0000-4000-8000-000000000071', t: '00000000-0000-4000-8000-000000000072', s: '00000000-0000-4000-8000-000000000073', g: '00000000-0000-4000-8000-000000000074', v: '00000000-0000-4000-8000-000000000075' }
const cell = (page: Page, start = 720, date = '2026-09-14') => page.locator(`.ac-window-cell[data-date="${date}"][data-start="${start}"]:visible`)
const duration = (page: Page) => page.getByRole('spinbutton', { name: 'Окно (мин)', exact: true })
const speaker = (page: Page) => page.getByRole('combobox', { name: 'Докладчик окна', exact: true })
const refreshWindows = (page: Page) => page.getByRole('button', { name: 'Обновить календарь', exact: true })
const choose = (page: Page) => page.getByRole('dialog').getByRole('button', { name: /^Выбрать G2,/ })
const editorGroup = (page: Page) => page.getByRole('dialog').getByRole('combobox', { name: 'Группа', exact: true })

function windowState(helper = true) {
  const state = fixtureState(helper)
  state.members.push(...state.members.map(m => ({ ...m, user_id: m.role === 'auditor' ? extra.a : m.role === 'tech' ? extra.t : extra.s, code: `${m.code}2`, full_name: `${m.full_name} второй группы`, can_manage: false })))
  state.groups.push({ id: extra.g, code: 'G2', label: 'Независимая группа', legacy: false, archived: false, versions: [{ id: extra.v, effective_from: '2026-09-01', auditor_id: extra.a, tech_id: extra.t }] })
  return state
}

function optionsFor(state: CalendarState, start: number): CalendarMeetingWindowOption[] {
  const available: CalendarMeetingWindowOption = { group_id: extra.g, group_version_id: extra.v, auditor_id: extra.a, tech_id: extra.t, speaker_id: extra.s, status: 'available', warnings: [] }
  const warning: CalendarMeetingWindowOption = { group_id: ids.g, group_version_id: state.groups[0].versions[0].id, auditor_id: ids.a, tech_id: ids.t, speaker_id: ids.s, status: 'warning', warnings: [{ code: 'UNKNOWN_AVAILABILITY', message: 'Доступность докладчика не указана.', user_id: ids.s, participant_name: 'Тестовый докладчик', role: 'speaker' }] }
  return start === 600 ? [available] : start === 630 ? [{ ...available, status: 'warning', warnings: [{ ...warning.warnings[0], user_id: extra.s }] }] : start === 720 ? [available, warning] : []
}

function detailResponse(route: Route, state: CalendarState): CalendarMeetingWindowOptions {
  const p = new URL(route.request().url()).searchParams
  const query = { date: p.get('date')!, start: Number(p.get('start')), duration: Number(p.get('duration')), group_id: p.get('group'), speaker_id: p.get('speaker_id') }
  return { version: state.scope.version, now: state.scope.now, query, options: optionsFor(state, query.start).filter(o => (!query.group_id || query.group_id === o.group_id) && (!query.speaker_id || query.speaker_id === o.speaker_id)) }
}

function batchResponse(route: Route, state: CalendarState): CalendarMeetingWindows {
  const p = new URL(route.request().url()).searchParams
  const period = { from: p.get('from')!, to: p.get('to')!, duration: Number(p.get('duration')), group_id: p.get('group'), speaker_id: p.get('speaker_id'), full_day: p.get('full_day') === 'true' }
  return { version: state.scope.version, now: state.scope.now, period, cells: dateRange(period.from, period.to).flatMap(date => (period.full_day ? allSlots : workSlots).map(start => {
    const options = date < state.scope.today || start + period.duration > (period.full_day ? 1440 : 1080) ? [] : optionsFor(state, start).filter(o => (!period.group_id || period.group_id === o.group_id) && (!period.speaker_id || period.speaker_id === o.speaker_id))
    const confirmed = options.filter(o => o.status === 'available').length
    const uncertain = options.filter(o => o.status === 'warning').length
    return { date, start, status: confirmed ? 'available' : uncertain ? 'warning' : 'unavailable', confirmed, uncertain }
  })) }
}

type Handlers = { batch?: (route: Route, data: CalendarMeetingWindows) => Promise<void>; detail?: (route: Route, data: CalendarMeetingWindowOptions) => Promise<void> }
async function mountWindows(page: Page, state = windowState(), handlers: Handlers = {}) {
  // Install specific routes before entering the graph; generic fixtures remain owned by main.
  const fixture = await mountCalendar(page, { state, view: 'directories' })
  const batches: URLSearchParams[] = []
  const details: URLSearchParams[] = []
  await page.route('**/api/audit-calendar/meeting-windows?**', async route => {
    expect(route.request().method()).toBe('GET')
    batches.push(new URL(route.request().url()).searchParams)
    const data = batchResponse(route, state)
    return handlers.batch ? handlers.batch(route, data) : route.fulfill({ json: data })
  })
  await page.route('**/api/audit-calendar/meeting-window-options?**', async route => {
    expect(route.request().method()).toBe('GET')
    details.push(new URL(route.request().url()).searchParams)
    const data = detailResponse(route, state)
    return handlers.detail ? handlers.detail(route, data) : route.fulfill({ json: data })
  })
  await page.getByRole('link', { name: 'График встреч', exact: true }).click()
  return { ...fixture, batches, details }
}

test('one batch supplies independent semantic windows without changing occupied plans or the normal plus', async ({ page }) => {
  const { batches, details, commands } = await mountWindows(page)
  await expect(cell(page, 600)).toHaveClass(/ac-window-available/)
  await expect(cell(page, 630)).toHaveClass(/ac-window-warning/)
  await expect(cell(page, 660)).toHaveClass(/ac-window-unavailable/)
  await expect(cell(page, 660)).toBeDisabled()
  await expect(cell(page)).toHaveAccessibleName(/Вариантов: 2; подтверждено: 1; с неизвестной доступностью: 1/)
  await expect(cell(page)).toHaveAttribute('title', /Доступные окна/)
  await expect(cell(page).locator('svg')).toHaveCount(1)
  await expect(page.locator('.ac-plan:visible').first()).toContainText('И43')
  await expect(page.locator('button[aria-label="Создать план 2026-09-14 10:00"]:visible')).toHaveCount(1)
  expect(batches).toHaveLength(1)
  expect(Object.fromEntries(batches[0])).toEqual({ from: '2026-09-14', to: '2026-09-20', duration: '30', full_day: 'false' })
  expect(details).toHaveLength(0)
  await page.locator('button[aria-label="Создать план 2026-09-14 12:00"]:visible').click()
  await expect(editorGroup(page)).toHaveValue('')
  await expect(page.getByRole('dialog').getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue('')
  expect(details).toHaveLength(0)
  expect(commands).toHaveLength(0)
})

test('fresh detail waits, lists exact participants and warnings, and prefills a protected draft without autosave', async ({ page }) => {
  let release: (() => void) | undefined
  const { commands, details } = await mountWindows(page, windowState(), { detail: async (route, data) => {
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: data })
  } })
  await duration(page).fill('60')
  await expect(cell(page)).toBeEnabled()
  await cell(page).click()
  await expect.poll(() => !!release).toBe(true)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('status')).toContainText('Проверка вариантов')
  await expect(choose(page)).toHaveCount(0)
  expect(commands).toHaveLength(0)
  release?.()
  await expect(choose(page)).toBeVisible()
  await expect(dialog.locator('.ac-window-option')).toHaveCount(2)
  await expect(dialog.locator('.ac-window-participants').first()).toContainText('Тестовый аудитор второй группы')
  await expect(dialog.locator('.ac-window-participants').first()).toContainText('Тестовый технический специалист с длинным именем второй группы')
  await expect(dialog.locator('.ac-warning')).toContainText('Доступность докладчика не указана.')
  expect(Object.fromEntries(details[0])).toEqual({ date: '2026-09-14', start: '720', duration: '60' })
  await choose(page).click()
  await expect(dialog.getByRole('heading', { name: 'План встречи', exact: true })).toBeVisible()
  await expect(editorGroup(page)).toHaveValue(extra.g)
  await expect(dialog.getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue(extra.s)
  await expect(dialog.getByLabel('Основание', { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await expect(dialog.getByRole('combobox', { name: 'Начало', exact: true })).toHaveValue('720')
  await expect(dialog.getByLabel('Дата', { exact: true })).toHaveValue('2026-09-14')
  await expect(dialog.getByLabel('Длительность, мин', { exact: true })).toHaveValue('60')
  expect(commands).toHaveLength(0)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(dialog.getByText('Есть несохранённые изменения. Удалить черновик?', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
  await expect(cell(page)).toBeFocused()
})

test('prefilled group never falls back and a fresh options check does not rebase the form CAS version', async ({ page }) => {
  const state = windowState()
  const { commands } = await mountWindows(page, state)
  await cell(page).click()
  await choose(page).click()
  await expect(editorGroup(page)).toBeEnabled()
  await page.getByRole('dialog').getByLabel('Активность', { exact: true }).fill('Проверка окна')
  await page.route('**/api/audit-calendar/meeting-options?**', route => {
    const p = new URL(route.request().url()).searchParams
    return route.fulfill({ json: { version: state.scope.version, date: p.get('date'), start: Number(p.get('start')), duration: Number(p.get('duration')), groups: state.groups.map(g => ({ id: g.id, code: g.code, label: g.label, eligible: g.id !== extra.g || state.scope.version > 1, issues: [], warnings: [] })) } })
  })
  await page.getByRole('dialog').getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Длительность, мин', { exact: true }).fill('60')
  await expect(editorGroup(page).locator(`option[value="${extra.g}"]`)).toHaveJSProperty('disabled', true)
  await expect(editorGroup(page)).toHaveValue(extra.g)
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Выберите доступную группу')
  expect(commands).toHaveLength(0)
  state.scope.version = 2
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).evaluate((button: HTMLButtonElement) => button.click())
  await expect(editorGroup(page).locator(`option[value="${extra.g}"]`)).toHaveJSProperty('disabled', false)
  await expect(editorGroup(page)).toHaveValue(extra.g)
  await page.getByRole('dialog').getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'plan.save', expected_version: 1, payload: { duration: 60, group_id: extra.g, speaker_id: extra.s } })
})

test('URL controls keep exact group and active speaker filters and survive reload', async ({ page }) => {
  const { batches } = await mountWindows(page)
  await duration(page).fill('90')
  await speaker(page).selectOption(extra.s)
  await page.locator('.ac-toolbar').getByRole('combobox', { name: 'Группа', exact: true }).selectOption(extra.g)
  await expect(cell(page)).toBeEnabled()
  await expect.poll(() => Object.fromEntries(batches.at(-1)!)).toEqual({ from: '2026-09-14', to: '2026-09-20', duration: '90', full_day: 'false', group: extra.g, speaker_id: extra.s })
  await expect(page).toHaveURL(/window_duration=90/)
  await expect(page).toHaveURL(new RegExp(`window_speaker=${extra.s}`))
  await page.reload()
  await expect(duration(page)).toHaveValue('90')
  await expect(speaker(page)).toHaveValue(extra.s)
  await expect(cell(page)).toBeEnabled()
})

test('pending A to B to A batches clear colors immediately and ignore a late aborted response', async ({ page }) => {
  const releases: (() => void)[] = []
  let finished = 0
  const { batches } = await mountWindows(page, windowState(), { batch: async (route, data) => {
    if (data.period.duration === 30) {
      await new Promise<void>(resolve => { releases.push(resolve) })
      data.cells = data.cells.map(c => ({ ...c, status: 'unavailable', confirmed: 0, uncertain: 0 }))
    }
    await route.fulfill({ json: data })
    finished++
  } })
  await expect.poll(() => releases.length).toBe(1)
  await expect(cell(page)).toHaveClass(/ac-window-pending/)
  await duration(page).fill('60')
  await expect(cell(page)).toHaveClass(/ac-window-available/)
  releases[0]()
  await expect.poll(() => finished).toBe(2)
  await expect(cell(page)).toHaveClass(/ac-window-available/)
  await duration(page).fill('30')
  await expect.poll(() => releases.length).toBe(2)
  await expect(page.locator('.ac-window-cell.ac-window-available')).toHaveCount(0)
  await expect(cell(page)).toBeDisabled()
  releases[1]()
  await expect(cell(page)).toHaveClass(/ac-window-unavailable/)
  expect(batches).toHaveLength(3)
})

test('a new state source with the same version clears all colors while its batch is pending', async ({ page }) => {
  let calls = 0
  let release: (() => void) | undefined
  await mountWindows(page, windowState(), { batch: async (route, data) => {
    if (++calls > 1) await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: data })
  } })
  await expect(cell(page)).toHaveClass(/ac-window-available/)
  await refreshWindows(page).click()
  await expect.poll(() => !!release).toBe(true)
  await expect(page.locator('.ac-window-cell.ac-window-available')).toHaveCount(0)
  release?.()
  await expect(cell(page)).toHaveClass(/ac-window-available/)
})

test('31 days are allowed; a longer range keeps the graph but sends no windows request', async ({ page }) => {
  const { batches } = await mountWindows(page)
  await expect(cell(page)).toBeEnabled()
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  await page.locator('.ac-period').getByLabel('По', { exact: true }).fill('2026-10-14')
  await page.locator('.ac-period').getByRole('button', { name: 'Применить', exact: true }).click()
  await expect.poll(() => batches.at(-1)?.get('to')).toBe('2026-10-14')
  await expect(cell(page)).toBeEnabled()
  const count = batches.length
  await page.locator('.ac-period').getByLabel('По', { exact: true }).fill('2026-10-15')
  await page.locator('.ac-period').getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('ограничен 31 днём')
  await expect(page.locator('.ac-plan:visible').first()).toContainText('И43')
  await expect(page.locator('.ac-window-row')).toHaveCount(32)
  await expect(page.locator('.ac-window-cell.ac-window-available')).toHaveCount(0)
  expect(batches).toHaveLength(count)
})

for (const kind of ['422', '503', 'tuple', 'version', 'partial'] as const) {
  test(`batch ${kind} is neutral, actionable and explicitly retryable`, async ({ page }) => {
    let attempts = 0
    await mountWindows(page, windowState(), { batch: async (route, data) => {
      if (++attempts === 1) {
        if (kind === '422' || kind === '503') return route.fulfill({ status: Number(kind), json: { detail: kind === '422' ? 'Более 2000 сочетаний.' : 'Сервис окон недоступен.' } })
        if (kind === 'tuple') data.period.speaker_id = extra.s
        if (kind === 'version') data.version = 0
        if (kind === 'partial') data.cells.pop()
      }
      await route.fulfill({ json: data })
    } })
    await expect(page.getByRole('alert')).toBeVisible()
    if (kind === '422') await expect(page.getByRole('alert')).toContainText('Выберите группу или докладчика')
    await expect(page.locator('.ac-window-cell.ac-window-available')).toHaveCount(0)
    await expect(cell(page)).toBeDisabled()
    await refreshWindows(page).click()
    await expect(cell(page)).toBeEnabled()
  })
}

test('detail is fresh on every click, rejects a mismatched query, and can become empty', async ({ page }) => {
  let calls = 0
  const { details, commands } = await mountWindows(page, windowState(), { detail: async (route, data) => {
    if (++calls === 1) data.query.group_id = ids.g
    if (calls === 3) data.options = []
    await route.fulfill({ json: data })
  } })
  await cell(page).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('параметры вариантов изменились')
  await expect(choose(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
  await expect(choose(page)).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(cell(page)).toBeFocused()
  await cell(page).click()
  await expect(page.getByRole('dialog')).toContainText('Для этого интервала вариантов больше нет.')
  await expect(choose(page)).toHaveCount(0)
  expect(details).toHaveLength(3)
  expect(commands).toHaveLength(0)
})

test('late detail from a closed interval cannot replace options after parameters change', async ({ page }) => {
  let release: (() => void) | undefined
  let finished = false
  const { commands } = await mountWindows(page, windowState(), { detail: async (route, data) => {
    if (data.query.duration === 30) {
      await new Promise<void>(resolve => { release = resolve })
      data.options = []
      await route.fulfill({ json: data })
      finished = true
    } else await route.fulfill({ json: data })
  } })
  await cell(page).click()
  await expect.poll(() => !!release).toBe(true)
  await page.getByRole('dialog').getByRole('button', { name: 'Закрыть', exact: true }).click()
  await duration(page).fill('60')
  await expect(cell(page)).toBeEnabled()
  await cell(page).click()
  await expect(choose(page)).toBeVisible()
  release?.()
  await expect.poll(() => finished).toBe(true)
  await expect(choose(page)).toBeVisible()
  await expect(page.getByRole('dialog').locator('.ac-window-detail-head')).toContainText('60 мин')
  expect(commands).toHaveLength(0)
})

test('a failed source refresh clears choices, keeps the modal interactive and offers recovery', async ({ page }) => {
  let release: (() => void) | undefined
  await mountWindows(page)
  await cell(page).click()
  await expect(choose(page)).toBeVisible()
  const failState = async (route: Route) => {
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ status: 503, json: { detail: 'Не удалось обновить исходный календарь.' } })
  }
  await page.route('**/api/audit-calendar/state?**', failState)
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
  await expect.poll(() => !!release).toBe(true)
  await expect(choose(page)).toHaveCount(0)
  expect(await page.getByRole('dialog').evaluate(el => el.closest('[inert]') === null)).toBe(true)
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Закрыть', exact: true })).toBeEnabled()
  release?.()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Не удалось обновить исходный календарь.')
  await page.unroute('**/api/audit-calendar/state?**', failState)
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
  await expect(choose(page)).toBeVisible()
})

for (const kind of ['422', 'version', 'participant'] as const) {
  test(`detail ${kind} never exposes a selectable stale option`, async ({ page }) => {
    let calls = 0
    await mountWindows(page, windowState(), { detail: async (route, data) => {
      if (++calls === 1) {
        if (kind === '422') return route.fulfill({ status: 422, json: { detail: 'Более 2000 сочетаний.' } })
        if (kind === 'version') data.version = 0
        if (kind === 'participant') data.options[0].auditor_id = ids.a
      }
      await route.fulfill({ json: data })
    } })
    await cell(page).click()
    await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible()
    await expect(choose(page)).toHaveCount(0)
    await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
    await expect(choose(page)).toBeVisible()
  })
}

test('focus remains in the modal when refreshed permissions remove the focused selection', async ({ page }) => {
  const state = windowState()
  await mountWindows(page, state)
  await cell(page).click()
  await expect(choose(page)).toBeVisible()
  await choose(page).focus()
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).evaluate(button => button.click())
  await expect(page.getByRole('dialog')).toContainText('Только просмотр.')
  await expect(choose(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Обновить варианты окна', exact: true })).toBeFocused()
})

for (const mode of ['member', 'archive'] as const) {
  test(`${mode} can inspect options but cannot select`, async ({ page }) => {
    const state = windowState(mode !== 'member')
    state.scope.archived = mode === 'archive'
    const { commands } = await mountWindows(page, state)
    await cell(page).click()
    await expect(page.getByRole('dialog').locator('.ac-window-option')).toHaveCount(2)
    await expect(page.getByRole('dialog')).toContainText('Только просмотр.')
    await expect(choose(page)).toHaveCount(0)
    expect(commands).toHaveLength(0)
  })
}

test('lost helper permissions abort a pending detail and late options cannot restore selection', async ({ page }) => {
  const state = windowState()
  let release: (() => void) | undefined
  let firstDone = false
  let calls = 0
  const { commands } = await mountWindows(page, state, { detail: async (route, data) => {
    const first = ++calls === 1
    if (first) await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: data })
    if (first) firstDone = true
  } })
  await cell(page).click()
  await expect.poll(() => !!release).toBe(true)
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('Только просмотр.')
  release?.()
  await expect.poll(() => firstDone).toBe(true)
  await expect(page.getByRole('dialog').locator('.ac-window-option')).toHaveCount(2)
  await expect(choose(page)).toHaveCount(0)
  expect(commands).toHaveLength(0)
})

for (const endpoint of ['batch', 'detail'] as const) {
  test(`${endpoint} 403 revokes display and cannot be retried through focus`, async ({ page }) => {
    const handlers: Handlers = { [endpoint]: (route: Route) => route.fulfill({ status: 403, json: { detail: 'Доступ отозван.' } }) }
    const { batches, details, commands } = await mountWindows(page, windowState(), handlers)
    if (endpoint === 'detail') await cell(page).click()
    await expect(page.getByRole('alert')).toContainText('Нет доступа к контуру')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('.ac-window-cell')).toHaveCount(0)
    const count = batches.length + details.length
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    expect(batches.length + details.length).toBe(count)
    expect(commands).toHaveLength(0)
  })
}

test('an explicit revoke invalidates a late successful detail', async ({ page }) => {
  let release: (() => void) | undefined
  let finished = false
  const { commands } = await mountWindows(page, windowState(), { detail: async (route, data) => {
    await new Promise<void>(resolve => { release = resolve })
    await route.fulfill({ json: data })
    finished = true
  } })
  await cell(page).click()
  await expect.poll(() => !!release).toBe(true)
  await page.evaluate(() => window.dispatchEvent(new Event('audit-calendar:access-revoked')))
  release?.()
  await expect.poll(() => finished).toBe(true)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.ac-window-cell')).toHaveCount(0)
  expect(commands).toHaveLength(0)
})

test('focus and visibility preserve the snapshot; explicit refresh reloads state and fresh detail', async ({ page }) => {
  let stateCalls = 0
  page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/audit-calendar/state')) stateCalls++ })
  const { batches, details } = await mountWindows(page)
  await cell(page).click()
  await expect(choose(page)).toBeVisible()
  const initial = batches.length
  const initialStateCalls = stateCalls
  const initialDetails = details.length
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
  })
  await expect(choose(page)).toBeVisible()
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect(choose(page)).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  // Allow scheduled effects/requests time to run before asserting no background work.
  await page.waitForTimeout(300)
  expect(stateCalls).toBe(initialStateCalls)
  expect(batches).toHaveLength(initial)
  expect(details).toHaveLength(initialDetails)
  await page.getByRole('button', { name: 'Обновить варианты окна', exact: true }).click()
  await expect.poll(() => batches.length).toBe(initial + 1)
  await expect.poll(() => details.length).toBe(initialDetails + 1)
  expect(stateCalls).toBe(initialStateCalls + 1)
  await expect(choose(page)).toBeVisible()
})

test('outside-hours meetings switch to a full-day graph with one 48-slot batch and neutral overruns', async ({ page }) => {
  const state = windowState()
  state.plans[0].start = 540
  const { batches } = await mountWindows(page, state)
  await expect(cell(page)).toBeEnabled()
  await expect(page.locator('.ac-window-cell:visible')).toHaveCount(48)
  expect(batches).toHaveLength(1)
  expect(batches[0].get('full_day')).toBe('true')
  await duration(page).fill('480')
  await expect(cell(page, 1410)).toHaveClass(/ac-window-unavailable/)
  await expect(cell(page, 1410)).toBeDisabled()
  await expect(page.locator('.ac-plan:visible').first()).toContainText('И43')
})

test('duration bounds and an inactive URL speaker never send an invalid search or fall back to all', async ({ page }) => {
  const { batches } = await mountWindows(page)
  await expect(cell(page)).toBeEnabled()
  const initial = batches.length
  for (const value of ['0', '45', '510']) {
    await duration(page).fill(value)
    await expect(page.getByRole('alert')).toContainText('от 30 до 480 минут')
    await expect(cell(page)).toBeDisabled()
  }
  expect(batches).toHaveLength(initial)
  await page.goto('/audit-calendar?from=2026-09-14&to=2026-09-20&window_speaker=unavailable-speaker')
  await expect(page.getByRole('alert')).toContainText('неактивен или недоступен')
  await expect(speaker(page)).toHaveValue('unavailable-speaker')
  expect(batches).toHaveLength(initial)
})

test('desktop and mobile windows, modal focus and all themes stay within viewport', async ({ page }, testInfo) => {
  await mountWindows(page)
  await expect(cell(page)).toBeEnabled()
  for (const theme of ['light', 'dark', 'rose']) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme)
    for (const width of [1920, 1440, 1024, 390, 320]) {
      await page.setViewportSize({ width, height: 900 })
      await expect(cell(page)).toBeVisible()
      await expect(page.locator('.ac-window-cell:visible')).toHaveCount(width > 1200 ? 112 : 16)
      if (width <= 1200) {
        const box = await cell(page).boundingBox()
        expect(box!.width).toBeGreaterThanOrEqual(44)
        expect(box!.height).toBeGreaterThanOrEqual(44)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`windows-${theme}-${width}.png`), animations: 'disabled' })
    }
    await cell(page).click()
    await expect(choose(page)).toBeVisible()
    const dialog = page.getByRole('dialog')
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true)
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`window-options-${theme}-320.png`), animations: 'disabled' })
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await expect(cell(page)).toBeFocused()
  }
})
