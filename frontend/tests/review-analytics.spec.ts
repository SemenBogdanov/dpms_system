import { expect, test } from '@playwright/test'
import { fixture, stamp, user } from './review-main-helpers'

const usage = {
  start_date: '2026-09-27', end_date: '2026-10-03', timezone: 'Europe/Moscow', login_count: 0,
  login_users: 0, section_view_count: 2, section_users: 1, first_login_at: stamp, first_section_view_at: stamp,
  sections: [{ section: 'admin-users', label: 'Пользователи', views: 2, users: 1 }],
  users: [], daily: [], logins: { total: 0, items: [] },
}

test('R21: invalid user filter recovers without an invalid API request', async ({ page }) => {
  const requests: string[] = []
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/admin/usage') return false
    requests.push(url.search)
    await route.fulfill({ json: { ...usage, users: [{ id: user.id, name: user.full_name, email: user.email, logins: 0 }] } }); return true
  })
  await page.goto('/admin/usage?usage_user=broken&usage_offset=50&keep=1')
  await expect(page.getByRole('status').filter({ hasText: 'Некорректный фильтр' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Популярные разделы' })).toBeVisible()
  await expect(page).toHaveURL(/keep=1/)
  expect(new URL(page.url()).searchParams.has('usage_user')).toBe(false)
  expect(requests.every((query) => !query.includes('user_id=') && query.includes('offset=0'))).toBe(true)
  await expect(page.getByRole('rowheader', { name: 'Администрирование: пользователи и аналитика' })).toBeVisible()
  await page.getByText('Журнал входов', { exact: true }).click()
  await page.getByRole('combobox', { name: /Сотрудник в журнале/ }).selectOption(user.id)
  await expect(page).toHaveURL(new RegExp(`usage_user=${user.id}`))
  await expect(page.getByRole('status').filter({ hasText: 'Некорректный фильтр' })).toHaveCount(0)
  await page.goBack()
  await expect(page.getByRole('combobox', { name: /Сотрудник в журнале/ })).toHaveValue('')
  await page.goForward()
  await expect(page.getByRole('combobox', { name: /Сотрудник в журнале/ })).toHaveValue(user.id)
  await expect(page.getByRole('status').filter({ hasText: 'Некорректный фильтр' })).toHaveCount(0)
})

test('R21: unsent visit survives navigation with its original id and no duplicate on reload', async ({ page }) => {
  const attempts: Array<{ section: string; event_id: string }> = []
  let failing = true
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/usage/section-views') return false
    const event = route.request().postDataJSON()
    attempts.push(event)
    await route.fulfill({ status: failing ? 503 : 200, json: {} }); return true
  })
  await page.goto('/settings')
  await expect.poll(() => attempts.length).toBeGreaterThan(0)
  const first = attempts[0]
  await page.waitForTimeout(100)
  failing = false
  await page.goto('/knowledge')
  await expect.poll(() => attempts.some((event) => event.section === 'knowledge')).toBe(true)
  expect(attempts.filter((event) => event.event_id === first.event_id).length).toBe(2)
  const count = attempts.length
  await page.reload()
  await page.waitForTimeout(500)
  expect(attempts).toHaveLength(count)
})

test('A04: server boot pagination retains focus while loading and after response', async ({ page }) => {
  await fixture(page, async (route, url) => {
    if (url.pathname !== '/api/admin/server-boots') return false
    const offset = Number(url.searchParams.get('offset') || 0)
    if (offset) await new Promise((resolve) => setTimeout(resolve, 450))
    await route.fulfill({ json: {
      period_days: 0, total: 75, all_time_count: 75, last_7_days_count: 3, first_imported_at: stamp,
      items: Array.from({ length: 25 }, (_, i) => ({ source_id: 'synthetic', event_id: String(i + offset), boot_time: stamp, recorded_at: stamp, imported_at: stamp, uptime_seconds: 12, reason: 'unknown' })),
      import_status: { state: 'ok', last_attempt_at: stamp, last_success_at: stamp, invalid_files: 0, conflicting_files: 0, checked_files: 75, error_code: null },
    } }); return true
  })
  await page.goto('/admin/users')
  const next = page.getByRole('button', { name: 'Следующие записи', exact: true })
  await next.focus()
  await expect(next).toHaveAttribute('aria-disabled', 'false')
  await next.press('Enter')
  await expect(next).toBeFocused()
  await expect(next).toHaveAttribute('aria-disabled', 'true')
  await expect(next).toHaveAttribute('aria-disabled', 'false')
  await expect(next).toBeFocused()
  await next.press('Enter')
  await expect(page.getByRole('status').filter({ hasText: '51–75 из 75' })).toBeVisible()
  await expect(next).toBeFocused()
})
