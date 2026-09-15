import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium, webkit, expect } from '@playwright/test'

// Run after approval: node scripts/verify-calendar-controls-native.mjs --candidate-ready [--browser=chromium|webkit] [--archive]
// All mutations use real UI/API. Each run leaves its lock, request and availability history intact.
assert(process.argv.includes('--candidate-ready'), 'Candidate approval required: pass --candidate-ready after the candidate is ready')
assert(process.argv.slice(2).every(arg => ['--candidate-ready', '--archive', '--browser=chromium', '--browser=webkit', '--diagnose-lock'].includes(arg)), 'Unknown command-line option')
const selectedBrowser = process.argv.find(arg => arg.startsWith('--browser='))?.split('=')[1]
const diagnoseLock = process.argv.includes('--diagnose-lock')
assert(!diagnoseLock || (selectedBrowser && !process.argv.includes('--archive')), 'Lock diagnosis requires one browser and excludes archival')
const base = 'http://localhost:5177'
const withArchive = process.argv.includes('--archive')
const runId = new Date().toISOString().replace(/[:.]/g, '-')
const output = new URL(`../../artifacts/audit-calendar/native-controls/${runId}/`, import.meta.url)
const results = []
const artifacts = []
const retained = []
let lastLogin = 0
let currentCheck = 'preflight'
let currentBrowser = ''
let activePage = null
let fixtureVerified = false
let restoreRequired = false
let failure = null
await mkdir(output, { recursive: true })

const dateAfter = (day, offset) => {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + offset)
  return date.toISOString().slice(0, 10)
}
const timeLabel = value => new Date(value).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })
const calendarPath = (date, extra = {}) => `/audit-calendar?${new URLSearchParams({ from: date, to: date, day: date, ...extra })}`
const availablePath = (date, user) => calendarPath(date, { view: 'availability', availability_person: user })
const summaryPath = date => calendarPath(date, { view: 'readiness', summary_tab: 'requests' })
const isLocal = value => {
  const url = new URL(value)
  return ['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol) && ['localhost', '127.0.0.1'].includes(url.hostname) && url.port === '5177'
}
const apiResponse = (page, path) => page.waitForResponse(response => new URL(response.url()).origin === base && new URL(response.url()).pathname === path, { timeout: 15000 })
const lockAt = (state, user, date) => state.availability_locks.find(lock => lock.user_id === user && lock.date === date)
const requestAt = (state, id) => state.change_requests.find(request => request.id === id)
const slot = (page, date) => page.locator(`[data-ac-slot][data-date="${date}"][data-start="600"]:visible`)
const dayButton = (page, date, label) => page.getByRole('button', { name: `${date}: ${label}`, exact: true }).filter({ visible: true })
const requestRow = (page, reason) => page.locator('.ac-request').filter({ hasText: reason })

async function report(status, failure = null) {
  await writeFile(new URL('results.json', output), JSON.stringify({ run_id: runId, tested_at: new Date().toISOString(), base, status, current_browser: currentBrowser, current_check: currentCheck, archive_requested: withArchive, restore_required: restoreRequired, results, retained_history: retained, screenshots: artifacts, failure }, null, 2))
}

async function passed(check, detail = {}) {
  results.push({ browser: currentBrowser, check, result: 'PASS', ...detail })
  await report('RUNNING')
}

async function newActor(browser, browserName, role) {
  assert(['helper', 'employee', 'admin'].includes(role), 'Only calendar synthetic accounts are permitted')
  const mobile = browserName === 'webkit'
  const context = await browser.newContext({ locale: 'ru-RU', timezoneId: 'Europe/Moscow', viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: mobile, hasTouch: mobile, serviceWorkers: 'block' })
  await context.route('**/*', route => isLocal(route.request().url()) ? route.continue() : route.abort())
  await context.routeWebSocket('**', route => { if (isLocal(route.url())) route.connectToServer(); else route.close() })
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  page.setDefaultNavigationTimeout(15000)
  const health = { runtime_errors: 0, calendar_http_errors: [] }
  page.on('pageerror', () => { health.runtime_errors++ })
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/api/audit-calendar/') && response.status() >= 400) health.calendar_http_errors.push({ path, status: response.status() })
  })
  activePage = page
  currentCheck = `login-${role}`
  // Share pacing across actors and browsers; never inspect login bodies, headers or storage.
  await delay(Math.max(0, 13000 - (Date.now() - lastLogin)))
  await page.goto(`${base}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByLabel('Email', { exact: true }).fill(`calendar.${role}@example.com`)
  await page.getByLabel('Пароль', { exact: true }).fill('Calendar-local-2026!')
  lastLogin = Date.now()
  const [response] = await Promise.all([apiResponse(page, '/api/auth/login'), page.getByRole('button', { name: 'Войти', exact: true }).click()])
  assert.equal(response.status(), 200, `Synthetic ${role} login must succeed`)
  await expect(page).toHaveURL(/\/messages(?:\?|$)/)
  await expect(page.getByRole('heading', { name: 'Сообщения', exact: true })).toBeVisible()
  return { page, context, health, role }
}

async function openState(page, path) {
  activePage = page
  const [response] = await Promise.all([apiResponse(page, '/api/audit-calendar/state'), page.goto(`${base}${path}`, { waitUntil: 'domcontentloaded' })])
  assert.equal(response.status(), 200, 'CalendarState must return HTTP 200')
  const state = await response.json()
  assert(Array.isArray(state.availability_locks) && Array.isArray(state.change_requests), 'Candidate must expose availability locks and requests')
  await expect(page.getByRole('heading', { name: 'Сетевой план-график', exact: true })).toBeVisible()
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  return state
}

async function openAdmin(page) {
  activePage = page
  const refresh = new URL(page.url()).pathname === '/admin/users'
  const [response] = await Promise.all([apiResponse(page, '/api/audit-calendar/admin'), refresh
    ? page.getByRole('button', { name: 'Обновить участников календаря', exact: true }).click()
    : page.goto(`${base}/admin/users`, { waitUntil: 'domcontentloaded' })])
  assert.equal(response.status(), 200, 'Synthetic global admin must access AdminPanel')
  const state = await response.json()
  await expect(page.getByRole('region', { name: 'Администрирование календаря аудита', exact: true })).toBeVisible()
  return state
}

async function command(page, operation, payload, action) {
  activePage = page
  const [response] = await Promise.all([apiResponse(page, '/api/audit-calendar/commands'), action()])
  const body = response.request().postDataJSON()
  assert.equal(body.operation, operation, 'UI must send the expected calendar operation')
  assert.deepEqual(body.payload, payload, 'UI must send exactly the approved payload, without a client timestamp')
  assert.equal(response.status(), 200, 'Calendar command must return HTTP 200; stop on conflict or validation failure')
  const result = await response.json()
  assert(Number.isInteger(result.version), 'Successful command must return the scope version')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  }), { message: 'Saving must release the calendar draft navigation guard' }).toBe(false)
  if (await page.locator('.ac-bound-content').count()) await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  return result.version
}

async function protectedReason(page, reason) {
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание', { exact: true }).fill(reason)
  await page.keyboard.press('Escape')
  await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
  try {
    const field = dialog.getByLabel('Основание', { exact: true })
    await expect(field).toHaveValue(reason)
    await expect(field).toHaveAccessibleName('Основание')
    assert(await field.evaluate(element => element.labels?.length === 1 && element.id !== '' && element.labels[0].htmlFor === element.id && element.labels[0].textContent === 'Основание'), 'Reason must retain its explicit label association after input')
  }
  catch (error) {
    const field = dialog.getByLabel('Основание', { exact: true })
    const count = await field.count()
    failure = { type: error.name, check: currentCheck, assertion: 'reason-preserved-after-escape-and-backdrop', assertion_summary: error.message.split('\n')[0].replace(/https?:\/\/\S+/g, '[url]').slice(0, 400), dialog_count: await dialog.count(), calendar_reason_field_count: count, reason_matches: count === 1 ? await field.inputValue().then(value => value === reason).catch(() => null) : null }
    throw error
  }
  return dialog
}

async function reasonCommand(page, operation, payload) {
  const dialog = await protectedReason(page, payload.reason)
  return command(page, operation, payload, () => dialog.getByRole('button', { name: 'Сохранить', exact: true }).click())
}

async function controls(page, date, disabled) {
  const slots = page.locator(`[data-ac-slot][data-date="${date}"]:visible`)
  await expect(slots).toHaveCount(16)
  assert(await slots.evaluateAll((elements, value) => elements.every(element => element.disabled === value), disabled), 'All 16 day slots must respect the day lock')
  for (const label of ['Свободен', 'Занят', 'Очистить']) {
    const button = dayButton(page, date, `${label}, весь день 00:00–24:00`)
    if (disabled) await expect(button).toBeDisabled()
    else await expect(button).toBeEnabled()
  }
}

function serverTimestamp(value, before, after, label) {
  const stamp = Date.parse(value)
  assert(Number.isFinite(stamp), `${label}: valid server timestamp required`)
  assert(stamp >= Date.parse(before.scope.now) && stamp <= Date.parse(after.scope.now), `${label}: timestamp must be between the surrounding server reads`)
}

async function screenshots(page, role, stage, verify = async () => undefined, region = null, sizes = [[1440, 900], [390, 844]]) {
  const original = page.viewportSize()
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height })
    if (width < 600) {
      const menu = page.getByRole('button', { name: 'Меню', exact: true })
      if (await menu.count() && await menu.getAttribute('aria-expanded') === 'true') await menu.click()
      await expect.poll(() => page.locator('.app-sidebar').evaluate(element => element.getBoundingClientRect().right), {
        message: 'Mobile sidebar transition must finish before inspecting content',
      }).toBeLessThanOrEqual(1)
    }
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      await verify()
      if (width < 600 && !region && !(await page.getByRole('dialog').count())) {
        const target = page.locator(stage === 'closed-request' ? '.ac-request' : stage === 'workload' ? '.ac-workload-table tbody tr' : '.ac-av-mobile .ac-whole-day').first()
        if (await target.count()) await target.scrollIntoViewIfNeeded()
      }
      const pageFits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
      if (region) {
        const box = await region.boundingBox()
        assert(box && box.x >= 0 && box.x + box.width <= width + 1, 'Calendar admin region must fit the viewport')
        if (!pageFits && !results.some(r => r.check === 'outer-admin-page-overflow' && r.browser === currentBrowser)) {
          results.push({ browser: currentBrowser, check: 'outer-admin-page-overflow', result: 'RESIDUAL', scope: 'outside-calendar-admin-region', width })
        }
      } else assert(pageFits, 'Native calendar page must fit the viewport without horizontal overflow')
      const path = `${currentBrowser}-${role}-${stage}-${width}-${theme}.png`
      if (region) await region.screenshot({ path: new URL(path, output).pathname, animations: 'disabled', timeout: 15000 })
      else await page.screenshot({ path: new URL(path, output).pathname, fullPage: true, animations: 'disabled', timeout: 15000 })
      artifacts.push({ path, browser: currentBrowser, role, stage, width, height, theme, route: new URL(page.url()).pathname + new URL(page.url()).search })
    }
  }
  await page.setViewportSize(original)
  await page.evaluate(() => { document.documentElement.dataset.theme = 'light' })
}

async function summary(page, date, reason, expected) {
  const [readiness, state] = await Promise.all([apiResponse(page, '/api/audit-calendar/readiness'), openState(page, summaryPath(date))])
  assert.equal(readiness.status(), 200, 'Native readiness endpoint must succeed')
  const data = await readiness.json()
  assert.equal(data.from, date, 'Summary must keep the notification link period')
  assert.equal(data.to, date, 'Summary must keep the single-day period')
  assert.equal(data.duration, 30, 'Summary default window must be 30 minutes')
  assert.equal(data.working_start, 600, 'Summary working day must begin at 10:00 Moscow')
  assert.equal(data.working_end, 1080, 'Summary working day must end at 18:00 Moscow')
  const row = requestRow(page, reason)
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(expected)
  return state
}

function chooseDay(state, today, employeeId) {
  return Array.from({ length: 51 }, (_, index) => dateAfter(today, index + 10)).find(date =>
    ![0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay()) &&
    !state.availability_locks.some(lock => lock.date === date) &&
    !state.change_requests.some(request => request.date === date) &&
    !state.availability.some(window => window.user_id === employeeId && window.date === date) &&
    !state.absences.some(absence => absence.user_id === employeeId && absence.status === 'active' && absence.start_date <= date && absence.end_date >= date) &&
    !state.plans.some(plan => plan.date === date) && !state.facts.some(fact => fact.date === date))
}

async function checkMeeting(page, date, state) {
  await openState(page, calendarPath(date, { view: 'graph' }))
  const trigger = page.locator(`button[aria-label="Создать план ${date} 12:00"]:visible`)
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Длительность, мин', { exact: true })).toHaveValue('30')
  const select = dialog.getByRole('combobox', { name: 'Докладчик', exact: true })
  const actual = await select.locator('option').evaluateAll(options => options.filter(option => option.value && !option.disabled).map(option => option.value).sort())
  const expected = state.members.filter(member => member.active && member.role === 'speaker').map(member => member.user_id).sort()
  assert(expected.length > 0, 'Synthetic fixture must include an active speaker')
  assert.deepEqual(actual, expected, 'New meeting must offer only active role=speaker members')
  const [optionsResponse] = await Promise.all([apiResponse(page, '/api/audit-calendar/meeting-options'), select.selectOption(expected[0])])
  assert.equal(optionsResponse.status(), 200, 'Meeting group eligibility must load from the real API')
  const options = await optionsResponse.json()
  const groupSelect = dialog.getByRole('combobox', { name: 'Группа', exact: true })
  const eligible = options.groups.filter(group => group.eligible).map(group => group.id).sort()
  await expect.poll(() => groupSelect.locator('option').evaluateAll(items => items.filter(item => item.value && !item.disabled).map(item => item.value).sort())).toEqual(eligible)
  await dialog.getByLabel('Активность', { exact: true }).fill(`Native controls ${runId}`)
  await page.keyboard.press('Escape')
  await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
  await screenshots(page, 'helper', 'meeting-default-30', async () => {
    await expect(dialog.getByLabel('Длительность, мин', { exact: true })).toHaveValue('30')
    assert(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1), 'Native meeting dialog must fit at both viewport sizes')
  })
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  const after = await openState(page, calendarPath(date, { view: 'graph' }))
  assert(!after.plans.some(plan => plan.date === date), 'Inspecting a new meeting must not create a stored plan')
}

async function archiveAndRestore(admin, helper, date, initial) {
  const page = admin.page
  await openAdmin(page)
  const panel = page.getByRole('region', { name: 'Администрирование календаря аудита', exact: true })
  const reason = `Native controls archive ${runId} ${currentBrowser}`
  restoreRequired = true
  await report('RUNNING')
  try {
    await panel.getByRole('button', { name: 'Архивировать контур', exact: true }).click()
    await reasonCommand(page, 'scope.archive', { archived: true, reason })
    const archived = await openAdmin(page)
    assert.equal(archived.scope.archived, true, 'Global admin archive must persist without membership')
    assert(!archived.members.some(member => member.user_id === initial.users.find(user => user.email === 'calendar.admin@example.com').id), 'Global admin must remain outside calendar membership')
    await screenshots(page, 'admin', 'archived', async () => {
      await expect(panel.getByRole('button', { name: 'Вернуть из архива', exact: true })).toBeVisible()
    }, panel)
    const helperState = await openState(helper.page, calendarPath(date, { view: 'graph' }))
    assert.equal(helperState.scope.archived, true, 'Helper must observe archived scope')
    await expect(helper.page.locator('button[aria-label^="Создать план"]')).toHaveCount(0)
  } finally {
    // Restore only this run's optional archive; never delete audit events or test history.
    const latest = await openAdmin(page)
    if (latest.scope.archived) {
      await panel.getByRole('button', { name: 'Вернуть из архива', exact: true }).click()
      await reasonCommand(page, 'scope.archive', { archived: false, reason: `${reason}: restore` })
    }
    const restored = await openAdmin(page)
    assert.equal(restored.scope.archived, false, 'Optional archive must restore the original active scope')
    restoreRequired = false
    await report('RUNNING')
  }
}

async function run(browser, browserName) {
  let admin = null
  let adminState = null
  if (withArchive) {
    admin = await newActor(browser, browserName, 'admin')
    currentCheck = 'synthetic-fixture-preflight'
    adminState = await openAdmin(admin.page)
    assert(adminState.scope && !adminState.scope.archived, 'Synthetic calendar scope must exist and be active')
    assert(adminState.members.length > 0, 'Synthetic scope must contain members')
    const synthetic = adminState.users.filter(user => /^calendar\.[a-z0-9._-]+@example\.com$/.test(user.email))
    assert(adminState.members.every(member => synthetic.some(user => user.id === member.user_id)), 'Archival requires every scope member to be a calendar.* synthetic user')
    const globalAdmin = synthetic.find(user => user.email === 'calendar.admin@example.com')
    assert(globalAdmin && !adminState.members.some(member => member.user_id === globalAdmin.id), 'Native global admin fixture must have no calendar membership')
  }
  const helper = await newActor(browser, browserName, 'helper')
  const employee = await newActor(browser, browserName, 'employee')
  console.log(`LOGINS READY: ${browserName}, helper + employee; last login ${new Date(lastLogin).toISOString()}; ${selectedBrowser ? 'no more logins in this run' : 'another browser will log in later'}.`)
  currentCheck = 'actor-and-day-preflight'
  const initial = await openState(helper.page, '/audit-calendar')
  assert.equal(initial.members.length, 5, 'This runner requires the five-member calendar synthetic fixture')
  assert.equal(initial.scope.archived, false, 'Synthetic calendar scope must be active')
  if (adminState) assert.equal(initial.scope.id, adminState.scope.id, 'Admin and helper must reference the same synthetic scope')
  assert.equal(initial.actor.can_manage, true, 'Helper must manage the scope')
  assert.equal(initial.actor.can_archive, false, 'Helper must not have archive capability')
  const own = await openState(employee.page, '/audit-calendar')
  assert.equal(own.scope.id, initial.scope.id, 'Employee must reference the same synthetic scope')
  assert.notEqual(own.actor.user_id, initial.actor.user_id, 'Separate synthetic helper and employee identities required')
  assert(own.members.some(member => member.user_id === own.actor.user_id && member.active), 'Synthetic employee must be an active calendar member')
  assert.equal(own.actor.can_manage, false, 'Employee must not inherit helper rights')
  assert.equal(own.actor.can_archive, false, 'Employee must not archive the scope')
  fixtureVerified = true
  const window = await openState(helper.page, `/audit-calendar?${new URLSearchParams({ from: dateAfter(initial.scope.today, 10), to: dateAfter(initial.scope.today, 60) })}`)
  const date = chooseDay(window, initial.scope.today, own.actor.user_id)
  assert(date, 'No unused weekday in server-today +10..60; stop without reusing or deleting existing history')
  const user = own.actor.user_id
  const retainedRun = { browser: browserName, date, user_id: user, lock_id: null, request_id: null, final_status: 'selected' }
  retained.push(retainedRun)
  await passed(currentCheck, { date, fixture: 'calendar.*@example.com', scope_id: initial.scope.id })

  currentCheck = 'employee-unlocked-day-has-no-lock-button'
  await openState(employee.page, availablePath(date, user))
  await controls(employee.page, date, false)
  await expect(employee.page.getByRole('button', { name: /Зафиксировать день/ })).toHaveCount(0)
  await expect(dayButton(employee.page, date, 'Запросить изменение дня')).toHaveCount(0)
  await passed(currentCheck)

  currentCheck = 'new-meeting-default-30-and-speaker-role'
  await checkMeeting(helper.page, date, window)
  await passed(currentCheck)

  currentCheck = 'helper-cannot-archive'
  await openState(helper.page, calendarPath(date, { view: 'management' }))
  await expect(helper.page.getByRole('button', { name: 'Архивировать контур', exact: true })).toHaveCount(0)
  await passed(currentCheck)

  currentCheck = 'helper-lock-day'
  let before = await openState(helper.page, availablePath(date, user))
  assert(!lockAt(before, user, date), 'Selected day must still be unused before mutation')
  await controls(helper.page, date, false)
  await dayButton(helper.page, date, 'Зафиксировать день').click()
  await reasonCommand(helper.page, 'availability.lock', { user_id: user, date, reason: `Native controls lock ${runId} ${browserName}` })
  let state = await openState(helper.page, availablePath(date, user))
  const lock = lockAt(state, user, date)
  assert(lock?.locked, 'Helper lock must persist')
  assert.equal(lock.locked_by_id, initial.actor.user_id, 'Lock must record the real helper actor')
  serverTimestamp(lock.locked_at, before, state, 'lock')
  retainedRun.lock_id = lock.id; retainedRun.final_status = 'locked'
  await screenshots(helper.page, 'helper', 'locked', () => controls(helper.page, date, true))
  await passed(currentCheck)

  currentCheck = 'employee-request-locked-day'
  before = await openState(employee.page, availablePath(date, user))
  await controls(employee.page, date, true)
  const reason = `Native controls request ${runId} ${browserName}`
  await dayButton(employee.page, date, 'Запросить изменение дня').click()
  await reasonCommand(employee.page, 'availability.request', { user_id: user, date, reason })
  state = await summary(employee.page, date, reason, 'Ожидает решения')
  let request = state.change_requests.find(item => item.user_id === user && item.date === date && item.reason === reason)
  assert(request && request.status === 'pending', 'Employee request must persist as pending')
  const id = request.id
  retainedRun.request_id = id; retainedRun.final_status = 'pending'
  assert.equal(request.requested_by_id, user, 'Request must record the real employee actor')
  serverTimestamp(request.requested_at, before, state, 'request')
  assert(lockAt(state, user, date)?.locked, 'Pending request must not unlock the day')
  assert(state.change_requests.every(item => item.user_id === user), 'Employee state must expose only own requests')
  await expect(requestRow(employee.page, reason)).toContainText(timeLabel(request.requested_at))
  await expect(employee.page.getByRole('button', { name: 'Одобрить и открыть день', exact: true })).toHaveCount(0)
  await screenshots(employee.page, 'employee', 'pending-request', async () => {
    await expect(requestRow(employee.page, reason)).toContainText(timeLabel(request.requested_at))
  })
  await passed(currentCheck, { requested_at: request.requested_at })

  currentCheck = 'helper-approve-request'
  before = await summary(helper.page, date, reason, 'Ожидает решения')
  await requestRow(helper.page, reason).getByRole('button', { name: 'Одобрить и открыть день', exact: true }).click()
  await reasonCommand(helper.page, 'availability.resolve', { id, action: 'approve', reason: `Native controls approve ${runId} ${browserName}` })
  state = await summary(helper.page, date, reason, 'Открыто для изменений')
  request = requestAt(state, id)
  assert.equal(request.status, 'approved', 'Helper approval must persist')
  assert.equal(request.opened_by_id, initial.actor.user_id, 'Approval must record the helper actor')
  serverTimestamp(request.opened_at, before, state, 'approve')
  assert.equal(lockAt(state, user, date)?.locked, false, 'Only approval opens the day')
  retainedRun.final_status = 'approved'
  await expect(requestRow(helper.page, reason)).toContainText(timeLabel(request.opened_at))
  await passed(currentCheck, { opened_at: request.opened_at })

  currentCheck = 'employee-edits-approved-day'
  state = await openState(employee.page, availablePath(date, user))
  await controls(employee.page, date, false)
  await expect(dayButton(employee.page, date, 'Зафиксировать день')).toHaveCount(0)
  await command(employee.page, 'availability.paint', { user_id: user, patches: [{ date, start: 600, end: 630, value: true }],
    expected: [{ date, start: 600, end: 630, value: null }] }, () => slot(employee.page, date).click())
  state = await openState(employee.page, availablePath(date, user))
  assert(state.availability.some(item => item.user_id === user && item.date === date && item.start <= 600 && item.end >= 630 && item.available), 'Employee edit must survive a real reload')
  await screenshots(employee.page, 'employee', 'approved-edit', async () => {
    await controls(employee.page, date, false)
    await expect(slot(employee.page, date)).toHaveAttribute('aria-label', `${date} 10:00: Свободен`)
  })
  await passed(currentCheck)

  currentCheck = 'helper-close-and-relock'
  before = await summary(helper.page, date, reason, 'Открыто для изменений')
  await requestRow(helper.page, reason).getByRole('button', { name: 'Закрыть заявку и день', exact: true }).click()
  await reasonCommand(helper.page, 'availability.resolve', { id, action: 'close', reason: `Native controls close ${runId} ${browserName}` })
  state = await summary(helper.page, date, reason, 'Закрыта, день зафиксирован')
  request = requestAt(state, id)
  assert.equal(request.status, 'closed', 'Closing a request must persist the closed state')
  assert.equal(request.closed_by_id, initial.actor.user_id, 'Close must record the helper actor')
  serverTimestamp(request.closed_at, before, state, 'close')
  assert(lockAt(state, user, date)?.locked, 'Closing a request must relock the day')
  assert(Array.isArray(request.before) && Array.isArray(request.after) && request.after.length > request.before.length, 'Closing must retain before/after snapshots for the new interval')
  retainedRun.final_status = 'closed'
  await screenshots(helper.page, 'helper', 'closed-request', async () => {
    const row = requestRow(helper.page, reason)
    for (const timestamp of [request.requested_at, request.opened_at, request.closed_at]) await expect(row).toContainText(timeLabel(timestamp))
  })
  await passed(currentCheck, { requested_at: request.requested_at, opened_at: request.opened_at, closed_at: request.closed_at })

  currentCheck = 'closed-controls-readonly-for-helper-and-employee'
  for (const actor of [helper, employee]) {
    await openState(actor.page, availablePath(date, user))
    await screenshots(actor.page, actor.role, 'closed-readonly', () => controls(actor.page, date, true))
    await summary(actor.page, date, reason, 'Закрыта, день зафиксирован')
    const row = requestRow(actor.page, reason)
    for (const timestamp of [request.requested_at, request.opened_at, request.closed_at]) await expect(row).toContainText(timeLabel(timestamp))
    await expect(row.getByRole('button')).toHaveCount(0)
  }
  await passed(currentCheck)

  currentCheck = 'workload-and-group-norm-native'
  const [workloadResponse] = await Promise.all([apiResponse(helper.page, '/api/audit-calendar/workload'),
    openState(helper.page, calendarPath(date, { view: 'workload' }))])
  assert.equal(workloadResponse.status(), 200, 'Workload must use the real scoped API')
  const report = await workloadResponse.json()
  const employeeReport = report.members.find(member => member.user_id === user)
  assert.equal(employeeReport.free_slots, 1, 'The saved half-hour must appear in reporting')
  assert.equal(employeeReport.free_minutes, 30)
  assert.equal(employeeReport.power_percent, 0, 'An empty planned day uses zero of the declared free time')
  await expect(helper.page.getByRole('table', { name: 'Плановая загрузка сотрудников' })).toBeVisible()
  await screenshots(helper.page, 'helper', 'workload', async () => {
    await expect(helper.page.locator('.ac-workload-table thead th')).toHaveCount(5)
  }, null, [[1920, 1080], [1440, 900], [1024, 768], [390, 844], [320, 700]])
  const directory = await openState(helper.page, calendarPath(date, { view: 'directories' }))
  const group = directory.groups.find(item => !item.archived && !item.legacy)
  assert(group, 'Synthetic fixture requires an editable group')
  await helper.page.getByRole('button', { name: `Изменить норму ${group.code}`, exact: true }).click()
  const normDialog = helper.page.getByRole('dialog')
  await expect(normDialog.getByRole('combobox', { name: /Область нормы/ })).toHaveValue(group.id)
  await expect(normDialog.getByLabel('Встреч на 10 будней', { exact: true })).toBeVisible()
  await screenshots(helper.page, 'helper', 'group-norm')
  await normDialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(normDialog).toHaveCount(0)
  await passed(currentCheck)

  currentCheck = 'global-admin-archive-and-restore'
  if (withArchive) {
    await archiveAndRestore(admin, helper, date, adminState)
    await passed(currentCheck)
  } else results.push({ browser: browserName, check: currentCheck, result: 'SKIP', reason: 'Native archive not requested; HTTP acceptance remains with the integrator. Use --archive for native coverage.' })

  currentCheck = 'native-runtime-health'
  for (const actor of [admin, helper, employee].filter(Boolean)) {
    assert.equal(actor.health.runtime_errors, 0, 'No uncaught frontend errors allowed')
    assert.equal(actor.health.calendar_http_errors.length, 0, 'No failed calendar API responses allowed')
  }
  await passed(currentCheck)
}

async function diagnoseLockForm(browser, browserName) {
  const helper = await newActor(browser, browserName, 'helper')
  console.log(`LOGINS READY: ${browserName}, helper diagnosis only; no more logins in this run.`)
  currentCheck = 'diagnose-lock-draft-without-submit'
  const initial = await openState(helper.page, '/audit-calendar')
  // This read-only diagnosis permits additional members added during acceptance.
  // The mutating runner above still requires its exact synthetic fixture.
  assert(initial.members.some(member => member.user_id === initial.actor.user_id && member.active && member.can_manage), 'Synthetic helper must still be an active planning assistant')
  assert(initial.actor.can_manage && !initial.scope.archived, 'Active helper scope required')
  fixtureVerified = true
  const state = await openState(helper.page, `/audit-calendar?${new URLSearchParams({ from: dateAfter(initial.scope.today, 10), to: dateAfter(initial.scope.today, 20) })}`)
  const date = chooseDay(state, initial.scope.today, initial.actor.user_id)
  assert(date, 'No unused diagnostic date')
  await openState(helper.page, availablePath(date, initial.actor.user_id))
  await screenshots(helper.page, 'helper', 'whole-day-actions', async () => {
    const actions = helper.page.getByRole('group', { name: `${date}: Действия на весь день`, exact: true }).filter({ visible: true })
    await expect(actions.getByRole('button')).toHaveCount(4)
    const tops = await actions.getByRole('button').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().top))
    assert(tops.every(top => Math.abs(top - tops[0]) <= 1), 'Four whole-day actions must share the same row')
  })
  await passed('whole-day-four-buttons-inline', { mutation_submitted: false })
  await dayButton(helper.page, date, 'Зафиксировать день').click()
  const dialog = await protectedReason(helper.page, `Native controls lock ${runId} ${browserName}`)
  await screenshots(helper.page, 'helper', 'diagnostic-lock-draft')
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
  await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
  await passed(currentCheck, { mutation_submitted: false })
}

try {
  for (const [browserName, launcher] of [['chromium', chromium], ['webkit', webkit]]) {
    if (selectedBrowser && browserName !== selectedBrowser) continue
    currentBrowser = browserName; currentCheck = 'launch'; fixtureVerified = false; activePage = null
    const browser = await launcher.launch()
    try { if (diagnoseLock) await diagnoseLockForm(browser, browserName); else await run(browser, browserName) }
    catch (error) {
      // Persist only allowlisted diagnostics, never raw responses, headers, traces or browser storage.
      if (fixtureVerified && activePage && !activePage.isClosed()) {
        const calendar = activePage.locator('.ac-page')
        if (await calendar.count()) {
          const path = `${browserName}-failure.png`
          await calendar.screenshot({ path: new URL(path, output).pathname, animations: 'disabled', timeout: 5000 }).then(() => artifacts.push({ path, browser: browserName, stage: currentCheck })).catch(() => undefined)
        }
      }
      failure = { ...failure, type: error.name, check: currentCheck, location: error.stack?.match(/verify-calendar-controls-native\.mjs:\d+:\d+/)?.[0] || null }
      await report('FAIL', failure)
      throw error
    } finally { await browser.close() }
  }
  await report('PASS')
  console.log(`PASS: ${results.filter(item => item.result === 'PASS').length} native control checks. Evidence: ${output.pathname}`)
} catch {
  await report('FAIL', failure || { check: currentCheck, browser: currentBrowser })
  console.error(`FAIL: ${currentBrowser}/${currentCheck}. Evidence: ${output.pathname}${restoreRequired ? ' RESTORE REQUIRED: inspect the synthetic scope archive state.' : ''}`)
  process.exitCode = 1
}
