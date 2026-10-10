import { expect, test, type Page } from '@playwright/test'
import { caseId, finishHeld, hold, install, makeState, unloadProtected } from './review-audit-helpers'

declare global {
  interface Window { __auditNativePops: number }
}

type Mode = 'draft' | 'alpha' | 'comparison'
const titles: Record<Mode, string> = {
  draft: 'Проверка черновиков атомов', alpha: 'Альфа-проверка атомов', comparison: 'Сравнительный анализ моделей',
}

async function enterFromRegistry(page: Page) {
  await page.addInitScript(() => {
    window.__auditNativePops = 0
    // Observe actual history traversal before application listeners can stop it.
    window.addEventListener('popstate', event => { if (event.isTrusted) window.__auditNativePops++ })
  })
  await page.goto('/audit?view=registry')
  await page.getByRole('button', { name: 'Открыть договор', exact: true }).first().click()
  await expect(page.getByRole('button', { name: 'Редактировать договор' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`case=${caseId}`))
}

async function openReview(page: Page, mode: Mode) {
  const name = mode === 'comparison' ? 'Продолжить сравнение' : mode === 'alpha' ? 'Альфа-проверка' : 'Проверить черновики'
  await page.getByRole('button', { name, exact: true }).click()
  return page.getByRole('dialog', { name: titles[mode], exact: true })
}

async function editReview(page: Page, mode: Mode) {
  const dialog = page.getByRole('dialog', { name: titles[mode], exact: true })
  if (mode !== 'comparison') {
    const surface = dialog.locator('[tabindex="-1"]').first()
    await surface.focus()
    await surface.press(mode === 'draft' ? 'e' : 'ArrowDown')
  }
  return dialog.getByRole('textbox', {
    name: mode === 'alpha' ? 'Почему элемент не найден или требует уточнения' : 'Название атома', exact: true,
  })
}

for (const mode of ['draft', 'alpha', 'comparison'] as const) {
  test(`CI01: ${mode} cancelled internal Back preserves URL, screen and input; accepted Back leaves clean history`, async ({ page }) => {
    const state = makeState()
    if (mode === 'alpha') state.atoms.forEach(atom => { atom.state = 'ready' })
    await install(page, state)
    await enterFromRegistry(page)
    const entry = await page.evaluate(() => ({ href: location.href, index: history.state.idx, length: history.length }))
    const dialog = await openReview(page, mode)
    const field = await editReview(page, mode)
    const original = await field.inputValue()
    await field.fill('Сохранить мой несохранённый ввод')
    expect(await unloadProtected(page)).toBe(true)
    const writes = state.writes.length
    let prompts = 0
    page.once('dialog', async prompt => { prompts++; await prompt.dismiss() })
    await page.evaluate(() => history.back())
    await expect.poll(() => prompts).toBe(1)
    await expect(page).toHaveURL(entry.href)
    await expect(dialog).toBeVisible()
    await expect(field).toHaveValue('Сохранить мой несохранённый ввод')
    expect(await page.evaluate(() => ({ index: history.state.idx, length: history.length }))).toEqual({ index: entry.index, length: entry.length })
    expect(state.writes).toHaveLength(writes)

    // Inert blocks physical background clicks; exercise the router's PUSH guard too.
    page.once('dialog', async prompt => { prompts++; await prompt.dismiss() })
    await page.getByRole('button', { name: 'Реестр', exact: true, includeHidden: true }).last().evaluate((button: HTMLButtonElement) => button.click())
    await expect.poll(() => prompts).toBe(2)
    await expect(page).toHaveURL(entry.href)
    await expect(field).toHaveValue('Сохранить мой несохранённый ввод')

    page.once('dialog', async prompt => { prompts++; await prompt.accept() })
    await page.evaluate(() => history.back())
    await expect(page).toHaveURL('http://localhost:55177/audit?view=registry')
    await expect(dialog).toBeHidden()
    expect(prompts).toBe(3)
    await page.evaluate(() => history.forward())
    await expect(page).toHaveURL(entry.href)
    await openReview(page, mode)
    await expect(await editReview(page, mode)).toHaveValue(original)
    expect(await unloadProtected(page)).toBe(false)
    await page.evaluate(() => history.back())
    await expect(page).toHaveURL('http://localhost:55177/audit?view=registry')
    expect(state.writes.length).toBe(writes + (mode === 'alpha' ? 1 : 0))
    expect(state.errors).toEqual([])
    expect(state.unexpected).toEqual([])
  })

  test(`CI01: ${mode} pending internal Back is held without discarding; failure releases clean navigation`, async ({ page }) => {
    const state = makeState()
    if (mode === 'alpha') state.atoms.forEach(atom => { atom.state = 'ready' })
    const pending = hold()
    await install(page, state, async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (mode === 'comparison' ? path.endsWith('/comparison-A/commit') : request.method() === 'PATCH' && path.endsWith('/atoms/atom-1')) return pending.handle(route)
      return false
    })
    await enterFromRegistry(page)
    const href = page.url()
    const dialog = await openReview(page, mode)
    const submit = dialog.getByRole('button', { name: mode === 'comparison' ? 'Сохранить сравнение' : mode === 'alpha' ? 'Есть в системе' : 'Принять', exact: true })
    await submit.click()
    try {
      await expect.poll(() => pending.entered).toBe(true)
      expect(await unloadProtected(page)).toBe(true)
      let prompts = 0
      page.on('dialog', async prompt => { prompts++; await prompt.dismiss() })
      const pops = await page.evaluate(() => window.__auditNativePops)
      await page.evaluate(() => history.back())
      await expect.poll(() => page.evaluate(() => window.__auditNativePops)).toBe(pops + 2)
      await expect(page).toHaveURL(href)
      await expect(dialog).toBeVisible()
      await expect(submit).toBeDisabled()
      expect(prompts).toBe(0)
      await finishHeld(page, pending, { detail: 'Синтетический отказ сохранения' }, 503)
      await expect(dialog.getByText('Синтетический отказ сохранения', { exact: true })).toBeVisible()
      expect(await unloadProtected(page)).toBe(false)
      await page.evaluate(() => history.back())
      await expect(page).toHaveURL('http://localhost:55177/audit?view=registry')
      expect(prompts).toBe(0)
      expect(state.errors).toEqual([])
      expect(state.unexpected).toEqual([])
    } finally { pending.release({ detail: 'Завершение теста' }, 503) }
  })
}
