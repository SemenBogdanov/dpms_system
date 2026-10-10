import type { Locator, Page, Route } from '@playwright/test'
import { calibration, estimate, expect, focus, longName, operation, overdue, periodReport, reply, reviewer, test } from './review-catalog-reports-calculator-helpers'

test.use({ serviceWorkers: 'block' })

async function rendered(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

async function reachableLastColumn(region: Locator) {
  const geometry = await region.evaluate((node) => {
    const table = node.querySelector('table')!
    node.scrollLeft = node.scrollWidth
    return {
      overflow: getComputedStyle(node).overflowX,
      scrollable: node.scrollWidth > node.clientWidth,
      lastRight: table.querySelector('tbody tr td:last-child')!.getBoundingClientRect().right,
      regionRight: node.getBoundingClientRect().right,
    }
  })
  expect(geometry.overflow).toBe('auto')
  expect(geometry.scrollable).toBe(true)
  expect(geometry.lastRight).toBeLessThanOrEqual(geometry.regionRight + 2)
}

test('R07 catalog pending, failure, retry and successful empty remain distinct', async ({ page, mockApi }) => {
  const reads: Route[] = []
  mockApi.handle = async (route, url) => {
    if (url.pathname !== '/api/catalog') return false
    reads.push(route)
    return true
  }
  await page.goto('/catalog')
  await expect.poll(() => reads.length).toBe(1)
  await expect(page.getByRole('status')).toContainText('Загрузка каталога')
  await expect(page.getByText('Нет операций', { exact: true })).toHaveCount(0)
  await reply(reads[0], { detail: 'catalog unavailable' }, 503)
  await expect(page.getByRole('alert')).toContainText('catalog unavailable')
  await expect(page.getByText('Нет операций', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Повторить загрузку каталога' }).click()
  await expect.poll(() => reads.length).toBe(2)
  await reply(reads[1], [])
  await expect(page.getByText('Нет операций', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const staleStatus of [200, 503]) {
  test(`R05 catalog ignores stale success/error/finally (${staleStatus})`, async ({ page, mockApi }) => {
    const reads = new Map<string, Route>()
    mockApi.handle = async (route, url) => {
      if (url.pathname !== '/api/catalog') return false
      const search = url.searchParams.get('search')
      if (!search) return reply(route, [])
      reads.set(search, route)
      return true
    }
    await page.goto('/catalog')
    const search = page.getByRole('textbox', { name: 'Поиск по названию' })
    await search.fill('A')
    await expect.poll(() => reads.has('A')).toBe(true)
    await search.fill('B')
    await expect.poll(() => reads.has('B')).toBe(true)
    await reply(reads.get('A')!, staleStatus === 200 ? [operation('a', 'Устаревшая операция')] : { detail: 'stale catalog failure' }, staleStatus)
    await rendered(page)
    await expect(page.getByRole('status')).toContainText('Загрузка каталога')
    await expect(page.getByText('Устаревшая операция', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
    await reply(reads.get('B')!, [operation('b', 'Актуальная операция')])
    await expect(page.getByRole('cell', { name: 'Актуальная операция', exact: true })).toBeVisible()
    await search.fill('C')
    await expect.poll(() => reads.has('C')).toBe(true)
    await search.fill('D')
    await expect.poll(() => reads.has('D')).toBe(true)
    await reply(reads.get('D')!, [operation('d', 'Последняя операция')])
    await expect(page.getByRole('cell', { name: 'Последняя операция', exact: true })).toBeVisible()
    await reply(reads.get('C')!, staleStatus === 200 ? [operation('c', 'Устаревшая операция')] : { detail: 'stale catalog failure' }, staleStatus)
    await rendered(page)
    await expect(page.getByRole('cell', { name: 'Последняя операция', exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}

for (const mode of ['create', 'edit'] as const) {
  test(`R06 catalog ${mode} awaits write, retains failed draft and separates refresh failure`, async ({ page, mockApi }) => {
    const writes: Route[] = []
    let refreshFails = false
    mockApi.handle = async (route, url) => {
      if (!url.pathname.startsWith('/api/catalog')) return false
      if (route.request().method() !== 'GET') {
        writes.push(route)
        return true
      }
      return refreshFails ? reply(route, { detail: 'catalog refresh failed' }, 503) : reply(route, [operation()])
    }
    await page.goto('/catalog')
    await page.getByRole('button', { name: mode === 'create' ? /Добавить операцию/ : /Редактировать/ }).click()
    const dialog = page.getByRole('dialog')
    const name = dialog.getByRole('textbox', { name: 'Название' })
    await name.fill('Сохранённый черновик')
    await dialog.locator('form').evaluate((form: HTMLFormElement) => { form.requestSubmit(); form.requestSubmit() })
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0].request().method()).toBe(mode === 'create' ? 'POST' : 'PATCH')
    await expect(dialog).toBeVisible()
    await expect(name).toBeDisabled()
    await expect(dialog.getByRole('button', { name: 'Отмена' })).toBeDisabled()
    await reply(writes[0], { detail: 'write rejected' }, 503)
    await expect(dialog.getByRole('alert')).toContainText('write rejected')
    await expect(name).toHaveValue('Сохранённый черновик')
    await expect(name).toBeEnabled()
    await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click()
    await expect.poll(() => writes.length).toBe(2)
    refreshFails = true
    await reply(writes[1], operation())
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('alert')).toContainText('catalog refresh failed')
    await page.getByRole('button', { name: 'Повторить загрузку каталога' }).click()
    await expect(page.getByRole('alert')).toContainText('catalog refresh failed')
    expect(writes).toHaveLength(2)
    await page.getByRole('button', { name: /Добавить операцию/ }).click()
    await expect(dialog.getByRole('textbox', { name: 'Название' })).toHaveValue('')
    await expect(dialog.getByRole('alert')).toHaveCount(0)
  })
}

test('R07 calculator catalog failure has retry, not empty', async ({ page, mockApi }) => {
  let failed = true
  mockApi.handle = async (route, url) => url.pathname === '/api/catalog'
    ? reply(route, failed ? { detail: 'calculator catalog failed' } : [], failed ? 503 : 200) : false
  await page.goto('/calculator')
  await expect(page.getByRole('alert')).toContainText('calculator catalog failed')
  await expect(page.getByText('Нет операций', { exact: true })).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: 'Повторить загрузку каталога' }).click()
  await expect(page.getByText('Нет операций', { exact: true })).toBeVisible()
})

for (const mutation of ['quantity', 'add', 'remove'] as const) {
  test(`R05 estimate revision invalidated by ${mutation}`, async ({ page, mockApi }) => {
    const estimates: Route[] = []
    mockApi.handle = async (route, url) => {
      if (url.pathname !== '/api/calculator/estimate') return false
      estimates.push(route)
      return true
    }
    await page.goto('/calculator')
    await page.getByRole('button', { name: '+ Добавить', exact: true }).first().click()
    await page.getByRole('button', { name: '+ Добавить', exact: true }).nth(1).click()
    await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
    await expect.poll(() => estimates.length).toBe(1)
    if (mutation === 'quantity') await page.getByRole('spinbutton', { name: 'Количество: Операция А' }).fill('3')
    if (mutation === 'add') await page.getByRole('button', { name: '+ Добавить', exact: true }).first().click()
    if (mutation === 'remove') await page.getByRole('button', { name: 'Удалить', exact: true }).first().click()
    await reply(estimates[0], estimate)
    await rendered(page)
    await expect(page.getByRole('button', { name: 'Создать задачу', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: /Скачать расчёт/ })).toHaveCount(0)
    await expect(page.getByText('Расчёт выполнен', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
    await expect.poll(() => estimates.length).toBe(2)
    await reply(estimates[1], estimate)
    await expect(page.getByRole('button', { name: 'Создать задачу', exact: true })).toBeEnabled()
    expect(estimates[0].request().postDataJSON()).not.toEqual(estimates[1].request().postDataJSON())
  })
}

for (const staleStatus of [200, 503]) {
  test(`R05 stale estimate ${staleStatus} cannot finish the next pending calculation`, async ({ page, mockApi }) => {
    const estimates: Route[] = []
    mockApi.handle = async (route, url) => {
      if (url.pathname !== '/api/calculator/estimate') return false
      estimates.push(route)
      return true
    }
    await page.goto('/calculator')
    await page.getByRole('button', { name: '+ Добавить', exact: true }).first().click()
    await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
    await expect.poll(() => estimates.length).toBe(1)
    await page.getByRole('spinbutton', { name: 'Количество: Операция А' }).fill('2')
    await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
    await expect.poll(() => estimates.length).toBe(2)
    await reply(estimates[0], staleStatus === 200 ? estimate : { detail: 'stale estimate failure' }, staleStatus)
    await rendered(page)
    await expect(page.getByRole('button', { name: '...', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Создать задачу', exact: true })).toBeDisabled()
    await expect(page.getByText('stale estimate failure', { exact: false })).toHaveCount(0)
    await reply(estimates[1], estimate)
    await expect(page.getByRole('button', { name: 'Создать задачу', exact: true })).toBeEnabled()
  })
}

test('R09 calculator modal focus, dirty Escape, pending draft and failed retry', async ({ page, mockApi }) => {
  const creates: Route[] = []
  mockApi.handle = async (route, url) => {
    if (url.pathname === '/api/calculator/estimate') return reply(route, estimate)
    if (url.pathname === '/api/calculator/create-task') { creates.push(route); return true }
    return false
  }
  await page.goto('/calculator')
  await page.getByRole('button', { name: '+ Добавить', exact: true }).first().click()
  await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
  const opener = page.getByRole('button', { name: 'Создать задачу', exact: true })
  await expect(opener).toBeEnabled()
  await opener.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog')
  await expect.poll(() => dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(opener).toBeFocused()
  await opener.click()
  const title = dialog.getByRole('textbox', { name: 'Название задачи' })
  await title.fill('Новый черновик задачи')
  page.once('dialog', (confirmation) => confirmation.dismiss())
  await page.keyboard.press('Escape')
  await expect(title).toHaveValue('Новый черновик задачи')
  const submit = dialog.getByRole('button', { name: 'Создать и отправить в очередь', exact: true })
  await submit.focus()
  await page.keyboard.press('Tab')
  await expect(title).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(submit).toBeFocused()
  await submit.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect.poll(() => creates.length).toBe(1)
  await expect(title).toBeDisabled()
  await expect(dialog.getByRole('button', { name: 'Отмена' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await reply(creates[0], { detail: 'synthetic create failure' }, 503)
  await expect(title).toBeEnabled()
  await expect(title).toHaveValue('Новый черновик задачи')
  await dialog.getByRole('button', { name: 'Отмена' }).click()
  await opener.click()
  await expect(dialog.getByRole('textbox', { name: 'Название задачи' })).toHaveValue('')
})

test('R19 both exports follow the loaded period, including pending B', async ({ page, mockApi }) => {
  const reports = new Map<string, Route>()
  const exported: string[] = []
  mockApi.handle = async (route, url) => {
    if (/^\/api\/reports\/\d{4}-\d{2}$/.test(url.pathname)) { reports.set(url.pathname.split('/').pop()!, route); return true }
    if (url.pathname === '/api/tasks/export') {
      const period = url.searchParams.get('period')!
      exported.push(period)
      return reply(route, { period, rows: [], total_tasks: 0 })
    }
    return false
  }
  await page.goto('/reports')
  const period = page.getByRole('combobox', { name: 'Период отчёта' })
  const csv = page.getByRole('button', { name: /Экспорт CSV/ })
  const tasks = page.getByRole('button', { name: /Выгрузить задачи/ })
  await period.selectOption('2026-01')
  await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await expect.poll(() => reports.has('2026-01')).toBe(true)
  await reply(reports.get('2026-01')!, periodReport('2026-01'))
  await expect(csv).toBeEnabled()
  await expect(tasks).toBeEnabled()
  await period.selectOption('2026-02')
  await expect(csv).toBeDisabled()
  await expect(tasks).toBeDisabled()
  await expect(page.getByRole('heading', { name: 'Отчёт за 2026-01' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await expect.poll(() => reports.has('2026-02')).toBe(true)
  await expect(csv).toBeDisabled()
  await expect(tasks).toBeDisabled()
  await reply(reports.get('2026-02')!, periodReport('2026-02'))
  await expect(page.getByRole('heading', { name: 'Отчёт за 2026-02' })).toBeVisible()
  const csvDownload = page.waitForEvent('download')
  await csv.click()
  expect((await csvDownload).suggestedFilename()).toBe('dpms-report-2026-02.csv')
  const taskDownload = page.waitForEvent('download')
  await tasks.click()
  expect((await taskDownload).suggestedFilename()).toBe('dpms-tasks-2026-02.csv')
  expect(exported).toEqual(['2026-02'])
})

for (const staleStatus of [200, 503]) {
  test(`R19 late report ${staleStatus} cannot change B or clear its pending guard`, async ({ page, mockApi }) => {
    const reports = new Map<string, Route>()
    mockApi.handle = async (route, url) => {
      if (!/^\/api\/reports\/\d{4}-\d{2}$/.test(url.pathname)) return false
      reports.set(url.pathname.split('/').pop()!, route)
      return true
    }
    await page.goto('/reports')
    const period = page.getByRole('combobox', { name: 'Период отчёта' })
    await period.selectOption('2026-01')
    await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
    await expect.poll(() => reports.has('2026-01')).toBe(true)
    await period.selectOption('2026-02')
    await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
    await expect.poll(() => reports.has('2026-02')).toBe(true)
    await reply(reports.get('2026-01')!, staleStatus === 200 ? periodReport('2026-01') : { detail: 'stale report failure' }, staleStatus)
    await rendered(page)
    await expect(page.getByRole('button', { name: '...', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: /Экспорт CSV/ })).toBeDisabled()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await reply(reports.get('2026-02')!, periodReport('2026-02'))
    await expect(page.getByRole('heading', { name: 'Отчёт за 2026-02' })).toBeVisible()
  })
}

for (const staleStatus of [200, 503]) {
test(`R19 pending task export ${staleStatus} is discarded without clearing the next export`, async ({ page, mockApi }) => {
  const exports: Route[] = []
  const downloads: string[] = []
  page.on('download', (download) => downloads.push(download.suggestedFilename()))
  mockApi.handle = async (route, url) => {
    if (/^\/api\/reports\/\d{4}-\d{2}$/.test(url.pathname)) return reply(route, periodReport(url.pathname.split('/').pop()!))
    if (url.pathname === '/api/tasks/export') { exports.push(route); return true }
    return false
  }
  await page.goto('/reports')
  await page.getByRole('combobox', { name: 'Период отчёта' }).selectOption('2026-01')
  await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await page.getByRole('button', { name: /Выгрузить задачи/ }).click()
  await expect.poll(() => exports.length).toBe(1)
  await page.getByRole('combobox', { name: 'Период отчёта' }).selectOption('2026-02')
  await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
  await page.getByRole('button', { name: /Выгрузить задачи/ }).click()
  await expect.poll(() => exports.length).toBe(2)
  await reply(exports[0], staleStatus === 200 ? { period: '2026-01', rows: [], total_tasks: 0 } : { detail: 'stale export failure' }, staleStatus)
  await rendered(page)
  expect(downloads).toEqual([])
  await expect(page.getByRole('button', { name: '...', exact: true })).toBeDisabled()
  await expect(page.getByText('stale export failure', { exact: false })).toHaveCount(0)
  const download = page.waitForEvent('download')
  await reply(exports[1], { period: '2026-02', rows: [], total_tasks: 0 })
  expect((await download).suggestedFilename()).toBe('dpms-tasks-2026-02.csv')
  expect(downloads).toEqual(['dpms-tasks-2026-02.csv'])
})
}

for (const section of ['Рейтинг сотрудников', 'Сводка по сотруднику']) {
  test(`R05 report filters invalidate pending ${section}`, async ({ page, mockApi }) => {
    const reads: Route[] = []
    mockApi.handle = async (route, url) => {
      if (!['/api/reports/scorecard', '/api/reports/employee-summary'].includes(url.pathname)) return false
      reads.push(route)
      return true
    }
    await page.goto('/reports')
    const panel = page.locator('section').filter({ has: page.getByRole('heading', { name: section, exact: true }) })
    const generate = panel.getByRole('button', { name: /Сформировать/ })
    await generate.click()
    await expect.poll(() => reads.length).toBe(1)
    await panel.getByLabel('Начало', { exact: true }).fill('2026-01-01')
    await generate.click()
    await expect.poll(() => reads.length).toBe(2)
    await reply(reads[0], { detail: 'stale filtered report' }, 503)
    await rendered(page)
    await expect(panel.getByRole('button', { name: 'Формируется...' })).toBeDisabled()
    await expect(page.getByText('stale filtered report', { exact: false })).toHaveCount(0)
    await reply(reads[1], { detail: 'current report unavailable' }, 503)
    await expect(panel.getByText('current report unavailable')).toBeVisible()
    await expect(generate).toBeEnabled()
  })
}

test('R07 calibration retry retains period controls and clears error', async ({ page, mockApi }) => {
  let failed = true
  mockApi.handle = async (route, url) => url.pathname === '/api/dashboard/calibration'
    ? reply(route, failed ? { detail: 'calibration unavailable' } : calibration('Успешная калибровка'), failed ? 503 : 200) : false
  await page.goto('/calibration')
  await expect(page.getByRole('alert')).toContainText('calibration unavailable')
  await expect(page.getByRole('combobox', { name: 'Период:' })).toBeVisible()
  failed = false
  await page.getByRole('button', { name: 'Повторить загрузку калибровки' }).click()
  await expect(page.getByRole('cell', { name: 'Успешная калибровка', exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const staleStatus of [200, 503]) {
  test(`R05 calibration period switch rejects late ${staleStatus}`, async ({ page, mockApi }) => {
    const reads = new Map<string, Route>()
    mockApi.handle = async (route, url) => {
      if (url.pathname !== '/api/dashboard/calibration') return false
      reads.set(url.searchParams.get('period') ?? 'current', route)
      return true
    }
    await page.goto('/calibration')
    await expect.poll(() => reads.has('current')).toBe(true)
    await page.getByRole('combobox', { name: 'Период:' }).selectOption('all')
    await expect.poll(() => reads.has('all')).toBe(true)
    await reply(reads.get('current')!, staleStatus === 200 ? calibration('Старый период') : { detail: 'stale calibration' }, staleStatus)
    await rendered(page)
    await expect(page.getByRole('status')).toContainText('Загрузка калибровки')
    await expect(page.getByRole('alert')).toHaveCount(0)
    await reply(reads.get('all')!, calibration('Все данные'))
    await expect(page.getByRole('cell', { name: 'Все данные', exact: true })).toBeVisible()
    await expect(page.getByText('Старый период', { exact: true })).toHaveCount(0)
  })
}

test('R07 dashboard preserves focus and overdue data after secondary refresh failures', async ({ page, mockApi }) => {
  let failed = false
  mockApi.handle = async (route, url) => {
    if (url.pathname === '/api/dashboard/focus-status') return reply(route, failed ? { detail: 'focus failed' } : focus, failed ? 503 : 200)
    if (url.pathname === '/api/tasks' && url.searchParams.has('is_overdue')) return reply(route, failed ? { detail: 'overdue failed' } : overdue, failed ? 503 : 200)
    return false
  }
  await page.clock.install()
  await page.goto('/dashboard')
  await expect(page.getByText('Сотрудник в фокусе', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Просроченная работа/ })).toBeVisible()
  failed = true
  await page.clock.fastForward(30_000)
  await expect(page.getByRole('alert').filter({ hasText: 'Не удалось обновить состояние команды' })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'Не удалось обновить просроченные задачи' })).toBeVisible()
  await expect(page.getByText('Сотрудник в фокусе', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Просроченная работа/ })).toBeVisible()
  await expect(page.getByText('Нет активных исполнителей.', { exact: true })).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: 'Повторить загрузку команды' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Не удалось обновить состояние команды' })).toHaveCount(0)
  await page.clock.fastForward(30_000)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const phase of ['initial', 'refresh'] as const) {
  for (const coreStatus of [200, 503]) {
    test(`UX03 dashboard ${phase} core ${coreStatus} commits while focus/history/overdue remain pending`, async ({ page, mockApi }) => {
      let delayed = phase === 'initial'
      const core: Route[] = []
      const optional = new Map<string, Route>()
      let optionalRequests = 0
      mockApi.handle = async (route, url) => {
        if (!delayed) return false
        if (url.pathname === '/api/dashboard/capacity') { core.push(route); return true }
        if (['/api/dashboard/focus-status', '/api/dashboard/capacity-history'].includes(url.pathname) ||
            (url.pathname === '/api/tasks' && url.searchParams.has('is_overdue'))) {
          optionalRequests += 1
          optional.set(url.pathname, route)
          return true
        }
        return false
      }
      await page.clock.install()
      await page.goto('/dashboard')
      if (phase === 'refresh') {
        await expect(page.getByText('5.0 / 10.0 Q', { exact: true })).toBeVisible()
        await expect(page.getByText('Сотрудник в фокусе', { exact: true })).toBeVisible()
        delayed = true
        await page.clock.fastForward(30_000)
      }
      await expect.poll(() => core.length).toBe(1)
      await expect.poll(() => optional.size).toBe(3)
      await reply(core[0], coreStatus === 200
        ? { load: 8, capacity: 10, utilization: 80, status: 'yellow' }
        : { detail: 'core unavailable before optional settles' }, coreStatus)
      if (coreStatus === 200) {
        await expect(page.getByText('8.0 / 10.0 Q', { exact: true })).toBeVisible({ timeout: 3000 })
      } else {
        await expect(page.getByRole('alert')).toContainText('core unavailable before optional settles', { timeout: 3000 })
        if (phase === 'refresh') await expect(page.getByText('5.0 / 10.0 Q', { exact: true })).toBeVisible()
        const retry = page.getByRole('button', { name: 'Повторить загрузку дашборда' })
        await expect(retry).toBeEnabled()
        await retry.click()
        await expect.poll(() => core.length).toBe(2)
        await expect(page.getByRole('status').filter({ hasText: /основных данных/ })).toBeVisible()
        expect(optionalRequests).toBe(3)
        await reply(core[1], { load: 8, capacity: 10, utilization: 80, status: 'yellow' })
        await expect(page.getByText('8.0 / 10.0 Q', { exact: true })).toBeVisible()
        await expect(page.getByRole('alert')).toHaveCount(0)
      }
      await expect(page.getByRole('status').filter({ hasText: /основных данных/ })).toHaveCount(0)
      await expect(page.getByRole('status').filter({ hasText: 'Обновление истории ёмкости' })).toBeVisible()
      await expect(page.getByRole('status').filter({ hasText: 'Обновление состояния команды' })).toBeVisible()
      await expect(page.getByText('Нет активных исполнителей.', { exact: true })).toHaveCount(0)
      await reply(optional.get('/api/dashboard/capacity-history')!, { weeks: [] })
      await reply(optional.get('/api/dashboard/focus-status')!, focus)
      await reply(optional.get('/api/tasks')!, overdue)
      await expect(page.getByRole('status')).toHaveCount(0)
      await expect(page.getByText('8.0 / 10.0 Q', { exact: true })).toBeVisible()
    })
  }
}

test('R07 dashboard initial secondary failure is not a business empty; team link supports keyboard', async ({ page, mockApi }) => {
  mockApi.handle = async (route, url) => url.pathname === '/api/dashboard/focus-status' || (url.pathname === '/api/tasks' && url.searchParams.has('is_overdue'))
    ? reply(route, { detail: 'secondary unavailable' }, 503) : false
  await page.goto('/dashboard')
  await expect(page.getByRole('button', { name: 'Повторить загрузку команды' })).toBeVisible()
  await expect(page.getByText('Нет активных исполнителей.', { exact: true })).toHaveCount(0)
  const link = page.getByRole('link', { name: reviewer.full_name, exact: true })
  await expect(link).toHaveAttribute('href', `/profile?user_id=${reviewer.id}`)
  await link.focus()
  await expect(link).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(new RegExp(`/profile\\?user_id=${reviewer.id}`))
})

for (const width of [320, 390, 1024, 1280]) {
  test(`R12 populated catalog, calibration and report use local scrolling at ${width}`, async ({ page, mockApi }) => {
    await page.setViewportSize({ width, height: 844 })
    mockApi.handle = async (route, url) => {
      if (url.pathname === '/api/catalog') return reply(route, [operation('long', longName)])
      if (url.pathname === '/api/dashboard/calibration') return reply(route, calibration())
      if (/^\/api\/reports\/\d{4}-\d{2}$/.test(url.pathname)) return reply(route, periodReport(url.pathname.split('/').pop()!))
      return false
    }
    await page.goto('/catalog')
    await expect(page.getByRole('cell', { name: longName, exact: true })).toBeVisible()
    await reachableLastColumn(page.getByRole('region', { name: 'Операции каталога' }))
    await page.goto('/calibration')
    await expect(page.getByRole('region', { name: 'Калибровка по задачам' })).toBeVisible()
    await reachableLastColumn(page.getByRole('region', { name: 'Калибровка по задачам' }))
    await page.getByRole('button', { name: 'По оценщикам', exact: true }).click()
    await reachableLastColumn(page.getByRole('region', { name: 'Калибровка по оценщикам' }))
    await page.getByRole('button', { name: 'Популярность операций', exact: true }).click()
    await reachableLastColumn(page.getByRole('region', { name: 'Популярность операций' }))
    await page.goto('/reports')
    await page.getByRole('combobox', { name: 'Период отчёта' }).selectOption('2026-01')
    await page.getByRole('button', { name: 'Сформировать', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Команда за период' })).toBeVisible()
    await reachableLastColumn(page.getByRole('region', { name: 'Команда за период' }))
  })
}

for (const viewport of [{ width: 768, height: 500 }, { width: 1024, height: 768 }, { width: 1440, height: 1150 }, { width: 390, height: 844 }, { width: 320, height: 700 }]) {
  test(`R11 calculator and catalog dialog actions remain reachable ${viewport.width}x${viewport.height}`, async ({ page, mockApi }) => {
    await page.setViewportSize(viewport)
    mockApi.handle = async (route, url) => url.pathname === '/api/calculator/estimate' ? reply(route, estimate) : false
    for (const path of ['/catalog', '/calculator']) {
      await page.goto(path)
      if (path === '/catalog') {
        await page.getByRole('button', { name: /Добавить операцию/ }).click()
      } else {
        await page.getByRole('button', { name: '+ Добавить', exact: true }).first().click()
        await page.getByRole('button', { name: 'Рассчитать', exact: true }).click()
        await page.getByRole('button', { name: 'Создать задачу', exact: true }).click()
        await page.getByRole('button', { name: 'По критериям', exact: true }).click()
      }
      const dialog = page.getByRole('dialog')
      const cancel = dialog.getByRole('button', { name: 'Отмена', exact: true })
      const bounds = await cancel.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.y).toBeGreaterThanOrEqual(0)
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height)
      await expect.poll(() => dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
      await cancel.click()
      await expect(dialog).toHaveCount(0)
    }
  })
}
