import { expect, test, type Page, type Route } from '@playwright/test'
import type { AvailabilityPatch, CalendarCommand, CalendarState } from '../src/api/auditCalendar'
import { availabilityIntent, availabilityReview } from '../src/lib/auditCalendarAvailability'
import { slotValue } from '../src/lib/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const day = '2026-09-14'
const nextDay = '2026-09-15'
type PaintRequest = Extract<CalendarCommand, { operation: 'availability.paint' }> & { request_id: string; expected_version: number }
const asPaint = (body: Record<string, unknown>) => body as unknown as PaintRequest
const region = (page: Page) => page.getByRole('region', { name: 'Доступное время', exact: true })
const participant = (page: Page) => page.getByRole('combobox', { name: 'Участник', exact: true })
const selectedDay = (page: Page) => page.locator('.ac-av-mobile select')
const slot = (page: Page, date = day, start = 600) => page.locator(`[data-ac-slot][data-date="${date}"][data-start="${start}"]:visible`)
const refresh = (page: Page) => page.getByRole('button', { name: 'Обновить календарь', exact: true })
const review = (page: Page) => page.getByRole('button', { name: 'Обновить и проверить изменения', exact: true })
const apply = (page: Page) => page.getByRole('button', { name: 'Применить изменения', exact: true })
const retry = (page: Page) => page.getByRole('button', { name: 'Повторить сохранение', exact: true })
const cancel = (page: Page) => page.getByRole('button', { name: 'Отменить несохранённые изменения', exact: true })
const status = (page: Page) => page.getByRole('status').filter({ hasText: /Изменения сохранены|Сохранение не подтверждено|Сохранение…|Обновление…/ })
const saved = (page: Page) => expect(status(page)).toHaveText('Изменения сохранены')
const approve = (page: Page) => page.getByRole('checkbox', { name: 'Подтверждаю изменения выбранных интервалов', exact: true }).check()
const lock = () => ({ id: 'synthetic-day-lock', user_id: ids.a, date: day, locked: true, locked_at: '2026-09-14T06:17:23Z', locked_by_id: ids.t, snapshot: [] })

function paint(state: CalendarState, user: string, patches: AvailabilityPatch[]) {
  for (const patch of patches) {
    const windows = state.availability.flatMap(window => {
      if (window.user_id !== user || window.date !== patch.date || window.end <= patch.start || window.start >= patch.end) return [window]
      return [
        ...(window.start < patch.start ? [{ ...window, end: patch.start }] : []),
        ...(window.end > patch.end ? [{ ...window, start: patch.end }] : []),
      ]
    })
    if (patch.value !== null) windows.push({ user_id: user, date: patch.date, start: patch.start, end: patch.end, available: patch.value })
    state.availability.splice(0, state.availability.length, ...windows)
  }
  state.scope.version++
}

// Synthetic interval CAS and receipts only. Real transactional HTTP coverage is
// owned by the backend suite; these tests exercise browser intent and recovery.
function paintServer(state: CalendarState) {
  const receipts = new Map<string, { body: string; version: number }>()
  return async (route: Route, body: Record<string, unknown>) => {
    const command = asPaint(body)
    expect(command.operation).toBe('availability.paint')
    const raw = route.request().postData()!
    const receipt = receipts.get(command.request_id)
    if (receipt) {
      expect(raw).toBe(receipt.body)
      await route.fulfill({ json: { version: receipt.version, result: {} } })
      return
    }
    const { user_id: user, patches, expected } = command.payload
    const touched = patches.flatMap(patch => Array.from({ length: (patch.end - patch.start) / 30 }, (_, index) => `${patch.date}/${patch.start + index * 30}`))
    expect(expected?.map(cell => `${cell.date}/${cell.start}`).sort()).toEqual([...new Set(touched)].sort())
    expect(expected?.every(cell => cell.end - cell.start === 30)).toBe(true)
    const conflicts = expected!.flatMap(cell => {
      const current = slotValue(state.availability, user, cell.date, cell.start)
      const requested = [...patches].reverse().find(patch => patch.date === cell.date && patch.start <= cell.start && patch.end >= cell.end)!.value
      return current !== cell.value && current !== requested ? [{ date: cell.date, start: cell.start, end: cell.end, expected: cell.value, current, requested }] : []
    })
    if (conflicts.length) {
      await route.fulfill({ status: 409, json: { detail: { code: 'AVAILABILITY_CHANGED', message: 'Эти интервалы уже изменены. Сравните изменения перед сохранением.', conflicts, version: state.scope.version } } })
      return
    }
    const changedCells = expected!.filter(cell => {
      const requested = [...patches].reverse().find(patch => patch.date === cell.date && patch.start <= cell.start && patch.end >= cell.end)!.value
      return slotValue(state.availability, user, cell.date, cell.start) !== requested
    }).length
    if (changedCells) paint(state, user, patches)
    else state.scope.version++
    receipts.set(command.request_id, { body: raw, version: state.scope.version })
    await route.fulfill({ json: { version: state.scope.version, result: { changed_cells: changedCells, unchanged: changedCells === 0 } } })
  }
}

test('expected covers every touched half hour, including false, null and all-day edges', () => {
  const state = fixtureState()
  state.availability.push(
    { user_id: ids.a, date: day, start: 0, end: 60, available: true },
    { user_id: ids.a, date: day, start: 600, end: 660, available: false },
    { user_id: ids.t, date: day, start: 0, end: 1440, available: true },
  )
  const patches = [{ date: day, start: 0, end: 1440, value: null }, { date: nextDay, start: 600, end: 630, value: true }]
  const intent = availabilityIntent(state, ids.a, patches)
  expect(intent.command.payload.expected).toEqual([
    ...Array.from({ length: 48 }, (_, index) => ({ date: day, start: index * 30, end: index * 30 + 30, value: index < 2 ? true : index === 20 || index === 21 ? false : null })),
    { date: nextDay, start: 600, end: 630, value: null },
  ])
  const before = JSON.stringify(intent)
  paint(state, ids.a, [{ date: day, start: 60, end: 90, value: true }])
  patches[0].end = 30
  expect(JSON.stringify(intent)).toBe(before)
  const rows = availabilityReview(intent, state)
  expect(rows.find(row => row.start === 60)).toMatchObject({ expected: null, current: true, value: null })
})

test('overlapping intervals review the final intent: whole day free then 10:00 busy', () => {
  const state = fixtureState()
  const intent = availabilityIntent(state, ids.a, [
    { date: day, start: 0, end: 1440, value: true },
    { date: day, start: 600, end: 630, value: false },
  ])
  expect(intent.command.payload.expected).toHaveLength(48)
  expect(availabilityReview(intent, state)).toEqual([
    { date: day, start: 0, end: 600, expected: null, current: null, value: true },
    { date: day, start: 600, end: 630, expected: null, current: null, value: false },
    { date: day, start: 630, end: 1440, expected: null, current: null, value: true },
  ])
})

for (const concurrent of ['other participant', 'other date', 'other cell', 'already requested value'] as const) {
  test(`another actor saves ${concurrent} without blocking this stale UI`, async ({ page, context }) => {
    const state = fixtureState()
    const command = paintServer(state)
    const first = await mountCalendar(page, { state, view: 'availability', command })
    await expect(slot(page)).toBeEnabled()
    const other = await context.newPage()
    const otherState = { ...state, actor: { ...state.actor, user_id: ids.t } }
    const second = await mountCalendar(other, { state: otherState, view: 'availability', command })
    if (concurrent !== 'other participant') await participant(other).selectOption(ids.a)
    if (concurrent === 'other date' && await other.locator('.ac-av-mobile').isVisible()) await selectedDay(other).selectOption(nextDay)
    await slot(other, concurrent === 'other date' ? nextDay : day, concurrent === 'other cell' ? 630 : 600).click()
    await other.getByRole('button', { name: /^Сохранить$/ }).click()
    await saved(other)
    expect(state.scope.version).toBe(2)
    await slot(page).click()
    await page.getByRole('button', { name: /^Сохранить$/ }).click()
    await saved(page)
    expect(first.commands).toHaveLength(1)
    expect(second.commands).toHaveLength(1)
    expect(first.commands[0].expected_version).toBe(1)
    expect(asPaint(first.commands[0]).payload.expected).toEqual([{ date: day, start: 600, end: 630, value: null }])
    expect(slotValue(state.availability, ids.a, day, 600)).toBe(true)
    if (concurrent === 'already requested value') expect(state.scope.version).toBe(3)
    await expect(region(page).getByRole('alert')).toHaveCount(0)
    await expect(region(page).getByRole('region', { name: 'Несохранённые интервалы' })).toHaveCount(0)
    await other.close()
  })
}

test('whole-day clear sends exact 48-cell baseline and preserves mixed values', async ({ page }) => {
  const state = fixtureState()
  state.availability.push(
    { user_id: ids.a, date: day, start: 0, end: 660, available: true },
    { user_id: ids.a, date: day, start: 660, end: 690, available: false },
    { user_id: ids.a, date: day, start: 690, end: 1440, available: true },
  )
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: paintServer(state) })
  await page.getByRole('button', { name: `${day}: Очистить, весь день 00:00–24:00`, exact: true }).filter({ visible: true }).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await saved(page)
  const payload = asPaint(commands[0]).payload
  expect(payload.patches).toEqual([{ date: day, start: 0, end: 1440, value: null }])
  expect(payload.expected).toHaveLength(48)
  expect(payload.expected?.slice(20, 24).map(cell => cell.value)).toEqual([true, true, false, true])
  expect(payload.expected?.[0]).toEqual({ date: day, start: 0, end: 30, value: true })
  expect(payload.expected?.at(-1)).toEqual({ date: day, start: 1410, end: 1440, value: true })
  expect(state.availability).toEqual([])
})

test('actual overlap retains draft and navigation guards until refresh, review and explicit apply', async ({ page }, testInfo) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: paintServer(state) })
  await expect(slot(page)).toBeEnabled()
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  paint(state, ids.a, [{ date: day, start: 600, end: 630, value: false }])
  await slot(page).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await expect(region(page).getByRole('alert')).toContainText('Черновик сохранён')
  await expect(region(page).getByRole('alert')).not.toContainText('Конфликт версии')
  await expect(slot(page)).toHaveAccessibleName(`${day} 10:00: Свободен`)
  await expect(participant(page)).toBeDisabled()
  await expect(selectedDay(page)).toBeDisabled()
  const url = page.url()
  await page.getByRole('link', { name: 'Соседняя страница', exact: true }).click()
  await expect(page).toHaveURL(url)
  await expect(page.getByRole('button', { name: 'Следующий период', exact: true })).toBeDisabled()
  await expect(page.locator('.ac-period input').first()).toBeDisabled()
  await expect(page.locator('.ac-period input').first()).toHaveValue(day)
  await expect(page).toHaveURL(url)
  expect(await page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })).toBe(true)
  await refresh(page).click()
  await expect(region(page)).not.toHaveAttribute('inert')
  await expect(apply(page)).toHaveCount(0)
  await expect(retry(page)).toHaveCount(0)
  expect(commands).toHaveLength(1)
  await review(page).click()
  const table = page.getByRole('table', { name: 'Проверка изменений', exact: true })
  await expect(table.locator('tbody tr').first().locator('td')).toHaveText([/14 сент\..*10:00–10:30/, 'Не указано', 'Занят', 'Свободен'])
  await expect(apply(page)).toBeDisabled()
  await page.screenshot({ path: testInfo.outputPath('overlap-review.png'), fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(await table.evaluate(element => element.parentElement!.scrollWidth <= element.parentElement!.clientWidth)).toBe(true)
  await approve(page)
  expect(commands).toHaveLength(1)
  await apply(page).click()
  await saved(page)
  expect(commands).toHaveLength(2)
  expect(commands[1].request_id).not.toBe(commands[0].request_id)
  expect(commands[1].expected_version).toBe(2)
  expect(asPaint(commands[1]).payload.expected).toEqual([{ date: day, start: 600, end: 630, value: false }])
  expect(asPaint(commands[1]).payload.patches).toEqual(asPaint(commands[0]).payload.patches)
  await expect(participant(page)).toBeEnabled()
  await expect(page.locator('.ac-period input').first()).toBeEnabled()
  await page.getByRole('link', { name: 'Соседняя страница', exact: true }).click()
  await expect(page).toHaveURL(/\/other$/)
})

test('another refresh after review cannot silently replace the approved snapshot', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: paintServer(state) })
  await expect(slot(page)).toBeEnabled()
  paint(state, ids.a, [{ date: day, start: 600, end: 630, value: false }])
  await slot(page).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await review(page).click()
  await approve(page)
  paint(state, ids.a, [{ date: day, start: 600, end: 630, value: null }])
  await refresh(page).click()
  await apply(page).click()
  await expect(region(page).getByRole('alert')).toContainText('Черновик сохранён')
  expect(commands).toHaveLength(2)
  expect(asPaint(commands[1]).payload.expected?.[0].value).toBe(false)
  expect(commands[1].expected_version).toBe(2)
  await expect(slot(page)).toHaveAccessibleName(`${day} 10:00: Свободен`)
  await expect(apply(page)).toHaveCount(0)
})

test('uncertain committed write replays UUID and byte-identical body after unrelated refresh and day lock', async ({ page }) => {
  const state = fixtureState()
  const raw: string[] = []
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async (route, body) => {
    raw.push(route.request().postData()!)
    if (raw.length === 1) {
      paint(state, ids.a, asPaint(body).payload.patches)
      state.availability_locks.push(lock())
      state.scope.version++
      await route.abort('failed')
      return
    }
    await route.fulfill({ json: { version: 2, result: {} } })
  } })
  await slot(page).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await expect(status(page)).toContainText('Сохранение не подтверждено')
  await expect(cancel(page)).toBeDisabled()
  await expect(review(page)).toHaveCount(0)
  await refresh(page).click()
  await expect(slot(page)).toHaveAttribute('title', 'День закрыт для изменений')
  await expect(review(page)).toHaveCount(0)
  await retry(page).click()
  await saved(page)
  expect(commands).toHaveLength(2)
  expect(raw[1]).toBe(raw[0])
  expect(commands[1]).toEqual(commands[0])
  expect(asPaint(commands[1]).payload.expected).toEqual([{ date: day, start: 600, end: 630, value: null }])
  await expect(participant(page)).toBeEnabled()
})

test('503 uncertainty never rebases; replay may resolve into a genuine conflict', async ({ page }) => {
  const state = fixtureState()
  const server = paintServer(state)
  let calls = 0
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async (route, body) => {
    if (++calls === 1) return route.fulfill({ status: 503, json: { detail: 'Синтетическая потеря ответа' } })
    return server(route, body)
  } })
  await slot(page).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await expect(status(page)).toContainText('Сохранение не подтверждено')
  paint(state, ids.a, [{ date: day, start: 600, end: 630, value: false }])
  await refresh(page).click()
  await expect(cancel(page)).toBeDisabled()
  await expect(review(page)).toHaveCount(0)
  await retry(page).click()
  await expect(region(page).getByRole('alert')).toContainText('Черновик сохранён')
  expect(commands[1]).toEqual(commands[0])
  await expect(cancel(page)).toBeEnabled()
  await expect(review(page)).toBeEnabled()
})

test('single in-flight protects actor, dates and cells through the success refresh', async ({ page }) => {
  const state = fixtureState()
  let releaseWrite: () => void = () => undefined
  const writeGate = new Promise<void>(resolve => { releaseWrite = resolve })
  let releaseRead: () => void = () => undefined
  const readGate = new Promise<void>(resolve => { releaseRead = resolve })
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async (route, body) => {
    await writeGate
    paint(state, ids.a, asPaint(body).payload.patches)
    await route.fulfill({ json: { version: state.scope.version, result: {} } })
  } })
  await expect(slot(page)).toBeEnabled()
  await page.route('**/api/audit-calendar/state?**', async route => { await readGate; await route.fulfill({ json: state }) })
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  try {
    await slot(page).click()
    await page.getByRole('button', { name: /^Сохранить$/ }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
    await expect.poll(() => commands.length).toBe(1)
    await expect(participant(page)).toBeDisabled()
    await expect(selectedDay(page)).toBeDisabled()
    await expect(slot(page, day, 630)).toBeDisabled()
    const url = page.url()
    await expect(page.getByRole('button', { name: 'Следующий период', exact: true })).toBeDisabled()
    await expect(page).toHaveURL(url)
    releaseWrite()
    await expect(status(page)).toHaveText('Обновление…')
    await expect(slot(page, day, 630)).toBeDisabled()
    expect(commands).toHaveLength(1)
    releaseRead()
    await saved(page)
    await expect(slot(page, day, 630)).toBeEnabled()
  } finally { releaseWrite(); releaseRead() }
})

test('successful write with failed refresh is not submitted a second time', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: paintServer(state) })
  await expect(slot(page)).toBeEnabled()
  let reads = 0
  await page.route('**/api/audit-calendar/state?**', async route => {
    if (++reads === 1) return route.fulfill({ status: 503, json: { detail: 'Синтетическая ошибка обновления' } })
    await route.fulfill({ json: state })
  })
  await slot(page).click()
  await page.getByRole('button', { name: /^Сохранить$/ }).click()
  await expect(region(page).getByRole('alert')).toContainText('Изменения сохранены')
  await expect(slot(page)).toBeDisabled()
  await expect(retry(page)).toHaveCount(0)
  await page.getByRole('button', { name: 'Обновить сохранённые интервалы', exact: true }).click()
  await expect(slot(page)).toBeEnabled()
  await saved(page)
  expect(commands).toHaveLength(1)
})

for (const blocked of ['day lock', 'archive', 'membership'] as const) {
  test(`server ${blocked} rejection retains draft and is not mislabeled as a version conflict`, async ({ page }) => {
    const state = fixtureState()
    const message = blocked === 'day lock' ? 'Доступность закрыта помощником. Подайте заявку на изменение дня.' : blocked === 'archive' ? 'Контур календаря находится в архиве и недоступен для изменений' : 'Нет прав изменять доступность этого участника'
    const { commands } = await mountCalendar(page, { state, view: 'availability', command: async route => {
      if (blocked === 'day lock') state.availability_locks.push(lock())
      if (blocked === 'archive') state.scope.archived = true
      if (blocked === 'membership') state.members[0].active = false
      await route.fulfill({ status: 409, json: { detail: message } })
    } })
    await slot(page).click()
    await page.getByRole('button', { name: /^Сохранить$/ }).click()
    await expect(region(page).getByRole('alert')).toHaveText(message)
    await expect(region(page).getByRole('alert')).not.toContainText('Конфликт версии')
    await review(page).click()
    await approve(page)
    await expect(apply(page)).toBeDisabled()
    await expect(region(page).getByRole('region', { name: 'Несохранённые интервалы', exact: true })).toBeVisible()
    expect(commands).toHaveLength(1)
    await cancel(page).click()
    await expect(region(page).getByRole('region', { name: 'Несохранённые интервалы', exact: true })).toHaveCount(0)
    await expect(participant(page)).toBeEnabled()
  })
}
