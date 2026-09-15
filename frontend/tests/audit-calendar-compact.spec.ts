import { expect, test } from '@playwright/test'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

test('requested title, equal-height tools, narrow window and single-row presets', async ({ page }) => {
  const state = fixtureState()
  state.scope.name = 'Календарь аудита · локальная проверка'
  await mountCalendar(page, { state })
  await expect(page.locator('.ac-page-title h1')).toHaveText('Календарь аудита')
  await expect(page.locator('.ac-page-title p')).toHaveText('Сетевой план-график')
  for (const width of [1920, 1440, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
    const inputs = await page.locator('.ac-toolbar select, input[name="window_duration"]').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().toJSON()))
    const tools = await page.locator('.ac-search-disclosure summary, .ac-toolbar > button').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().toJSON()))
    for (const tool of tools) {
      expect(tool.height).toBe(inputs[0].height)
      if (width >= 1440) expect(Math.abs(tool.top - inputs[0].top)).toBeLessThanOrEqual(1)
    }
    const window = await page.getByLabel('Окно (мин)', { exact: true }).boundingBox()
    expect(window!.width).toBe(84)
    const presets = page.locator('.ac-period-presets button')
    await expect(presets).toHaveText(['Сегодня', '7', '14', '', ''])
    const boxes = await presets.evaluateAll(elements => elements.map(element => ({ ...element.getBoundingClientRect().toJSON(), overflow: element.scrollWidth > element.clientWidth })))
    expect(boxes.every(box => box.top === boxes[0].top && !box.overflow)).toBe(true)
    if (width <= 700) expect(boxes.every(box => box.height >= 44 && box.width >= 44)).toBe(true)
  }
  await page.getByRole('button', { name: '7 дней', exact: true }).click()
  await expect(page).toHaveURL(/to=2026-09-20/)
  await page.getByRole('button', { name: '14 дней', exact: true }).click()
  await expect(page).toHaveURL(/to=2026-09-27/)
})

test('compact header and sidebar preserve geometry, accessible controls and themes', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const state = fixtureState()
  state.scope.name = 'Календарь аудита'
  await mountCalendar(page, { state })
  await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
  const measurements = []
  for (const [width, height] of [[1920, 1080], [1440, 900], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => document.documentElement.dataset.theme = value, theme)
      const boxes = await page.evaluate(() => {
        const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().toJSON()
        return { period: box('.ac-period-panel'), nav: box('.ac-local-column nav'), graph: box('.ac-graph'), header: box('.ac-page-head'),
          filters: box('.ac-toolbar'), kpis: box('.ac-kpis'), pageWidth: document.documentElement.scrollWidth }
      })
      expect(boxes.pageWidth).toBeLessThanOrEqual(width + 1)
      expect(boxes.period.bottom).toBeLessThanOrEqual(boxes.nav.top)
      await expect(page.locator('.ac-period-panel')).not.toHaveAttribute('open')
      if (width >= 1440) {
        expect(boxes.period.right).toBeLessThan(boxes.graph.left)
        expect(boxes.filters.top).toBeLessThan(boxes.kpis.bottom)
        expect(boxes.filters.bottom).toBeGreaterThan(boxes.kpis.top)
        expect(boxes.graph.top).toBeLessThanOrEqual(boxes.header.bottom + 18)
        expect(boxes.graph.top).toBeLessThan(150)
      }
      if (width <= 700) {
        expect(boxes.nav.bottom).toBeLessThan(boxes.graph.top)
        const targets = await page.locator('.ac-toolbar button:visible, .ac-toolbar select:visible, .ac-toolbar input:visible, .ac-search-disclosure summary').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height))
        expect(targets.every(value => value >= 44)).toBe(true)
      }
      await expect(page.getByRole('button', { name: 'Обновить календарь', exact: true })).toHaveCount(1)
      measurements.push({ width, height, theme, ...boxes })
      await page.screenshot({ path: testInfo.outputPath(`${width}-${theme}-compact.png`), animations: 'disabled' })
    }
  }
  await testInfo.attach('geometry', { body: JSON.stringify(measurements, null, 2), contentType: 'application/json' })
})

test('period, compact search and all filters preserve URL state and Back navigation', async ({ page }) => {
  await mountCalendar(page)
  await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  await page.getByLabel('С', { exact: true }).fill('2026-09-15')
  await page.getByLabel('По', { exact: true }).fill('2026-09-21')
  await page.getByRole('button', { name: 'Применить', exact: true }).click()
  await expect(page).toHaveURL(/from=2026-09-15&to=2026-09-21/)
  await page.locator('.ac-toolbar').getByRole('combobox', { name: 'Группа', exact: true }).selectOption(ids.g)
  await page.getByRole('combobox', { name: 'Участник', exact: true }).selectOption(ids.a)
  await page.getByLabel('Докладчик окна', { exact: true }).selectOption(ids.s)
  await page.getByLabel('Окно (мин)', { exact: true }).fill('60')
  await page.locator('.ac-search-disclosure summary').click()
  await page.getByRole('searchbox', { name: 'Поиск активности', exact: true }).fill('И43')
  await page.getByRole('button', { name: 'Найти', exact: true }).click()
  const query = new URL(page.url()).searchParams
  expect(Object.fromEntries(query)).toMatchObject({ from: '2026-09-15', to: '2026-09-21', group: ids.g, person: ids.a, window_speaker: ids.s, window_duration: '60', q: 'И43' })
  await expect(page.locator('.ac-search-disclosure summary')).toHaveAttribute('data-active', 'true')
  await page.goBack()
  await expect(page.getByRole('searchbox', { name: 'Поиск активности', exact: true })).toHaveValue('')
  await expect(page.getByLabel('Докладчик окна', { exact: true })).toHaveValue(ids.s)
  await page.getByRole('link', { name: 'Доступное время', exact: true }).click()
  await expect(page.getByLabel('Окно (мин)', { exact: true })).toHaveCount(0)
})

test('graph focus, clicks and returning to the browser do not poll; refresh makes one state and one windows request', async ({ page }) => {
  let stateCalls = 0
  let windowCalls = 0
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/audit-calendar/state') stateCalls++
    if (path === '/api/audit-calendar/meeting-windows') windowCalls++
  })
  await mountCalendar(page)
  await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
  const initial = [stateCalls, windowCalls]
  await page.locator('.ac-graph').click({ position: { x: 5, y: 5 } })
  await page.evaluate(() => {
    window.dispatchEvent(new Event('focus'))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
  })
  await page.waitForTimeout(300)
  expect([stateCalls, windowCalls]).toEqual(initial)
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect.poll(() => [stateCalls, windowCalls]).toEqual(initial.map(n => n + 1))
  await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
})

test('expanded mobile search fits graph and availability, including its submit button', async ({ page }, testInfo) => {
  await mountCalendar(page)
  for (const view of ['graph', 'availability']) {
    await page.getByRole('link', { name: view === 'graph' ? 'График встреч' : 'Доступное время', exact: true }).click()
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 })
      if (await page.locator('.ac-search-disclosure').getAttribute('open') === null) await page.locator('.ac-search-disclosure summary').click()
      const form = page.locator('.ac-search')
      for (const theme of ['light', 'dark', 'rose']) {
        await page.evaluate(value => document.documentElement.dataset.theme = value, theme)
        const box = await form.boundingBox()
        expect(box!.x).toBeGreaterThanOrEqual(0)
        expect(box!.x + box!.width).toBeLessThanOrEqual(width)
        await expect(form.getByRole('button', { name: 'Найти', exact: true })).toBeInViewport()
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        await page.screenshot({ path: testInfo.outputPath(`${view}-${width}-${theme}-search.png`), animations: 'disabled' })
      }
      await form.getByRole('searchbox').fill('И43')
      await form.getByRole('button', { name: 'Найти', exact: true }).click()
      await expect(page).toHaveURL(/q=/)
    }
  }
})
