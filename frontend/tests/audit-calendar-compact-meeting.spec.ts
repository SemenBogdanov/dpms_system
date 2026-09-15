import { expect, test, type Page } from '@playwright/test'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const dialog = (page: Page) => page.getByRole('dialog')
const timeToggle = (page: Page) => dialog(page).getByRole('button', { name: 'Изменить дату и время встречи', exact: true })
const field = (page: Page, name: string) => ['Группа', 'Докладчик', 'Начало', 'Статус'].includes(name)
  ? dialog(page).getByRole('combobox', { name, exact: true })
  : ['Активность', 'Основание', 'Подтверждение'].includes(name) ? dialog(page).getByRole('textbox', { name, exact: true })
  : dialog(page).getByLabel(name, { exact: true })
const save = (page: Page) => dialog(page).getByRole('button', { name: 'Сохранить', exact: true })
async function openNew(page: Page) {
  await page.locator('button[aria-label="Создать план 2026-09-14 12:00"]:visible').click()
  await expect(field(page, 'Группа')).toBeEnabled()
}
async function fillNew(page: Page) {
  await field(page, 'Группа').selectOption(ids.g)
  await field(page, 'Активность').fill('И29')
  await field(page, 'Докладчик').selectOption(ids.s)
  await expect(field(page, 'Группа')).toBeEnabled()
}

test('new meeting matches compact hierarchy across themes and viewports', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const { commands } = await mountCalendar(page)
  await openNew(page)
  await expect(field(page, 'Дата')).toHaveCount(0)
  await expect(field(page, 'Начало')).toHaveCount(0)
  await expect(field(page, 'Длительность, мин')).toHaveCount(0)
  await expect(field(page, 'Основание')).toHaveCount(0)
  await expect(dialog(page).locator('.ac-meeting-time')).toContainText('14.09.2026')
  await expect(dialog(page).locator('.ac-meeting-time')).toContainText('12:00–12:30 · 30 мин')
  await expect(dialog(page)).not.toContainText('А: Не указан')
  for (const filled of [false, true]) {
    if (filled) await fillNew(page)
    for (const width of [1920, 1440, 1024, 390, 320]) {
      await page.setViewportSize({ width, height: width <= 390 ? 844 : 900 })
      for (const theme of ['light', 'dark', 'rose']) {
        await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
        expect(await dialog(page).evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
        const boxes = await Promise.all(['Группа', 'Активность', 'Докладчик'].map(name => field(page, name).boundingBox()))
        if (width >= 1024) {
          expect(Math.abs(boxes[0]!.y - boxes[1]!.y)).toBeLessThan(1)
          expect(Math.abs(boxes[0]!.y - boxes[2]!.y)).toBeLessThan(1)
          expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x)
          expect(boxes[1]!.x).toBeLessThan(boxes[2]!.x)
          expect((await dialog(page).boundingBox())!.height).toBeLessThan(460)
        } else {
          expect(boxes[0]!.y + boxes[0]!.height).toBeLessThan(boxes[1]!.y)
          expect(boxes[1]!.y + boxes[1]!.height).toBeLessThan(boxes[2]!.y)
          const controls = await dialog(page).locator('button:visible,input:visible,select:visible').evaluateAll(elements => elements.map(el => el.getBoundingClientRect().height))
          expect(controls.every(height => height >= 44)).toBe(true)
        }
        await dialog(page).screenshot({ path: testInfo.outputPath(`${filled ? 'filled' : 'empty'}-${width}-${theme}.png`), animations: 'disabled' })
      }
    }
  }
  expect(commands).toHaveLength(0)
  expect(errors).toEqual([])
})

test('compact new meeting saves the selected slot without an optional reason', async ({ page }) => {
  const { commands } = await mountCalendar(page)
  await openNew(page)
  await fillNew(page)
  await save(page).click()
  await expect(dialog(page)).toHaveCount(0)
  expect(commands).toHaveLength(1)
  expect(commands[0]).toMatchObject({ operation: 'plan.save', expected_version: 1, payload: { date: '2026-09-14', start: 720, duration: 30, group_id: ids.g, activity: 'И29', speaker_id: ids.s, status: 'planned', reason: '' } })
})

test('time pencil preserves entered fields and submits the revised slot after collapsing', async ({ page }) => {
  const { commands } = await mountCalendar(page)
  await openNew(page)
  await fillNew(page)
  await timeToggle(page).click()
  await expect(timeToggle(page)).toHaveAttribute('aria-expanded', 'true')
  await field(page, 'Дата').fill('2026-09-15')
  await field(page, 'Начало').selectOption('840')
  await field(page, 'Длительность, мин').fill('60')
  await timeToggle(page).click()
  await expect(field(page, 'Дата')).toHaveCount(0)
  await expect(dialog(page).locator('.ac-meeting-time')).toContainText('15.09.2026')
  await expect(dialog(page).locator('.ac-meeting-time')).toContainText('14:00–15:00 · 60 мин')
  await expect(field(page, 'Активность')).toHaveValue('И29')
  await expect(field(page, 'Группа')).toBeEnabled()
  await save(page).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'plan.save', payload: { date: '2026-09-15', start: 840, duration: 60, group_id: ids.g, activity: 'И29', speaker_id: ids.s } })
})

for (const invalid of ['Дата', 'Длительность, мин']) test(`invalid hidden ${invalid} cannot bypass validation in a draft plan`, async ({ page }) => {
  const { commands } = await mountCalendar(page)
  await openNew(page)
  await fillNew(page)
  await field(page, 'Статус').selectOption('draft')
  await timeToggle(page).click()
  await field(page, invalid).fill(invalid === 'Дата' ? '' : '15')
  await timeToggle(page).click()
  await save(page).click()
  await expect(dialog(page).getByRole('alert')).toContainText(invalid === 'Дата' ? 'Укажите дату' : 'Длительность должна')
  await expect(field(page, invalid)).toBeVisible()
  expect(commands).toHaveLength(0)
})

test('cancellation reason remains required and is not silently hidden on status round-trip', async ({ page }) => {
  const { commands } = await mountCalendar(page)
  await openNew(page)
  await fillNew(page)
  await field(page, 'Статус').selectOption('cancelled')
  await expect(field(page, 'Основание')).toHaveAttribute('required', '')
  await save(page).click()
  expect(commands).toHaveLength(0)
  await field(page, 'Основание').fill('Согласовано изменение плана')
  await field(page, 'Статус').selectOption('planned')
  await expect(field(page, 'Основание')).toHaveValue('Согласовано изменение плана')
})

test('existing revisions and fact recording retain required evidence and actual time', async ({ page }) => {
  await mountCalendar(page, { state: fixtureState() })
  await page.locator('.ac-plan:visible').first().click()
  await expect(field(page, 'Основание')).toHaveAttribute('required', '')
  await expect(field(page, 'Дата')).toHaveCount(0)
  await dialog(page).getByRole('button', { name: 'Факт', exact: true }).click()
  await expect(field(page, 'Дата')).toHaveValue('2026-09-14')
  await expect(field(page, 'Начало')).toHaveValue('600')
  await expect(field(page, 'Подтверждение')).toHaveAttribute('required', '')
  await expect(field(page, 'Основание')).toHaveAttribute('required', '')
})
