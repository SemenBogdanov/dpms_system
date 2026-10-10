import { expect, test } from '@playwright/test'
import { deferred, install, project, projectA, projectB, respond, summary } from './review-projects-competencies-helpers'

test('CFI01: late portfolio summary cannot overwrite the newer project detail', async ({ page }) => {
  const old = deferred()
  let calls = 0
  let oldFinished = false
  await install(page, async (route, url) => {
    if (url.pathname !== `/api/work-entities/${projectA}/summary`) return false
    calls += 1
    if (calls === 1) {
      await old.promise
      await respond(route, summary(projectA, 0))
      oldFinished = true
      return true
    }
    return respond(route, summary(projectA, 2))
  })
  try {
    await page.goto('/work-entities')
    await expect.poll(() => calls).toBe(1)
    const portfolio = page.getByRole('region', { name: 'Обзор проектов и целей' })
    await portfolio.getByRole('button', { name: /Проект А/ }).click()
    await expect(page.locator('[aria-label="Статус выбранного проекта"]').getByText('Есть просрочка')).toBeVisible()
    old.release()
    await expect.poll(() => oldFinished).toBe(true)
    await page.goBack()
    await expect(portfolio.getByRole('button', { name: /Проект А/ })).toContainText('Есть просрочка')
    expect(calls).toBe(2)
  } finally { old.release() }
})

test('CFI02: refresh generations share a three-request portfolio summary limit', async ({ page }) => {
  const held = deferred()
  let hold = true
  let lists = 0
  let active = 0
  let peak = 0
  let started = 0
  await install(page, async (route, url) => {
    if (url.pathname === '/api/work-entities') {
      lists += 1
      return respond(route, [project(projectA), project(projectB), project('cccccccc-cccc-4ccc-8ccc-cccccccccccc')])
    }
    if (!/^\/api\/work-entities\/[^/]+\/summary$/.test(url.pathname)) return false
    started += 1
    active += 1
    peak = Math.max(peak, active)
    if (hold) await held.promise
    active -= 1
    return respond(route, summary(url.pathname.split('/')[3], 2))
  })
  try {
    await page.goto('/work-entities')
    await expect.poll(() => started).toBe(3)
    const refresh = page.getByRole('button', { name: 'Обновить сводку', exact: true })
    for (let index = 0; index < 2; index += 1) {
      await refresh.click()
      await expect.poll(() => lists).toBe(index + 2)
      await expect(refresh).toBeEnabled()
    }
    await page.waitForTimeout(250)
    expect(started).toBe(3)
    expect(peak).toBe(3)
    hold = false
    held.release()
    await expect(page.getByRole('region', { name: 'Обзор проектов и целей' }).getByText('Есть просрочка')).toHaveCount(3)
    expect(started).toBe(6)
    expect(peak).toBe(3)
  } finally { hold = false; held.release() }
})
