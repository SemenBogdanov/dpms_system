import { expect, test, type Locator, type Page } from '@playwright/test'
import { fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'

type State = ReturnType<typeof fixtureState>
type Plan = State['plans'][number]
type Fact = State['facts'][number]
const day = '2026-09-14'
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const third = { group: uuid(214), speaker: uuid(213) }
const graph = (page: Page) => page.getByRole('region', { name: 'График встреч', exact: true })
const modal = (page: Page) => page.getByRole('dialog')
const hiddenCancelled = (page: Page) => graph(page).getByRole('checkbox', { name: 'Скрыть отменённые', exact: true })
const add = (page: Page, time: string, date = day) => graph(page).locator(`button[aria-label="Создать план ${date} ${time}"]:visible`)
const entry = (page: Page, layer: 'plan' | 'fact', activity: string) => graph(page).locator(`.ac-meeting.ac-${layer}:visible`).filter({ hasText: activity })
const clock = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`

function parallelState(): State {
  const state = fixtureState()
  const originalMembers = [...state.members]
  for (const [index, base] of [[2, 200], [3, 210]]) {
    state.members.push(...originalMembers.map((member, i) => ({ ...member, user_id: uuid(base + i + 1), code: `${member.code}${index}`, full_name: `${member.full_name} ${index}`, can_manage: false })))
    state.groups.push({ ...state.groups[0], id: uuid(base + 4), code: `G${index}`, label: `Независимая группа ${index}`, versions: [{ ...state.groups[0].versions[0], id: uuid(base + 6), auditor_id: uuid(base + 1), tech_id: uuid(base + 2) }] })
  }
  state.plans = [
    { ...state.plans[0], activity: 'Параллель А', issues: [], warnings: [] },
    { ...state.plans[0], id: uuid(205), group_id: uuid(204), speaker_id: uuid(203), activity: 'Параллель Б', duration: 60, issues: [], warnings: [] },
  ]
  return state
}

function fact(state: State, plan: Plan, n: number, overrides: Partial<Fact> = {}): Fact {
  return { id: uuid(n), plan_id: plan.id, date: plan.date, start: plan.start, duration: plan.duration,
    group_id: plan.group_id, activity: `Факт ${plan.activity}`, speaker_id: plan.speaker_id, outcome: 'completed',
    reason: `Основание ${n}`, evidence: `Протокол ${n}`, recorded_by_id: ids.a, recorded_at: state.scope.now,
    participant_snapshot: [], planned_snapshot: { id: plan.id, activity: plan.activity }, composition_unknown: true, origin: 'native', ...overrides }
}

function pairedState(): State {
  const state = parallelState()
  // Array order and actual start times deliberately differ from plan order.
  state.facts = [
    fact(state, state.plans[1], 302, { duration: 30 }),
    fact(state, state.plans[0], 301, { start: 630, duration: 60 }),
    fact(state, state.plans[0], 303, { plan_id: null, start: 720, duration: 30, activity: 'Самостоятельный факт', planned_snapshot: {} }),
  ]
  return state
}

function cancelledState(): State {
  const state = parallelState()
  state.plans[1].status = 'cancelled'
  state.plans.push(
    { ...state.plans[0], id: uuid(401), start: 780, duration: 30, activity: 'Действующий план' },
    { ...state.plans[0], id: uuid(402), start: 840, duration: 30, activity: 'Отменённый план без факта', status: 'cancelled' },
    { ...state.plans[0], id: uuid(407), start: 870, duration: 30, activity: 'План с отменой вне периода', fact_outcome: 'cancelled' },
    { ...state.plans[0], id: uuid(408), start: 930, duration: 30, activity: 'План с проведением вне периода', fact_outcome: 'completed' },
  )
  state.facts = [
    fact(state, state.plans[0], 403, { outcome: 'cancelled', activity: 'Отменённый факт семьи' }),
    fact(state, state.plans[1], 404, { activity: 'Проведённый факт отменённого плана' }),
    fact(state, state.plans[0], 405, { plan_id: null, start: 900, duration: 30, activity: 'Проведённый факт без плана', planned_snapshot: {} }),
    fact(state, state.plans[0], 406, { plan_id: null, start: 960, duration: 30, activity: 'Отменённый факт без плана', outcome: 'cancelled', planned_snapshot: {} }),
  ]
  return state
}

async function settledGraph(page: Page) {
  await expect(page.locator('.ac-bound-content')).toHaveAttribute('aria-busy', 'false')
  const cell = graph(page).locator('.ac-window-cell:visible').first()
  await expect(cell).toBeVisible()
  await expect(cell).not.toHaveAttribute('aria-busy', 'true')
}

function watchReads(page: Page) {
  const reads: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (request.method() === 'GET' && /\/api\/audit-calendar\/(state|meeting-windows)$/.test(url.pathname)) reads.push(url.pathname + url.search)
  })
  return reads
}

async function expectNoReload(page: Page, reads: string[], baseline: string[]) {
  await settledGraph(page)
  // A bounded observation window catches effects scheduled after URL rendering.
  await page.waitForTimeout(300)
  expect(reads).toEqual(baseline)
}

async function box(locator: Locator) {
  await expect(locator).toBeVisible()
  const bounds = await locator.boundingBox()
  expect(bounds).not.toBeNull()
  return bounds!
}

async function expectDisjoint(locators: Locator[]) {
  const boxes = []
  for (const locator of locators) boxes.push(await box(locator))
  for (let i = 0; i < boxes.length; i++) {
    expect(boxes[i].width).toBeGreaterThan(0)
    expect(boxes[i].height).toBeGreaterThan(0)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j]
      const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
      const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
      expect(overlapX <= 0.5 || overlapY <= 0.5, `controls ${i} and ${j} must not overlap`).toBe(true)
    }
  }
}

async function expectFreshSlot(page: Page, start: number) {
  await expect(modal(page).getByRole('heading', { name: 'План встречи', exact: true })).toBeVisible()
  await expect(modal(page).getByRole('combobox', { name: 'Группа', exact: true })).toHaveValue('')
  await expect(modal(page).getByRole('combobox', { name: 'Докладчик', exact: true })).toHaveValue('')
  await expect(modal(page).getByRole('textbox', { name: 'Активность', exact: true })).toHaveValue('')
  await expect(modal(page).locator('.ac-meeting-time')).toContainText(`${clock(start)}–${clock(start + 30)} · 30 мин`)
}

async function closeModal(page: Page) {
  await modal(page).getByRole('button', { name: 'Закрыть', exact: true }).click()
  await expect(modal(page)).toHaveCount(0)
}

for (const width of [1440, 390]) test(`occupied start and continuation create an independent plan with the exact payload at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  const state = parallelState()
  const originalPlans = structuredClone(state.plans)
  const { commands } = await mountCalendar(page, { state })
  const optionQueries: URLSearchParams[] = []
  await page.route('**/api/audit-calendar/meeting-options?**', route => {
    const query = new URL(route.request().url()).searchParams
    optionQueries.push(query)
    return route.fulfill({ json: { version: state.scope.version, date: query.get('date'), start: Number(query.get('start')), duration: Number(query.get('duration')),
      groups: state.groups.map(group => ({ id: group.id, code: group.code, label: group.label, eligible: group.id === third.group, issues: [], warnings: [] })) } })
  })
  await settledGraph(page)
  await expectDisjoint(state.plans.map(plan => entry(page, 'plan', plan.activity)))
  await expect(graph(page).locator(`button[aria-label^="Создать план ${day} "]:visible`)).toHaveCount(16)
  if (width === 1440) {
    const row = graph(page).locator('.ac-add-meeting-row:visible').filter({ has: page.getByRole('button', { name: `Создать план ${day} 10:00`, exact: true }) })
    await expect(row).toHaveCount(1)
    await expect(row.getByRole('button', { name: /^Создать план/ })).toHaveCount(16)
    await expect(graph(page).locator('button[aria-label^="Создать план 2026-09-15 "]:visible')).toHaveCount(16)
  }
  for (const start of [600, 630]) {
    await expect(add(page, clock(start))).toHaveCount(1)
    await add(page, clock(start)).click()
    await expectFreshSlot(page, start)
    if (start === 600) await closeModal(page)
  }
  const group = modal(page).getByRole('combobox', { name: 'Группа', exact: true })
  await expect(group).toBeEnabled()
  await group.selectOption(third.group)
  await modal(page).getByRole('textbox', { name: 'Активность', exact: true }).fill('Новая независимая встреча')
  await modal(page).getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption(third.speaker)
  await expect(group).toBeEnabled()
  await modal(page).getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(modal(page)).toHaveCount(0)
  expect(commands).toHaveLength(1)
  expect(commands[0]).toMatchObject({ operation: 'plan.save', expected_version: 1 })
  expect(commands[0].payload).toEqual({ date: day, start: 630, duration: 30, group_id: third.group, activity: 'Новая независимая встреча', speaker_id: third.speaker, status: 'planned', reason: '' })
  expect(optionQueries.length).toBeGreaterThan(0)
  expect(optionQueries.every(query => !query.has('plan_id'))).toBe(true)
  expect(state.plans).toEqual(originalPlans)
})

test('full-day occupied slots retain exactly one create action through the final half-hour', async ({ page }) => {
  const state = parallelState()
  state.plans.forEach(plan => { plan.start = 450 })
  const { commands } = await mountCalendar(page, { state })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(graph(page).getByRole('combobox', { name: 'День', exact: true })).toBeVisible()
    await expect(graph(page).locator(`button[aria-label^="Создать план ${day} "]:visible`)).toHaveCount(48)
    for (const start of [450, 480, 1410]) {
      await expect(add(page, clock(start))).toHaveCount(1)
      await add(page, clock(start)).click()
      await expectFreshSlot(page, start)
      await closeModal(page)
    }
  }
  expect(commands).toEqual([])
})

test('parallel plan/fact lanes preserve plan_id association when fact order and actual times differ', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = pairedState()
  const { commands } = await mountCalendar(page, { state })
  for (const plan of state.plans) {
    const ownFact = state.facts.find(item => item.plan_id === plan.id)!
    const lane = graph(page).getByRole('group', { name: /^Встречи 2026-09-14, дорожка / }).filter({ has: page.locator('.ac-plan').filter({ hasText: plan.activity }) })
    await expect(lane).toHaveCount(1)
    await expect(lane.locator('.ac-plan')).toHaveCount(1)
    await expect(lane.locator('.ac-fact').filter({ hasText: ownFact.activity })).toHaveCount(1)
    const otherFact = state.facts.find(item => item.plan_id && item.plan_id !== plan.id)!
    await expect(lane.locator('.ac-fact').filter({ hasText: otherFact.activity })).toHaveCount(0)
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expectDisjoint([...state.plans.map(plan => entry(page, 'plan', plan.activity)), ...state.facts.map(item => entry(page, 'fact', item.activity))])
    for (const plan of state.plans) {
      const ownFact = state.facts.find(item => item.plan_id === plan.id)!
      for (const button of [entry(page, 'plan', plan.activity), entry(page, 'fact', ownFact.activity)]) {
        await button.click()
        await expect(modal(page).getByRole('heading', { name: 'Факт встречи', exact: true })).toBeVisible()
        await expect(modal(page).getByText(ownFact.evidence, { exact: true })).toBeVisible()
        await expect(modal(page)).toContainText(plan.activity)
        await expect(modal(page).getByRole('button', { name: 'Сохранить', exact: true })).toHaveCount(0)
        await closeModal(page)
      }
    }
    await entry(page, 'fact', 'Самостоятельный факт').click()
    await expect(modal(page).getByText('Протокол 303', { exact: true })).toBeVisible()
    await closeModal(page)
    await add(page, '10:30').click()
    await expectFreshSlot(page, 630)
    await closeModal(page)
  }
  expect(commands).toEqual([])
})

async function expectCancelledVisibility(page: Page, state: State, show: boolean) {
  const visiblePlans = new Set(['Действующий план', 'План с проведением вне периода'])
  for (const plan of state.plans) await expect(entry(page, 'plan', plan.activity)).toHaveCount(show || visiblePlans.has(plan.activity) ? 1 : 0)
  for (const item of state.facts) await expect(entry(page, 'fact', item.activity)).toHaveCount(show || item.outcome === 'completed' ? 1 : 0)
}

for (const width of [1440, 390]) test(`cancelled families default hidden; URL Back/Forward is local and preserves completed facts at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  const reads = watchReads(page)
  const state = cancelledState()
  const original = structuredClone({ plans: state.plans, facts: state.facts })
  const { commands } = await mountCalendar(page, { state })
  await settledGraph(page)
  const baseline = [...reads]
  expect(baseline.some(url => url.includes('/state?'))).toBe(true)
  expect(baseline.some(url => url.includes('/meeting-windows?'))).toBe(true)
  const initialQuery = Object.fromEntries(new URL(page.url()).searchParams)
  await expect(hiddenCancelled(page)).toBeChecked()
  await expectCancelledVisibility(page, state, false)
  const outside = state.plans.filter(plan => plan.fact_outcome)
  expect(outside).toHaveLength(2)
  expect(state.facts.some(item => outside.some(plan => item.plan_id === plan.id))).toBe(false)
  const completed = outside.find(plan => plan.fact_outcome === 'completed')!
  await entry(page, 'plan', completed.activity).click()
  await expect(modal(page)).toContainText('Результат зафиксирован вне текущей выборки: Проведено. План неизменяем.')
  await expect(modal(page).getByRole('button', { name: 'Сохранить', exact: true })).toHaveCount(0)
  await expect(modal(page).getByRole('combobox')).toHaveCount(0)
  await closeModal(page)
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).not.toBeChecked()
  await expect(page).toHaveURL(/[?&]show_cancelled=1(?:&|$)/)
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ ...initialQuery, show_cancelled: '1' })
  await expectCancelledVisibility(page, state, true)
  const cancelled = outside.find(plan => plan.fact_outcome === 'cancelled')!
  await entry(page, 'plan', cancelled.activity).click()
  await expect(modal(page)).toContainText('Результат зафиксирован вне текущей выборки: Отменено. План неизменяем.')
  await expect(modal(page).getByRole('button', { name: 'Сохранить', exact: true })).toHaveCount(0)
  await expect(modal(page).getByRole('combobox')).toHaveCount(0)
  await closeModal(page)
  await expectNoReload(page, reads, baseline)
  await page.goBack()
  await expect(hiddenCancelled(page)).toBeChecked()
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(initialQuery)
  await expectCancelledVisibility(page, state, false)
  await expectNoReload(page, reads, baseline)
  await page.goForward()
  await expect(hiddenCancelled(page)).not.toBeChecked()
  await expectCancelledVisibility(page, state, true)
  await expectNoReload(page, reads, baseline)
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).toBeChecked()
  expect(new URL(page.url()).searchParams.has('show_cancelled')).toBe(false)
  await expectCancelledVisibility(page, state, false)
  await expectNoReload(page, reads, baseline)
  expect({ plans: state.plans, facts: state.facts }).toEqual(original)
  expect(commands).toEqual([])
})

test('showing a cancelled out-of-hours family does not reload state or the windows batch', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const reads = watchReads(page)
  const state = cancelledState()
  state.plans[0].start = 450
  state.facts[0].start = 450
  const { commands } = await mountCalendar(page, { state })
  await settledGraph(page)
  const baseline = [...reads]
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).not.toBeChecked()
  await expect(entry(page, 'plan', state.plans[0].activity)).toBeVisible()
  await expect(entry(page, 'fact', state.facts[0].activity)).toBeVisible()
  await expectNoReload(page, reads, baseline)
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).toBeChecked()
  await expect(entry(page, 'plan', state.plans[0].activity)).toHaveCount(0)
  await expectNoReload(page, reads, baseline)
  expect(commands).toEqual([])
})

test('cancellation filtering is graph-only and leaves the dataset and period KPIs intact', async ({ page }) => {
  const state = cancelledState()
  const { commands } = await mountCalendar(page, { state })
  await expectCancelledVisibility(page, state, false)
  const kpis = await page.locator('.ac-kpis').innerText()
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).not.toBeChecked()
  await expect(page.locator('.ac-kpis')).toHaveText(kpis, { useInnerText: true })
  await hiddenCancelled(page).click()
  await expect(hiddenCancelled(page)).toBeChecked()
  const navigation = page.getByRole('navigation', { name: 'Представления календаря' })
  await navigation.getByRole('link', { name: 'Датасет', exact: true }).click()
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  for (const record of [...state.plans, ...state.facts]) await expect(page.getByRole('main')).toContainText(record.activity)
  await navigation.getByRole('link', { name: 'График встреч', exact: true }).click()
  await expect(hiddenCancelled(page)).toBeChecked()
  await expectCancelledVisibility(page, state, false)
  expect(commands).toEqual([])
})

test('readonly and archived calendars expose meetings but no create action in working or full-day layouts', async ({ page }) => {
  for (const mode of ['readonly', 'archive']) {
    for (const fullDay of [false, true]) {
      const state = parallelState()
      state.actor.can_manage = mode !== 'readonly'
      state.scope.archived = mode === 'archive'
      if (fullDay) state.plans.forEach(plan => { plan.start = 450 })
      const { commands } = await mountCalendar(page, { state })
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 900 })
        await expect(entry(page, 'plan', state.plans[0].activity)).toBeVisible()
        await expect(graph(page).getByRole('button', { name: /^Создать план / })).toHaveCount(0)
        await entry(page, 'plan', state.plans[0].activity).click()
        await expect(modal(page).getByRole('heading', { name: 'План встречи', exact: true })).toBeVisible()
        await expect(modal(page).getByRole('button', { name: 'Сохранить', exact: true })).toHaveCount(0)
        await closeModal(page)
      }
      expect(commands).toEqual([])
    }
  }
})

test('parallel entries and create controls remain separate at 1440/390 in all themes', async ({ page }, testInfo) => {
  const state = pairedState()
  state.plans.forEach(plan => { plan.activity += ' · Проверка согласования большой программы независимой группы с длинным названием' })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const { commands } = await mountCalendar(page, { state })
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      await settledGraph(page)
      await add(page, '10:00').scrollIntoViewIfNeeded()
      await add(page, '10:00').click({ trial: true })
      const entries = [...state.plans.map(plan => entry(page, 'plan', plan.activity)), ...state.facts.map(item => entry(page, 'fact', item.activity))]
      await expectDisjoint([...entries, add(page, '10:00')])
      const plus = await box(add(page, '10:00'))
      const plans = []
      for (const plan of state.plans) plans.push(await box(entry(page, 'plan', plan.activity)))
      expect(plus.y).toBeGreaterThanOrEqual(Math.max(...plans.map(bounds => bounds.y + bounds.height)) - 0.5)
      if (width === 390) {
        for (const bounds of plans) {
          expect(plus.x).toBeGreaterThanOrEqual(bounds.x - 1)
          expect(plus.x + plus.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1)
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
      await page.screenshot({ path: testInfo.outputPath(`parallel-${width}-${theme}.png`), fullPage: true, animations: 'disabled' })
    }
  }
  expect(errors).toEqual([])
  expect(commands).toEqual([])
})
