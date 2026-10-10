import { createHash } from 'node:crypto'
import { expect, test } from '@playwright/test'
import {
  assignment, base, caseId, finishHeld, hold, install, makeComparison, makeState,
  openCase, otherCaseId, preview, reply, switchCase, unloadProtected,
} from './review-audit-helpers'

declare global {
  interface Window {
    __auditImportSubmissions: Array<{ name: string; bytes: number[]; checksum: FormDataEntryValue | null }>
  }
}

test('R02: provenance Space/Enter and interactive descendants never accept an atom', async ({ page }) => {
  const state = makeState()
  await install(page, state)
  await openCase(page)
  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  const dialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  const summary = dialog.locator('summary').filter({ hasText: 'Идентификаторы и SHA-256' })
  await summary.focus()
  await summary.press('Space')
  await expect(summary.locator('..')).toHaveAttribute('open', '')
  await summary.press('Enter')
  await expect(summary.locator('..')).not.toHaveAttribute('open')
  await expect(dialog.getByRole('heading', { name: 'Атом 1', exact: true })).toBeVisible()

  const prevented = await dialog.locator('[tabindex="-1"]').first().evaluate((surface) => {
    const controls = [
      '<input>', '<textarea></textarea>', '<select><option>A</option></select>',
      '<button><span>Действие</span></button>', '<a href="#test"><span>Ссылка</span></a>',
      '<div contenteditable=""><span>Текст</span></div>', '<div contenteditable="plaintext-only">Текст</div>',
      '<div role="switch"><span>Переключатель</span></div>', '<div tabindex="0"><span>Контрол</span></div>',
      '<video controls></video>', '<audio controls></audio>',
    ]
    return controls.map((markup) => {
      const wrapper = document.createElement('div')
      wrapper.innerHTML = markup
      surface.append(wrapper)
      const target = wrapper.querySelector('span') ?? wrapper.firstElementChild!
      const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })
      target.dispatchEvent(event)
      wrapper.remove()
      return event.defaultPrevented
    })
  })
  expect(prevented).toEqual(Array(11).fill(false))
  expect(state.writes.filter((w) => w.method === 'PATCH')).toHaveLength(0)
  await dialog.getByRole('button', { name: 'Принять', exact: true }).click()
  await expect(dialog.getByRole('heading', { name: 'Атом 2', exact: true })).toBeVisible()
  expect(state.writes.filter((w) => w.method === 'PATCH')).toHaveLength(1)
  expect(state.errors).toEqual([])
  expect(state.unexpected).toEqual([])
})

test('R02/A12: summary stays in the modal Tab cycle and focus returns to its trigger', async ({ page }) => {
  const state = makeState()
  await install(page, state)
  await openCase(page)
  const trigger = page.getByRole('button', { name: 'Проверить черновики' })
  await trigger.focus()
  await trigger.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await expect(dialog.locator('[tabindex="-1"]').first()).toBeFocused()
  await dialog.getByRole('button', { name: 'Закрыть диалог' }).focus()
  let reachedSummary = false
  const focusTrail: unknown[] = []
  for (let i = 0; i < 18; i += 1) {
    await page.keyboard.press('Tab')
    const focus = await dialog.evaluate((panel) => ({
      inside: panel.contains(document.activeElement), summary: document.activeElement?.tagName === 'SUMMARY',
      tag: document.activeElement?.tagName,
      label: document.activeElement?.getAttribute('aria-label') || document.activeElement?.textContent?.slice(0, 80),
      controls: Array.from(panel.querySelectorAll<HTMLElement>('summary,button')).map(el => ({
        tag: el.tagName, text: el.textContent?.trim(), tabIndex: el.tabIndex, explicit: el.getAttribute('tabindex'),
      })),
    }))
    focusTrail.push(focus)
    expect(focus.inside, JSON.stringify(focusTrail)).toBe(true)
    reachedSummary ||= focus.summary
  }
  expect(reachedSummary).toBe(true)
  await dialog.getByRole('button', { name: 'Закрыть диалог' }).focus()
  await page.keyboard.press('Shift+Tab')
  expect(await dialog.evaluate((panel) => panel.contains(document.activeElement))).toBe(true)
  await dialog.getByRole('button', { name: 'Закрыть диалог' }).click()
  await expect(trigger).toBeFocused()
  expect(state.writes.filter((w) => w.method === 'PATCH')).toHaveLength(0)
})

for (const mode of ['draft', 'alpha'] as const) {
  test(`R14: ${mode} dirty reload guard clears after explicit cancellation`, async ({ page }) => {
    const state = makeState()
    if (mode === 'alpha') state.atoms.forEach((a) => { a.state = 'ready' })
    await install(page, state)
    await openCase(page)
    await page.getByRole('button', { name: mode === 'draft' ? 'Проверить черновики' : 'Альфа-проверка', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: mode === 'draft' ? 'Проверка черновиков атомов' : 'Альфа-проверка атомов' })
    expect(await unloadProtected(page)).toBe(false)
    const surface = dialog.locator('[tabindex="-1"]').first()
    await surface.focus()
    await surface.press(mode === 'draft' ? 'e' : 'ArrowDown')
    const field = dialog.getByLabel(mode === 'draft' ? 'Название атома' : 'Почему элемент не найден или требует уточнения')
    await field.fill('Несохранённое решение')
    expect(await unloadProtected(page)).toBe(true)
    await page.keyboard.press('Escape')
    await expect(field).toHaveValue('Несохранённое решение')
    await dialog.getByRole('button', { name: mode === 'draft' ? 'Отменить изменения' : 'Отмена', exact: true }).click()
    expect(await unloadProtected(page)).toBe(false)
    expect(state.errors).toEqual([])
  })
}

test('R04/R14: comparison locks every editor during save; error retains draft and retry clears dirty', async ({ page }) => {
  const state = makeState()
  const pending = hold()
  let attempts = 0
  await install(page, state, async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/comparison-A/commit')) return false
    attempts += 1
    if (attempts === 1) return pending.handle(route)
    state.comparisons[0].status = 'committed'
    await reply(route, { review_only: true, atoms_created: 0 })
    return true
  })
  await openCase(page)
  await page.getByRole('button', { name: 'Продолжить сравнение' }).click()
  const dialog = page.getByRole('dialog', { name: 'Сравнительный анализ моделей' })
  expect(await unloadProtected(page)).toBe(false)
  await dialog.getByLabel('Название атома').fill('Моё решение')
  expect(await unloadProtected(page)).toBe(true)
  const save = dialog.getByRole('button', { name: 'Сохранить сравнение' })
  await save.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect.poll(() => pending.entered).toBe(true)
  for (const name of ['Название атома', 'Цифровой продукт', 'Тип объекта', 'Вид работ']) {
    await expect(dialog.getByRole('textbox', { name, exact: true })).toBeDisabled()
  }
  for (const name of ['Выбрать все', 'Включить атом 1 в сравнение']) {
    await expect(dialog.getByRole('checkbox', { name, exact: true })).toBeDisabled()
  }
  expect(attempts).toBe(1)
  await finishHeld(page, pending, { detail: 'Сохранение не выполнено' }, 503)
  await expect(dialog.getByText('Сохранение не выполнено')).toBeVisible()
  await expect(dialog.getByLabel('Название атома')).toHaveValue('Моё решение')
  await expect(save).toBeEnabled()
  expect(await unloadProtected(page)).toBe(true)
  await save.click()
  await expect(dialog).toBeHidden()
  expect(await unloadProtected(page)).toBe(false)
  expect(attempts).toBe(2)
  expect(state.atoms.every((a) => a.state === 'draft')).toBe(true)
  expect(state.errors).toEqual([])
  expect(state.unexpected).toEqual([])
})

for (const oldStatus of [200, 503]) {
  test(`R04: comparison A late ${oldStatus} cannot close/unlock a new case B save`, async ({ page }) => {
    const state = makeState()
    state.comparisons.push(makeComparison('comparison-B', otherCaseId))
    const a = hold()
    const b = hold()
    await install(page, state, async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/comparison-A/commit')) return a.handle(route)
      if (path.endsWith('/comparison-B/commit')) return b.handle(route)
      return false
    })
    await openCase(page)
    await page.getByRole('button', { name: 'Продолжить сравнение' }).click()
    const dialog = page.getByRole('dialog', { name: 'Сравнительный анализ моделей' })
    await dialog.getByRole('button', { name: 'Сохранить сравнение' }).click()
    await expect.poll(() => a.entered).toBe(true)
    await switchCase(page, otherCaseId)
    await page.getByRole('button', { name: 'Продолжить сравнение' }).click()
    await dialog.getByLabel('Название атома').fill('Решение B')
    await dialog.getByRole('button', { name: 'Сохранить сравнение' }).click()
    await expect.poll(() => b.entered).toBe(true)
    await finishHeld(page, a, oldStatus === 200 ? {} : { detail: 'Устаревшая ошибка A' }, oldStatus)
    await expect(dialog.getByLabel('Название атома')).toHaveValue('Решение B')
    await expect(dialog.getByLabel('Название атома')).toBeDisabled()
    await expect(dialog.getByRole('button', { name: 'Сохранить сравнение' })).toBeDisabled()
    await expect(page.getByText('Устаревшая ошибка A')).toHaveCount(0)
    await finishHeld(page, b, { detail: 'Ошибка B' }, 503)
    await expect(dialog.getByText('Ошибка B')).toBeVisible()
    await expect(dialog.getByLabel('Название атома')).toBeEnabled()
    expect(await unloadProtected(page)).toBe(true)
  })
}

for (const oldStatus of [200, 503]) {
  test(`R05: old assignments ${oldStatus} cannot end loading or overwrite the next period`, async ({ page }) => {
    const state = makeState()
    const a = hold()
    const b = hold()
    let count = 0
    let dayB = ''
    await install(page, state, async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname !== '/api/audit/assignments') return false
      count += 1
      if (count === 1) return a.handle(route)
      dayB = url.searchParams.get('date_from')!
      return b.handle(route)
    })
    await page.goto('/audit?view=assignments')
    await expect.poll(() => a.entered).toBe(true)
    await page.getByRole('button', { name: 'Следующий период' }).click()
    await expect.poll(() => b.entered).toBe(true)
    await finishHeld(page, a, oldStatus === 200 ? { items: [assignment(dayB, 'Старый ответ A')] } : { detail: 'Ошибка периода A' }, oldStatus)
    await expect(page.getByText('Загружаем матрицу')).toBeVisible()
    await expect(page.getByText('Ошибка периода A')).toHaveCount(0)
    await finishHeld(page, b, { items: [assignment(dayB, 'Текущий ответ B')] })
    await expect(page.getByText('Текущий ответ B')).toBeVisible()
    await expect(page.getByText('Старый ответ A')).toHaveCount(0)
    expect(state.errors).toEqual([])
    expect(state.unexpected).toEqual([])
  })
}

test('R05: B first stays authoritative after A; current failure is not an empty matrix and retry works', async ({ page }) => {
  const state = makeState()
  const a = hold()
  let count = 0
  await install(page, state, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname !== '/api/audit/assignments') return false
    count += 1
    if (count === 1) return a.handle(route)
    if (count === 3) await reply(route, { detail: 'Матрица недоступна' }, 503)
    else await reply(route, { items: [assignment(url.searchParams.get('date_from')!, 'Назначение B')] })
    return true
  })
  await page.goto('/audit?view=assignments')
  await expect.poll(() => a.entered).toBe(true)
  await page.getByRole('button', { name: 'Следующий период' }).click()
  await expect(page.getByText('Назначение B')).toBeVisible()
  await finishHeld(page, a, { items: [] })
  await expect(page.getByText('Назначение B')).toBeVisible()
  await page.getByRole('button', { name: 'Обновить назначения' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Матрица недоступна' })).toBeVisible()
  await expect(page.locator('button[title="Изменить назначенные договоры"]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Обновить назначения' }).click()
  await expect(page.getByText('Назначение B')).toBeVisible()
})

for (const oldStatus of [200, 503]) {
  test(`R15: preview A late ${oldStatus} cannot validate B or end its pending preview`, async ({ page }) => {
    const state = makeState()
    const a = hold()
    const b = hold()
    let previews = 0
    await install(page, state, async (route) => {
      if (!new URL(route.request().url()).pathname.endsWith('/imports/preview')) return false
      previews += 1
      return (previews === 1 ? a : b).handle(route)
    })
    await openCase(page)
    await page.getByRole('button', { name: 'Загрузить реестр атомов', exact: true }).click()
    const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('Excel-файл') })
    const file = dialog.getByLabel('Excel-файл')
    const check = dialog.getByRole('button', { name: 'Проверить файл' })
    const commit = dialog.getByRole('button', { name: 'Подтвердить импорт' })
    await file.setInputFiles({ name: 'same.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('A') })
    await check.click()
    await expect.poll(() => a.entered).toBe(true)
    await file.setInputFiles({ name: 'same.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('B') })
    await expect(commit).toBeDisabled()
    await check.click()
    await expect.poll(() => b.entered).toBe(true)
    await finishHeld(page, a, oldStatus === 200 ? preview('Старый preview A') : { detail: 'Ошибка файла A' }, oldStatus)
    await expect(check).toBeDisabled()
    await expect(commit).toBeDisabled()
    await expect(dialog.getByText('Старый preview A')).toHaveCount(0)
    await expect(page.getByText('Ошибка файла A')).toHaveCount(0)
    await finishHeld(page, b, preview('Текущий preview B'))
    await expect(dialog.getByText('Текущий preview B')).toBeVisible()
    await expect(commit).toBeEnabled()
    expect(state.writes.filter((w) => w.path.endsWith('/imports/commit'))).toHaveLength(0)
    expect(state.errors).toEqual([])
    expect(state.unexpected).toEqual([])
  })
}

test('R15: recheck failure invalidates ready preview; successful commit uses the exact current file checksum', async ({ page }) => {
  const state = makeState()
  const committing = hold()
  let checks = 0
  // WebKit's request.postData() omits multipart file bytes. Observe the actual
  // submitted FormData instead of treating protocol serialization as file loss.
  await page.addInitScript(() => {
    window.__auditImportSubmissions = []
    const nativeFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      if (url.pathname.endsWith('/imports/commit') && init?.body instanceof FormData) {
        const file = init.body.get('file')
        if (file instanceof File) window.__auditImportSubmissions.push({
          name: file.name, bytes: Array.from(new Uint8Array(await file.arrayBuffer())),
          checksum: init.body.get('expected_sha256'),
        })
      }
      return nativeFetch(input, init)
    }
  })
  await install(page, state, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/imports/preview')) {
      checks += 1
      await reply(route, checks === 2 ? { detail: 'Невалидный файл' } : preview('Проверен B'), checks === 2 ? 422 : 200)
      return true
    }
    if (path.endsWith('/imports/commit')) return committing.handle(route)
    return false
  })
  await openCase(page)
  await page.getByRole('button', { name: 'Загрузить реестр атомов', exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ has: page.getByLabel('Excel-файл') })
  const file = dialog.getByLabel('Excel-файл')
  const check = dialog.getByRole('button', { name: 'Проверить файл' })
  const commit = dialog.getByRole('button', { name: 'Подтвердить импорт' })
  await file.setInputFiles({ name: 'A.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('A contents') })
  await check.click()
  await expect(commit).toBeEnabled()
  await file.setInputFiles({ name: 'B.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('exact B contents') })
  await expect(commit).toBeDisabled()
  await check.click()
  await expect(dialog.getByText('Невалидный файл')).toBeVisible()
  await expect(commit).toBeDisabled()
  await expect(dialog.getByText('Проверен B')).toHaveCount(0)
  await check.click()
  await expect(commit).toBeEnabled()
  await commit.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect.poll(() => committing.entered).toBe(true)
  await expect(file).toBeDisabled()
  const writes = state.writes.filter((w) => w.path.endsWith('/imports/commit'))
  expect(writes).toHaveLength(1)
  expect(writes[0].path).toBe(`${base}/imports/commit`)
  expect(writes[0].raw).toContain('filename="B.xlsx"')
  const checksum = createHash('sha256').update('exact B contents').digest('hex')
  expect(writes[0].raw).toContain(checksum)
  expect(await page.evaluate(() => window.__auditImportSubmissions)).toEqual([{
    name: 'B.xlsx', bytes: [...Buffer.from('exact B contents')], checksum,
  }])
  await finishHeld(page, committing, { created_atom_count: 1 })
  await expect(dialog).toBeHidden()
})

test('R15: late preview from case A does not enter a new import session of case B', async ({ page }) => {
  const state = makeState()
  const a = hold()
  await install(page, state, async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/imports/preview')) return false
    return a.handle(route)
  })
  await openCase(page)
  await page.getByRole('button', { name: 'Загрузить реестр атомов', exact: true }).click()
  await page.getByLabel('Excel-файл').setInputFiles({ name: 'A.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('A') })
  await page.getByRole('button', { name: 'Проверить файл' }).click()
  await expect.poll(() => a.entered).toBe(true)
  await switchCase(page, otherCaseId)
  await page.getByRole('button', { name: 'Загрузить реестр атомов', exact: true }).first().click()
  await page.getByLabel('Excel-файл').setInputFiles({ name: 'B.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('B') })
  await finishHeld(page, a, preview('Чужой preview'))
  await expect(page.getByText('Чужой preview')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Подтвердить импорт' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Проверить файл' })).toBeEnabled()
})

test('R18: filtered review completion and empty queue show scope and global remaining count', async ({ page }) => {
  const state = makeState()
  await install(page, state)
  await openCase(page, caseId, '&atomSource=registry:source-1')
  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  const dialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await dialog.getByRole('button', { name: 'Принять', exact: true }).click()
  await expect(dialog.getByRole('heading', { name: 'Очередь выбранного источника проверена' })).toBeVisible()
  await expect(dialog.getByText('Осталось по всему договору: 1.')).toBeVisible()
  await dialog.getByRole('button', { name: 'Закрыть проверку' }).click()
  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  await expect(page.getByText('В очереди выбранного источника нет непроверенных черновиков. Осталось по всему договору: 1.')).toBeVisible()
  expect(state.atoms[1].state).toBe('draft')
})

for (const theme of ['light', 'dark', 'rose']) {
  test(`G8: assignment search focus is visible in ${theme}`, async ({ page }, info) => {
    const state = makeState()
    await page.addInitScript((value) => localStorage.setItem('dpms-theme', value), theme)
    await install(page, state)
    await page.goto('/audit?view=assignments')
    await page.locator('button[title="Изменить назначенные договоры"]').first().click()
    const search = page.getByRole('textbox', { name: 'Поиск договора' })
    await search.focus()
    await expect(search).toBeFocused()
    const visual = await search.evaluate((input) => {
      const label = input.closest('label')!
      return { shadow: getComputedStyle(label).boxShadow, width: label.getBoundingClientRect().width }
    })
    expect(visual.shadow).not.toBe('none')
    expect(visual.width).toBeGreaterThan(0)
    await page.screenshot({ path: info.outputPath(`audit-assignment-focus-${theme}.png`) })
  })
}

test('G8: full model identity wraps without clipping on narrow screens', async ({ page }) => {
  const state = makeState()
  const model = `model-${'long-identifier-'.repeat(12)}distinct-suffix`
  await install(page, state, async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith('/model-registries')) return false
    await reply(route, { items: [{
      id: 'R1', case_id: caseId, provider_name: 'Провайдер', model_name: model,
      provider_config_version: 3, atom_count: 1, published_atom_count: 1,
      created_at: '2026-10-03T08:00:00Z', items: [], warnings: [], coverage_summary: {},
    }] })
    return true
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await openCase(page)
  const identity = page.getByText(`${model} · конфигурация v3`, { exact: true })
  await expect(identity).toBeVisible()
  const bounds = await identity.evaluate((element) => ({
    client: element.clientWidth, scroll: element.scrollWidth,
    overflow: getComputedStyle(element).textOverflow,
  }))
  expect(bounds.client).toBeGreaterThan(0)
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.client + 1)
  expect(bounds.overflow).not.toBe('ellipsis')
})
