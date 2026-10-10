import { expect, test } from '@playwright/test'
import { article, fixture, stamp, user } from './review-main-helpers'

test('R17 knowledge selection follows URL and browser history', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/knowledge') return false
    await route.fulfill({ json: [article('A'), article('B')] })
    return true
  })
  await page.goto('/knowledge?article=A')
  const reader = page.locator('#knowledge-article-reader')
  await expect(reader.getByRole('heading', { name: 'Статья A' })).toBeVisible()
  await page.locator('#knowledge-article-list').getByRole('button', { name: /Статья B/ }).click()
  await expect(page).toHaveURL(/article=B/)
  await expect(reader.getByRole('heading', { name: 'Статья B' })).toBeVisible()
  await page.goBack()
  await expect(reader.getByRole('heading', { name: 'Статья A' })).toBeVisible()
})

test('R05 knowledge ignores late search response', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/knowledge') return false
    const query = url.searchParams.get('search')
    if (query === 'A') await new Promise((resolve) => setTimeout(resolve, 800))
    await route.fulfill({ json: [article(query || 'Initial')] })
    return true
  })
  await page.goto('/knowledge')
  const search = page.getByRole('searchbox', { name: 'Поиск по базе знаний' })
  const oldRequest = page.waitForRequest((req) => req.url().includes('search=A'))
  await search.fill('A')
  await oldRequest
  await search.fill('B')
  await expect(page.locator('#knowledge-article-reader').getByRole('heading', { name: 'Статья B' })).toBeVisible()
  await page.waitForTimeout(1000)
  await expect(page.locator('#knowledge-article-reader').getByRole('heading', { name: 'Статья B' })).toBeVisible()
})

test('R04 knowledge freezes submitted draft and preserves it on failure', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname === '/api/knowledge' && route.request().method() === 'GET') {
      await route.fulfill({ json: [article('A')] }); return true
    }
    if (url.pathname === '/api/knowledge/A') {
      await new Promise((resolve) => setTimeout(resolve, 650))
      await route.fulfill({ status: 503, json: { detail: 'Сбой сохранения теста' } }); return true
    }
    return false
  })
  await page.goto('/knowledge?article=A')
  await page.getByRole('button', { name: 'Редактировать', exact: true }).click()
  const dialog = page.getByRole('dialog')
  const title = dialog.getByRole('textbox', { name: 'Название', exact: true })
  await title.fill('Изменённая статья')
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(title).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Закрыть', exact: true })).toBeDisabled()
  await expect(title).toBeEnabled()
  await expect(title).toHaveValue('Изменённая статья')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true)
})

test('R05 absence filter does not accept older month response', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/absences') return false
    const start = url.searchParams.get('from') || '2026-10-01'
    if (start === '2026-05-01') await new Promise((resolve) => setTimeout(resolve, 800))
    await route.fulfill({ json: [{
      id: start, user_id: user.id, user_name: 'Период ' + start, start_date: start, end_date: start,
      type: 'vacation', affects_plan: true, working_days: 1, comment: '', created_at: stamp, updated_at: stamp,
    }] })
    return true
  })
  await page.goto('/absences')
  const month = page.getByLabel('Месяц', { exact: true })
  const oldRequest = page.waitForRequest((req) => req.url().includes('from=2026-05-01'))
  await month.fill('2026-05')
  await oldRequest
  await month.fill('2026-06')
  await expect(page.getByText('Период 2026-06-01', { exact: true }).first()).toBeVisible()
  await page.waitForTimeout(1000)
  await expect(page.getByText('Период 2026-05-01', { exact: true })).toHaveCount(0)
})

test('R04 absence pending save prevents draft replacement and supports retry', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/absences' || route.request().method() !== 'POST') return false
    await new Promise((resolve) => setTimeout(resolve, 650))
    await route.fulfill({ status: 503, json: { detail: 'Сбой сохранения отсутствия' } })
    return true
  })
  await page.goto('/absences')
  await page.getByRole('button', { name: 'Добавить отсутствие', exact: true }).click()
  const form = page.getByRole('region', { name: 'Новое отсутствие' })
  const comment = form.getByRole('textbox', { name: 'Комментарий' })
  await comment.fill('Сохранить этот черновик')
  await form.getByRole('button', { name: 'Сохранить', exact: true }).click()
  await expect(comment).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Добавить отсутствие', exact: true })).toBeDisabled()
  await expect(comment).toBeEnabled()
  await expect(comment).toHaveValue('Сохранить этот черновик')
})

test('R07 profile error leaves skeleton and allows retry', async ({ page }) => {
  let failed = true
  await fixture(page, async (route, url) => {
    const path = url.pathname
    if (path === '/api/users/' + user.id) {
      await route.fulfill(failed ? { status: 503, json: { detail: 'Профиль временно недоступен' } } : { json: user })
      return true
    }
    if (path.endsWith('/progress')) {
      await route.fulfill({ json: { percent: 0, target: 0, full_target: 0 } }); return true
    }
    if (path.endsWith('/league-progress') || path.endsWith('/run-rate')) {
      await route.fulfill({ status: 503, json: { detail: 'Вторичная метрика недоступна' } }); return true
    }
    return false
  })
  await page.goto('/profile')
  await expect(page.getByRole('alert')).toContainText('Профиль временно недоступен')
  failed = false
  await page.getByRole('button', { name: 'Повторить', exact: true }).click()
  await expect(page.getByRole('heading', { name: user.full_name, exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('UX02: publishing A preserves a newer selection B and its URL', async ({ page }) => {
  let published = false
  await fixture(page, async (route, url) => {
    if (url.pathname === '/api/knowledge') {
      await route.fulfill({ json: [{ ...article('A'), status: published ? 'published' : 'draft' }, article('B')] }); return true
    }
    if (url.pathname === '/api/knowledge/A') {
      await new Promise((resolve) => setTimeout(resolve, 650))
      published = true
      await route.fulfill({ json: { ...article('A'), status: 'published' } }); return true
    }
    return false
  })
  await page.goto('/knowledge?article=A')
  await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
  await page.locator('#knowledge-article-list').getByRole('button', { name: /Статья B/ }).click()
  await expect.poll(() => published).toBe(true)
  await expect(page.getByRole('button', { name: 'Редактировать', exact: true })).toBeEnabled()
  await expect(page).toHaveURL(/article=B/)
  await expect(page.locator('#knowledge-article-reader').getByRole('heading', { name: 'Статья B' })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(/article=A/)
})

test('UX05: clean knowledge editor closes on Escape and restores focus', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/knowledge') return false
    await route.fulfill({ json: [article('A')] }); return true
  })
  await page.goto('/knowledge?article=A')
  const trigger = page.getByRole('button', { name: 'Редактировать', exact: true })
  await trigger.focus()
  await trigger.press('Enter')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

for (const status of [200, 503]) {
  test(`UX04: pending holidays and failure ${status} are never a confirmed empty period`, async ({ page }) => {
    await fixture(page, async (route, url) => {
      if (url.pathname !== '/api/absences/holidays') return false
      await new Promise((resolve) => setTimeout(resolve, 800))
      await route.fulfill({ status, json: status === 200 ? [] : { detail: 'Праздники недоступны' } }); return true
    })
    await page.goto('/absences')
    await expect(page.getByText('Загрузка итогов периода…', { exact: true })).toBeVisible()
    await expect(page.getByText('Нет отсутствий', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Праздников: —', { exact: true })).toBeVisible()
    if (status === 503) {
      await expect(page.getByRole('alert')).toContainText('Праздники недоступны')
      await expect(page.getByText('Итоги периода недоступны', { exact: true })).toBeVisible()
      await expect(page.getByText('Нет отсутствий', { exact: true })).toHaveCount(0)
    } else {
      await expect(page.getByText('Нет отсутствий', { exact: true })).toBeVisible()
      await expect(page.getByText('Праздников: 0', { exact: true })).toBeVisible()
    }
  })
}
