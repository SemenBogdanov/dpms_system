import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium, webkit, expect } from '@playwright/test'

// Read-only calendar verification. No storage/session export or calendar writes.
const compactPages = process.argv.includes('--compact-pages')
assert.deepEqual(process.argv.slice(2), compactPages ? ['--candidate-ready', '--compact-pages'] : ['--candidate-ready'], 'Requires explicit local candidate readiness')
const base = 'http://localhost:5177'
const output = new URL(`../../artifacts/audit-calendar/native-windows/${new Date().toISOString().replace(/[:.]/g, '-')}/`, import.meta.url)
await mkdir(output, { recursive: true })
const results = []
const screenshots = []
let failure = null
let lastLogin = 0
let check = 'startup'
const local = address => {
  const url = new URL(address)
  return ['localhost', '127.0.0.1'].includes(url.hostname) && url.port === '5177'
}
const responseFor = (page, path) => page.waitForResponse(response => new URL(response.url()).pathname === path)
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const future = new Date(`${today}T00:00:00Z`)
future.setUTCDate(future.getUTCDate() + 1)
const date = future.toISOString().slice(0, 10)
future.setUTCDate(future.getUTCDate() + 13)
const through = future.toISOString().slice(0, 10)

async function capture(page, browser, stage) {
  const sizes = browser === 'chromium' ? [[1920, 1080], [1440, 900], [1024, 768]] : [[390, 844], [320, 700]]
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      if (stage === 'graph') await page.locator('.ac-window-controls').scrollIntoViewIfNeeded()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      if (stage === 'graph' && width >= 1440) {
        const widths = await page.locator('.ac-toolbar > label select').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().width))
        assert(widths.every(value => value >= 135), 'Sidebar must not squeeze the top-level filters')
      }
      const filename = `${browser}-${stage}-${width}-${theme}.png`
      await page.screenshot({ path: new URL(filename, output).pathname, fullPage: true, animations: 'disabled' })
      screenshots.push({ filename, browser, stage, width, height, theme })
    }
  }
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light' })
}

for (const [name, engine] of [['chromium', chromium], ['webkit', webkit]]) {
  const browser = await engine.launch()
  const context = await browser.newContext({ locale: 'ru-RU', timezoneId: 'Europe/Moscow',
    viewport: name === 'webkit' ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    isMobile: name === 'webkit', hasTouch: name === 'webkit', serviceWorkers: 'block' })
  let writes = 0
  const reads = { state: 0, windows: 0 }
  const errors = []
  await context.route('**/*', route => {
    const req = route.request()
    if (!local(req.url())) return route.abort()
    if (new URL(req.url()).pathname.startsWith('/api/audit-calendar/') && req.method() !== 'GET') {
      writes++
      return route.abort()
    }
    return route.continue()
  })
  await context.routeWebSocket('**', socket => local(socket.url()) ? socket.connectToServer() : socket.close())
  const page = await context.newPage()
  page.on('request', request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/audit-calendar/state') reads.state++
    if (path === '/api/audit-calendar/meeting-windows') reads.windows++
  })
  page.setDefaultTimeout(15000)
  page.on('pageerror', error => errors.push(error.name))
  page.on('response', response => {
    if (new URL(response.url()).pathname.startsWith('/api/audit-calendar/') && response.status() >= 400) errors.push(`HTTP ${response.status()}`)
  })
  try {
    await delay(Math.max(0, 13000 - (Date.now() - lastLogin)))
    await page.goto(`${base}/login`)
    await page.getByLabel('Email', { exact: true }).fill('calendar.helper@example.com')
    await page.getByLabel('Пароль', { exact: true }).fill('Calendar-local-2026!')
    lastLogin = Date.now()
    await page.getByRole('button', { name: 'Войти', exact: true }).click()
    await expect(page).toHaveURL(/\/messages(?:\?|$)/)
    if (compactPages) {
      for (const view of ['availability', 'readiness', 'readiness&summary_tab=employees', 'readiness&summary_tab=groups', 'readiness&summary_tab=requests', 'workload', 'dataset', 'directories', 'management', 'history', 'imports', 'help']) {
        check = view
        const pending = responseFor(page, '/api/audit-calendar/state')
        await page.goto(`${base}/audit-calendar?view=${view}&from=${date}&to=${through}`)
        assert.equal((await pending).status(), 200)
        await expect(page.locator('.ac-content')).toHaveAttribute('aria-busy', 'false')
        await expect(page.locator('.ac-content [role="status"]', { hasText: /Загрузка/ })).toHaveCount(0)
        if (view === 'workload') await expect(page.locator('.ac-workload')).toHaveAttribute('aria-busy', 'false')
        if (view === 'readiness') await expect(page.locator('.ac-timeline-table')).toBeVisible()
        await capture(page, name, view.replace('&summary_tab=', '-'))
      }
      assert.equal(writes, 0, 'Must not write to calendar')
      assert.deepEqual(errors, [])
      results.push({ browser: name, status: 'PASS', calendar_writes: writes, views: 12 })
      continue
    }
    const statePending = responseFor(page, '/api/audit-calendar/state')
    const windowsPending = responseFor(page, '/api/audit-calendar/meeting-windows')
    await page.goto(`${base}/audit-calendar?view=graph&from=${date}&to=${through}`)
    const stateResponse = await statePending
    assert.equal(stateResponse.status(), 200)
    const state = await stateResponse.json()
    assert(state.actor.can_manage && !state.scope.archived, 'Active local planning helper required')
    const windowsResponse = await windowsPending
    assert.equal(windowsResponse.status(), 200)
    const windows = await windowsResponse.json()
    await expect(page.getByLabel('Окно (мин)', { exact: true })).toHaveValue('30')
    await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
    await expect(page.locator('.ac-window-status [role="alert"]')).toHaveCount(0)
    const beforeFocus = { ...reads }
    await page.evaluate(() => {
      window.dispatchEvent(new Event('focus'))
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await delay(400)
    assert.deepEqual(reads, beforeFocus, 'Browser focus must not refresh the calendar or windows')
    const refreshState = responseFor(page, '/api/audit-calendar/state')
    const refreshWindows = responseFor(page, '/api/audit-calendar/meeting-windows')
    await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
    assert.equal((await refreshState).status(), 200)
    assert.equal((await refreshWindows).status(), 200)
    await expect(page.locator('.ac-window-cell:visible').first()).not.toHaveAttribute('aria-busy', 'true')
    assert.deepEqual(reads, { state: beforeFocus.state + 1, windows: beforeFocus.windows + 1 })
    await capture(page, name, 'graph')
    const eligible = windows.cells.find(cell => cell.status !== 'unavailable')
    assert(eligible, 'Fixture must contain an eligible future trio; do not mutate local data to create one')
    const detailsPending = responseFor(page, '/api/audit-calendar/meeting-window-options')
    await page.locator(`.ac-window-cell[data-date="${eligible.date}"][data-start="${eligible.start}"]:visible`).click()
    const detailsResponse = await detailsPending
    assert.equal(detailsResponse.status(), 200)
    const details = await detailsResponse.json()
    assert(details.options.length > 0)
    const dialog = page.getByRole('dialog', { name: 'Доступные окна', exact: true })
    await expect(dialog.locator('.ac-window-option').first()).toBeVisible()
    await capture(page, name, 'participants')
    await dialog.getByRole('button', { name: /^Выбрать / }).first().click()
    const editor = page.getByRole('dialog', { name: 'План встречи', exact: true })
    check = 'prefill-time-open'
    await editor.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
    check = 'prefill-date'
    await expect(editor.getByLabel('Дата', { exact: true })).toHaveValue(eligible.date)
    check = 'prefill-start'
    await expect(editor.getByRole('combobox', { name: 'Начало', exact: true })).toHaveValue(String(eligible.start))
    check = 'prefill-duration'
    await expect(editor.getByLabel('Длительность, мин', { exact: true })).toHaveValue('30')
    check = 'prefill-group'
    await expect(editor.getByRole('combobox', { name: 'Группа', exact: true })).toHaveValue(details.options[0].group_id)
    check = 'prefill-speaker'
    await expect(editor.getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue(details.options[0].speaker_id)
    await page.keyboard.press('Escape')
    await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
    await expect(editor).toBeVisible()
    check = 'prefill-time-close'
    await editor.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
    await capture(page, name, 'prefill')
    await editor.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await editor.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    assert.equal(writes, 0, 'Must not write to calendar')
    assert.deepEqual(errors, [])
    results.push({ browser: name, status: 'PASS', calendar_writes: writes, focus_refresh: false, explicit_refresh: 'one state + one windows',
      group_count: state.groups.length, batch_cells: windows.cells.length,
      selected_status: eligible.status, option_count: details.options.length })
  } catch (error) {
    failure = { browser: name, check, name: error.name, message: error.message.slice(0, 700) }
    await page.screenshot({ path: new URL(`${name}-failure.png`, output).pathname, fullPage: true }).catch(() => undefined)
    break
  } finally {
    await context.close()
    await browser.close()
  }
}
await writeFile(new URL('results.json', output), JSON.stringify({ status: failure ? 'FAIL' : 'PASS', date, through, results, screenshots, failure }, null, 2))
console.log(JSON.stringify({ status: failure ? 'FAIL' : 'PASS', output: output.pathname, checks: results.length, screenshots: screenshots.length, failure }))
if (failure) process.exitCode = 1
