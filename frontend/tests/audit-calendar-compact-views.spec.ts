import { expect, test } from '@playwright/test'
import { fixtureReadiness, fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const views = ['availability', 'readiness&summary_tab=employees', 'readiness&summary_tab=groups', 'readiness&summary_tab=requests', 'workload', 'dataset', 'directories', 'management', 'history', 'imports', 'help']
for (const view of views) test(`compact non-graph view: ${view}`, async ({ page }, testInfo) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const state = fixtureState()
  state.members[1].full_name = 'Технический специалист с очень длинным именем и дополнительным уточнением'
  if (view === 'dataset') { state.plans[0].activity = 'И'; state.members[2].full_name = 'А' }
  state.change_requests.push({ id: 'request-compact', user_id: ids.a, date: state.scope.today, reason: 'Участие в другом совещании. Требуется изменить время по согласованию с помощником.', status: 'pending', requested_at: state.scope.now, requested_by_id: ids.a, opened_at: null, opened_by_id: null, closed_at: null, closed_by_id: null, resolution: '', before: [], after: null })
  const { commands } = await mountCalendar(page, { state, readiness: (from, to, duration) => {
    const data = fixtureReadiness(state, from, to, duration)
    const day = data.groups[0].days[0]
    day.status = 'no_overlap'; day.missing_user_ids = []
    data.groups[0].days[1].common_windows = [{ start: 600, end: 900 }]
    data.groups[0].days[1].free_windows = [{ start: 660, end: 750 }]
    return data
  } })
  await page.route('**/api/audit-calendar/workload?**', route => {
    const query = new URL(route.request().url()).searchParams
    return route.fulfill({ json: { version: 1, period: { from: query.get('from'), to: query.get('to'), group_id: query.get('group') }, working_days: 5, working_window: { start: 600, end: 1080, slot_minutes: 30 }, members: state.members.map(m => ({ ...m, filled_days: 2, partial_days: 1, unfilled_days: 2, absence_days: 0, free_slots: 4, free_minutes: 120, planned_meetings: 6, planned_minutes: 180, planned_work_minutes: 180, outside_work_minutes: 0, target: 3, norm_percent: 200, power_percent: 150 })) } })
  })
  await page.goto(`/audit-calendar?view=${view}&from=2026-09-14&to=2026-09-20`)
  const content = page.locator('.ac-bound-content')
  await expect(content).toHaveAttribute('aria-busy', 'false')
  if (view.startsWith('readiness') && !view.includes('requests')) await expect(page.locator('.ac-readiness-list')).toBeVisible()
  if (view === 'workload') await expect(page.locator('.ac-workload-table')).toBeVisible()
  if (view === 'history') await expect(content.locator('tbody tr')).toHaveCount(1)
  if (view === 'imports') {
    await page.getByLabel('JSON V5').setInputFiles({ name: 'synthetic.json', mimeType: 'application/json', buffer: Buffer.from('{}') })
    await page.getByRole('button', { name: 'Сопоставление', exact: true }).click()
    await page.getByLabel('Код в источнике', { exact: true }).fill('TA')
    await page.getByRole('combobox', { name: 'Сотрудник DPMS', exact: true }).selectOption(ids.a)
  }
  const measurements = []
  for (const width of [1920, 1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: width <= 390 ? 844 : 900 })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => document.documentElement.dataset.theme = value, theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
      if (width <= 700) {
        const targets = await content.locator('button:visible, select:visible, summary:visible').evaluateAll(elements => elements.map(el => ({ label: el.getAttribute('aria-label') || el.textContent, height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width })))
        expect(targets.filter(box => box.height < 44 || box.width < 44)).toEqual([])
      }
      if (width >= 1440 && view === 'availability') {
        await expect(page.getByRole('heading', { name: 'Доступное время', exact: true })).toHaveCount(0)
        await expect(page.locator('.ac-header-controls .ac-availability-save')).toHaveCount(1)
      }
      if (view === 'readiness&summary_tab=groups' && width >= 1024) {
        const nav = await page.locator('.ac-summary-tabs').boundingBox()
        const input = await page.getByLabel('Окно встречи, мин', { exact: true }).boundingBox()
        expect(input!.width).toBe(84)
        expect(Math.abs(input!.y + input!.height - nav!.y - nav!.height)).toBeLessThan(2)
        const empty = page.locator('.ac-readiness-notify:empty').first()
        await expect(empty).not.toBeVisible()
      }
      measurements.push({ width, theme, height: await content.evaluate(el => el.getBoundingClientRect().height) })
      await page.screenshot({ path: testInfo.outputPath(`${width}-${theme}.png`), fullPage: true, animations: 'disabled' })
    }
  }
  if (view === 'history' || view === 'help' || view === 'workload') {
    const detail = content.locator('details').first()
    await detail.locator('summary').focus()
    if (await detail.getAttribute('open') === null) await page.keyboard.press('Enter')
    await expect(detail).toHaveAttribute('open', '')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(321)
  }
  if (view === 'imports') await expect(page.getByLabel('Код в источнике', { exact: true })).toHaveValue('TA')
  expect(commands).toHaveLength(0)
  expect(errors).toEqual([])
  await testInfo.attach('layout', { body: JSON.stringify(measurements), contentType: 'application/json' })
})
