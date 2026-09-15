import { expect, test, type Page, type Route } from '@playwright/test'
import type { CalendarState, CalendarWorkload } from '../src/api/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const first = '2026-09-14'
const last = '2026-09-20'
const endpoint = '**/api/audit-calendar/workload?**'

function report(state: CalendarState, from = first, to = last, group: string | null = null): CalendarWorkload {
  return { version: state.scope.version, period: { from, to, group_id: group }, working_days: 5,
    working_window: { start: 600, end: 1080, slot_minutes: 30 },
    members: state.members.map((member, i) => ({ ...member,
      filled_days: i ? 0 : 2, partial_days: i ? 0 : 1, unfilled_days: i ? 5 : 1, absence_days: i ? 0 : 1,
      free_slots: i ? 0 : 20, free_minutes: i ? 0 : 600,
      planned_meetings: i ? 0 : 3, planned_minutes: i ? 0 : 150,
      planned_work_minutes: i ? 0 : 90, outside_work_minutes: i ? 0 : 60,
      target: i ? 0 : 1.5, norm_percent: i ? null : 200, power_percent: i ? null : 15,
    })) }
}

async function mountReport(page: Page, handle?: (route: Route, value: CalendarWorkload) => Promise<void>, state = fixtureState()) {
  await mountCalendar(page, { state })
  const queries: URLSearchParams[] = []
  await page.route(endpoint, route => {
    const params = new URL(route.request().url()).searchParams
    queries.push(params)
    const value = report(state, params.get('from')!, params.get('to')!, params.get('group'))
    return handle ? handle(route, value) : route.fulfill({ json: value })
  })
  await page.getByRole('link', { name: 'Отчётность', exact: true }).click()
  return { state, queries }
}

test('report has five compact columns and secondary metrics behind employee details', async ({ page }) => {
  const state = fixtureState(); state.members[1].active = false
  await mountReport(page, undefined, state)
  const region = page.getByRole('region', { name: 'Отчётность', exact: true })
  await expect(region.getByRole('heading', { name: 'Плановая загрузка сотрудников' })).toBeVisible()
  await expect(region.locator('thead th')).toHaveText(['Сотрудник', 'Заполнено дней', 'Встречи за весь период', 'Свободные слотыпо 30 мин', 'Загрузка, %'])
  const row = region.getByRole('row').filter({ hasText: 'Тестовый аудитор' })
  await expect(row.locator('td')).toHaveCount(4)
  await expect(row).toContainText('ТА · Аудитор')
  await expect(row.getByText('Активен', { exact: true })).toHaveCount(0)
  await expect(row.locator('[data-label="Заполнено дней"]')).toHaveText('2 из 5Частично: 1')
  await expect(row.locator('[data-label="Встречи за весь период"] strong')).toHaveText('3')
  await expect(row.locator('[data-label="Встречи за весь период"] span')).toHaveText('150 мин')
  await expect(row.locator('[data-label="Свободные слоты"] strong')).toHaveText('20')
  await expect(row.locator('[data-label="Свободные слоты"] span')).toHaveText('600 мин')
  await expect(row.locator('[data-label="Загрузка, %"]')).toHaveText('15 %')
  const detail = row.locator('details')
  await expect(detail.locator('dl')).not.toBeVisible()
  await row.locator('summary').click()
  await expect(detail.locator('dl')).toBeVisible()
  for (const [label, value] of [['Норма встреч', '1,5'], ['План к норме', '200 %'], ['Отсутствие, дней', '1'], ['Не заполнено, дней', '1'], ['План в рабочее время, мин', '90'], ['Вне рабочего времени, мин', '60']]) {
    await expect(detail.locator('dl > div').filter({ hasText: label }).locator('dd')).toHaveText(value)
  }
  const inactive = region.getByRole('row').filter({ hasText: 'Тестовый технический' })
  await expect(inactive).toContainText('Неактивен')
  await expect(inactive.locator('[data-label="Заполнено дней"]')).toHaveText('0 из 5')
  await inactive.locator('summary').click()
  await expect(inactive.getByText('Нет нормы', { exact: true })).toBeVisible()
  await expect(region.getByText('Нет свободного времени', { exact: true })).toHaveCount(2)
  await expect(region).not.toContainText('Infinity')
  await expect(region).not.toContainText('NaN')
})

test('report binds full selected period and optional group, ignoring activity/person filters', async ({ page }) => {
  const { queries } = await mountReport(page)
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  await page.goto(`/audit-calendar?view=workload&from=${first}&to=2026-12-01&person=${ids.s}&q=missing`)
  await expect.poll(() => queries.at(-1)?.get('to')).toBe('2026-12-01')
  await page.getByLabel('Группа отчёта', { exact: true }).selectOption(ids.g)
  await expect.poll(() => queries.at(-1)?.get('group')).toBe(ids.g)
  expect(queries.at(-1)?.has('person')).toBe(false)
  expect(queries.at(-1)?.has('q')).toBe(false)
  await expect(page).toHaveURL(new RegExp(`group=${ids.g}`))
  await page.getByLabel('Группа отчёта', { exact: true }).selectOption('')
  await expect.poll(() => queries.at(-1)?.has('group')).toBe(false)
  await page.getByLabel('С', { exact: true }).fill('2026-10-01')
  await page.getByLabel('По', { exact: true }).fill('2026-10-31')
  await page.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect.poll(() => queries.at(-1)?.get('from')).toBe('2026-10-01')
  await expect.poll(() => queries.at(-1)?.get('to')).toBe('2026-10-31')
})

test('invalid URL period never requests a fallback report', async ({ page }) => {
  const { queries } = await mountReport(page)
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  const before = queries.length
  await page.goto(`/audit-calendar?view=workload&from=${first}&to=2028-01-01`)
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
  expect(queries).toHaveLength(before)
})

test('network failure hides previous data and allows retry', async ({ page }) => {
  let fails = false
  await mountReport(page, (route, value) => fails ? route.fulfill({ status: 503, json: { detail: 'Сервис отчётности недоступен' } }) : route.fulfill({ json: value }))
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  fails = true
  await page.getByRole('button', { name: 'Обновить отчёт', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Сервис отчётности недоступен')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
  fails = false
  await page.getByRole('button', { name: 'Повторить загрузку отчёта', exact: true }).click()
  await expect(page.locator('.ac-workload-table')).toBeVisible()
})

test('late previous-period response cannot replace the current period', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  let delayed = false
  await mountReport(page, async (route, value) => {
    if (value.period.from === first) {
      delayed = true
      await hold
      value.members[0].full_name = 'Устаревшая строка'
    }
    await route.fulfill({ json: value }).catch(() => undefined)
  })
  await expect.poll(() => delayed).toBe(true)
  await expect(page.locator('.ac-workload').getByRole('status')).toContainText('Загрузка')
  await page.getByRole('button', { name: 'Следующий период', exact: true }).click()
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  release()
  await expect(page.locator('.ac-workload')).not.toContainText('Устаревшая строка')
  await expect(page).toHaveURL(/from=2026-09-21/)
})

test('response period mismatch and older version are rejected', async ({ page }) => {
  let mismatch = true
  await mountReport(page, (route, value) => {
    if (mismatch) value.period.to = '2026-09-21'
    else value.version = 0
    return route.fulfill({ json: value })
  })
  await expect(page.getByRole('alert')).toContainText('Период отчёта не совпадает')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
  mismatch = false
  await page.getByRole('button', { name: 'Повторить загрузку отчёта', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Версия отчёта устарела')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
})

test('access refusal clears rows and disables report reload', async ({ page }) => {
  let deny = false
  await mountReport(page, (route, value) => deny ? route.fulfill({ status: 403, json: { detail: 'Доступ отозван' } }) : route.fulfill({ json: value }))
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  deny = true
  await page.getByRole('button', { name: 'Обновить отчёт', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Доступ к отчётности отозван')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Обновить отчёт', exact: true })).toBeDisabled()
})

test('revocation during a pending request never restores rows', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  let pending = false
  await mountReport(page, async (route, value) => {
    pending = true
    await hold
    await route.fulfill({ json: value }).catch(() => undefined)
  })
  await expect.poll(() => pending).toBe(true)
  await page.evaluate(() => window.dispatchEvent(new Event('audit-calendar:access-revoked')))
  release()
  await expect(page.getByRole('alert')).toContainText('Доступ отозван')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
})

test('scope refresh refetches report even when period and version are unchanged', async ({ page }) => {
  let name = 'До обновления'
  const { queries } = await mountReport(page, (route, value) => {
    value.members[0].full_name = name
    return route.fulfill({ json: value })
  })
  await expect(page.locator('.ac-workload-table')).toContainText(name)
  name = 'После обновления'
  const before = queries.length
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect(page.locator('.ac-workload-table')).toContainText(name)
  expect(queries.length).toBeGreaterThan(before)
})

test('empty selected group has an explicit empty state', async ({ page }) => {
  await mountReport(page, (route, value) => route.fulfill({ json: { ...value, members: [] } }))
  await expect(page.locator('.ac-workload').getByRole('status')).toContainText('нет сотрудников')
  await expect(page.locator('.ac-workload-table')).toHaveCount(0)
})

test('bookings without available time retain minutes but never show zero or infinite power', async ({ page }) => {
  await mountReport(page, (route, value) => {
    value.members[0] = { ...value.members[0], free_minutes: 0, free_slots: 0, power_percent: null }
    return route.fulfill({ json: value })
  })
  const row = page.locator('.ac-workload-table tbody tr').filter({ hasText: 'Тестовый аудитор' })
  await expect(row.locator('[data-label="Встречи за весь период"] strong')).toHaveText('3')
  await expect(row.locator('[data-label="Загрузка, %"]')).toHaveText('Нет свободного времени')
  await row.locator('summary').click()
  await expect(row.locator('dl > div').filter({ hasText: 'План в рабочее время, мин' }).locator('dd')).toHaveText('90')
  await expect(row.locator('dl > div').filter({ hasText: 'Вне рабочего времени, мин' }).locator('dd')).toHaveText('60')
  await expect(row.locator('dl > div').filter({ hasText: 'План к норме' }).locator('dd')).toHaveText('200 %')
})

test('power above 100 has a soft booking warning and details work with the keyboard', async ({ page }) => {
  await mountReport(page, (route, value) => {
    value.members[0].power_percent = 150
    value.members[1].power_percent = 100
    return route.fulfill({ json: value })
  })
  const row = page.locator('.ac-workload-table tbody tr').filter({ hasText: 'Тестовый аудитор' })
  await expect(row.locator('.ac-workload-overbooked')).toContainText('150 %')
  await expect(row.locator('.ac-workload-overbooked-mark')).toHaveAttribute('title', 'План превышает свободное время')
  await expect(page.locator('.ac-workload-overbooked')).toHaveCount(1)
  await row.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(row.locator('details dl')).toBeVisible()
  await page.keyboard.press('Space')
  await expect(row.locator('details dl')).not.toBeVisible()
})

test('report fits desktop and mobile in all themes', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const state = fixtureState()
  state.members[1].full_name = 'ОченьДлинноеНеразрывноеИмяСотрудника'.repeat(4)
  state.groups[0].label = 'ОченьДлинноеНазваниеГруппы'.repeat(4)
  await mountReport(page, undefined, state)
  await expect(page.locator('.ac-workload-table')).toBeVisible()
  for (const [width, height] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      expect(await page.locator('.ac-workload').evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`workload-${width}-${theme}.png`), fullPage: true })
      if (width === 320 || width === 1440) {
        await page.locator('.ac-workload-table summary').nth(1).click()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
        expect(await page.locator('.ac-workload-details').nth(1).evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`workload-details-${width}-${theme}.png`), fullPage: true })
        await page.locator('.ac-workload-table summary').nth(1).click()
      }
    }
  }
})
