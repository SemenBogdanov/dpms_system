import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium, webkit, expect } from '@playwright/test'

const base = 'http://localhost:5177'
const output = new URL('../../artifacts/audit-calendar/native/', import.meta.url)
await mkdir(output, { recursive: true })
const results = []
let lastLogin = 0
const dateAfter = (day, offset) => {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + offset)
  return date.toISOString().slice(0, 10)
}

async function login(page, role) {
  // Respect the real five-logins-per-minute policy across browser contexts.
  await delay(Math.max(0, 13_000 - (Date.now() - lastLogin)))
  await page.goto(`${base}/login`)
  await page.getByLabel('Email', { exact: true }).fill(`calendar.${role}@example.com`)
  await page.getByLabel('Пароль', { exact: true }).fill('Calendar-local-2026!')
  const response = page.waitForResponse(r => r.url().endsWith('/api/auth/login'))
  lastLogin = Date.now()
  await page.getByRole('button', { name: 'Войти', exact: true }).click()
  assert.equal((await response).status(), 200, `Native login: ${role}`)
  await expect(page).toHaveURL(/\/messages(?:\?|$)/)
  await expect(page.getByRole('heading', { name: 'Сообщения', exact: true })).toBeVisible()
}

async function command(page, action) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/audit-calendar/commands'))
  await action()
  const result = await response
  assert.equal(result.status(), 200, await result.text())
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
}

async function openState(page, path) {
  const response = page.waitForResponse(r => r.url().includes('/api/audit-calendar/state') && r.status() === 200)
  await page.goto(`${base}${path}`)
  const state = await (await response).json()
  await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
  return state
}

for (const [browserName, launcher] of [['chromium', chromium], ['webkit', webkit]]) {
  const browser = await launcher.launch()
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await context.route('**/*', route => {
      const url = new URL(route.request().url())
      return ['localhost', '127.0.0.1'].includes(url.hostname) ? route.continue() : route.abort()
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await login(page, 'helper')
    const stateResponse = page.waitForResponse(r => r.url().includes('/api/audit-calendar/state') && r.status() === 200)
    void stateResponse.catch(() => undefined)
    await page.goto(`${base}/audit-calendar`)
    const initial = await (await stateResponse).json()
    const from = initial.scope.today
    const day = dateAfter(from, 1)
    const path = `/audit-calendar?from=${from}&to=${dateAfter(from, 6)}`
    await page.goto(`${base}${path}`)
    await expect(page.getByRole('heading', { name: 'Сетевой план-график', exact: true })).toBeVisible()
    await expect(page.locator('.ac-bound-content')).not.toHaveAttribute('inert')
    await expect(page.getByRole('link', { name: 'Календарь аудита', exact: true })).toBeVisible()
    await expect(page.locator('.ac-scope-caption')).toContainText('Цель: Команда')
    assert.equal(initial.members.length, 5, 'This runner requires the synthetic local fixture')
    for (const [width, height] of [[1440, 900], [1920, 1080], [1024, 768], [390, 844], [320, 700]]) {
      await page.setViewportSize({ width, height })
      for (const theme of ['light', 'dark', 'rose']) {
        await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
        await expect(page.locator('.ac-content')).toBeVisible()
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${browserName}/${width}/${theme}: page overflow`)
        if (width >= 1440) {
          await expect(page.locator('.ac-desktop-graph')).toBeVisible()
          const lastHour = page.locator('.ac-graph-heading > div > span').last()
          await expect(lastHour).toHaveText('17:30')
          const box = await lastHour.boundingBox()
          assert(box && box.x + box.width <= width, 'Last desktop hour must fit')
        } else {
          await expect(page.locator('.ac-day-graph')).toBeVisible()
        }
        await page.screenshot({ path: new URL(`${browserName}-${width}-${theme}-graph.png`, output).pathname, animations: 'disabled' })
        results.push({ browser: browserName, role: 'helper', width, height, theme, path, fixture: 'calendar_local_fixture', result: 'PASS' })
      }
    }
    await page.setViewportSize({ width: 1440, height: 900 })
    const create = page.locator(`button[aria-label="Создать план ${day} 15:00"]:visible`)
    await create.click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox', { name: 'Группа', exact: true }).selectOption({ label: 'G1 · Первая группа' })
    await dialog.getByLabel('Активность', { exact: true }).fill('Нативная проверка календаря')
    await dialog.getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption({ label: 'Д1 · Докладчик Виктор' })
    await page.keyboard.press('Escape')
    await page.locator('.ac-overlay').click({ position: { x: 1, y: 1 } })
    await expect(dialog.getByLabel('Активность', { exact: true })).toHaveValue('Нативная проверка календаря')
    for (const theme of ['light', 'dark', 'rose']) {
      await page.evaluate(value => { document.documentElement.dataset.theme = value }, theme)
      assert((await dialog.locator('select').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height))).every(height => height >= 36), 'Native select controls must match input height')
      await page.screenshot({ path: new URL(`${browserName}-1440-${theme}-modal.png`, output).pathname, animations: 'disabled' })
    }
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
    await dialog.getByRole('button', { name: 'Удалить черновик', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(create).toBeFocused()

    const meetingDay = dateAfter(from, browserName === 'chromium' ? 3 : 4)
    const activity = `Проверка сохранения ${browserName}`
    const employeeId = initial.groups.find(g => g.code === 'G1').versions.at(-1).auditor_id
    if (initial.plans.some(p => p.activity === activity) && initial.availability.some(a => a.user_id === employeeId && a.date === meetingDay)) {
      await openState(page, `${path}&view=availability&availability_person=${employeeId}`)
      await command(page, () => page.getByRole('button', { name: `${meetingDay}: Очистить, весь день 00:00–24:00`, exact: true }).click())
      await openState(page, path)
    }
    const existing = page.locator('.ac-meeting:visible').filter({ hasText: activity })
    if (await existing.count()) await existing.click()
    else await page.locator(`button[aria-label="Создать план ${meetingDay} 15:00"]:visible`).click()
    await dialog.getByRole('combobox', { name: 'Группа', exact: true }).selectOption({ label: 'G1 · Первая группа' })
    await dialog.getByLabel('Активность', { exact: true }).fill(activity)
    await dialog.getByRole('combobox', { name: 'Докладчик', exact: true }).selectOption({ label: 'Д1 · Докладчик Виктор' })
    await dialog.getByLabel('Длительность, мин', { exact: true }).fill('90')
    await dialog.getByRole('combobox', { name: 'Статус', exact: true }).selectOption('planned')
    await dialog.getByLabel('Основание', { exact: true }).fill('Синтетическая сквозная проверка')
    await command(page, () => dialog.getByRole('button', { name: 'Сохранить', exact: true }).click())
    await expect(dialog).not.toBeVisible()
    let saved = await openState(page, path)
    assert.equal(saved.plans.filter(p => p.activity === activity).length, 1, '90 minutes is one plan after reload')
    assert.equal(saved.plans.find(p => p.activity === activity).duration, 90)
    results.push({ browser: browserName, role: 'helper', result: 'PASS', check: 'native 90-minute save and reload' })
    assert.deepEqual(errors, [], 'No uncaught frontend errors')

    for (const role of ['employee', 'admin', 'outsider']) {
      const context = await browser.newContext()
      const page = await context.newPage()
      await login(page, role)
      await page.goto(`${base}${path}`)
      if (role === 'employee') {
        await expect(page.getByRole('heading', { name: 'Сетевой план-график', exact: true })).toBeVisible()
        await expect(page.getByRole('link', { name: 'Управление', exact: true })).toHaveCount(0)
        await expect(page.locator('button[aria-label^="Создать план"]')).toHaveCount(0)
        await expect(page.locator('.ac-meeting:visible').filter({ hasText: activity })).toBeVisible()
        await page.getByRole('link', { name: 'Доступное время', exact: true }).click()
        const busy = page.getByRole('button', { name: `${meetingDay}: Занят, весь день 00:00–24:00`, exact: true })
        await command(page, () => busy.click())
        saved = await openState(page, `${path}&view=availability`)
        await command(page, () => page.getByRole('button', { name: `${meetingDay}: Очистить, весь день 00:00–24:00`, exact: true }).click())
        assert(saved.availability.some(a => a.user_id === saved.actor.user_id && a.date === meetingDay && a.start === 0 && a.end === 1440 && a.available === false), 'Whole-day own availability is persisted')
        results.push({ browser: browserName, role, result: 'PASS', check: 'shared saved plan and own whole-day availability' })
      } else {
        await expect(page.locator('.ac-error, [role="alert"]').first()).toBeVisible()
        await expect(page.locator('.ac-bound-content')).toHaveCount(0)
      }
      results.push({ browser: browserName, role, result: 'PASS', check: 'native login and scoped UI' })
      await context.close()
    }
    await openState(page, path)
    await page.locator('.ac-meeting:visible').filter({ hasText: activity }).click()
    await dialog.getByRole('combobox', { name: 'Статус', exact: true }).selectOption('cancelled')
    await dialog.getByLabel('Основание', { exact: true }).fill('Сквозная проверка завершена; тестовый план снят')
    await command(page, () => dialog.getByRole('button', { name: 'Сохранить', exact: true }).click())
    saved = await openState(page, path)
    assert.equal(saved.plans.find(p => p.activity === activity).status, 'cancelled')
    assert.deepEqual(errors, [], 'No uncaught frontend errors after mutations')
    await context.close()
  } catch (error) {
    console.error(`Native calendar check failed in ${browserName}:`, error.message)
    throw error
  } finally {
    await browser.close()
  }
}
await writeFile(new URL('results.json', output), JSON.stringify({ tested_at: new Date().toISOString(), base, results }, null, 2))
console.log(`PASS: ${results.length} native browser checks. Evidence: ${output.pathname}`)
