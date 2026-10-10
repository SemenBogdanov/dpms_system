import { expect, test } from '@playwright/test'
import { batch, calendarFixture, editMeeting, gate, ids, openCalendar, sourceFile } from './review-calendar-helpers'

test.use({ serviceWorkers: 'block', timezoneId: 'Europe/Moscow' })

test('R15/A07: invalid replacement clears confirmed preview; the same file can be selected after cancel', async ({ page }) => {
  const control = await calendarFixture(page)
  await openCalendar(page)
  const file = page.getByLabel('JSON V5', { exact: true })
  await file.setInputFiles(sourceFile())
  await expect(file).toHaveValue('')
  await page.getByRole('button', { name: 'Предварительный просмотр', exact: true }).click()
  await page.getByLabel('Основание переноса').fill('Синтетическое основание')
  await page.getByLabel('Подтверждаю источник, горизонт истории и сопоставление').check()
  await expect(page.getByRole('button', { name: 'Применить импорт', exact: true })).toBeEnabled()
  await file.setInputFiles(sourceFile('invalid.json', '{broken'))
  await expect(page.getByRole('region', { name: 'Импорт источника' }).getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Применить импорт', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Предварительный просмотр', exact: true })).toHaveCount(0)
  await file.setInputFiles(sourceFile())
  await page.getByRole('button', { name: 'Отменить загрузку' }).click()
  await expect(file).toHaveValue('')
  await file.setInputFiles(sourceFile())
  await expect(page.getByRole('heading', { name: 'Сопоставление учётных записей' })).toBeVisible()
  await page.getByRole('button', { name: 'Предварительный просмотр', exact: true }).click()
  await expect(page.getByLabel('Подтверждаю источник, горизонт истории и сопоставление')).not.toBeChecked()
  await expect(page.getByLabel('Основание переноса')).toHaveValue('')
  expect(control.writes.filter(path => path.endsWith('/apply'))).toEqual([])
  expect(control.errors).toEqual([])
})

declare global {
  interface Window {
    __calendarReads: Record<string, (fail?: boolean) => void>
  }
}

for (const oldFails of [false, true]) {
  for (const oldFirst of [false, true]) {
    test(`R15: obsolete file ${oldFails ? 'error' : 'success'}/finally is ignored, old finishes ${oldFirst ? 'first' : 'last'}`, async ({ page }) => {
      await calendarFixture(page)
      await page.addInitScript(() => {
        window.__calendarReads = {}
        const read = File.prototype.text
        File.prototype.text = function () {
          if (!this.name.startsWith('slow-')) return read.call(this)
          return new Promise<string>((resolve, reject) => {
            window.__calendarReads[this.name] = fail => fail ? reject(new Error('Obsolete read failure')) : resolve('{"version":5}')
          })
        }
      })
      await openCalendar(page)
      const file = page.getByLabel('JSON V5', { exact: true })
      await file.setInputFiles(sourceFile('slow-A.json'))
      await expect(page.getByRole('status').filter({ hasText: 'Чтение файла…' })).toBeVisible()
      await file.setInputFiles(sourceFile('slow-B.json'))
      if (oldFirst) {
        await page.evaluate(fail => window.__calendarReads['slow-A.json'](fail), oldFails)
        await expect(page.getByRole('status').filter({ hasText: 'Чтение файла…' })).toBeVisible()
        await expect(page.getByRole('heading', { name: 'Сопоставление учётных записей' })).toHaveCount(0)
      }
      await page.evaluate(() => window.__calendarReads['slow-B.json']())
      await expect(page.getByRole('heading', { name: 'Сопоставление учётных записей' })).toBeVisible()
      if (!oldFirst) await page.evaluate(fail => window.__calendarReads['slow-A.json'](fail), oldFails)
      await expect(page.getByText('slow-B.json', { exact: true })).toBeVisible()
      await expect(page.getByText('slow-A.json', { exact: true })).toHaveCount(0)
      await expect(page.getByText('Obsolete read failure')).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Предварительный просмотр', exact: true })).toBeEnabled()
    })
  }
}

test('R15: preview locks its file/mapping through refresh and one apply cannot be repeated after refresh failure', async ({ page }) => {
  const control = await calendarFixture(page)
  const previewGate = gate()
  let previewCalls = 0
  control.handlers.set('/api/audit-calendar/imports/preview', async route => {
    previewCalls++
    await previewGate.promise
    await route.fulfill({ json: batch() })
  })
  await openCalendar(page)
  await page.getByLabel('JSON V5', { exact: true }).setInputFiles(sourceFile())
  const preview = page.getByRole('button', { name: 'Предварительный просмотр', exact: true })
  await preview.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  try {
    await expect.poll(() => previewCalls).toBe(1)
    await expect(page.getByLabel('JSON V5', { exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Отменить загрузку' })).toBeDisabled()
    previewGate.release()
    await page.getByLabel('Основание переноса').fill('Подтверждение')
    await page.getByLabel('Подтверждаю источник, горизонт истории и сопоставление').check()
    control.handlers.set('/api/audit-calendar/imports/synthetic-batch-1/apply', route => route.fulfill({ json: { version: 2, result: {} } }))
    control.handlers.set('/api/audit-calendar/state', route => route.fulfill({ status: 503, json: { detail: 'Синтетический отказ обновления' } }))
    await page.getByRole('button', { name: 'Применить импорт', exact: true }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Импорт сохранён.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Применить импорт', exact: true })).toHaveCount(0)
    await expect(page.getByLabel('JSON V5', { exact: true })).toHaveValue('')
    expect(control.writes.filter(path => path.endsWith('/apply'))).toHaveLength(1)
  } finally { previewGate.release() }
})

test('imports: loading/error are not empty; retry only reads the package list', async ({ page }) => {
  const control = await calendarFixture(page)
  const listGate = gate()
  let calls = 0
  control.handlers.set('/api/audit-calendar/imports', async route => {
    if (++calls === 1) { await listGate.promise; return route.fulfill({ status: 503, json: { detail: 'Список временно недоступен' } }) }
    return route.fulfill({ json: [batch()] })
  })
  await openCalendar(page)
  try {
    await expect(page.getByText('Загрузка пакетов…')).toBeVisible()
    await expect(page.getByText('Импортированных пакетов нет.')).toHaveCount(0)
    listGate.release()
    await page.getByRole('button', { name: 'Повторить загрузку пакетов' }).click()
    await expect(page.getByRole('cell', { name: 'synthetic-batch-1', exact: true })).toBeVisible()
    expect(control.writes.filter(path => path.startsWith('/api/audit-calendar/'))).toEqual([])
  } finally { listGate.release() }
})

for (const overlap of [false, true]) {
  test(`R16: 409 preserves input and reconciles ${overlap ? 'overlapping' : 'disjoint'} fields explicitly`, async ({ page }) => {
    const control = await calendarFixture(page)
    await openCalendar(page, 'dataset')
    const dialog = await editMeeting(page)
    await dialog.getByRole('button', { name: 'Изменить дату и время встречи' }).click()
    await dialog.getByRole('spinbutton', { name: 'Длительность, мин', exact: true }).fill('120')
    await dialog.getByRole('textbox', { name: 'Основание', exact: true }).fill('Моя причина')
    if (overlap) await dialog.getByRole('textbox', { name: 'Активность', exact: true }).fill('Моя активность')
    control.state.scope.version = 2
    control.state.plans[0].activity = 'Редакция другого участника'
    control.state.plans[0].version = 2
    await dialog.getByRole('button', { name: 'Сохранить', exact: true }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
    await expect(dialog.getByRole('alert')).toContainText('Конфликт версии')
    expect(control.commands).toHaveLength(1)
    await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled()
    const reloadGate = gate()
    const reads = control.stateReads
    control.handlers.set('/api/audit-calendar/state', async route => { await reloadGate.promise; await route.fulfill({ json: control.state }) })
    await dialog.getByRole('button', { name: 'Перечитать, сохранив ввод' }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
    try {
      await expect.poll(() => control.stateReads).toBe(reads + 1)
      await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeDisabled()
      await expect(dialog.getByRole('textbox', { name: 'Активность', exact: true })).toBeDisabled()
      reloadGate.release()
      const review = dialog.getByRole('region', { name: 'Согласование плана' })
      await expect(review.getByText('Редакция другого участника', { exact: true })).toBeVisible()
      await expect(dialog.getByRole('spinbutton', { name: 'Длительность, мин', exact: true })).toHaveValue('120')
      await expect(dialog.getByRole('textbox', { name: 'Основание', exact: true })).toHaveValue('Моя причина')
      await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled()
      if (overlap) {
        await expect(review.getByRole('button', { name: 'Согласовать изменения' })).toBeDisabled()
        await review.getByRole('combobox', { name: 'Решение: Активность', exact: true }).selectOption('local')
      }
      await review.getByRole('button', { name: 'Согласовать изменения' }).click()
      await expect(dialog.getByRole('textbox', { name: 'Активность', exact: true })).toHaveValue(overlap ? 'Моя активность' : 'Редакция другого участника')
      await expect(dialog.getByRole('combobox', { name: 'Группа', exact: true })).toBeEnabled()
      await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
      await expect.poll(() => control.commands.length).toBe(2)
      expect(control.commands[0].expected_version).toBe(1)
      expect(control.commands[1].expected_version).toBe(2)
      expect(control.commands[1].request_id).not.toBe(control.commands[0].request_id)
      expect(control.commands[1].payload).toMatchObject({ activity: overlap ? 'Моя активность' : 'Редакция другого участника', duration: 120, reason: 'Моя причина' })
      expect(control.errors).toEqual([])
    } finally { reloadGate.release() }
  })
}

test('R16: failed reload retains input; newly frozen plan cannot be rebased or hide the draft', async ({ page }) => {
  const control = await calendarFixture(page)
  await openCalendar(page, 'dataset')
  const dialog = await editMeeting(page)
  await dialog.getByRole('textbox', { name: 'Активность', exact: true }).fill('Несохранённая активность')
  await dialog.getByRole('textbox', { name: 'Основание', exact: true }).fill('Несохранённое основание')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  control.handlers.set('/api/audit-calendar/state', route => route.fulfill({ status: 503, json: { detail: 'Временный отказ' } }))
  await dialog.getByRole('button', { name: 'Перечитать, сохранив ввод' }).click()
  await expect(dialog.getByRole('textbox', { name: 'Активность', exact: true })).toHaveValue('Несохранённая активность')
  await expect(dialog.getByRole('button', { name: 'Перечитать, сохранив ввод' })).toBeEnabled()
  await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled()
  control.state.scope.version++
  control.state.plans[0].fact_outcome = 'completed'
  control.handlers.delete('/api/audit-calendar/state')
  await dialog.getByRole('button', { name: 'Перечитать, сохранив ввод' }).click()
  await expect(dialog.getByText(/Повторная запись заблокирована/)).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: 'Активность', exact: true })).toHaveValue('Несохранённая активность')
  await expect(dialog.getByRole('button', { name: 'Согласовать изменения' })).toHaveCount(0)
  expect(control.commands).toHaveLength(1)
})

test('A03: refresh rereads requests, prevents duplicates and recovers from errors', async ({ page }) => {
  const control = await calendarFixture(page)
  await openCalendar(page, 'readiness', '&summary_tab=requests')
  const summary = page.getByRole('region', { name: 'Сводка доступности', exact: true })
  await expect(summary.getByText('Заявок за период нет.')).toBeVisible()
  const readGate = gate()
  const reads = control.stateReads
  control.handlers.set('/api/audit-calendar/state', async route => { await readGate.promise; await route.fulfill({ status: 503, json: { detail: 'Временный отказ' } }) })
  await summary.getByRole('button', { name: 'Обновить сводку', exact: true }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  try {
    await expect.poll(() => control.stateReads).toBe(reads + 1)
    await expect(summary.getByRole('button', { name: 'Обновить сводку', exact: true })).toBeDisabled()
    readGate.release()
    await expect(summary.getByRole('alert')).toContainText('Сводка и заявки не обновлены')
    await expect(summary.getByText('Заявок за период нет.')).toHaveCount(0)
    control.state.change_requests.push({ id: 'synthetic-request', user_id: ids.a, date: '2026-09-14', reason: 'Новая заявка после загрузки', status: 'pending', requested_at: control.state.scope.now, requested_by_id: ids.a, opened_at: null, opened_by_id: null, closed_at: null, closed_by_id: null, resolution: '', before: [], after: null })
    control.handlers.delete('/api/audit-calendar/state')
    await summary.getByRole('button', { name: 'Повторить обновление сводки' }).click()
    await expect(summary.getByText('Новая заявка после загрузки')).toBeVisible()
    await expect(summary.getByRole('link', { name: 'Заявки (1)' })).toBeVisible()
    await expect(summary.getByRole('button', { name: 'Одобрить и открыть день' })).toBeVisible()
    expect(control.writes.filter(path => path.startsWith('/api/audit-calendar/'))).toEqual([])
  } finally { readGate.release() }
})

for (const theme of ['light', 'dark', 'rose']) {
  test(`G5: ${theme} hover keeps interval backgrounds and absence hatching`, async ({ page }) => {
    const control = await calendarFixture(page)
    control.state.availability.push({ user_id: ids.a, date: '2026-09-14', start: 600, end: 630, available: true }, { user_id: ids.a, date: '2026-09-14', start: 630, end: 660, available: false })
    control.state.absences.push({ id: 'synthetic-absence', user_id: ids.t, start_date: '2026-09-14', end_date: '2026-09-14', status: 'active', version: 1, reason: 'Тест' })
    await openCalendar(page, 'readiness')
    await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
    for (const status of ['free', 'busy', 'unknown', 'absent']) {
      const cell = page.locator(`.ac-timeline-cell.ac-time-${status}`).first()
      await expect(cell).toBeVisible()
      await page.mouse.move(0, 0)
      const before = await cell.evaluate(el => ({ background: getComputedStyle(el).backgroundColor, image: getComputedStyle(el).backgroundImage }))
      await cell.hover()
      expect(await cell.evaluate(el => ({ background: getComputedStyle(el).backgroundColor, image: getComputedStyle(el).backgroundImage }))).toEqual(before)
      if (status === 'absent') expect(before.image).not.toBe('none')
      expect(await cell.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe('none')
    }
    await page.getByRole('link', { name: 'Доступное время', exact: true }).click()
    for (const status of ['free', 'busy']) {
      const cell = page.locator(`.ac-av-slot.ac-${status}:visible`).first()
      await expect(cell).toBeVisible()
      await page.mouse.move(0, 0)
      const color = await cell.evaluate(el => getComputedStyle(el).backgroundColor)
      await cell.hover()
      expect(await cell.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(color)
    }
  })
}

for (const viewport of [{ width: 768, height: 500 }, { width: 1024, height: 768 }, { width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 700 }]) {
  test(`R09/051: modal body scroll, safe bounds and focus at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const control = await calendarFixture(page)
    control.state.groups.push({ ...structuredClone(control.state.groups[0]), id: 'synthetic-archived-group', code: 'G2', archived: true })
    await openCalendar(page, 'dataset')
    const trigger = page.getByRole('region', { name: 'Датасет', exact: true }).getByRole('button', { name: /G1 · И43/ })
    const dialog = await editMeeting(page)
    await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeFocused()
    await dialog.getByRole('button', { name: 'Изменить дату и время встречи' }).click()
    // Simulate resolved nonzero device insets without pretending Chromium is an iPhone.
    await page.locator('.ac-overlay').evaluate(el => { (el as HTMLElement).style.setProperty('--ac-safe-top', '44px'); (el as HTMLElement).style.setProperty('--ac-safe-bottom', '34px') })
    const bounds = await dialog.boundingBox()
    expect(bounds!.y).toBeGreaterThanOrEqual(44)
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height - 34 + 1)
    const save = dialog.getByRole('button', { name: 'Сохранить', exact: true })
    const saveBounds = await save.boundingBox()
    expect(saveBounds!.y + saveBounds!.height).toBeLessThanOrEqual(viewport.height - 34)
    const summary = dialog.locator('summary', { hasText: 'Недоступные группы' })
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).focus()
    let found = false
    for (let i = 0; i < 30; i++) {
      await page.keyboard.press('Tab')
      expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true)
      if (await summary.evaluate(el => el === document.activeElement)) { found = true; break }
    }
    expect(found).toBe(true)
    await page.keyboard.press('Space')
    await expect(summary.locator('..')).toHaveAttribute('open', '')
    await page.keyboard.press('Shift+Tab')
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true)
    await dialog.getByRole('textbox', { name: 'Активность', exact: true }).fill('Черновик для проверки фокуса')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('calendar-modal.png') })
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Активность', exact: true })).toHaveValue('И43')
    expect(control.errors).toEqual([])
  })
}
