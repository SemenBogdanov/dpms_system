import { expect, test, type Page, type Route } from '@playwright/test'
import type { CalendarMeetingWindowOptions, CalendarMeetingWindows, CalendarState, CalendarWorkload } from '../src/api/auditCalendar'
import { allSlots, dateRange, workSlots } from '../src/lib/auditCalendar'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

const first = '2026-09-14'
const last = '2026-09-20'
const beforeTen = '2026-09-14T06:59:00Z'
const afterPeriod = '2026-09-21T06:00:00Z'
const cell = (page: Page, start = 600, date = first) => page.locator(`.ac-window-cell[data-date="${date}"][data-start="${start}"]:visible`)
const dialog = (page: Page) => page.getByRole('dialog')
const choose = (page: Page) => dialog(page).getByRole('button', { name: /^Выбрать G1,/ })
const report = (page: Page) => page.getByRole('region', { name: 'Истекшие свободные окна', exact: true })
const count = (page: Page) => report(page).getByLabel('Количество истекших окон', { exact: true })
type Counts = (date: string, start: number, query: URLSearchParams) => [number, number]
type Batch = CalendarMeetingWindows
type Settings = {
  state?: CalendarState
  now?: string
  view?: 'graph' | 'workload'
  query?: Record<string, string>
  counts?: Counts
  batch?: (route: Route, data: Batch) => Promise<void>
  command?: (route: Route, body: Record<string, unknown>) => Promise<void>
}

function batchFor(route: Route, state: CalendarState, counts: Counts): Batch {
  const query = new URL(route.request().url()).searchParams
  const period = { from: query.get('from')!, to: query.get('to')!, duration: Number(query.get('duration')),
    group_id: query.get('group'), speaker_id: query.get('speaker_id'), full_day: query.get('full_day') === 'true' }
  return { version: state.scope.version, now: state.scope.now, period,
    cells: dateRange(period.from, period.to).flatMap(date => (period.full_day ? allSlots : workSlots).map(start => {
      const [confirmed, rawUncertain] = counts(date, start, query)
      const past = Date.parse(`${date}T00:00:00+03:00`) + start * 60000 < Date.parse(state.scope.now)
      const uncertain = past && !confirmed ? 0 : rawUncertain
      return { date, start, confirmed, uncertain, status: confirmed ? past ? 'expired' : 'available' : uncertain ? 'warning' : 'unavailable' }
    })) }
}

function detailFor(route: Route, state: CalendarState): CalendarMeetingWindowOptions {
  const params = new URL(route.request().url()).searchParams
  const composition = state.groups[0].versions[0]
  return { version: state.scope.version, now: state.scope.now,
    query: { date: params.get('date')!, start: Number(params.get('start')), duration: Number(params.get('duration')), group_id: params.get('group'), speaker_id: params.get('speaker_id') },
    options: [{ group_id: ids.g, group_version_id: composition.id, auditor_id: ids.a, tech_id: ids.t, speaker_id: ids.s, status: 'available', warnings: [] }] }
}

function workloadFor(route: Route, state: CalendarState): CalendarWorkload {
  const query = new URL(route.request().url()).searchParams
  const from = query.get('from')!, to = query.get('to')!
  const workingDays = dateRange(from, to).filter(date => ![0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay())).length
  return { version: state.scope.version, period: { from, to, group_id: query.get('group') }, working_days: workingDays,
    working_window: { start: 600, end: 1080, slot_minutes: 30 },
    members: state.members.map(member => ({ ...member, filled_days: 0, partial_days: 0, unfilled_days: workingDays, absence_days: 0,
      free_slots: 0, free_minutes: 0, planned_meetings: 0, planned_minutes: 0, planned_work_minutes: 0, outside_work_minutes: 0,
      target: 0, norm_percent: null, power_percent: null })) }
}

async function mountExpired(page: Page, settings: Settings = {}) {
  const state = settings.state || fixtureState()
  state.scope.now = settings.now || beforeTen
  state.scope.today = new Date(Date.parse(state.scope.now) + 3 * 3600000).toISOString().slice(0, 10)
  state.plans = settings.state ? state.plans : []
  const reads: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname.startsWith('/api/audit-calendar/')) reads.push(url.pathname + url.search)
  })
  // Enter a view without window requests until all local handlers are installed.
  const fixture = await mountCalendar(page, { state, view: 'directories', command: settings.command || (route => route.fulfill({ status: 409, json: { detail: 'Unexpected synthetic write' } })) })
  const wall = await page.evaluate(() => Date.now())
  const batches: URLSearchParams[] = [], details: URLSearchParams[] = [], workloads: URLSearchParams[] = []
  await page.route('**/api/audit-calendar/meeting-windows?**', async route => {
    expect(route.request().method()).toBe('GET')
    batches.push(new URL(route.request().url()).searchParams)
    const data = batchFor(route, state, settings.counts || ((date, start) => date === first && start === 600 ? [1, 0] : [0, 0]))
    if (settings.batch) await settings.batch(route, data)
    else await route.fulfill({ json: data })
  })
  await page.route('**/api/audit-calendar/meeting-window-options?**', route => {
    expect(route.request().method()).toBe('GET')
    details.push(new URL(route.request().url()).searchParams)
    return route.fulfill({ json: detailFor(route, state) })
  })
  await page.route('**/api/audit-calendar/workload?**', route => {
    expect(route.request().method()).toBe('GET')
    workloads.push(new URL(route.request().url()).searchParams)
    return route.fulfill({ json: workloadFor(route, state) })
  })
  const query = new URLSearchParams({ from: first, to: last, view: settings.view || 'graph', ...settings.query })
  await page.goto(`/audit-calendar?${query}`)
  await expect(page.locator('.ac-bound-content')).toHaveAttribute('aria-busy', 'false')
  const advance = async (milliseconds: number, focus = true) => {
    await page.clock.setSystemTime(new Date(wall + milliseconds))
    if (focus) await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  }
  return { ...fixture, reads, batches, details, workloads, advance }
}

async function noNewReads(page: Page, reads: string[], baseline: string[]) {
  // Negative request assertions need a short observation window after clock effects.
  await page.waitForTimeout(300)
  expect(reads).toEqual(baseline)
}

test('server-clock deadline expires windows without GET and a backward clock jump never reopens them', async ({ page }) => {
  const { reads, commands, advance } = await mountExpired(page, { counts: (date, start) => date !== first ? [0, 0] : start === 600 ? [2, 1] : start === 630 ? [0, 3] : start === 660 ? [1, 0] : [0, 0] })
  await expect(cell(page)).toHaveClass(/ac-window-available/)
  await expect(cell(page, 630)).toHaveClass(/ac-window-warning/)
  const baseline = [...reads]
  await advance(2 * 60000)
  await expect(cell(page)).toHaveClass(/ac-window-expired/)
  await expect(cell(page)).toBeDisabled()
  await expect(cell(page)).toHaveAccessibleName(/Окно истекло/)
  await expect(cell(page).locator('svg.lucide-x')).toHaveCount(1)
  await expect(cell(page).locator('span')).toHaveCount(0)
  await expect(cell(page, 630)).toBeEnabled()
  await noNewReads(page, reads, baseline)
  await advance(32 * 60000)
  await expect(cell(page, 630)).toHaveClass(/ac-window-unavailable/)
  await expect(cell(page, 630)).toBeDisabled()
  await expect(cell(page, 630)).toHaveAccessibleName(/Вариантов: 0; подтверждено: 0; с неизвестной доступностью: 0/)
  await expect(cell(page, 660)).toBeEnabled()
  await noNewReads(page, reads, baseline)
  await advance(0)
  await noNewReads(page, reads, baseline)
  await expect(cell(page)).toHaveClass(/ac-window-expired/)
  await expect(cell(page)).toBeDisabled()
  await expect(cell(page, 630)).toHaveClass(/ac-window-unavailable/)
  await expect(cell(page, 630)).toBeDisabled()
  await expect(cell(page, 630)).toHaveAccessibleName(/Вариантов: 0; подтверждено: 0; с неизвестной доступностью: 0/)
  await expect(cell(page, 660)).toBeEnabled()
  expect(commands).toEqual([])
})

test('a delayed batch includes request elapsed time instead of reopening a deadline from stale serverNow', async ({ page }) => {
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  const { reads, batches, commands, advance } = await mountExpired(page, { batch: async (route, data) => {
    await hold
    await route.fulfill({ json: data })
  } })
  try {
    await expect.poll(() => batches.length).toBe(1)
    await expect(cell(page)).toHaveClass(/ac-window-pending/)
    const baseline = [...reads]
    await advance(2 * 60000)
    release()
    await expect(cell(page)).toHaveAttribute('aria-busy', 'false')
    await expect(cell(page)).toHaveClass(/ac-window-expired/)
    await expect(cell(page)).toBeDisabled()
    await noNewReads(page, reads, baseline)
    expect(commands).toEqual([])
  } finally { release() }
})

test('an already-open options dialog loses choose actions at the deadline without refreshing', async ({ page }) => {
  const { reads, details, commands, advance } = await mountExpired(page)
  await expect(cell(page)).toBeEnabled()
  await cell(page).click()
  await expect(choose(page)).toBeVisible()
  expect(details).toHaveLength(1)
  const baseline = [...reads]
  await advance(2 * 60000)
  await expect(dialog(page)).toBeVisible()
  await expect(dialog(page).getByRole('status')).toContainText('Окно истекло')
  await expect(choose(page)).toHaveCount(0)
  await expect(dialog(page).locator('.ac-window-option')).toHaveCount(1)
  await expect(dialog(page).getByRole('button', { name: 'Закрыть', exact: true })).toBeEnabled()
  await noNewReads(page, reads, baseline)
  expect(commands).toEqual([])
})

test('a prefilled editor checks the live deadline on submit and preserves the draft without POST', async ({ page }) => {
  const { commands, advance } = await mountExpired(page)
  await expect(cell(page)).toBeEnabled()
  await cell(page).click()
  await choose(page).click()
  const group = dialog(page).getByRole('combobox', { name: 'Группа', exact: true })
  await expect(group).toBeEnabled()
  await expect(group).toHaveValue(ids.g)
  await expect(dialog(page).getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue(ids.s)
  const activity = dialog(page).getByRole('textbox', { name: 'Активность', exact: true })
  await activity.fill('Черновик до истечения окна')
  // No focus event: validation must read current time, not rely on a prior render.
  await advance(2 * 60000, false)
  await dialog(page).getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog(page).getByRole('alert')).toContainText('окно истекло')
  await expect(activity).toHaveValue('Черновик до истечения окна')
  await expect(group).toHaveValue(ids.g)
  expect(commands).toEqual([])
})

test('an uncertain prefill replays the identical command after expiry; changed fields cannot borrow that exemption', async ({ page }) => {
  const state = fixtureState()
  state.plans = []
  const raw: string[] = []
  const receipts = new Map<string, number>()
  const { commands, advance } = await mountExpired(page, { state, command: async (route, body) => {
    raw.push(route.request().postData()!)
    const id = String(body.request_id)
    if (!receipts.has(id)) receipts.set(id, ++state.scope.version)
    // The synthetic server committed once, but the first two responses are lost.
    if (raw.length <= 2) return route.abort('failed')
    await route.fulfill({ json: { version: receipts.get(id), result: {} } })
  } })
  await expect(cell(page)).toBeEnabled()
  await cell(page).click()
  await choose(page).click()
  const group = dialog(page).getByRole('combobox', { name: 'Группа', exact: true })
  const activity = dialog(page).getByRole('textbox', { name: 'Активность', exact: true })
  const save = dialog(page).getByRole('button', { name: 'Сохранить', exact: true })
  const originalActivity = 'Проверка потерянного ответа'
  await expect(group).toBeEnabled()
  await activity.fill(originalActivity)
  await save.click()
  await expect.poll(() => commands.length).toBe(1)
  await expect(dialog(page).getByRole('alert')).toBeVisible()
  await expect(save).toBeEnabled()
  const original = structuredClone(commands[0])
  expect(original.request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i)
  expect(original).toMatchObject({ operation: 'plan.save', expected_version: 1, payload: {
    date: first, start: 600, duration: 30, group_id: ids.g, speaker_id: ids.s, activity: originalActivity, status: 'planned', reason: '',
  } })
  await advance(2 * 60000)
  await save.click()
  await expect.poll(() => commands.length).toBe(2)
  await expect(save).toBeEnabled()
  await expect(dialog(page).getByRole('alert')).toBeVisible()
  expect(commands[1]).toEqual(original)
  expect(raw[1]).toBe(raw[0])
  await activity.fill('Изменённый запрос после дедлайна')
  await save.click()
  await expect(dialog(page).getByRole('alert')).toContainText('окно истекло')
  expect(commands).toHaveLength(2)
  await expect(activity).toHaveValue('Изменённый запрос после дедлайна')
  await activity.fill(originalActivity)
  await save.click()
  await expect(dialog(page)).toHaveCount(0)
  expect(commands).toHaveLength(3)
  expect(commands[2]).toEqual(original)
  expect(raw).toEqual([raw[0], raw[0], raw[0]])
  expect(receipts.size).toBe(1)
  expect(state.scope.version).toBe(2)
})

test('Moscow midnight expires the new local-day slot even while the UTC date is unchanged', async ({ page }) => {
  const state = fixtureState()
  state.plans[0].start = 1410
  state.plans[0].duration = 30
  const next = '2026-09-15'
  const { reads, batches, commands, advance } = await mountExpired(page, { state, now: '2026-09-14T20:59:00Z', query: { day: next }, counts: (date, start) => date === next && [0, 30].includes(start) ? [1, 0] : [0, 0] })
  await expect(cell(page, 0, next)).toBeEnabled()
  await expect(cell(page, 30, next)).toBeEnabled()
  expect(batches[0].get('full_day')).toBe('true')
  const baseline = [...reads]
  await advance(2 * 60000)
  await expect(cell(page, 0, next)).toHaveClass(/ac-window-expired/)
  await expect(cell(page, 0, next)).toBeDisabled()
  await expect(cell(page, 30, next)).toBeEnabled()
  await noNewReads(page, reads, baseline)
  expect(commands).toEqual([])
})

test('expired report counts unique weekday intervals at fixed 30 minutes, excludes unknown-only past and applies group filtering', async ({ page }) => {
  const state = fixtureState()
  const extraId = (n: number) => `00000000-0000-4000-8000-00000000050${n}`
  state.members.push(...state.members.map((member, i) => ({ ...member, user_id: extraId(i + 1), code: `${member.code}2`, full_name: `${member.full_name} второй группы`, can_manage: false })))
  state.groups.push({ ...state.groups[0], id: extraId(4), code: 'G2', label: 'Вторая тестовая группа', versions: [{ ...state.groups[0].versions[0], id: extraId(5), auditor_id: extraId(1), tech_id: extraId(2) }] })
  const { batches, commands } = await mountExpired(page, { state, now: afterPeriod, view: 'workload', query: { window_duration: '90', window_speaker: ids.s }, counts: (date, start, query) => {
    if (date === first && start === 600) return [2, 0]
    if (date === first && start === 630 && !query.has('group')) return [1, 0]
    if (date === '2026-09-15' && start === 600) return [0, 2]
    if (['2026-09-19', '2026-09-20'].includes(date) && start === 600) return [2, 0]
    return [0, 0]
  } })
  await expect(count(page)).toHaveText('2')
  expect(batches).toHaveLength(1)
  expect(Object.fromEntries(batches[0])).toEqual({ from: first, to: last, duration: '30', full_day: 'false' })
  await page.getByLabel('Группа отчёта', { exact: true }).selectOption(ids.g)
  await expect.poll(() => batches.at(-1)?.get('group')).toBe(ids.g)
  await expect(count(page)).toHaveText('1')
  expect(Object.fromEntries(batches.at(-1)!)).toEqual({ from: first, to: last, duration: '30', full_day: 'false', group: ids.g })
  await page.getByLabel('Группа отчёта', { exact: true }).selectOption('')
  await expect(count(page)).toHaveText('2')
  expect(commands).toEqual([])
})

test('local report refresh waits for fresh state v2 before fetching its windows and does not start polling', async ({ page }) => {
  const state = fixtureState()
  const versions: number[] = []
  const { reads, batches, workloads, commands, advance } = await mountExpired(page, { state, now: afterPeriod, view: 'workload',
    counts: (date, start) => date === first && (start === 600 || (state.scope.version === 2 && start === 630)) ? [1, 0] : [0, 0],
    batch: async (route, data) => {
      versions.push(data.version)
      await route.fulfill({ json: data })
    },
  })
  await expect(count(page)).toHaveText('1')
  expect(versions).toEqual([1])
  const initialWorkloads = workloads.length
  let stateRequests = 0
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  state.scope.version = 2
  await page.route('**/api/audit-calendar/state?**', async route => {
    expect(route.request().method()).toBe('GET')
    stateRequests++
    await hold
    await route.fulfill({ json: state })
  })
  try {
    await page.getByRole('button', { name: 'Обновить отчёт', exact: true }).click()
    await expect.poll(() => stateRequests).toBe(1)
    await page.waitForTimeout(300)
    expect(batches).toHaveLength(1)
    expect(workloads).toHaveLength(initialWorkloads)
    release()
    await expect(count(page)).toHaveText('2')
    await expect(page.locator('.ac-workload-table')).toBeVisible()
    expect(versions).toEqual([1, 2])
    expect(workloads).toHaveLength(initialWorkloads + 1)
    expect(stateRequests).toBe(1)
    await expect(report(page).getByRole('status')).toHaveCount(0)
    const baseline = [...reads]
    await advance(2 * 60000)
    await noNewReads(page, reads, baseline)
    expect(commands).toEqual([])
  } finally { release() }
})

test('loading, failed, incomplete and duplicate report batches remain unknown rather than a measured zero', async ({ page }) => {
  let phase: 'pending' | 'partial' | 'duplicate' | 'zero' = 'pending'
  let release!: () => void
  const hold = new Promise<void>(resolve => { release = resolve })
  const { commands, batches } = await mountExpired(page, { now: afterPeriod, view: 'workload', counts: () => [0, 0], batch: async (route, data) => {
    if (phase === 'pending') await hold
    if (phase === 'pending') return route.fulfill({ status: 503, json: { detail: 'Сервис окон недоступен' } })
    if (phase === 'partial') data.cells.pop()
    if (phase === 'duplicate') data.cells[data.cells.length - 1] = { ...data.cells[0] }
    await route.fulfill({ json: data })
  } })
  try {
    await expect(report(page)).toHaveAttribute('aria-busy', 'true')
    await expect(count(page)).toHaveText('—')
    release()
    await expect(report(page).getByRole('status')).toContainText('Сервис окон недоступен')
    await expect(count(page)).toHaveText('—')
    for (const next of ['partial', 'duplicate', 'zero'] as const) {
      phase = next
      const before = batches.length
      await page.getByRole('button', { name: 'Обновить отчёт', exact: true }).click()
      await expect.poll(() => batches.length).toBe(before + 1)
      await expect(report(page)).toHaveAttribute('aria-busy', 'false')
      if (phase === 'zero') {
        await expect(count(page)).toHaveText('0')
        await expect(report(page).getByRole('status')).toHaveCount(0)
      } else {
        await expect(report(page).getByRole('status')).toContainText('неполный или некорректный набор')
        await expect(count(page)).toHaveText('—')
      }
    }
    expect(commands).toEqual([])
  } finally { release() }
})

test('31-day report is allowed but a longer period never fetches a truncated or partial windows report', async ({ page }) => {
  const { batches, workloads, commands } = await mountExpired(page, { now: afterPeriod, view: 'workload', query: { to: '2026-10-14' }, counts: () => [0, 0] })
  await expect(count(page)).toHaveText('0')
  expect(batches).toHaveLength(1)
  expect(batches[0].get('to')).toBe('2026-10-14')
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  await page.locator('.ac-period').getByLabel('По', { exact: true }).fill('2026-10-15')
  await page.locator('.ac-period').getByRole('button', { name: 'Применить', exact: true }).click()
  await expect.poll(() => workloads.at(-1)?.get('to')).toBe('2026-10-15')
  await expect(report(page).getByRole('status')).toContainText('31 днём')
  await expect(count(page)).toHaveText('—')
  await page.waitForTimeout(300)
  expect(batches).toHaveLength(1)
  expect(commands).toEqual([])
})
