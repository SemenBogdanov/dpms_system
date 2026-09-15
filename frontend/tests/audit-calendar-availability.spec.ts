import { expect, test, type Page } from '@playwright/test'
import type { CalendarChangeRequest, CalendarCommand, CalendarReadiness } from '../src/api/auditCalendar'
import { fixtureReadiness, fixtureState, ids, mountCalendar } from './audit-calendar.fixtures'
import { readinessEnd, serverTimeLabel } from '../src/lib/auditCalendar'

const day = '2026-09-14'
const requestTime = '2026-09-14T06:17:23Z'
const lockFor = (user = ids.a) => ({ id: `lock-${user}`, user_id: user, date: day, locked: true, locked_at: requestTime, locked_by_id: ids.a, snapshot: [] })
const requestFor = (user = ids.a, status: CalendarChangeRequest['status'] = 'pending'): CalendarChangeRequest => ({ id: `request-${user}`, user_id: user, date: day, reason: 'Изменился график комиссии', status, requested_at: requestTime, requested_by_id: user, opened_at: null, opened_by_id: null, closed_at: null, closed_by_id: null, resolution: '', before: [], after: null })
const slot = (page: Page) => page.locator(`[data-ac-slot][data-date="${day}"][data-start="600"]:visible`)
const wholeDay = (page: Page) => page.getByRole('button', { name: `${day}: Свободен, весь день 00:00–24:00`, exact: true }).filter({ visible: true })
const dayAction = (page: Page, label: string) => page.getByRole('button', { name: `${day}: ${label}`, exact: true }).filter({ visible: true })

for (const closed of [false, true]) test(`whole-day controls keep the fourth action inline, closed=${closed}`, async ({ page }, testInfo) => {
  const state = fixtureState()
  if (closed) state.availability_locks.push(lockFor())
  const { commands } = await mountCalendar(page, { state, view: 'availability' })
  for (const [width, height] of [[1920, 1080], [1440, 900], [1240, 900], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    const toolbar = page.getByRole('group', { name: `${day}: Действия на весь день`, exact: true }).filter({ visible: true })
    await expect(toolbar.getByRole('button')).toHaveCount(4)
    const boxes = await toolbar.getByRole('button').evaluateAll(buttons => buttons.map(button => {
      const { x, y, width, height } = button.getBoundingClientRect()
      return { x, y, width, height }
    }))
    for (let index = 0; index < boxes.length; index++) {
      expect(Math.abs(boxes[index].y - boxes[0].y)).toBeLessThanOrEqual(1)
      expect(boxes[index].width).toBeGreaterThanOrEqual(width <= 700 ? 44 : 34)
      expect(boxes[index].height).toBeGreaterThanOrEqual(width <= 700 ? 44 : 34)
      if (index) expect(boxes[index].x).toBeGreaterThanOrEqual(boxes[index - 1].x + boxes[index - 1].width)
      expect(boxes[index].x + boxes[index].width).toBeLessThanOrEqual(width)
    }
    await expect(toolbar.getByRole('button').nth(3)).toHaveAccessibleName(`${day}: ${closed ? 'Запросить изменение дня' : 'Зафиксировать день'}`)
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await toolbar.screenshot({ path: testInfo.outputPath(`day-actions-${width}-${theme}.png`) })
    }
  }
  expect(commands).toHaveLength(0)
})

async function saveReason(page: Page, reason = 'Проверенное основание') {
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание', { exact: true }).fill(reason)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  return dialog
}
async function openRequests(page: Page) {
  await page.getByRole('link', { name: 'Сводка доступности', exact: true }).click()
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: /Заявки/ }).click()
}

for (const form of ['availability', 'member-archive', 'global-admin-archive'] as const) test(`strict reason label stays stable after input: ${form}`, async ({ page }, testInfo) => {
  const state = fixtureState()
  if (form === 'member-archive') state.actor.can_archive = true
  if (form === 'global-admin-archive') { state.members = []; state.actor.user_id = 'global-admin' }
  const { commands } = await mountCalendar(page, { state, admin: form === 'global-admin-archive', view: form === 'availability' ? 'availability' : 'management' })
  if (form === 'availability') await dayAction(page, 'Зафиксировать день').click()
  else await page.getByRole('button', { name: 'Архивировать контур', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const field = dialog.getByLabel('Основание', { exact: true })
  const reason = 'Synthetic reason: label remains stable'
  await field.fill(reason)
  await page.keyboard.press('Escape')
  await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
  await expect(field).toHaveCount(1)
  await expect(field).toHaveValue(reason)
  await expect(field).toHaveAccessibleName('Основание')
  const association = await field.evaluate((element: HTMLTextAreaElement) => ({
    hasId: element.id !== '',
    labels: Array.from(element.labels ?? [], label => ({ text: label.textContent, explicit: label.htmlFor === element.id, wrapsControl: label.contains(element) })),
  }))
  expect(association).toEqual({ hasId: true, labels: [{ text: 'Основание', explicit: true, wrapsControl: false }] })
  await field.fill(`${reason}: edited`)
  await expect(dialog.getByLabel('Основание', { exact: true })).toHaveValue(`${reason}: edited`)
  expect(commands).toHaveLength(0)
  await page.screenshot({ path: testInfo.outputPath('stable-reason-label.png'), fullPage: true })
})

test('new meeting defaults to 30 and only active speakers are selectable', async ({ page }) => {
  const state = fixtureState()
  state.members.push({ ...state.members[2], user_id: 'inactive-speaker', full_name: 'Отключённый докладчик', active: false })
  const { commands } = await mountCalendar(page, { state })
  await page.locator(`button[aria-label="Создать план ${day} 12:00"]:visible`).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('Основание', { exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await expect(dialog.getByLabel('Длительность, мин', { exact: true })).toHaveValue('30')
  const speakers = dialog.getByRole('combobox', { name: 'Докладчик', exact: true })
  await expect(speakers.locator('option')).toHaveCount(2)
  await speakers.selectOption(ids.s)
  await dialog.getByRole('combobox', { name: 'Группа', exact: true }).selectOption(ids.g)
  await dialog.getByLabel('Активность', { exact: true }).fill('Новая комиссия')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].payload).toMatchObject({ duration: 30, speaker_id: ids.s })
})

test('saved non-speaker remains visible and is not rewritten on revision', async ({ page }) => {
  const state = fixtureState(); state.plans[0].speaker_id = ids.t
  const { commands } = await mountCalendar(page, { state })
  await page.locator('.ac-plan:visible').first().click()
  const dialog = page.getByRole('dialog')
  const speakers = dialog.getByRole('combobox', { name: 'Докладчик', exact: true })
  await expect(speakers).toHaveValue(ids.t)
  await expect(speakers.locator(`option[value="${ids.t}"]`)).toHaveAttribute('disabled', '')
  await expect(speakers.locator(`option[value="${ids.t}"]`)).toContainText('сохранён в плане')
  await dialog.getByRole('button', { name: 'Изменить дату и время встречи', exact: true }).click()
  await expect(dialog.getByLabel('Длительность, мин')).toHaveValue('90')
  await saveReason(page, 'Сохранить исторического докладчика')
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0].payload).toMatchObject({ speaker_id: ids.t, duration: 90 })
})

for (const active of [true, false]) test(`historical restoration follows active access, not current role, active=${active}`, async ({ page }) => {
  const state = fixtureState()
  state.members[0].active = active
  state.plans[0] = { ...state.plans[0], source_id: '00000000-0000-4000-8000-000000000080', origin: 'source', date: '2026-09-10' }
  const { commands } = await mountCalendar(page, { state, view: 'dataset' })
  await page.getByRole('button', { name: 'Исторический факт', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const speakers = dialog.getByRole('combobox', { name: 'Докладчик', exact: true })
  await expect(speakers.locator('option')).toHaveCount(state.members.length + 1)
  if (!active) {
    await expect(speakers.locator(`option[value="${ids.a}"]`)).toHaveAttribute('disabled', '')
    await expect(speakers).toHaveValue(state.plans[0].speaker_id!)
    expect(commands).toHaveLength(0)
    return
  }
  await speakers.selectOption(ids.a)
  await expect(speakers).toHaveValue(ids.a)
  await dialog.getByLabel('Состав не установлен', { exact: true }).check()
  await dialog.getByLabel('Основание', { exact: true }).fill('Исторический докладчик теперь аудитор')
  await dialog.getByLabel('Документ / подтверждение', { exact: true }).fill('Проверенный исторический протокол')
  await dialog.getByLabel('Подтверждаю источник и фактические сведения', { exact: true }).check()
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'fact.restore', payload: { source_row_id: state.plans[0].source_id, speaker_id: ids.a, composition_unknown: true } })
  expect(state.members[0].role).toBe('auditor')
})

test('helper lock and employee request protect the reason and use server timestamps', async ({ page }, testInfo) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async (route, body) => {
    const command = body as unknown as CalendarCommand
    if (command.operation === 'availability.lock') state.availability_locks.push(lockFor())
    if (command.operation === 'availability.request') state.change_requests.push(requestFor())
    state.scope.version++
    await route.fulfill({ json: { version: state.scope.version, result: {} } })
  } })
  await dayAction(page, 'Зафиксировать день').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание').fill('День проверен сотрудником')
  await page.keyboard.press('Escape')
  await page.locator('.ac-overlay').click({ position: { x: 2, y: 2 } })
  await expect(dialog.getByLabel('Основание')).toHaveValue('День проверен сотрудником')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(slot(page)).toBeDisabled()
  await expect(wholeDay(page)).toBeDisabled()
  await page.screenshot({ path: testInfo.outputPath('helper-locked-day.png'), fullPage: true })
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await dayAction(page, 'Запросить изменение дня').click()
  await saveReason(page, 'Изменился график комиссии')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(commands[1]).toMatchObject({ operation: 'availability.request', payload: { user_id: ids.a, date: day, reason: 'Изменился график комиссии' } })
  expect(commands[1].payload).not.toHaveProperty('reported_at')
  await expect(dayAction(page, 'Запросить изменение дня')).toHaveCount(0)
  await expect(slot(page)).toBeDisabled()
  await openRequests(page)
  await expect(page.getByText('Ожидает решения', { exact: true })).toBeVisible()
  await expect(page.locator('.ac-request-times')).toContainText(serverTimeLabel(requestTime))
  await expect(page.getByRole('button', { name: 'Одобрить и открыть день' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('self-pending-request.png'), fullPage: true })
})

test('employee has no lock button on an unlocked own day', async ({ page }) => {
  const { commands } = await mountCalendar(page, { helper: false, view: 'availability' })
  await expect(slot(page)).toBeEnabled()
  await expect(wholeDay(page)).toBeEnabled()
  await expect(page.getByRole('button', { name: /Зафиксировать день/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Запросить изменение дня/ })).toHaveCount(0)
  expect(commands).toHaveLength(0)
})

test('lock form refuses submission if helper permission is revoked while open', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'availability' })
  await dayAction(page, 'Зафиксировать день').click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание').fill('Черновик фиксации')
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).evaluate((button: HTMLButtonElement) => button.click())
  await expect(page.getByRole('link', { name: 'Управление', exact: true })).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Фиксация дня доступна только помощнику')
  await expect(dialog.getByLabel('Основание')).toHaveValue('Черновик фиксации')
  expect(commands).toHaveLength(0)
})

test('helper can record a request for a user but cannot bypass a closed day', async ({ page }) => {
  const state = fixtureState(); state.availability_locks.push(lockFor(ids.t))
  const { commands } = await mountCalendar(page, { state, view: 'availability' })
  await page.getByRole('combobox', { name: 'Участник', exact: true }).selectOption(ids.t)
  await expect(slot(page)).toBeDisabled()
  await expect(wholeDay(page)).toBeDisabled()
  await expect(dayAction(page, 'Зафиксировать день')).toHaveCount(0)
  await dayAction(page, 'Запросить изменение дня').click()
  await saveReason(page, 'Сотрудник сообщил об изменении')
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'availability.request', payload: { user_id: ids.t, date: day, reason: 'Сотрудник сообщил об изменении' } })
  expect(commands[0].payload).not.toHaveProperty('reported_at')
})

test('request approve opens day, close relocks, reject keeps it closed', async ({ page }, testInfo) => {
  const state = fixtureState(); state.availability_locks.push(lockFor()); state.change_requests.push(requestFor())
  const { commands } = await mountCalendar(page, { state, view: 'readiness', command: async (route, body) => {
    const command = body as unknown as CalendarCommand
    if (command.operation === 'availability.resolve') {
      const request = state.change_requests.find(r => r.id === command.payload.id)!
      request.resolution = command.payload.reason
      if (command.payload.action === 'approve') {
        request.status = 'approved'; request.opened_at = '2026-09-14T06:30:01Z'; request.opened_by_id = ids.a; state.availability_locks[0].locked = false
      } else {
        request.status = command.payload.action === 'close' ? 'closed' : 'rejected'; request.closed_at = '2026-09-14T06:45:02Z'; request.closed_by_id = ids.a; state.availability_locks[0].locked = true
      }
    }
    state.scope.version++
    await route.fulfill({ json: { version: state.scope.version, result: {} } })
  } })
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: /Заявки/ }).click()
  await page.getByRole('button', { name: 'Одобрить и открыть день', exact: true }).click()
  await saveReason(page)
  await expect(page.getByText('Открыто для изменений', { exact: true })).toBeVisible()
  await expect(page.locator('.ac-request-times')).toContainText(serverTimeLabel('2026-09-14T06:30:01Z'))
  await page.screenshot({ path: testInfo.outputPath('helper-approved-request.png'), fullPage: true })
  await page.locator('.ac-request').getByRole('link', { name: 'Тестовый аудитор', exact: true }).click()
  await expect(slot(page)).toBeEnabled()
  await expect(wholeDay(page)).toBeEnabled()
  await expect(dayAction(page, 'Зафиксировать день')).toHaveCount(0)
  await openRequests(page)
  await page.getByRole('button', { name: 'Закрыть заявку и день', exact: true }).click()
  await saveReason(page)
  await expect(page.getByText('Закрыта, день зафиксирован', { exact: true })).toBeVisible()
  await page.locator('.ac-request').getByRole('link', { name: 'Тестовый аудитор', exact: true }).click()
  await expect(slot(page)).toBeDisabled()
  state.change_requests.push({ ...requestFor(), id: 'second-request' })
  await openRequests(page)
  await page.getByRole('button', { name: 'Отклонить', exact: true }).click()
  await saveReason(page, 'Изменение не согласовано')
  await expect(page.getByText('Отклонена', { exact: true })).toBeVisible()
  expect(state.availability_locks[0].locked).toBe(true)
  expect(commands.map(c => (c.payload as { action: string }).action)).toEqual(['approve', 'close', 'reject'])
})

test('request network retry reuses UUID, stale rebase preserves reason', async ({ page }) => {
  const state = fixtureState(false); state.availability_locks.push(lockFor())
  let calls = 0
  const { commands } = await mountCalendar(page, { state, view: 'availability', command: async route => {
    calls++
    if (calls === 1) return route.fulfill({ status: 503, json: { detail: 'Повторите запрос' } })
    if (calls === 2) { state.scope.version = 8; return route.fulfill({ status: 409, json: { detail: 'Scope version changed' } }) }
    return route.fulfill({ json: { version: 9, result: {} } })
  } })
  await dayAction(page, 'Запросить изменение дня').click()
  const dialog = await saveReason(page, 'Черновик обращения не терять')
  await expect(dialog.getByRole('alert')).toContainText('Повторите запрос')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Конфликт версии')
  expect(commands[0].request_id).toBe(commands[1].request_id)
  await dialog.getByRole('button', { name: 'Перечитать, сохранив ввод' }).click()
  await expect(dialog.getByLabel('Основание')).toHaveValue('Черновик обращения не терять')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(commands[2].expected_version).toBe(8)
  expect(commands[2].request_id).not.toBe(commands[1].request_id)
})

test('employee requests are own and period-filtered even with extra state rows', async ({ page }) => {
  const state = fixtureState(false)
  state.change_requests = [requestFor(), requestFor(ids.t), { ...requestFor(), id: 'outside', date: '2026-10-01', reason: 'Вне периода' }]
  await mountCalendar(page, { state, view: 'readiness' })
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: /Заявки/ }).click()
  await expect(page.locator('.ac-request')).toHaveCount(1)
  await expect(page.locator('.ac-request')).not.toContainText('Вне периода')
  await expect(page.getByRole('button', { name: 'Отклонить', exact: true })).toHaveCount(0)
})

test('archive depends on can_archive, not helper or membership', async ({ page }, testInfo) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'management' })
  await expect(page.getByRole('button', { name: 'Архивировать контур', exact: true })).toHaveCount(0)
  state.actor.can_manage = false; state.actor.can_archive = true
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Изменить норму', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Архивировать контур', exact: true }).click()
  await saveReason(page, 'Архив по решению администратора')
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'scope.archive', payload: { archived: true } })
  await page.screenshot({ path: testInfo.outputPath('admin-calendar-management.png'), fullPage: true })
})

test('global admin archives through AdminPanel without CalendarState or membership', async ({ page }, testInfo) => {
  const state = fixtureState(false); state.members = []; state.actor.user_id = 'global-admin'
  const { commands } = await mountCalendar(page, { state, admin: true, command: async route => {
    state.scope.archived = !state.scope.archived; state.scope.version++
    return route.fulfill({ json: { version: state.scope.version, result: {} } })
  } })
  await page.route('**/api/audit-calendar/state?**', route => route.fulfill({ status: 403, json: { detail: 'No membership' } }))
  await page.getByRole('button', { name: 'Архивировать контур', exact: true }).click()
  await saveReason(page, 'Закрытие контура глобальным администратором')
  await expect(page.getByRole('button', { name: 'Вернуть из архива', exact: true })).toBeVisible()
  expect(commands[0]).toMatchObject({ operation: 'scope.archive', payload: { archived: true } })
  await page.screenshot({ path: testInfo.outputPath('global-admin-archived.png'), fullPage: true })
  await page.getByRole('button', { name: 'Вернуть из архива', exact: true }).click()
  await saveReason(page)
  await expect(page.getByRole('button', { name: 'Архивировать контур', exact: true })).toBeVisible()
  expect(commands[1]).toMatchObject({ operation: 'scope.archive', payload: { archived: false } })
})

test('summary caps 31 days and keeps employee readiness from the server', async ({ page }) => {
  const state = fixtureState(false)
  const queries: { from: string; to: string; duration: number }[] = []
  await mountCalendar(page, { state, view: 'readiness', readiness: (from, to, duration) => {
    queries.push({ from, to, duration })
    const result = fixtureReadiness(state, from, to, duration)
    result.employees[0].days[0] = { date: from, status: 'partial', free_minutes: 30, locked: true }
    result.employees[0].filled_days = 2
    return result
  } })
  await page.goto(`/audit-calendar?view=readiness&summary_tab=employees&from=${day}&to=2026-12-01`)
  if (await page.locator('.ac-period-panel').getAttribute('open') === null) await page.locator('.ac-period-panel summary').click()
  await expect(page.getByLabel('По', { exact: true })).toHaveValue('2026-10-14')
  await expect(page.locator('.ac-readiness')).toContainText('Пн–Пт · 10:00–18:00 · Europe/Moscow')
  const employee = page.getByRole('region', { name: 'Тестовый аудитор', exact: true })
  await expect(employee).toContainText('заполнено 2 из 23')
  await expect(employee.getByRole('link', { name: /2026-09-14: Частично, день закрыт/ })).toContainText('30 мин свободно')
  expect(queries.every(q => q.to <= readinessEnd(q.from, q.to))).toBe(true)
  await employee.getByRole('link', { name: /2026-09-14: Частично, день закрыт/ }).click()
  await expect(page).toHaveURL(new RegExp(`availability_person=${ids.a}`))
  await expect(page).toHaveURL(/day=2026-09-14/)
})

test('groups show distinct server statuses and only no_overlap can notify manually', async ({ page }, testInfo) => {
  const state = fixtureState()
  const statuses: CalendarReadiness['groups'][number]['days'][number]['status'][] = ['no_overlap', 'absent', 'booked', 'missing', 'available']
  const { commands } = await mountCalendar(page, { state, view: 'readiness', readiness: (from, to, duration) => {
    const result = fixtureReadiness(state, from, to, duration)
    result.groups[0].days.forEach((d, i) => {
      d.status = statuses[i % statuses.length]; d.missing_user_ids = d.status === 'missing' ? [ids.t] : []
      if (d.status === 'available') { d.common_windows = [{ start: 600, end: 630 }]; d.free_windows = [...d.common_windows]; d.slots = [...d.free_windows] }
      if (d.status === 'booked') { d.common_windows = [{ start: 600, end: 630 }]; d.plans = [{ id: ids.p, start: 600, duration: 30, activity: 'И43', status: 'planned' }] }
      d.last_notified_at = d.status === 'no_overlap' ? requestTime : null
    })
    return result
  } })
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: 'Группы', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Уведомить группу', exact: true })).toHaveCount(1)
  await expect(page.locator('.ac-readiness')).toContainText('Отсутствие участника')
  await expect(page.locator('.ac-readiness')).toContainText('Общие окна заняты встречами')
  await expect(page.locator('.ac-readiness')).toContainText('Есть свободное окно')
  await expect(page.locator('.ac-readiness')).toContainText(serverTimeLabel(requestTime))
  expect(commands).toHaveLength(0)
  await page.screenshot({ path: testInfo.outputPath('group-readiness-statuses.png'), fullPage: true })
  await page.getByRole('button', { name: 'Уведомить группу', exact: true }).click()
  await saveReason(page, 'Согласовать общее окно')
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'availability.notify', payload: { group_id: ids.g, date: day, reason: 'Согласовать общее окно' } })
  state.actor.can_manage = false
  await page.getByRole('button', { name: 'Обновить календарь', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Уведомить группу', exact: true })).toHaveCount(0)
})

test('readiness network recovery and stale version never enable notifications', async ({ page }) => {
  const state = fixtureState()
  await mountCalendar(page, { state, view: 'readiness', readiness: (from, to, duration) => {
    const result = fixtureReadiness(state, from, to, duration); result.scope_version = 7; result.groups[0].days[0].status = 'no_overlap'
    return result
  } })
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: 'Группы', exact: true }).click()
  await expect(page.getByText('Версия сводки отличается', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Уведомить группу', exact: true })).toHaveCount(0)
  await page.route('**/api/audit-calendar/readiness?**', route => route.fulfill({ status: 503, json: { detail: 'Сводка временно недоступна' } }))
  await page.getByRole('button', { name: 'Обновить сводку', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Сводка временно недоступна')
  await page.unroute('**/api/audit-calendar/readiness?**')
  await page.getByRole('button', { name: 'Повторить загрузку сводки', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.locator('.ac-readiness-group-day')).toHaveCount(5)
})

test('group notification preserves the chosen 60 minute window when only 30 is free', async ({ page }) => {
  const state = fixtureState()
  const { commands } = await mountCalendar(page, { state, view: 'readiness', readiness: (from, to, duration) => {
    const result = fixtureReadiness(state, from, to, duration)
    const day = result.groups[0].days[0]
    day.status = duration === 30 ? 'available' : 'no_overlap'
    day.missing_user_ids = []
    day.common_windows = [{ start: 600, end: 630 }]
    day.free_windows = [...day.common_windows]
    day.slots = duration === 30 ? [...day.free_windows] : []
    return result
  } })
  await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: 'Группы', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Уведомить группу', exact: true })).toHaveCount(0)
  await page.getByRole('combobox', { name: 'Окно встречи, мин', exact: true }).selectOption('60')
  await page.getByRole('button', { name: 'Уведомить группу', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('общего свободного окна на 60 мин нет')
  await saveReason(page, 'Нужно согласовать встречу на 60 минут')
  await expect.poll(() => commands.length).toBe(1)
  expect(commands[0]).toMatchObject({ operation: 'availability.notify', payload: { group_id: ids.g, date: day, reason: 'Нужно согласовать встречу на 60 минут', duration: 60 } })
})

test('readiness and request forms fit all themes and viewport sizes', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const state = fixtureState(); state.availability_locks.push(lockFor()); state.change_requests.push(requestFor())
  await mountCalendar(page, { state, view: 'readiness' })
  for (const [width, height] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [320, 700]]) {
    await page.setViewportSize({ width, height })
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      for (const tab of ['Заполненность', 'Группы', 'Заявки']) {
        await page.getByRole('navigation', { name: 'Вкладки сводки' }).getByRole('link', { name: new RegExp(`^${tab}`) }).click()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
        if ((width === 1440 && theme === 'light') || (width === 390 && theme !== 'light') || width === 320) await page.screenshot({ path: testInfo.outputPath(`${width}-${theme}-${tab}.png`), fullPage: true })
      }
    }
  }
  await page.getByRole('button', { name: 'Одобрить и открыть день', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Основание').fill('ОченьДлинноеНеразрывноеОснование'.repeat(20))
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('320-rose-protected-request-modal.png') })
})
