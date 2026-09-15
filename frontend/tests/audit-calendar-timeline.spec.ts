import { expect, test, type Page, type Route } from '@playwright/test'
import type { CalendarState, CalendarTimeline, CalendarTimelineMeeting } from '../src/api/auditCalendar'
import { commonTimelineSlot, overlapsSlot, personMeetings, timelineLanes, timelineSlot } from '../src/lib/auditCalendarTimeline'
import { fixtureState, fixtureTimeline, ids, mountCalendar } from './audit-calendar.fixtures'

const first = '2026-09-14'
const second = '2026-09-15'
const last = '2026-09-20'
const endpoint = '**/api/audit-calendar/availability-timeline?**'
const region = (page: Page) => page.getByRole('region', { name: 'Доступность участников по времени', exact: true })
const table = (page: Page) => region(page).locator('.ac-timeline-table')
const picker = (page: Page) => page.getByRole('dialog', { name: 'Участники сводки', exact: true })
const cell = (page: Page, code: string, time: string) => region(page).getByRole('button', { name: new RegExp(`^${code}, ${time}–`) })
const common = (page: Page, time: string) => table(page).locator('.ac-timeline-common').getByRole('button', { name: new RegExp(`^${time}–`) })
const personRow = (page: Page, name: string) => table(page).getByRole('row').filter({ has: page.getByRole('button', { name: `Убрать из сводки: ${name}`, exact: true }) })

function meeting(id: string, changes: Partial<CalendarTimelineMeeting> = {}): CalendarTimelineMeeting {
  return { id, kind: 'plan', start: 600, duration: 30, activity: id, status: 'planned', group_code: 'G1', participants: [{ user_id: ids.s, role: 'speaker' }], ...changes }
}

function mixedTimeline(state: CalendarState, date = first): CalendarTimeline {
  const value = fixtureTimeline(structuredClone(state), date)
  value.availability = [
    ...state.members.map(member => ({ user_id: member.user_id, date, start: 600, end: 630, available: true })),
    { user_id: ids.a, date, start: 630, end: 660, available: true },
    { user_id: ids.a, date, start: 660, end: 690, available: false },
  ]
  value.meetings = [meeting('Черновик', { start: 690, duration: 60, status: 'draft' }), meeting('Пересечение', { start: 720, duration: 60 })]
  value.locks = [{ id: 'timeline-lock', user_id: ids.t, date, locked: true, locked_at: state.scope.now, locked_by_id: ids.a, snapshot: [] }]
  return value
}

function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}

type Handler = (route: Route, value: CalendarTimeline, call: number) => Promise<void>
async function mountTimeline(page: Page, { state = fixtureState(), handle, params = {} }: { state?: CalendarState; handle?: Handler; params?: Record<string, string> } = {}) {
  await mountCalendar(page, { state, command: route => route.abort('blockedbyclient') })
  // Install after the fixture so no unexpected mutation can reach its default handler.
  await page.route('**/api/**', route => ['GET', 'HEAD'].includes(route.request().method()) ? route.fallback() : route.abort('blockedbyclient'))
  const queries: string[] = []
  await page.route(endpoint, route => {
    expect(route.request().method()).toBe('GET')
    const query = new URL(route.request().url()).searchParams
    const date = query.get('date')!
    expect([...query.keys()]).toEqual(['date'])
    queries.push(date)
    const value = fixtureTimeline(structuredClone(state), date)
    return handle ? handle(route, value, queries.length) : route.fulfill({ json: value })
  })
  const query = new URLSearchParams({ view: 'readiness', from: first, to: last, summary_tab: 'timeline', ...params })
  await page.goto(`/audit-calendar?${query}`)
  return { state, queries }
}

test('timeline pure statuses preserve unknown, precedence and half-open boundaries without mutation', () => {
  const value = fixtureTimeline(fixtureState())
  value.availability = [
    { user_id: ids.a, date: first, start: 570, end: 600, available: false },
    { user_id: ids.a, date: first, start: 600, end: 630, available: true },
    { user_id: ids.a, date: first, start: 630, end: 660, available: false },
    { user_id: ids.a, date: first, start: 660, end: 675, available: true },
    { user_id: ids.a, date: first, start: 720, end: 810, available: true },
    { user_id: ids.a, date: first, start: 780, end: 795, available: false },
    { user_id: ids.s, date: first, start: 600, end: 630, available: true },
  ]
  const draft = meeting('draft', { start: 720, status: 'draft', participants: [{ user_id: ids.a, role: 'auditor' }] })
  value.meetings = [draft]
  value.absences = [
    { id: 'cancelled', user_id: ids.a, start_date: first, end_date: first, status: 'cancelled', reason: 'Отменено', version: 1 },
    { id: 'tomorrow', user_id: ids.a, start_date: second, end_date: second, status: 'active', reason: 'Завтра', version: 1 },
  ]
  const before = structuredClone(value)
  expect([600, 630, 660, 690, 720, 750, 780].map(start => timelineSlot(value, ids.a, start))).toEqual(['free', 'busy', 'unknown', 'unknown', 'booked', 'free', 'busy'])
  expect([690, 720, 750].map(start => overlapsSlot(draft, start))).toEqual([false, true, false])
  expect(commonTimelineSlot(value, [], 600)).toBe('empty')
  expect(commonTimelineSlot(value, [ids.a, ids.s], 600)).toBe('free')
  expect(commonTimelineSlot(value, [ids.a, ids.t], 600)).toBe('unknown')
  expect(commonTimelineSlot(value, [ids.a, ids.s], 720)).toBe('blocked')
  expect(value).toEqual(before)
  value.absences.push({ id: 'today', user_id: ids.a, start_date: first, end_date: first, status: 'active', reason: 'Отсутствие', version: 1 })
  expect(timelineSlot(value, ids.a, 720)).toBe('absent')
  expect(commonTimelineSlot(value, [ids.a, ids.s], 600)).toBe('blocked')
})

test('timeline pure lanes reuse touching intervals, separate overlaps and clip the visible hours', () => {
  const meetings = [meeting('b', { start: 630, duration: 60 }), meeting('c', { start: 660 }), meeting('a', { duration: 60 }), meeting('right', { start: 1050, duration: 90 }), meeting('before', { start: 570 }), meeting('after', { start: 1080 })]
  const before = structuredClone(meetings)
  expect(timelineLanes(meetings, 600, 1080).map(({ meeting: item, lane, first, last }) => [item.id, lane, first, last])).toEqual([
    ['a', 0, 1, 3], ['b', 1, 2, 4], ['c', 0, 3, 4], ['right', 0, 16, 17],
  ])
  expect(timelineLanes([meeting('left', { start: 570, duration: 60 })], 600, 1080)[0]).toMatchObject({ lane: 0, first: 1, last: 2 })
  expect(meetings).toEqual(before)
})

test.describe('timeline browser read-only', () => {
  const mutations = new WeakMap<Page, string[]>()
  test.beforeEach(({ page }) => {
    const calls: string[] = []
    mutations.set(page, calls)
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (path.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method())) calls.push(`${request.method()} ${path}`)
    })
  })
  test.afterEach(({ page }) => { expect(mutations.get(page)).toEqual([]) })

  test('role rows, common time, draft blocking, lanes and locks have explicit states', async ({ page }) => {
    const state = fixtureState()
    const { queries } = await mountTimeline(page, { state, handle: (route, value) => route.fulfill({ json: mixedTimeline(state, value.date) }) })
    await expect(table(page)).toBeVisible()
    await expect(table(page).locator('.ac-timeline-role th')).toHaveText(['Докладчики · 1', 'Техники · 1', 'Аудиторы · 1'])
    await expect(cell(page, 'ТА', '10:00')).toHaveAccessibleName('ТА, 10:00–10:30: Свободен')
    await expect(cell(page, 'ТА', '11:00')).toHaveClass(/ac-time-busy/)
    await expect(cell(page, 'ТТ', '10:30')).toHaveClass(/ac-time-unknown/)
    await expect(common(page, '10:00')).toHaveAccessibleName('10:00–10:30: Все свободны')
    await expect(common(page, '10:30')).toHaveAccessibleName('10:30–11:00: Не все указали время')
    await expect(common(page, '11:00')).toHaveClass(/ac-common-blocked/)
    await expect(common(page, '11:30')).toHaveClass(/ac-common-blocked/)
    await expect(cell(page, 'ТД', '11:30')).toHaveClass(/ac-time-booked/)
    await expect(table(page).getByRole('img', { name: 'День закрыт', exact: true })).toHaveCount(1)
    const events = personRow(page, state.members[2].full_name).locator('.ac-timeline-event')
    await expect(events).toHaveCount(2)
    expect(await events.evaluateAll(nodes => nodes.map(node => (node as HTMLElement).style.gridRow))).toEqual(['1', '2'])
    await expect(events.first()).toHaveClass(/ac-event-draft/)
    expect(queries).toEqual([first])
  })

  test('saved participants keep both plan and fact intervals; observer, absence and unassigned details stay explicit', async ({ page }) => {
    const state = fixtureState()
    const replacement = { ...state.members[0], user_id: '00000000-0000-4000-8000-000000000081', code: 'НА', full_name: 'Новый аудитор группы' }
    state.members.push(replacement)
    state.groups[0].versions[0].auditor_id = replacement.user_id
    const formerSpeaker = { ...state.members[2], user_id: '00000000-0000-4000-8000-000000000082', code: 'БД', full_name: 'Бывший докладчик', role: 'observer' as const }
    state.members.push(formerSpeaker)
    const value = fixtureTimeline(state)
    const participants: CalendarTimelineMeeting['participants'] = [{ user_id: ids.a, role: 'auditor' }, { user_id: ids.s, role: 'speaker' }]
    value.meetings = [
      meeting('saved-plan', { activity: 'Сохранённый состав', participants }),
      meeting('fact-of-saved-plan', { kind: 'fact', status: 'completed', start: 630, activity: 'Сохранённый состав', participants }),
      meeting('unassigned', { start: 660, activity: 'Без состава', participants: [] }),
      meeting('former-speaker', { start: 720, activity: 'Исторический докладчик', participants: [{ user_id: formerSpeaker.user_id, role: 'speaker' }] }),
    ]
    value.absences = [{ id: 'absence', user_id: ids.t, start_date: first, end_date: first, status: 'active', reason: 'Согласованное отсутствие', version: 1 }]
    expect(personMeetings(value, replacement.user_id)).toEqual([])
    await mountTimeline(page, { state, handle: route => route.fulfill({ json: value }) })
    const oldRow = personRow(page, state.members[0].full_name)
    await expect(oldRow.locator('.ac-timeline-event')).toHaveCount(2)
    await expect(oldRow.locator('.ac-event-plan')).toContainText('План · Сохранённый состав')
    await expect(oldRow.locator('.ac-event-fact')).toContainText('Факт · Сохранённый состав')
    await expect(cell(page, 'ТА', '10:00')).toHaveClass(/ac-time-booked/)
    await expect(cell(page, 'ТА', '10:30')).toHaveClass(/ac-time-booked/)
    await expect(cell(page, 'ТА', '11:00')).toHaveClass(/ac-time-unknown/)
    await expect(common(page, '10:00')).toHaveClass(/ac-common-blocked/)
    await expect(common(page, '10:30')).toHaveClass(/ac-common-blocked/)
    await expect(personRow(page, replacement.full_name).locator('.ac-timeline-event')).toHaveCount(0)
    await expect(personRow(page, formerSpeaker.full_name)).toHaveCount(0)
    for (const [kind, label] of [['plan', 'План'], ['fact', 'Факт']]) {
      await oldRow.locator(`.ac-event-${kind}`).press('Enter')
      const dialog = page.getByRole('dialog', { name: 'Встреча в сводке', exact: true })
      await expect(dialog.getByText(`G1 · ${label}`, { exact: true })).toBeVisible()
      await expect(dialog.locator('li')).toHaveText([`${state.members[0].full_name} · Аудитор`, `${state.members[2].full_name} · Докладчик`])
      await expect(dialog).not.toContainText(replacement.full_name)
      await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
    }
    await expect(cell(page, 'ТТ', '10:00')).toHaveClass(/ac-time-absent/)
    await common(page, '10:00').press('Enter')
    const detail = page.getByRole('dialog', { name: 'Доступность интервала', exact: true })
    await expect(detail.locator('.ac-timeline-detail > section')).toHaveCount(4)
    await expect(detail).toContainText('Согласованное отсутствие')
    await expect(detail).toContainText('Сохранённый состав')
    await detail.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await region(page).getByText('Встречи без установленного состава (1)', { exact: true }).click()
    await region(page).getByRole('button', { name: '11:00 · Без состава', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Состав не установлен. Встреча не отнесена к конкретным сотрудникам.')
    await page.getByRole('dialog').getByRole('button', { name: 'Закрыть', exact: true }).click()
    const hidden = region(page).locator('details.ac-warning')
    await expect(hidden.locator('summary')).toHaveText('Встречи участников вне отображаемых ролей (1)')
    await hidden.locator('summary').click()
    await hidden.getByRole('button', { name: '12:00 · Исторический докладчик', exact: true }).click()
    await expect(page.getByRole('dialog').locator('li')).toHaveText(['Бывший докладчик · Докладчик'])
  })

  test('picker search, cancel and apply preserve selection through URL Back and Forward without refetching', async ({ page }) => {
    const { queries } = await mountTimeline(page)
    await region(page).getByRole('button', { name: 'Участники (3)', exact: true }).click()
    await expect(picker(page).getByRole('heading', { level: 3 })).toHaveText(['Докладчики', 'Техники', 'Аудиторы'])
    const original = page.url()
    await picker(page).getByRole('searchbox', { name: 'Поиск сотрудника' }).fill('Тестовый аудитор')
    await picker(page).getByRole('button', { name: 'Снять выбор', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Закрыть', exact: true }).click()
    await expect(picker(page).getByRole('alert')).toContainText('Удалить черновик?')
    await picker(page).getByRole('button', { name: 'Удалить черновик', exact: true }).click()
    await expect(picker(page)).toHaveCount(0)
    expect(page.url()).toBe(original)
    await region(page).getByRole('button', { name: 'Участники (3)', exact: true }).click()
    await picker(page).getByRole('searchbox', { name: 'Поиск сотрудника' }).fill('Тестовый докладчик')
    await picker(page).getByRole('button', { name: 'Снять выбор', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Применить (2)', exact: true }).click()
    await expect.poll(() => new URL(page.url()).searchParams.get('summary_members')).toBe(`${ids.a},${ids.t}`)
    await expect(table(page).locator('.ac-timeline-role th')).toHaveText(['Техники · 1', 'Аудиторы · 1'])
    await page.goBack()
    await expect(region(page).getByRole('button', { name: 'Участники (3)', exact: true })).toBeVisible()
    expect(new URL(page.url()).searchParams.has('summary_members')).toBe(false)
    await page.goForward()
    await expect(region(page).getByRole('button', { name: 'Участники (2)', exact: true })).toBeVisible()
    expect(queries).toEqual([first])
  })

  test('explicit empty selection stays empty; selecting all and removing everyone survives history and reload', async ({ page }) => {
    const { state } = await mountTimeline(page, { params: { summary_members: '' } })
    await expect(region(page).getByText('Участники не выбраны.', { exact: true })).toBeVisible()
    await expect(table(page)).toHaveCount(0)
    await region(page).getByRole('button', { name: 'Участники (0)', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Выбрать найденных', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Применить (3)', exact: true }).click()
    await expect(table(page)).toBeVisible()
    for (const member of state.members) await region(page).getByRole('button', { name: `Убрать из сводки: ${member.full_name}`, exact: true }).click()
    await expect(region(page).getByText('Участники не выбраны.', { exact: true })).toBeVisible()
    expect(new URL(page.url()).searchParams.get('summary_members')).toBe('')
    await page.reload()
    await expect(region(page).getByRole('button', { name: 'Участники (0)', exact: true })).toBeVisible()
    await page.goBack()
    await expect(region(page).getByRole('button', { name: 'Участники (1)', exact: true })).toBeVisible()
  })

  test('day navigation fetches only that day; full hours are local and invalid URL days never load a fallback', async ({ page }) => {
    const { queries } = await mountTimeline(page, { params: { summary_members: ids.s }, handle: (route, value) => route.fulfill({ json: { ...value, meetings: [meeting('Ночная встреча', { start: 0 })] } }) })
    await expect(table(page).locator('thead th')).toHaveCount(17)
    await expect(region(page).getByRole('button', { name: 'Предыдущий день сводки', exact: true })).toBeDisabled()
    await region(page).getByRole('button', { name: 'Встречи за пределами 10:00–18:00: 1', exact: true }).click()
    await expect(table(page).locator('thead th')).toHaveCount(49)
    await expect(table(page).locator('thead th').last()).toHaveText('23:30')
    await expect(region(page).getByRole('checkbox', { name: 'Все часы', exact: true })).toBeChecked()
    expect(queries).toEqual([first])
    await region(page).getByRole('button', { name: 'Следующий день сводки', exact: true }).click()
    await expect.poll(() => queries.at(-1)).toBe(second)
    await expect(region(page)).toHaveAttribute('aria-busy', 'false')
    await region(page).getByRole('combobox', { name: 'День сводки', exact: true }).selectOption(last)
    await expect.poll(() => queries.at(-1)).toBe(last)
    await expect(region(page)).toHaveAttribute('aria-busy', 'false')
    await expect(region(page).getByRole('button', { name: 'Следующий день сводки', exact: true })).toBeDisabled()
    await region(page).getByRole('checkbox', { name: 'Все часы', exact: true }).click()
    await expect(region(page).getByRole('checkbox', { name: 'Все часы', exact: true })).not.toBeChecked()
    await expect(table(page).locator('thead th')).toHaveCount(17)
    expect(queries).toEqual([first, second, last])
    expect(new URL(page.url()).searchParams.get('summary_members')).toBe(ids.s)
    const url = new URL(page.url()); url.searchParams.set('summary_day', '2026-09-13')
    await page.goto(url.toString())
    await expect(region(page).getByRole('alert')).toContainText('Выберите день в установленном периоде.')
    await expect(table(page)).toHaveCount(0)
    expect(queries).toEqual([first, second, last])
  })

  test('failed day hides previous rows and common time, disables picker and recovers by GET retry', async ({ page }) => {
    let fail = true
    const { queries } = await mountTimeline(page, { handle: (route, value) => value.date === second && fail ? route.fulfill({ status: 503, json: { detail: 'Сводка временно недоступна' } }) : route.fulfill({ json: value }) })
    await expect(table(page)).toBeVisible()
    await region(page).getByRole('combobox', { name: 'День сводки', exact: true }).selectOption(second)
    await expect(region(page).getByRole('alert')).toContainText('Сводка временно недоступна')
    await expect(table(page)).toHaveCount(0)
    await expect(region(page).getByRole('button', { name: 'Участники', exact: true })).toBeDisabled()
    fail = false
    await region(page).getByRole('button', { name: 'Повторить загрузку', exact: true }).click()
    await expect(table(page)).toBeVisible()
    await expect(region(page).getByRole('alert')).toHaveCount(0)
    expect(queries).toEqual([first, second, second])
  })

  test('A-B-A ignores late A success and late B 403 after the newest A snapshot', async ({ page }) => {
    const releaseA = gate(), releaseB = gate(), doneA = gate(), doneB = gate()
    try {
      const { queries } = await mountTimeline(page, { handle: async (route, value, call) => {
        if (call === 1) {
          await releaseA.promise
          value.members[0].full_name = 'Устаревший снимок A1'
          try { await route.fulfill({ json: value }).catch(() => undefined) } finally { doneA.release() }
        } else if (call === 2) {
          await releaseB.promise
          try { await route.fulfill({ status: 403, json: { detail: 'Устаревший отказ B' } }).catch(() => undefined) } finally { doneB.release() }
        } else {
          value.members[0].full_name = 'Текущий снимок A2'
          await route.fulfill({ json: value })
        }
      } })
      await expect.poll(() => queries.length).toBe(1)
      await region(page).getByRole('combobox', { name: 'День сводки', exact: true }).selectOption(second)
      await expect.poll(() => queries.length).toBe(2)
      await region(page).getByRole('combobox', { name: 'День сводки', exact: true }).selectOption(first)
      await expect(table(page)).toContainText('Текущий снимок A2')
      releaseA.release(); releaseB.release()
      await Promise.all([doneA.promise, doneB.promise])
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
      await expect(table(page)).toContainText('Текущий снимок A2')
      await expect(page.getByRole('alert')).toHaveCount(0)
      await expect(table(page)).not.toContainText('Устаревший снимок A1')
      expect(queries).toEqual([first, second, first])
    } finally { releaseA.release(); releaseB.release() }
  })

  test('wrong response day and stale version hide data; explicit refresh retries even at the same source version', async ({ page }) => {
    let mismatch: 'date' | 'version' | null = 'date'
    const { state, queries } = await mountTimeline(page, { handle: (route, value) => {
      if (mismatch === 'date') value.date = second
      if (mismatch === 'version') value.version = 0
      return route.fulfill({ json: value })
    } })
    for (const kind of ['date', 'version'] as const) {
      if (kind === 'version') {
        mismatch = kind
        await page.getByRole('button', { name: 'Обновить сводку', exact: true }).click()
      }
      await expect(region(page).getByRole('alert')).toContainText('Данные сводки изменились.')
      await expect(table(page)).toHaveCount(0)
      const before = queries.length
      mismatch = null
      await region(page).getByRole('button', { name: 'Обновить календарь и сводку', exact: true }).click()
      await expect.poll(() => queries.length).toBeGreaterThan(before)
      await expect(table(page)).toBeVisible()
      await expect(region(page).getByRole('alert')).toHaveCount(0)
      expect(state.scope.version).toBe(1)
    }
  })

  test('a current timeline 403 clears all calendar rows and cannot restore them on focus', async ({ page }) => {
    const { queries } = await mountTimeline(page, { handle: (route, value) => value.date === second ? route.fulfill({ status: 403, json: { detail: 'Доступ отозван' } }) : route.fulfill({ json: value }) })
    await expect(table(page)).toBeVisible()
    await region(page).getByRole('combobox', { name: 'День сводки', exact: true }).selectOption(second)
    await expect(page.getByRole('alert')).toContainText('Доступ отозван')
    await expect(table(page)).toHaveCount(0)
    await expect(page.locator('.ac-kpis')).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await expect(page.getByRole('alert')).toContainText('Доступ отозван')
    expect(queries).toEqual([first, second])
  })

  test('timeline visual matrix keeps horizontal scrolling inside the table at five widths and three themes', async ({ page }, testInfo) => {
    test.setTimeout(60000)
    const state = fixtureState()
    await mountTimeline(page, { state, handle: (route, value) => route.fulfill({ json: mixedTimeline(state, value.date) }) })
    await expect(table(page)).toBeVisible()
    for (const [width, height] of [[1920, 1080], [1440, 900], [1024, 768], [390, 844], [320, 700]]) {
      await page.setViewportSize({ width, height })
      for (const theme of ['light', 'dark', 'rose']) {
        await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
        const box = await region(page).locator('.ac-timeline-scroll').boundingBox()
        expect(box!.width).toBeGreaterThan(0)
        expect(box!.height).toBeGreaterThan(0)
        expect(box!.x).toBeGreaterThanOrEqual(0)
        expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
        await expect(table(page).locator('.ac-timeline-role')).toHaveCount(3)
        const heading = await table(page).locator('thead th').nth(1).boundingBox()
        const firstCell = await common(page, '10:00').boundingBox()
        expect(Math.abs(heading!.x - firstCell!.x)).toBeLessThan(1)
        expect(Math.abs(heading!.width - firstCell!.width)).toBeLessThan(1)
        if (width <= 390) expect(await region(page).locator('.ac-timeline-scroll').evaluate(node => node.scrollWidth > node.clientWidth)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`timeline-${width}-${theme}.png`), fullPage: true, animations: 'disabled' })
      }
    }
  })

  test('bounded participant selection never renders a misleading partial explicit selection', async ({ page }) => {
    const state = fixtureState()
    state.members = Array.from({ length: 51 }, (_, i) => ({ ...state.members[0], user_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`, code: `A${i}`, full_name: `Аудитор ${i}` }))
    await mountTimeline(page, { state })
    await expect(region(page).getByText('Показано участников: 50 из 51.', { exact: true })).toBeVisible()
    await expect(table(page).locator('.ac-timeline-person')).toHaveCount(50)
    await region(page).getByRole('button', { name: 'Участники (50)', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Выбрать найденных', exact: true }).click()
    await expect(picker(page).getByRole('alert')).toContainText('Максимум: 50.')
    await expect(picker(page).getByRole('button', { name: 'Применить (51)', exact: true })).toBeDisabled()
    await picker(page).getByRole('button', { name: 'Закрыть', exact: true }).click()
    await picker(page).getByRole('button', { name: 'Удалить черновик', exact: true }).click()
    const url = new URL(page.url()); url.searchParams.set('summary_members', state.members.map(m => m.user_id).join(','))
    await page.goto(url.toString())
    await expect(region(page).getByRole('alert')).toContainText('Максимум: 50.')
    await expect(table(page)).toHaveCount(0)
  })

  test('timeline keyboard focus stays to the right of sticky names after horizontal scroll', async ({ page, browserName }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mountTimeline(page, { params: { summary_members: ids.a } })
    const scroll = region(page).locator('.ac-timeline-scroll')
    await expect(table(page)).toBeVisible()
    for (const time of ['17:00', '10:00', '17:30', '10:30']) {
      const target = cell(page, 'ТА', time)
      await target.focus()
      await expect(target).toBeFocused()
      await expect.poll(async () => {
        const outer = await scroll.boundingBox(), focus = await target.boundingBox()
        return !!outer && !!focus && focus.x >= outer.x + 169 && focus.x + focus.width <= outer.x + outer.width + 1
      }).toBe(true)
    }
    // Safari uses Option-Tab for all controls unless full keyboard access is enabled.
    await page.keyboard.press(browserName === 'webkit' ? 'Alt+Tab' : 'Tab')
    await expect(cell(page, 'ТА', '11:00')).toBeFocused()
    await page.keyboard.press(browserName === 'webkit' ? 'Alt+Shift+Tab' : 'Shift+Tab')
    await expect(cell(page, 'ТА', '10:30')).toBeFocused()
  })
})
