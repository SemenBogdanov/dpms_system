import { expect, test } from '@playwright/test'
import type { ReactNode } from 'react'
import { catalogItem, deferred, loadBoundary, modalBoundary, nodes, shellFixture, shellUser } from './review-shell-theme-forms-helpers'
import { install as auditFixture, makeState as auditState, openCase } from './review-audit-helpers'

test.use({ serviceWorkers: 'block' })

test('QA CI02 mobile backdrop remains clickable while the page stays inert', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shellFixture(page)
  await page.goto('/catalog')
  const trigger = page.getByRole('button', { name: 'Открыть все разделы' })
  await trigger.click()
  const menu = page.getByRole('dialog', { name: 'Разделы', exact: true })
  await expect(menu).toBeVisible()
  const main = page.locator('.app-main')
  expect(await main.evaluate((node) => Boolean(node.closest('[inert]')))).toBe(true)
  const x = page.viewportSize()!.width - 12
  const backdrop = menu.locator(':scope > [aria-hidden="true"]')
  const hit = await page.evaluate(({ x, y }) => {
    const target = document.elementFromPoint(x, y)
    return { backdrop: target?.getAttribute('aria-hidden') === 'true', inert: Boolean(target?.closest('[inert]')), main: Boolean(target?.closest('.app-main')) }
  }, { x, y: 300 })
  expect(hit).toEqual({ backdrop: true, inert: false, main: false })
  await backdrop.click({ position: { x, y: 300 } })
  await expect(menu).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect(await main.evaluate((node) => Boolean(node.closest('[inert]')))).toBe(false)
})

test('QA shared trap recovers without input events when active controls disable, hide or disappear', async ({ page }) => {
  await shellFixture(page)
  await page.goto('/catalog')
  const trigger = page.getByRole('button', { name: '+ Добавить операцию', exact: true })
  await trigger.focus()
  await trigger.press('Enter')
  const modal = page.getByRole('dialog', { name: 'Добавить операцию', exact: true })
  const name = modal.getByLabel('Название *', { exact: true })
  await expect(name).toBeFocused()
  await modal.locator('fieldset').evaluate((node: HTMLFieldSetElement) => { node.disabled = true })
  await expect.poll(() => modal.evaluate((node) => node.contains(document.activeElement) && !document.activeElement?.matches(':disabled'))).toBe(true)
  await modal.locator('button').evaluateAll((buttons) => buttons.forEach((button) => { (button as HTMLButtonElement).disabled = true }))
  await expect(modal.locator('.protected-modal-panel')).toBeFocused()
  // The dialog lives inside app-main: its background siblings, not the ancestor, must be inert.
  const background = await page.locator('.app-main').evaluate((node) =>
    Array.from(node.querySelectorAll('button, input, select, textarea, a[href], summary, [tabindex]'))
      .filter((control) => !control.closest('[role="dialog"]'))
      .map((control) => Boolean(control.closest('[inert]'))),
  )
  expect(background.length).toBeGreaterThan(0)
  expect(background.every(Boolean)).toBe(true)
  expect(await trigger.evaluate((node) => Boolean(node.closest('[inert]')))).toBe(true)
  await trigger.evaluate((node: HTMLElement) => node.focus())
  await expect(modal.locator('.protected-modal-panel')).toBeFocused()
  for (const mutation of ['remove', 'hide'] as const) {
    await modal.locator('.protected-modal-panel').evaluate((panel, action) => {
      const control = document.createElement('button')
      control.textContent = 'Временный контрол'
      panel.append(control)
      control.focus()
      if (action === 'remove') control.remove()
      else control.hidden = true
    }, mutation)
    await expect(modal.locator('.protected-modal-panel')).toBeFocused()
  }
  await modal.evaluate((node) => {
    node.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = false })
    node.querySelector<HTMLFieldSetElement>('fieldset')!.disabled = false
  })
  await page.keyboard.press('Tab')
  await expect(name).toBeFocused()
  await modal.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(trigger).toBeFocused()
  await trigger.press('Tab')
  expect(await page.locator('.app-main').evaluate((node) => Boolean(node.closest('[inert]')))).toBe(false)
})

test('QA audit summary cycle preserves focus under native WebKit Tab behavior', async ({ page }, testInfo) => {
  const state = auditState()
  await auditFixture(page, state)
  await openCase(page)
  const trigger = page.getByRole('button', { name: 'Проверить черновики' })
  await trigger.focus()
  await trigger.press('Enter')
  const modal = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await modal.getByRole('button', { name: 'Закрыть диалог' }).focus()
  const trace: unknown[] = []
  let summaryReached = false
  try {
    for (let i = 0; i < 18; i += 1) {
      const before = await modal.evaluate((node) => ({
        active: document.activeElement?.outerHTML.slice(0, 400),
        controls: Array.from(node.querySelectorAll<HTMLElement>('button, input, textarea, select, summary, [tabindex]')).map((control) => ({
          tag: control.tagName, tabIndex: control.tabIndex, disabled: control.matches(':disabled'),
          visible: Boolean(control.getClientRects().length), text: control.textContent?.slice(0, 50),
        })),
      }))
      await page.keyboard.press('Tab')
      const focus = await modal.evaluate((node) => ({
        inside: node.contains(document.activeElement), summary: document.activeElement?.tagName === 'SUMMARY',
        active: document.activeElement?.outerHTML.slice(0, 400),
      }))
      trace.push({ step: i, before, after: focus })
      expect(focus.inside).toBe(true)
      summaryReached ||= focus.summary
    }
    expect(summaryReached).toBe(true)
    await modal.getByRole('button', { name: 'Закрыть диалог' }).click()
    await expect(trigger).toBeFocused()
    expect(state.writes.filter((write) => write.method === 'PATCH')).toEqual([])
  } finally {
    await testInfo.attach('focus-cycle', { body: JSON.stringify(trace, null, 2), contentType: 'application/json' })
  }
})

test('R08 desktop hidden sidebar is inert and has a keyboard entry', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await shellFixture(page, { pinned: false })
  await page.goto('/catalog')
  const sidebar = page.locator('#app-sidebar')
  const trigger = page.getByRole('button', { name: 'Открыть боковую панель' })
  await expect(sidebar).toHaveAttribute('inert', '')
  let triggerReached = false
  for (let i = 0; i < 22; i += 1) {
    await page.keyboard.press('Tab')
    expect(await sidebar.evaluate((node) => node.contains(document.activeElement))).toBe(false)
    triggerReached ||= await trigger.evaluate((node) => node === document.activeElement)
  }
  expect(triggerReached).toBe(true)
  await trigger.focus()
  await page.keyboard.press('Enter')
  await expect(sidebar).toBeFocused()
  await page.keyboard.press('Tab')
  const pin = sidebar.getByRole('button', { name: 'Закрепить боковую панель' })
  await expect(pin).toBeFocused()
  await page.mouse.move(1200, 400)
  await expect(sidebar).toBeVisible()
  await page.keyboard.press('Tab')
  const tasks = sidebar.getByRole('button', { name: 'Задачи', exact: true })
  await expect(tasks).toBeFocused()
  await page.keyboard.press('Tab')
  expect(await sidebar.evaluate((node) => node.contains(document.activeElement) && document.activeElement?.tagName === 'A')).toBe(true)
  await page.keyboard.press('Shift+Tab')
  await expect(tasks).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(pin).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(trigger).toBeFocused()
  await expect(sidebar).toHaveAttribute('inert', '')
  await trigger.press('Enter')
  await expect(sidebar).toBeFocused()
  await sidebar.getByRole('button', { name: 'Выйти', exact: true }).focus()
  await page.keyboard.press('Tab')
  expect(await sidebar.evaluate((node) => node.contains(document.activeElement))).toBe(false)
  await expect(sidebar).toHaveAttribute('inert', '')
  await trigger.focus()
  await trigger.press('Enter')
  await expect(sidebar).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await expect(sidebar).toHaveAttribute('inert', '')
})

test('R08 mobile drawer traps focus, closes on Escape and Back, and restores trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shellFixture(page)
  await page.goto('/catalog')
  const trigger = page.getByRole('button', { name: 'Открыть все разделы' })
  await trigger.click()
  const menu = page.getByRole('dialog', { name: 'Разделы', exact: true })
  const close = menu.getByRole('button', { name: 'Закрыть меню' })
  await expect(close).toBeFocused()
  for (let i = 0; i < 30; i += 1) {
    await page.keyboard.press(i % 2 ? 'Shift+Tab' : 'Tab')
    expect(await menu.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  }
  expect(await page.locator('.app-main').evaluate((node) => Boolean(node.closest('[inert]')))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await expect(page.locator('#app-sidebar')).toHaveAttribute('inert', '')
  expect(await page.locator('.app-main').evaluate((node) => Boolean(node.closest('[inert]')))).toBe(false)
  await page.getByRole('link', { name: 'Заметки', exact: true }).click()
  await trigger.click()
  await page.goBack()
  await expect(page).toHaveURL(/\/catalog$/)
  await expect(menu).toHaveCount(0)
})

for (const storageFailure of ['read', 'write'] as const) {
  test(`R10 ${storageFailure} refusal does not crash theme or pin controls`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await shellFixture(page, { storageFailure })
    await page.goto('/catalog')
    for (const [name, theme] of [['Темная тема', 'dark'], ['Розовая тема', 'rose'], ['Светлая тема', 'light']]) {
      await page.getByRole('button', { name, exact: true }).click()
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    }
    await page.getByRole('button', { name: 'Открепить боковую панель' }).click()
    await expect(page.getByRole('button', { name: 'Закрепить боковую панель' })).toBeVisible()
    await page.getByRole('button', { name: 'Закрепить боковую панель' }).click()
    await expect(page.getByRole('heading', { name: 'Каталог операций' })).toBeVisible()
    expect(errors).toEqual([])
  })
}

for (const size of [{ width: 768, height: 500 }, { width: 1024, height: 768 }, { width: 1440, height: 1150 }, { width: 390, height: 844 }, { width: 320, height: 700 }]) {
  test(`R09 R11 catalog framing and labels ${size.width}x${size.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(size)
    await shellFixture(page)
    await page.goto('/catalog')
    const trigger = page.getByRole('button', { name: '+ Добавить операцию', exact: true })
    await trigger.focus()
    await trigger.press('Enter')
    const modal = page.getByRole('dialog', { name: 'Добавить операцию', exact: true })
    const name = modal.getByLabel('Название *', { exact: true })
    await expect(name).toBeFocused()
    for (const label of ['Категория', 'Сложность', 'Стоимость (Q) *', 'Мин. лига', 'Порядковый номер', 'Описание']) {
      await expect(modal.getByLabel(label, { exact: true })).toHaveCount(1)
    }
    await name.fill('Черновик')
    await page.keyboard.press('Escape')
    await expect(name).toHaveValue('Черновик')
    const geometry = await modal.evaluate((overlay) => {
      const panel = overlay.querySelector('.protected-modal-panel')!
      const formBody = panel.querySelector('fieldset')!.parentElement!
      const rect = panel.getBoundingClientRect()
      const button = Array.from(panel.querySelectorAll('button')).find((node) => node.type === 'submit')!.getBoundingClientRect()
      return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, buttonBottom: button.bottom, overflow: getComputedStyle(formBody).overflowY }
    })
    expect(geometry.top).toBeGreaterThanOrEqual(0)
    expect(geometry.bottom).toBeLessThanOrEqual(size.height)
    expect(geometry.buttonBottom).toBeLessThanOrEqual(size.height)
    expect(geometry.left).toBeGreaterThanOrEqual(0)
    expect(geometry.right).toBeLessThanOrEqual(size.width)
    expect(geometry.overflow).toBe('auto')
    await modal.getByRole('button', { name: 'Сохранить', exact: true }).focus()
    await page.keyboard.press('Tab')
    await expect(name).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(modal.getByRole('button', { name: 'Сохранить', exact: true })).toBeFocused()
    await page.screenshot({ path: testInfo.outputPath(`catalog-${size.width}.png`) })
    await modal.getByRole('button', { name: 'Отмена', exact: true }).click()
    await expect(trigger).toBeFocused()
  })
}

test('R09 catalog awaits rejected write, retains input and allows a deliberate retry', async ({ page }) => {
  const first = deferred()
  let count = 0
  await shellFixture(page, { write: async (route) => {
    if (new URL(route.request().url()).pathname !== '/api/catalog') return route.fulfill({ status: 409, json: {} })
    count += 1
    if (count === 1) {
      await first.promise
      return route.fulfill({ status: 422, json: { detail: 'Проверка отклонена' } })
    }
    return route.fulfill({ json: catalogItem })
  } })
  await page.goto('/catalog')
  await page.getByRole('button', { name: '+ Добавить операцию', exact: true }).click()
  const modal = page.getByRole('dialog', { name: 'Добавить операцию', exact: true })
  const name = modal.getByLabel('Название *', { exact: true })
  await name.fill('   ')
  await modal.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(modal.getByRole('alert')).toContainText('Название обязательно')
  await name.fill('Черновик после отказа')
  await modal.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(name).toBeDisabled()
  await expect(modal.getByRole('button', { name: 'Отмена', exact: true })).toBeDisabled()
  await expect.poll(() => modal.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await modal.locator('form').evaluate((form) => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await expect.poll(() => count).toBe(1)
  first.resolve()
  await expect(modal.getByRole('alert')).toContainText('Проверка отклонена')
  await expect(name).toHaveValue('Черновик после отказа')
  await expect(name).toBeEnabled()
  await modal.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(modal).toHaveCount(0)
  expect(count).toBe(2)
})

test('R09 summary participates in the native modal Tab order without closing on Escape', async ({ page }) => {
  const writes = await shellFixture(page)
  await page.goto('/personal-tasks')
  await page.getByRole('button', { name: 'Новая задача', exact: true }).click()
  const modal = page.getByRole('dialog', { name: 'Новая личная задача' })
  const summary = modal.locator('summary').filter({ hasText: 'Дополнительно' })
  let reached = false
  for (let i = 0; i < 16; i += 1) {
    if (await summary.evaluate((node) => node === document.activeElement)) { reached = true; break }
    await page.keyboard.press('Tab')
  }
  expect(reached).toBe(true)
  await page.keyboard.press('Space')
  await expect(summary.locator('..')).toHaveAttribute('open', '')
  await page.keyboard.press('Tab')
  expect(await modal.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(modal).toBeVisible()
  expect(writes.filter((write) => !write.path.startsWith('/api/usage/'))).toEqual([])
})

test('R09 R11 UserModal labels and footer remain reachable at short height', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 768, height: 500 })
  await shellFixture(page, { theme: 'dark' })
  await page.goto('/admin/users')
  await expect(page.getByRole('heading', { name: 'Сотрудники', exact: true })).toBeVisible()
  const trigger = page.getByRole('button', { name: 'Добавить сотрудника', exact: true })
  await trigger.focus()
  await trigger.press('Enter')
  const modal = page.getByRole('dialog', { name: 'Добавить сотрудника', exact: true })
  for (const label of ['Роль', 'Лига', 'План (MPW)']) await expect(modal.getByLabel(label, { exact: true })).toHaveCount(1)
  const box = await modal.getByRole('button', { name: 'Создать', exact: true }).boundingBox()
  expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height).toBeLessThanOrEqual(500)
  await page.screenshot({ path: testInfo.outputPath('user-short-dark.png') })
  await modal.getByRole('button', { name: 'Отмена', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Добавить сотрудника', exact: true })).toBeFocused()
})

test('R11 long TagInput values and suggestions retain reachable remove control', async ({ page }) => {
  const long = 'ОченьДлинныйРусскийТег'.repeat(30).toUpperCase()
  await page.setViewportSize({ width: 320, height: 700 })
  await shellFixture(page, { tags: [long] })
  await page.goto('/calculator')
  await page.getByRole('button', { name: '+ Добавить', exact: true }).click()
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
  await page.getByRole('button', { name: 'Создать задачу', exact: true }).click()
  const input = page.getByRole('textbox', { name: 'Новый тег', exact: true })
  const tagPanel = input.locator('../..')
  const suggestion = page.getByRole('button', { name: long, exact: true })
  const suggestionBox = await suggestion.boundingBox()
  expect(suggestionBox!.width).toBeLessThanOrEqual(320)
  await suggestion.click()
  const remove = page.getByRole('button', { name: `Удалить тег ${long}`, exact: true })
  await remove.scrollIntoViewIfNeeded()
  const dimensions = await tagPanel.evaluate((node) => ({ width: node.clientWidth, scroll: node.scrollWidth }))
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width + 1)
  await remove.click()
  await expect(remove).toHaveCount(0)
  await input.fill('IME')
  await input.evaluate((node) => node.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })))
  await expect(input).toHaveValue('IME')
  await input.press('Enter')
  await expect(page.getByRole('button', { name: 'Удалить тег IME', exact: true })).toBeVisible()
})

for (const theme of ['light', 'dark', 'rose'] as const) {
  test(`R13 ${theme}: primary selection, composite status colors, focus and invalid border`, async ({ page }) => {
    await shellFixture(page, { theme })
    await page.goto('/catalog')
    const selected = page.getByRole('group', { name: 'Выбор темы' }).locator('[aria-pressed="true"]')
    const before = await selected.evaluate((node) => ({ color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor }))
    await selected.hover()
    const after = await selected.evaluate((node) => ({ color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor }))
    expect(after).toEqual(before)
    expect(before.color).not.toBe(before.background)
    expect(await selected.getAttribute('class')).not.toContain('text-gray-500')
    const ratios = await page.evaluate(() => {
      const samples = [
        'bg-emerald-100 text-emerald-800', 'bg-red-100 text-red-800', 'bg-blue-100 text-blue-800',
        'bg-amber-50/60 text-amber-950', 'bg-violet-100 text-violet-800', 'bg-rose-50/70 text-rose-900',
        'bg-slate-50/80 text-slate-800',
      ]
      const parent = document.createElement('div')
      parent.className = 'bg-white'
      document.body.append(parent)
      const rgb = (value: string) => value.match(/[\d.]+/g)!.map(Number)
      const luminance = (channels: number[]) => channels.slice(0, 3).map((n) => {
        const c = n / 255
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
      }).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0)
      const result = samples.map((classes) => {
        const sample = document.createElement('span')
        sample.className = classes
        sample.textContent = 'Статус'
        parent.append(sample)
        const chain: Element[] = []
        for (let node: Element | null = sample; node; node = node.parentElement) chain.unshift(node)
        const composite = chain.reduce((background, node) => {
          const color = rgb(getComputedStyle(node).backgroundColor)
          const alpha = color[3] ?? 1
          return background.map((c, i) => color[i] * alpha + c * (1 - alpha))
        }, [255, 255, 255])
        const foreground = luminance(rgb(getComputedStyle(sample).color))
        const background = luminance(composite)
        return { classes, contrast: (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05) }
      })
      const input = document.createElement('input')
      input.id = 'review-focus-sample'
      input.className = 'outline-none border border-slate-300'
      input.setAttribute('aria-invalid', 'true')
      parent.append(input)
      return result
    })
    for (const result of ratios) expect(result.contrast, result.classes).toBeGreaterThanOrEqual(4.5)
    const input = page.locator('#review-focus-sample')
    await page.keyboard.press('Tab')
    await input.focus()
    await expect(input).toHaveCSS('outline-style', 'solid')
    if (theme !== 'light') {
      const invalid = await input.evaluate((node) => getComputedStyle(node).borderColor)
      await input.evaluate((node) => node.setAttribute('aria-invalid', 'false'))
      expect(await input.evaluate((node) => getComputedStyle(node).borderColor)).not.toBe(invalid)
    }
  })
}

test('A06 single direct and important markers have distinct persistent shapes', async ({ page }) => {
  const shapes: string[] = []
  for (const summary of [{ direct_count: 1, important_count: 0 }, { direct_count: 0, important_count: 1 }]) {
    await page.unrouteAll({ behavior: 'ignoreErrors' })
    await shellFixture(page, { summary })
    await page.goto('/catalog')
    const marker = page.locator('#app-sidebar span[aria-label^="Непросмотрено:"]').first()
    await expect(marker.locator('svg')).toHaveCount(1)
    shapes.push(await marker.locator('svg').innerHTML())
  }
  expect(shapes[0]).not.toBe(shapes[1])
})

type PreferenceBoundary = { readPreference(name: string): string | null; writePreference(name: string, value: string): void }

test('R10 source boundary: throwing getter and stale disk after write failure use memory', () => {
  const blocked = loadBoundary<PreferenceBoundary>('preferenceStorage', {}, {
    window: { get localStorage() { throw new Error('Synthetic getter denial') } },
  })
  expect(blocked.readPreference('theme')).toBeNull()
  blocked.writePreference('theme', 'rose')
  expect(blocked.readPreference('theme')).toBe('rose')
  const failedWrite = loadBoundary<PreferenceBoundary>('preferenceStorage', {}, {
    window: { localStorage: { getItem: () => 'light', setItem: () => { throw new Error('Synthetic quota') } } },
  })
  expect(failedWrite.readPreference('theme')).toBe('light')
  failedWrite.writePreference('theme', 'dark')
  expect(failedWrite.readPreference('theme')).toBe('dark')
})

for (const kind of ['CatalogModal', 'UserModal'] as const) {
  for (const outcome of ['success', 'error'] as const) {
    test(`R09 source boundary: ${kind} stale ${outcome}/finally cannot close or unlock a new session`, async () => {
      const runtime = modalBoundary(kind)
      const a = deferred()
      const b = deferred()
      let writes = 0
      let closes = 0
      const save = () => ++writes === 1 ? a.promise : b.promise
      const props = kind === 'CatalogModal'
        ? { item: { ...catalogItem, name: 'A' }, isOpen: true, onSave: save, onClose: () => closes++ }
        : { initial: { ...shellUser, full_name: 'A' }, mode: 'edit', open: true, onSubmit: save, onClose: () => closes++ }
      const formSubmit = (tree: ReactNode) => nodes(tree).find((node) => node.type === 'form')!.props.onSubmit as (event: { preventDefault(): void }) => Promise<void>
      const submitA = formSubmit(runtime.render(props))
      const pendingA = submitA({ preventDefault() {} })
      await submitA({ preventDefault() {} })
      expect(writes).toBe(1)
      runtime.render({ ...props, isOpen: false, open: false })
      const next = kind === 'CatalogModal'
        ? { ...props, item: { ...catalogItem, id: 'new-session', name: 'B' }, isOpen: true }
        : { ...props, initial: { ...shellUser, id: 'new-session', full_name: 'B' }, open: true }
      const pendingB = formSubmit(runtime.render(next))({ preventDefault() {} })
      if (outcome === 'success') a.resolve()
      else a.reject(new Error('Ошибка A'))
      await pendingA
      let tree = runtime.render(next)
      expect(closes).toBe(0)
      expect(nodes(tree).find((node) => node.type === 'fieldset')!.props.disabled).toBe(true)
      expect(nodes(tree).filter((node) => node.props.role === 'alert')).toHaveLength(0)
      b.reject(new Error('Ошибка B'))
      await pendingB
      tree = runtime.render(next)
      expect(nodes(tree).find((node) => node.type === 'fieldset')!.props.disabled).toBe(false)
      expect(nodes(tree).find((node) => node.props.role === 'alert')!.props.children).toBe('Ошибка B')
      expect(nodes(tree).find((node) => node.type === 'input' && node.props.type === 'text')!.props.value).toBe('B')
      expect(writes).toBe(2)
      runtime.unmount()
    })
  }
}
