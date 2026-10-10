import { expect, test, type Locator } from '@playwright/test'
import { fixture, gate, id, task, tracker, user } from './review-tasks-trackers-helpers'

test('R04/A02: journal drafts stay with A/B, pending A survives B completion and read failure', async ({ page }) => {
  const state = await fixture(page)
  const held = gate()
  let failRead = false
  state.intercept = async (call) => {
    if (call.method === 'POST' && call.path.endsWith('/events')) {
      if (call.path.includes(id(11))) await held.promise
      return { body: { id: id(101), ...call.body } }
    }
    if (failRead && call.method === 'GET' && call.path.endsWith('/events')) return { status: 503, body: { detail: 'История недоступна' } }
  }
  await page.goto(`/personal-tasks?task=${id(11)}`)
  const a = page.locator(`#personal-task-${id(11)}`)
  const b = page.locator(`#personal-task-${id(12)}`)
  await a.getByRole('button', { name: 'Добавить запись в журнал', exact: true }).first().click()
  await a.getByPlaceholder('Заголовок записи').fill('Черновик A')
  await a.getByRole('button', { name: 'Добавить запись в журнал', exact: true }).last().click()
  await expect(a.getByPlaceholder('Заголовок записи')).toBeDisabled()
  await b.getByRole('button', { name: 'Добавить запись в журнал', exact: true }).first().click()
  await expect(b.getByPlaceholder('Заголовок записи')).toHaveValue('')
  await b.getByPlaceholder('Заголовок записи').fill('Черновик B')
  await b.getByRole('button', { name: 'Добавить запись в журнал', exact: true }).last().click()
  await expect(b.getByPlaceholder('Заголовок записи')).toHaveValue('')
  await b.getByPlaceholder('Заголовок записи').fill('Новый B')
  failRead = true
  held.release()
  await expect.poll(() => state.calls.filter((call) => call.method === 'GET' && call.path === `/api/personal-tasks/${id(11)}/events`).length).toBeGreaterThan(1)
  await expect(b.getByPlaceholder('Заголовок записи')).toHaveValue('Новый B')
  await a.getByRole('button', { name: 'Добавить запись в журнал', exact: true }).first().click()
  await expect(a.getByPlaceholder('Заголовок записи')).toHaveValue('')
  await expect(a.getByText('История недоступна', { exact: false })).toBeVisible()
  expect(state.calls.filter((call) => call.method === 'POST' && call.path.endsWith('/events')).map((call) => call.body.title)).toEqual(['Черновик A', 'Черновик B'])
  expect(state.errors).toEqual([])
})

test('R04/A02: checkpoint form is parent-bound, preserves known failure and prevents duplicate submit', async ({ page }) => {
  const state = await fixture(page)
  const held = gate()
  state.intercept = async (call) => {
    if (call.method === 'POST' && call.path.endsWith('/checkpoints')) { await held.promise; return { status: 422, body: { detail: 'Этап отклонён' } } }
  }
  await page.goto('/personal-tasks')
  const a = page.locator(`#personal-task-${id(11)}`)
  const b = page.locator(`#personal-task-${id(12)}`)
  await a.getByRole('button', { name: 'Добавить этап контроля' }).click()
  await a.getByPlaceholder('Новый этап / контрольная точка').fill('Этап A')
  await b.getByRole('button', { name: 'Добавить этап контроля' }).click()
  await expect(b.getByPlaceholder('Новый этап / контрольная точка')).toHaveValue('')
  await a.getByRole('button', { name: 'Добавить этап контроля' }).click()
  await expect(a.getByPlaceholder('Новый этап / контрольная точка')).toHaveValue('Этап A')
  await a.getByRole('button', { name: 'Добавить этап', exact: true }).click()
  await expect(a.getByRole('button', { name: 'Добавить этап', exact: true })).toBeDisabled()
  await expect(a.getByLabel('Срок этапа')).toBeDisabled()
  held.release()
  await expect(a.getByRole('button', { name: 'Добавить этап', exact: true })).toBeEnabled()
  await expect(a.getByPlaceholder('Новый этап / контрольная точка')).toHaveValue('Этап A')
  expect(state.calls.filter((call) => call.method === 'POST' && call.path.endsWith('/checkpoints'))).toHaveLength(1)
  expect(state.errors).toEqual([])
})

test('R17: personal deep link permits manual selection, collapse, filter and browser history', async ({ page }) => {
  const state = await fixture(page)
  await page.goto(`/personal-tasks?task=${id(11)}`)
  await page.locator(`#personal-task-${id(12)}`).getByRole('button', { name: 'Добавить запись в журнал', exact: true }).first().click()
  await expect(page).toHaveURL(new RegExp(`task=${id(12)}`))
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`task=${id(11)}`))
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(`task=${id(12)}`))
  await page.getByRole('button', { name: 'Ожидание', exact: true }).first().click()
  await expect(page).not.toHaveURL(/task=/)
  await expect.poll(() => state.calls.filter((call) => call.path === '/api/personal-tasks').at(-1)?.query.get('status')).toBe('waiting')
  expect(state.errors).toEqual([])
})

test('R06/A02: override and return keep reason on failure and guard pending decision', async ({ page }) => {
  const state = await fixture(page)
  let hold = gate()
  let fail = true
  state.intercept = async (call) => {
    if (call.path === '/api/queue/validate') { await hold.promise; return fail ? { status: 422, body: { detail: 'Решение отклонено' } } : { body: {} } }
  }
  await page.goto('/my-tasks')
  await page.getByRole('button', { name: /Принять$/ }).click()
  let dialog = page.getByRole('dialog', { name: 'Принять по admin override' })
  await dialog.getByLabel('Причина override').fill('Проверено вручную')
  await dialog.getByRole('button', { name: 'Принять', exact: true }).click()
  await expect(dialog.getByLabel('Причина override')).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Отмена' })).toBeDisabled()
  hold.release()
  await expect(dialog.getByLabel('Причина override')).toBeEnabled()
  await expect(dialog.getByLabel('Причина override')).toHaveValue('Проверено вручную')
  fail = false
  await dialog.getByRole('button', { name: 'Принять', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: /Вернуть$/ }).click()
  dialog = page.getByRole('dialog', { name: 'Вернуть задачу' })
  await dialog.getByLabel('Причина возврата').fill('Нужно исправить')
  hold = gate(); fail = true
  await dialog.getByRole('button', { name: 'Вернуть', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Вернуть', exact: true })).toBeDisabled()
  hold.release()
  await expect(dialog.getByLabel('Причина возврата')).toBeEnabled()
  await expect(dialog.getByLabel('Причина возврата')).toHaveValue('Нужно исправить')
  expect(state.calls.filter((call) => call.path === '/api/queue/validate')).toHaveLength(3)
  expect(state.errors).toEqual([])
})

test('A02: B completion does not unblock pending direct approval A', async ({ page }) => {
  const state = await fixture(page)
  state.review = [task(31, 'review', user.id), task(32, 'review', user.id)]
  const held = gate()
  state.intercept = async (call) => {
    if (call.path === '/api/queue/validate' && call.body.task_id === id(31)) { await held.promise; return { body: {} } }
  }
  await page.goto('/my-tasks')
  await page.getByRole('button', { name: /Принять$/ }).nth(0).click()
  await page.getByRole('button', { name: /Принять$/ }).last().click()
  await expect.poll(() => state.calls.filter((call) => call.path === '/api/queue/validate').length).toBe(2)
  const cardA = page.getByRole('button', { name: 'Q-задача 31', exact: false }).locator('xpath=ancestor::div[contains(@class, "shadow-sm")][1]')
  await expect(cardA.getByRole('button', { name: /Принять|\.\.\./ }).first()).toBeDisabled()
  held.release()
  expect(state.errors).toEqual([])
})

test('R07: Q-plan distinguishes delayed/failed own tasks and review inbox from empty, retries locally', async ({ page }) => {
  const state = await fixture(page)
  const held = gate()
  let fail = true
  state.intercept = async (call) => {
    if (call.path === '/api/tasks') { await held.promise; if (fail) return { status: 503, body: { detail: 'Задачи недоступны' } } }
  }
  await page.goto('/my-tasks')
  await expect(page.getByText('Нет задач в работе', { exact: true })).toHaveCount(0)
  held.release()
  await expect(page.getByRole('button', { name: 'Повторить загрузку задач', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Повторить загрузку приёмки', exact: true })).toBeVisible()
  await expect(page.getByText('Нет задач в работе', { exact: true })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Повторить загрузку приёмки', exact: true }).click()
  await expect(page.getByRole('button', { name: /Принять$/ })).toBeVisible()
  await page.getByRole('button', { name: 'Повторить загрузку задач', exact: true }).click()
  await expect(page.getByText('Нет задач в работе', { exact: true })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('R17: queue URL tracks close/open/back and rejects late detail errors', async ({ page }) => {
  const state = await fixture(page)
  const held = gate()
  state.intercept = async (call) => {
    if (call.path === `/api/tasks/${id(21)}`) { await held.promise; return { status: 503, body: { detail: 'Старый отказ A' } } }
  }
  await page.goto(`/queue?task=${id(21)}`)
  await expect.poll(() => state.calls.some((call) => call.path === `/api/tasks/${id(21)}`)).toBe(true)
  await page.getByRole('button', { name: /Q-задача 22/ }).click()
  await expect(page.getByRole('dialog')).toContainText('Q-задача 22')
  held.release()
  await expect(page).toHaveURL(new RegExp(`task=${id(22)}`))
  await expect(page.getByText('Старый отказ A')).toHaveCount(0)
  await page.getByRole('dialog').getByLabel('Закрыть', { exact: true }).click()
  await expect(page).not.toHaveURL(/task=/)
  await page.goBack()
  await expect(page.getByRole('dialog')).toContainText('Q-задача 22')
  await page.reload()
  await expect(page.getByRole('dialog')).toContainText('Q-задача 22')
  expect(state.errors).toEqual([])
})

test('R17/R09: queue deadline updates row and keyboard sorting, detail fits short viewport', async ({ page }) => {
  const state = await fixture(page)
  await page.setViewportSize({ width: 768, height: 500 })
  await page.goto(`/queue?task=${id(21)}`)
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Q-задача 21')
  page.once('dialog', (prompt) => prompt.accept('24'))
  await dialog.getByRole('button', { name: /дедлайн/i }).click()
  await expect.poll(() => state.calls.some((call) => call.path.endsWith('/due-date'))).toBe(true)
  const changed = state.calls.find((call) => call.path.endsWith('/due-date'))!.body.due_date as string
  await dialog.getByLabel('Закрыть', { exact: true }).click()
  const dateText = await page.evaluate((value) => new Date(value).toLocaleDateString('ru'), changed)
  await expect(page.locator('tbody tr').filter({ hasText: 'Q-задача 21' })).toContainText(dateText)
  const sort = page.getByRole('columnheader').filter({ has: page.getByRole('button', { name: 'Название', exact: true }) })
  await sort.getByRole('button').focus()
  await page.keyboard.press('Enter')
  await expect(sort).toHaveAttribute('aria-sort', 'descending')
  await page.keyboard.press('Space')
  await expect(sort).toHaveAttribute('aria-sort', 'ascending')
  expect(state.errors).toEqual([])
})

test('R20/A05: history and list retry failed offsets without gaps, history reopens after editing', async ({ page }) => {
  const state = await fixture(page)
  state.trackers = Array.from({ length: 601 }, (_, index) => tracker(1000 + index))
  let listFailed = false
  let historyFailed = false
  let editing = false
  const heldEdit = gate()
  state.intercept = async (call) => {
    if (editing && call.path === `/api/deadline-trackers/${id(1000)}` && call.method === 'GET') await heldEdit.promise
    const offset = Number(call.query.get('offset') || 0)
    if (call.path === '/api/deadline-trackers' && offset === 300 && !listFailed) { listFailed = true; return { status: 503, body: { detail: 'Страница списка недоступна' } } }
    if (call.path.endsWith('/history')) {
      if (offset === 100 && !historyFailed) { historyFailed = true; return { status: 503, body: { detail: 'Страница истории недоступна' } } }
      return { body: Array.from({ length: offset < 200 ? 100 : 1 }, (_, index) => ({ id: id(5000 + offset + index), event_type: 'created', details: {}, created_at: '2026-09-01T09:00:00Z' })) }
    }
  }
  await page.goto('/deadline-trackers')
  await page.getByRole('button', { name: 'Загрузить еще трекеры' }).click()
  await expect(page.getByText('Страница списка недоступна', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Загрузить еще трекеры' })).toBeDisabled()
  await page.getByRole('button', { name: 'Повторить загрузку трекеров' }).click()
  await page.getByRole('button', { name: 'Загрузить еще трекеры' }).click()
  await expect(page.getByRole('link', { name: 'Трекер 1600', exact: true })).toBeVisible()
  expect(state.calls.filter((call) => call.path === '/api/deadline-trackers').map((call) => Number(call.query.get('offset')))).toEqual([0, 300, 300, 600])
  await page.getByRole('link', { name: 'Трекер 1000', exact: true }).click()
  let dialog = page.getByRole('dialog', { name: 'Трекер 1000', exact: true })
  await dialog.getByRole('button', { name: 'Загрузить еще историю' }).click()
  await expect(dialog.getByRole('button', { name: 'Загрузить еще историю' })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Повторить загрузку истории' }).click()
  await dialog.getByRole('button', { name: 'Загрузить еще историю' }).click()
  await expect(dialog.getByRole('button', { name: 'Загрузить еще историю' })).toHaveCount(0)
  expect(state.calls.filter((call) => call.path.endsWith('/history')).map((call) => Number(call.query.get('offset')))).toEqual([0, 100, 100, 200])
  await dialog.getByText('Журнал изменений', { exact: true }).click()
  await expect(dialog.getByText('Трекер создан', { exact: true })).toHaveCount(201)
  editing = true
  await dialog.getByRole('button', { name: 'Редактировать трекер' }).click()
  await expect(dialog.getByRole('button', { name: 'Отмена', exact: true })).toBeDisabled()
  await expect(page).toHaveURL(new RegExp(`tracker=${id(1000)}`))
  heldEdit.release()
  const editor = page.getByRole('dialog', { name: 'Редактирование трекера', exact: true })
  await expect(editor).toBeVisible()
  await expect(page).not.toHaveURL(/tracker=/)
  await editor.getByRole('button', { name: 'Отмена', exact: true }).click()
  await page.getByRole('link', { name: 'Трекер 1000', exact: true }).click()
  dialog = page.getByRole('dialog', { name: 'Трекер 1000', exact: true })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Редактировать трекер' }).click()
  await expect(editor).toBeVisible()
  await expect(page).not.toHaveURL(/tracker=/)
  await editor.getByLabel('Название', { exact: true }).fill('Трекер 1000 обновлен')
  await editor.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await page.getByRole('link', { name: 'Трекер 1000 обновлен', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Трекер 1000 обновлен', exact: true })).toBeVisible()
  expect(state.errors).toEqual([])
})

test('R20: back while target is pending clears loading and ignores its late result', async ({ page }) => {
  const state = await fixture(page)
  const held = gate()
  state.intercept = async (call) => {
    if (call.path === `/api/deadline-trackers/${id(41)}`) { await held.promise; return { body: tracker(41) } }
  }
  await page.goto('/deadline-trackers')
  await page.getByRole('link', { name: 'Трекер 41', exact: true }).click()
  await expect(page.getByText('Загрузка трекеров...', { exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByText('Загрузка трекеров...', { exact: true })).toHaveCount(0)
  held.release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('G6: all tracker primary buttons retain the theme pair on dark hover', async ({ page }) => {
  const state = await fixture(page)
  await page.addInitScript(() => localStorage.setItem('dpms-theme', 'dark'))
  await page.goto('/deadline-trackers')
  const checkHover = async (button: Locator) => {
    await button.hover()
    await expect.poll(() => button.evaluate((element) => {
      const reference = document.createElement('span')
      reference.style.backgroundColor = 'hsl(var(--primary) / 0.9)'
      reference.style.color = 'hsl(var(--primary-foreground))'
      element.appendChild(reference)
      const expected = getComputedStyle(reference)
      const actual = getComputedStyle(element)
      const matches = actual.backgroundColor === expected.backgroundColor && actual.color === expected.color
      reference.remove()
      return matches
    })).toBe(true)
  }
  const create = page.getByRole('button', { name: 'Новый трекер', exact: true })
  await checkHover(create)
  await create.click()
  await checkHover(page.getByRole('dialog').getByRole('button', { name: 'Создать трекер', exact: true }))
  await page.getByRole('dialog').getByRole('button', { name: 'Отмена', exact: true }).click()
  await page.getByRole('button', { name: 'Группы', exact: true }).click()
  await checkHover(page.getByRole('dialog').getByRole('button', { name: 'Создать', exact: true }))
  expect(state.errors).toEqual([])
})
