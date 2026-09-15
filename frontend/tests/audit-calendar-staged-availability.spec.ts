import { expect, test, type Page } from '@playwright/test'
import type { CalendarCommand } from '../src/api/auditCalendar'
import { stageAvailability } from '../src/lib/auditCalendarAvailability'
import { addDays } from '../src/lib/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const date = '2026-09-14'
const next = '2026-09-15'
const slot = (page: Page, start = 600, day = date) => page.locator(`[data-ac-slot][data-date="${day}"][data-start="${start}"]:visible`)
const save = (page: Page) => page.getByRole('button', { name: 'Сохранить', exact: true })
const status = (page: Page) => page.locator('.ac-save-status')
const chooseDay = async (page: Page, day: string) => {
  if (await page.locator('.ac-av-mobile').isVisible()) await page.locator('.ac-av-mobile select').selectOption(day)
}
type Paint = Extract<CalendarCommand, { operation: 'availability.paint' }>

test('header save stays before participant without shifting the grid across draft and save states', async ({ page }, testInfo) => {
  test.setTimeout(90000)
  for (const width of [1920, 1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: width <= 390 ? 844 : 900 })
    let release = () => undefined
    const gate = new Promise<void>(resolve => { release = resolve })
    const state = fixtureState()
    const { commands } = await mountCalendar(page, { state, view: 'availability', command: async route => {
      await gate
      state.availability.push({ user_id: ids.a, date, start: 600, end: 630, available: true })
      state.scope.version++
      await route.fulfill({ json: { version: state.scope.version, result: {} } })
    } })
    const geometry = () => page.locator('.ac-av-desktop:visible, .ac-av-mobile:visible').evaluate(el => ({ top: el.getBoundingClientRect().top + scrollY, left: el.getBoundingClientRect().left + scrollX }))
    const initial = await geometry()
    const headerSave = page.locator('.ac-header-controls .ac-availability-save')
    await expect(headerSave).toHaveCount(1)
    await expect(page.locator('.ac-availability-legend')).toHaveCount(0)
    await slot(page).click()
    expect(commands).toHaveLength(0)
    await expect(headerSave.getByRole('button', { name: 'Сохранить', exact: true })).toBeEnabled()
    expect(await geometry()).toEqual(initial)
    const savedBox = (await headerSave.boundingBox())!
    const participantBox = (await page.getByRole('combobox', { name: 'Участник', exact: true }).boundingBox())!
    if (width >= 1440) expect(savedBox.x + savedBox.width).toBeLessThan(participantBox.x)
    else expect(savedBox.y).toBeLessThanOrEqual(participantBox.y)
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
      expect(await headerSave.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`header-draft-${width}-${theme}.png`), fullPage: true, animations: 'disabled' })
    }
    await save(page).click()
    await expect(status(page)).toHaveText('Сохранение…')
    expect(await geometry()).toEqual(initial)
    release()
    await expect(status(page)).toHaveText('Изменения сохранены')
    await expect(slot(page)).toBeEnabled()
    expect(await geometry()).toEqual(initial)
    expect(commands).toHaveLength(1)
  }
})

test('staging coalesces final intent, drops reversals and keeps the original baseline', () => {
  const state = fixtureState()
  const first = stageAvailability(state, ids.a, null, [{ date, start: 0, end: 1440, value: true }])!
  const second = stageAvailability(state, ids.a, first, [{ date, start: 600, end: 630, value: false }])!
  expect(second.command.payload.patches).toEqual([
    { date, start: 0, end: 600, value: true }, { date, start: 600, end: 630, value: false }, { date, start: 630, end: 1440, value: true },
  ])
  expect(second.command.payload.expected).toHaveLength(48)
  expect(second.command.payload.expected.every(cell => cell.value === null)).toBe(true)
  expect(first.command.payload.patches).toEqual([{ date, start: 0, end: 1440, value: true }])
  expect(stageAvailability(state, ids.a, second, [{ date, start: 0, end: 1440, value: null }])).toBeNull()
})

test('the full fortnight fits one atomic server command, including alternating cells', () => {
  const state = fixtureState()
  const changes = Array.from({ length: 14 }, (_, day) => Array.from({ length: 48 }, (_, cell) => ({ date: addDays(date, day), start: cell * 30, end: cell * 30 + 30, value: cell % 2 === 0 }))).flat()
  const intent = stageAvailability(state, ids.a, null, changes)!
  expect(intent.command.payload.patches).toHaveLength(672)
  expect(intent.command.payload.expected).toHaveLength(672)
  expect(intent.command.payload.expected.every(cell => cell.value === null)).toBe(true)
})

test('multiple days stay editable without writes; Save sends one final batch and shows server confirmation', async ({ page }, testInfo) => {
  let release = () => undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async (route, body) => {
    await gate
    const command = body as unknown as Paint
    state.availability = command.payload.patches.filter(p => p.value !== null).map(p => ({ user_id: ids.a, date: p.date, start: p.start, end: p.end, available: p.value! }))
    state.scope.version++
    await route.fulfill({ json: { version: state.scope.version, result: {} } })
  } })
  await slot(page).click()
  await slot(page, 630).click()
  await slot(page, 630).click()
  await slot(page, 630).click()
  await chooseDay(page, next)
  await slot(page, 600, next).click()
  expect(commands).toHaveLength(0)
  await expect(slot(page, 600, next)).toBeEnabled()
  await expect(page.getByRole('combobox', { name: 'Участник', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Отсутствие', exact: true })).toBeDisabled()
  await page.locator('.ac-period-panel summary').click()
  await expect(page.getByRole('button', { name: 'Следующий период', exact: true })).toBeDisabled()
  await page.locator('.ac-period-panel summary').click()
  await page.screenshot({ path: testInfo.outputPath('draft.png'), fullPage: true })
  await save(page).click()
  await expect(status(page)).toHaveText('Сохранение…')
  await expect(slot(page, 600, next)).toBeDisabled()
  await expect(save(page)).toHaveCount(0)
  await expect.poll(() => commands.length).toBe(1)
  const payload = (commands[0] as unknown as Paint).payload
  expect(payload.patches).toEqual([{ date, start: 600, end: 630, value: true }, { date: next, start: 600, end: 630, value: true }])
  expect(payload.expected).toEqual([{ date, start: 600, end: 630, value: null }, { date: next, start: 600, end: 630, value: null }])
  await page.screenshot({ path: testInfo.outputPath('saving.png'), fullPage: true })
  release()
  await expect(status(page)).toHaveText('Изменения сохранены')
  await expect(slot(page, 600, next)).toBeEnabled()
  await expect(slot(page, 600, next)).toHaveAccessibleName(`${next} 10:00: Свободен`)
  await expect(page.getByRole('combobox', { name: 'Участник', exact: true })).toBeEnabled()
  await expect(save(page)).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('saved.png'), fullPage: true })
  await slot(page, 600, next).click()
  await expect(status(page)).not.toContainText('Изменения сохранены')
  await expect(save(page)).toBeEnabled()
})

test('reverting a draft needs no save, and cancel restores the server values', async ({ page }) => {
  const { commands } = await mountCalendar(page, { view: 'availability' })
  await slot(page).click()
  await slot(page).click()
  await slot(page).click()
  await expect(save(page)).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Участник', exact: true })).toBeEnabled()
  await slot(page).click()
  await slot(page, 630).click()
  await page.getByRole('button', { name: 'Отменить несохранённые изменения', exact: true }).click()
  await expect(slot(page)).toHaveAccessibleName(`${date} 10:00: Не указано`)
  await expect(slot(page, 630)).toHaveAccessibleName(`${date} 10:30: Не указано`)
  expect(commands).toHaveLength(0)
})

test('refresh during editing does not replace the original expectations', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async route => {
    await route.fulfill({ status: 409, json: { detail: { code: 'AVAILABILITY_CHANGED', message: 'Изменено другим участником' } } })
  } })
  await slot(page).click()
  state.availability.push({ user_id: ids.a, date, start: 600, end: 630, available: false })
  state.scope.version++
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect(slot(page)).toBeEnabled()
  await expect(slot(page)).toHaveAccessibleName(`${date} 10:00: Свободен`)
  await slot(page, 630).click()
  expect(commands).toHaveLength(0)
  await save(page).click()
  await expect(page.getByRole('alert')).toContainText('Черновик сохранён')
  expect(commands[0].expected_version).toBe(1)
  expect((commands[0] as unknown as Paint).payload.expected).toEqual([{ date, start: 600, end: 630, value: null }, { date, start: 630, end: 660, value: null }])
  await expect(page.getByRole('region', { name: 'Несохранённые интервалы', exact: true })).toBeVisible()
  await expect(status(page)).not.toContainText('Изменения сохранены')
})

test('a newly locked day preserves the draft and cannot be submitted', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability' })
  await slot(page).click()
  state.availability_locks.push({ id: 'lock', user_id: ids.a, date, locked: true, locked_at: state.scope.now, locked_by_id: ids.t, snapshot: [] })
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect(slot(page)).toBeDisabled()
  await save(page).click()
  await expect(page.getByRole('alert')).toContainText('День закрыт')
  expect(commands).toHaveLength(0)
  await expect(page.getByRole('region', { name: 'Несохранённые интервалы', exact: true })).toBeVisible()
})

test('availability toolbar sits above the table; period stays collapsed across resizing', async ({ page }) => {
  const state = fixtureState()
  state.availability_locks.push({ id: 'lock', user_id: ids.a, date, locked: true, locked_at: state.scope.now, locked_by_id: ids.t, snapshot: [] })
  await mountCalendar(page, { state, view: 'availability' })
  const period = page.locator('.ac-period-panel')
  const participant = page.getByRole('combobox', { name: 'Участник', exact: true })
  const absence = page.getByRole('button', { name: 'Отсутствие', exact: true })
  for (const width of [1920, 1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(period).not.toHaveAttribute('open')
    const participantBox = (await participant.boundingBox())!
    const absenceBox = (await absence.boundingBox())!
    const groupBox = (await page.getByRole('combobox', { name: 'Группа', exact: true }).boundingBox())!
    const table = (await page.locator('.ac-av-desktop:visible, .ac-av-mobile:visible').boundingBox())!
    await expect(page.getByRole('heading', { name: 'Доступное время', exact: true })).toHaveCount(0)
    await expect(period.locator('summary')).toContainText('14.09.2026 – 27.09.2026')
    await period.locator('summary').click()
    await expect(period.locator('summary span')).toBeVisible()
    await period.locator('summary').click()
    expect(participantBox.y).toBeLessThan(table.y)
    expect(absenceBox.y).toBeLessThan(table.y)
    if (width >= 1440) {
      expect(Math.abs(participantBox.y - groupBox.y)).toBeLessThan(2)
      expect(Math.abs(participantBox.height - absenceBox.height)).toBeLessThan(2)
      expect(participantBox.x).toBeLessThan(groupBox.x)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
    await expect(page.locator('.ac-whole-day').getByText('00:00–24:00', { exact: true })).toHaveCount(0)
    await expect(page.locator('.ac-whole-day').getByText('Закрыт', { exact: true })).toHaveCount(0)
  }
  await expect(page.getByRole('button', { name: `${date}: Запросить изменение дня`, exact: true }).filter({ visible: true })).toHaveAttribute('title', /День закрыт.*Зафиксировано/)
})

test('clean mobile day follows Back and Forward; a draft day is kept after cancellation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mountCalendar(page, { view: 'availability' })
  const daySelect = page.locator('.ac-av-mobile select')
  await daySelect.selectOption(next)
  await daySelect.selectOption('2026-09-16')
  await page.goBack()
  await expect(daySelect).toHaveValue(next)
  await expect(slot(page, 600, next)).toBeVisible()
  await page.goForward()
  await expect(daySelect).toHaveValue('2026-09-16')
  await slot(page, 600, '2026-09-16').click()
  const before = page.url()
  await daySelect.selectOption('2026-09-17')
  await expect(page).toHaveURL(before)
  await page.getByRole('button', { name: 'Отменить несохранённые изменения', exact: true }).click()
  await expect(page).toHaveURL(/day=2026-09-17/)
  await expect(daySelect).toHaveValue('2026-09-17')
})

test('read-only closed days retain a lock indicator without exposing a write action', async ({ page }) => {
  const state = fixtureState(false)
  state.availability_locks.push({ id: 'lock', user_id: ids.t, date, locked: true, locked_at: state.scope.now, locked_by_id: ids.a, snapshot: [] })
  await mountCalendar(page, { state, view: 'availability' })
  await page.getByRole('combobox', { name: 'Участник', exact: true }).selectOption(ids.t)
  await expect(page.getByRole('img', { name: `${date}: День закрыт`, exact: true }).filter({ visible: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `${date}: Запросить изменение дня`, exact: true })).toHaveCount(0)
  await expect(slot(page)).toBeDisabled()
})
