import { expect, test, type Page, type Route } from '@playwright/test'
import type { LegacyBatch, LegacyKind, LegacyMapping, LegacyReport } from '../src/api/auditLegacy'

const root = '/api/audit/legacy-imports'
const routeUrl = '/audit?view=legacy-imports'
const firstId = '11111111-1111-4111-8111-111111111111'
const secondId = '22222222-2222-4222-8222-222222222222'
const columns = [
  { column: 'A', label: 'Договор' }, { column: 'B', label: 'Продукт' },
  { column: 'C', label: 'Код' }, { column: 'D', label: 'Название' },
  { column: 'E', label: 'Дата' }, { column: 'F', label: 'Тип' },
  { column: 'G', label: 'Email' }, { column: 'H', label: 'Значение' },
]
function batch(id = firstId): LegacyBatch {
  return {
    id, sha256: (id === firstId ? 'a' : 'b').repeat(64), size_bytes: 2048,
    status: 'uploaded', created_at: '2026-09-06T10:00:00Z', updated_at: '2026-09-06T10:00:00Z', revision: 1,
    inspection: { parser_version: 'fixture-1', sheets: [
      { id: 'sheet-1', name: 'Исходный реестр', row_count: 45, column_count: 8, formula_count: 2, header_row: 1, columns, suggested_mapping: { kind: 'cases', fields: { case_key: 'A', digital_product: 'B' } } },
      { id: 'sheet-2', name: 'Атомы', row_count: 12, column_count: 8, formula_count: 0, header_row: 2, columns, suggested_mapping: { kind: 'atoms', fields: { case_key: 'A', atom_key: 'C', title: 'D' } } },
    ] }, mapping: null, report: null,
  }
}
function report(mapping: LegacyMapping): LegacyReport {
  return {
    ...mapping, total_rows: 44, valid_rows: 40, error_rows: 2, warning_rows: 1, duplicate_rows: 1,
    issue_count: 2, issues: [
      { row: 3, column: 'A', code: 'missing_case', severity: 'error', message: 'Не указан договор' },
      { row: 4, column: 'B', code: 'duplicate', severity: 'warning', message: 'Повторяющаяся строка' },
    ],
    preview_rows: Array.from({ length: 35 }, (_, index) => ({ row: index + 2, values: { case_key: `AUD-${index + 1}`, digital_product: 'Цифровой продукт с длинным названием', atom_key: null } })),
    columns, unmapped_columns: ['H'], ready_for_import: false,
  }
}
type State = {
  batches: LegacyBatch[]
  listed: string[] | null
  requests: Array<{ path: string; method: string; body: string | null }>
  uploads: number
  checks: Array<{ revision: number; mapping: LegacyMapping }>
  deletes: number
  failUpload: number
  failCheck: number
  failGet: number
  failList: number
  failDelete: number
  delay: number
  delayGet: string
  serverMessage: string
  role: string
}
const states = new WeakMap<Page, State>()
async function setup(page: Page, options: Partial<State> = {}) {
  const state: State = {
    batches: [batch(), batch(secondId)], listed: null, requests: [], uploads: 0, checks: [], deletes: 0,
    failUpload: 0, failCheck: 0, failGet: 0, failList: 0, failDelete: 0, delay: 0, delayGet: '', serverMessage: 'Ошибка проверки источника', role: 'admin', ...options,
  }
  states.set(page, state)
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-audit-legacy-fixture'))
  await page.routeWebSocket(/.*/, () => {})
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    const method = request.method()
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    state.requests.push({ path, method, body: method === 'POST' && path === root ? null : request.postData() })
    if (path === '/api/auth/me') return reply({
      id: 'fixture-user', full_name: 'Администратор проверки', email: 'fixture@example.test', role: state.role,
      is_active: true, audit_enabled: true, task_workspace_enabled: true, needs_password_change: false,
      competency_development_enabled: true, feedback_enabled: true, league: 'A', mpw: 0, wip_limit: 5,
      wallet_main: 0, wallet_karma: 0, quality_score: 1,
    })
    if (path === '/api/messages/summary') return reply({ direct_count: 0, important_count: 0 })
    if (path === root && method === 'GET') {
      if (state.failList) return reply({ detail: state.serverMessage }, 503)
      return reply(state.batches.filter((item) => !state.listed || state.listed.includes(item.id)))
    }
    if (path === root && method === 'POST') {
      state.uploads += 1
      expect(request.headers()['content-type']).toContain('multipart/form-data; boundary=')
      expect(request.postDataBuffer()?.toString()).toContain('name="file"')
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay))
      if (state.failUpload) { const status = state.failUpload; state.failUpload = 0; return reply({ detail: state.serverMessage }, status) }
      const result = state.batches[0] || batch()
      if (!state.batches.length) state.batches.push(result)
      return reply(result)
    }
    if (path.startsWith(root + '/')) {
      const [id, action] = path.slice(root.length + 1).split('/')
      const item = state.batches.find((value) => value.id === id)
      if (!item) return reply({ detail: 'Сохранённый файл не найден' }, 404)
      if (method === 'GET' && !action) {
        const snapshot = structuredClone(item)
        if (state.delayGet === id) await new Promise((resolve) => setTimeout(resolve, 450))
        if (state.failGet) return reply({ detail: state.serverMessage }, state.failGet)
        return reply(snapshot)
      }
      if (method === 'GET' && action === 'source') return route.fulfill({ contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body: Buffer.from('synthetic-source'), headers: { 'Content-Disposition': 'attachment; filename="source.xlsx"' } })
      if (method === 'PUT' && action === 'mapping') {
        const body = request.postDataJSON() as { revision: number; mapping: LegacyMapping }
        state.checks.push(body)
        if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay))
        if (state.failCheck) { const status = state.failCheck; state.failCheck = 0; return reply({ detail: state.serverMessage }, status) }
        if (body.revision !== item.revision) return reply({ detail: 'Ревизия изменилась' }, 409)
        item.mapping = body.mapping; item.report = report(body.mapping); item.revision += 1; item.status = 'checked'
        return reply(item)
      }
      if (method === 'DELETE' && !action) {
        state.deletes += 1
        expect(url.searchParams.get('revision')).toBe(String(item.revision))
        if (state.failDelete) { const status = state.failDelete; state.failDelete = 0; return reply({ detail: state.serverMessage }, status) }
        state.batches = state.batches.filter((value) => value.id !== id)
        return route.fulfill({ status: 204 })
      }
      return reply({ detail: 'Unexpected staging request' }, 400)
    }
    if (method !== 'GET') return reply({ detail: 'Unexpected target write' }, 400)
    return reply([])
  })
  return state
}
async function openBatch(page: Page, id = firstId) {
  await page.goto(`${routeUrl}&batch=${id}`)
  await expect(page.getByLabel('Лист', { exact: true })).toBeVisible()
}
async function uploadFile(page: Page, name = 'history.xlsx', size = 20) {
  await page.getByLabel('Исходный файл XLSX').setInputFiles({ name, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.alloc(size, 65) })
}
test.beforeEach(async ({ page }, info) => {
  const theme = info.project.name.includes('rose') ? 'rose' : info.project.name.includes('dark') ? 'dark' : 'light'
  await page.addInitScript((value) => localStorage.setItem('dpms-theme', value), theme)
})
test.afterEach(async ({ page }) => {
  const state = states.get(page)
  const writes = state?.requests.filter((request) => request.method !== 'GET') || []
  expect(writes.every((request) => request.path === root || request.path.startsWith(root + '/'))).toBe(true)
})

test('admin navigation and nonadmin deep-link denial preserve existing controls', async ({ page }) => {
  const state = await setup(page)
  await page.goto('/audit?view=registry')
  const nav = page.getByRole('navigation', { name: 'Разделы аудита' })
  for (const name of ['Новый документ', 'Статистика', 'Реестр', 'Назначения', 'Сотрудники', 'Исторический импорт']) await expect(nav.getByRole('button', { name, exact: true })).toBeVisible()
  await nav.getByRole('button', { name: 'Исторический импорт' }).click()
  await expect(page).toHaveURL(/view=legacy-imports/)
  for (const role of ['teamlead', 'employee']) {
    state.role = role; state.requests = []
    await page.goto(`${routeUrl}&batch=${firstId}`)
    await expect(page.getByRole('heading', { name: 'Доступ запрещён' })).toBeVisible()
    await expect(nav.getByRole('button', { name: 'Исторический импорт' })).toHaveCount(0)
    await expect(page.getByLabel('Исходный файл XLSX')).toHaveCount(0)
    expect(state.requests.filter((request) => request.path.startsWith(root))).toHaveLength(0)
  }
})

test('upload staging only, deduplicate, guard double POST and restore selected URL', async ({ page }) => {
  const state = await setup(page, { delay: 250, batches: [] })
  await page.goto(routeUrl)
  await expect(page.getByLabel('Сохранённые файлы')).toContainText('Нет сохранённых файлов')
  await uploadFile(page)
  await page.getByRole('button', { name: 'Загрузить файл', exact: true }).evaluate((node: HTMLButtonElement) => { node.click(); node.click() })
  await expect(page.getByText('Файл сохранён для проверки. Рабочий реестр не изменён.', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`batch=${firstId}`))
  expect(state.uploads).toBe(1)
  await uploadFile(page)
  await page.getByRole('button', { name: 'Загрузить файл', exact: true }).click()
  await expect.poll(() => state.uploads).toBe(2)
  await expect(page.getByRole('button', { name: 'Загрузить файл', exact: true })).toBeEnabled()
  expect(state.batches).toHaveLength(1)
  await page.reload()
  await expect(page.getByLabel('Лист', { exact: true })).toHaveValue('sheet-1')
  await expect(page.getByRole('button', { name: /Импортировать|Перенести в реестр|Подтвердить импорт/ })).toHaveCount(0)
})

test('XLSX size/type validation and server failure retain selected file', async ({ page }) => {
  const state = await setup(page, { failUpload: 422 })
  await page.goto(routeUrl)
  for (const [name, size] of [['source.csv', 20], ['empty.xlsx', 0], ['oversize.xlsx', 10 * 1024 * 1024 + 1]] as const) {
    await uploadFile(page, name, size)
    await page.getByRole('button', { name: 'Загрузить файл', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('не более 10 МиБ')
  }
  expect(state.uploads).toBe(0)
  await uploadFile(page)
  await page.getByRole('button', { name: 'Загрузить файл', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(state.serverMessage)
  expect(await page.getByLabel('Исходный файл XLSX').evaluate((input: HTMLInputElement) => input.files?.[0]?.name)).toBe('history.xlsx')
  await page.getByRole('button', { name: 'Загрузить файл', exact: true }).click()
  await expect(page.getByLabel('Лист', { exact: true })).toBeVisible()
})

test('mapping required fields, header validation, report max30 and refresh persistence', async ({ page }, info) => {
  const state = await setup(page, { delay: 250 })
  await openBatch(page)
  await page.getByLabel('Код договора').selectOption('')
  await page.getByLabel('Строка заголовков').fill('0')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByText('Укажите целый номер строки от 1 до 1048576.')).toBeVisible()
  await expect(page.getByText('Выберите столбец.', { exact: true })).toBeVisible()
  expect(state.checks).toHaveLength(0)
  await page.getByLabel('Код договора').selectOption('A')
  await page.getByLabel('Строка заголовков').fill('2')
  await page.getByText('Дополнительные поля', { exact: true }).click()
  await page.getByLabel('Дата договора', { exact: true }).selectOption('E')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).evaluate((node: HTMLButtonElement) => { node.click(); node.click() })
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks).toHaveLength(1)
  expect(state.checks[0]).toEqual({ revision: 1, mapping: { sheet_id: 'sheet-1', header_row: 2, kind: 'cases', fields: { case_key: 'A', digital_product: 'B', contract_date: 'E' } } })
  await expect(page.getByRole('region', { name: 'Предпросмотр строк' }).locator('tbody tr')).toHaveCount(30)
  await expect(page.getByRole('region', { name: 'Предпросмотр строк' }).getByRole('cell', { name: 'AUD-1', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Предпросмотр строк' }).getByRole('columnheader')).toHaveCount(4)
  await expect(page.getByRole('list', { name: 'Замечания проверки' })).toContainText('Не указан договор')
  await expect(page.getByText('Дубликаты', { exact: true })).toBeVisible()
  await page.getByText('Дополнительные поля', { exact: true }).click()
  await page.getByRole('heading', { name: 'Результат проверки' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('report.png'), animations: 'disabled' })
  await page.getByRole('region', { name: 'Предпросмотр строк' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('preview.png'), animations: 'disabled' })
  await page.reload()
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('2')
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  await page.getByLabel('Строка заголовков').fill('3')
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toHaveCount(0)
  await expect(page.getByText('Сопоставление изменено.', { exact: false })).toBeVisible()
})

test('all five dataset kinds expose mandatory fields and optional mapping', async ({ page }) => {
  const state = await setup(page)
  await openBatch(page)
  const cases: Array<[LegacyKind, Record<string, string>]> = [
    ['cases', { 'Код договора': 'A', 'Цифровой продукт': 'B' }],
    ['atoms', { 'Код договора': 'A', 'Код атома': 'C', 'Название атома': 'D' }],
    ['assignments', { 'Код договора': 'A', 'Email ответственного': 'G', 'Дата назначения': 'E' }],
    ['events', { 'Код договора': 'A', 'Код события': 'C', 'Тип события': 'F', 'Дата события': 'E' }],
    ['daily_totals', { 'Код договора': 'A', 'Дата показателя': 'E', 'Тип показателя': 'F', 'Значение': 'H' }],
  ]
  for (const [kind, fields] of cases) {
    await page.getByLabel('Набор данных').selectOption(kind)
    for (const [label, column] of Object.entries(fields)) {
      await expect(page.getByLabel(label + ' *', { exact: true })).toBeVisible()
      await page.getByLabel(label + ' *', { exact: true }).selectOption(column)
    }
    await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
    await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
    expect(state.checks.at(-1)?.mapping.kind).toBe(kind)
  }
  await page.getByLabel('Лист', { exact: true }).selectOption('sheet-2')
  await expect(page.getByLabel('Набор данных')).toHaveValue('atoms')
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('2')
  await expect(page.getByLabel('Название атома')).toHaveValue('D')
})

test('409 preserves mapping, requires explicit reload and uses fresh revision', async ({ page }) => {
  const state = await setup(page)
  await openBatch(page)
  await page.getByLabel('Строка заголовков').fill('3')
  state.batches[0].revision = 2
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('alert')).toContainText('Ваше сопоставление сохранено в форме')
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('3')
  await expect(page.getByRole('button', { name: 'Проверить сопоставление' })).toBeDisabled()
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('button', { name: 'Загрузить актуальную ревизию' }).click()
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('3')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Загрузить актуальную ревизию' }).click()
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('1')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks.at(-1)?.revision).toBe(2)
})

test('new header columns arrive through partial mapping report; issue display capped at500', async ({ page }) => {
  const state = await setup(page)
  await openBatch(page)
  await page.getByLabel('Код договора').selectOption('')
  await page.getByLabel('Строка заголовков').fill('3')
  await page.route(`${root}/${firstId}/mapping`, async (route) => {
    const body = route.request().postDataJSON() as { revision: number; mapping: LegacyMapping }
    state.checks.push(body)
    const checked = state.batches[0]
    checked.mapping = body.mapping; checked.revision += 1; checked.status = 'checked'
    checked.report = {
      ...report(body.mapping),
      columns: columns.map((column) => ({ ...column, label: `Новый заголовок ${column.column}` })),
      error_rows: 44, valid_rows: 0, issue_count: 650,
      issues: Array.from({ length: 550 }, () => ({ row: null, column: null, code: 'missing_field', severity: 'error', message: 'Сопоставьте обязательное поле case_key' })),
    }
    await route.fulfill({ json: checked })
  })
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks[0].mapping.fields).toEqual({ digital_product: 'B' })
  await expect(page.getByLabel('Код договора').locator('option[value="A"]')).toHaveText('A · Новый заголовок A')
  await expect(page.getByRole('list', { name: 'Замечания проверки' }).locator('li')).toHaveCount(500)
  await expect(page.getByText('Показано 500 из 650 замечаний.')).toBeVisible()
  await page.getByLabel('Код договора').selectOption('A')
  await expect(page.getByRole('button', { name: 'Проверить сопоставление' })).toBeEnabled()
})

test('data row count is not the maximum header row number', async ({ page }) => {
  const first = batch()
  first.inspection.sheets[0].row_count = 1
  first.inspection.sheets[0].header_row = 2
  first.inspection.sheets[1].row_count = 5
  first.inspection.sheets[1].header_row = 10
  const state = await setup(page, { batches: [first] })
  await openBatch(page)
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('2')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks[0].mapping.header_row).toBe(2)
  await page.getByLabel('Лист', { exact: true }).selectOption('sheet-2')
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('10')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks[1].mapping.header_row).toBe(10)
})

test('untrusted server, sheet and report content render only as text; retry keeps draft', async ({ page }) => {
  const payload = '<img src=x onerror="window.auditInjected=true">'
  const first = batch()
  first.inspection.sheets[0].name = payload
  const state = await setup(page, { batches: [first], failCheck: 422, serverMessage: payload })
  await openBatch(page)
  await page.getByLabel('Строка заголовков').fill('3')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('alert')).toContainText(payload)
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('3')
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  const result = state.batches[0].report!
  result.preview_rows[0].values.case_key = payload; result.issues[0].message = payload
  await page.reload()
  await expect(page.getByRole('region', { name: 'Предпросмотр строк' })).toContainText(payload)
  expect(await page.evaluate(() => 'auditInjected' in window)).toBe(false)
  await expect(page.locator('img[src="x"]')).toHaveCount(0)
})

test('unsaved navigation guard covers audit nav, batch change, browser Back and reload', async ({ page }) => {
  await setup(page)
  await page.goto(routeUrl)
  await expect(page.getByLabel('Сохранённые файлы').locator('option')).toHaveCount(3)
  await page.getByLabel('Сохранённые файлы').selectOption(firstId)
  await page.getByLabel('Строка заголовков').fill('2')
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('navigation', { name: 'Разделы аудита' }).getByRole('button', { name: 'Реестр', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`batch=${firstId}`))
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByLabel('Сохранённые файлы').selectOption(secondId)
  await expect(page.getByLabel('Сохранённые файлы')).toHaveValue(firstId)
  const dialog = page.waitForEvent('dialog')
  await page.evaluate(() => window.history.back())
  await (await dialog).dismiss()
  await expect(page).toHaveURL(new RegExp(`batch=${firstId}`))
  await expect(page.getByLabel('Строка заголовков')).toHaveValue('2')
  expect(await page.evaluate(() => !window.dispatchEvent(new Event('beforeunload', { cancelable: true })))).toBe(true)
  page.once('dialog', (event) => event.accept())
  await page.getByRole('navigation', { name: 'Разделы аудита' }).getByRole('button', { name: 'Реестр', exact: true }).click()
  await expect(page).toHaveURL(/view=registry/)
})

test('missing-list deep link loads independently, not-found retries, stale selection ignored', async ({ page }) => {
  const state = await setup(page, { listed: [secondId], failGet: 503 })
  await page.goto(`${routeUrl}&batch=${firstId}`)
  await expect(page.getByRole('alert')).toContainText(state.serverMessage)
  state.failGet = 0
  await page.getByRole('button', { name: 'Повторить загрузку' }).click()
  await expect(page.getByLabel('Лист', { exact: true })).toBeVisible()
  state.listed = null; state.delayGet = secondId
  await page.getByRole('button', { name: 'Обновить список файлов' }).click()
  await page.getByLabel('Сохранённые файлы').selectOption(secondId)
  await page.getByLabel('Сохранённые файлы').selectOption(firstId)
  await expect(page.getByLabel('Лист', { exact: true })).toBeVisible()
  await page.waitForTimeout(500)
  await expect(page.getByText('SHA-256: ' + 'a'.repeat(64), { exact: true })).toBeVisible()
  await page.goto(`${routeUrl}&batch=missing`)
  await expect(page.getByRole('alert')).toContainText('Сохранённый файл не найден')
  await expect(page.getByRole('button', { name: 'Проверить сопоставление' })).toHaveCount(0)
})

test('download generic source and confirm staging deletion, server failure leaves batch', async ({ page }) => {
  const state = await setup(page, { failDelete: 503 })
  await openBatch(page)
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Скачать исходник' }).click()
  expect((await downloaded).suggestedFilename()).toBe('audit-legacy-source.xlsx')
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.getByRole('button', { name: 'Удалить сохранённый файл', exact: true }).click()
  expect(state.deletes).toBe(0)
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Удалить сохранённый файл', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(state.serverMessage)
  await expect(page.getByLabel('Лист', { exact: true })).toBeVisible()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Удалить сохранённый файл', exact: true }).click()
  await expect(page).not.toHaveURL(/batch=/)
  await expect(page.getByText('Сохранённый файл удалён. Рабочий реестр не изменён.', { exact: true })).toBeVisible()
  expect(state.batches.map((item) => item.id)).toEqual([secondId])
})

test('inflight write blocks navigation and edits until response; list failure is recoverable', async ({ page }) => {
  const state = await setup(page, { delay: 600, failList: 1 })
  await openBatch(page)
  await expect(page.getByRole('alert')).toContainText(state.serverMessage)
  state.failList = 0
  await page.getByRole('button', { name: 'Обновить список файлов' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: 'Проверить сопоставление' }).click()
  await page.getByRole('navigation', { name: 'Разделы аудита' }).getByRole('button', { name: 'Реестр', exact: true }).click()
  await expect(page).toHaveURL(/view=legacy-imports/)
  await expect(page.getByLabel('Строка заголовков')).toBeDisabled()
  await expect(page.getByRole('heading', { name: 'Результат проверки' })).toBeVisible()
  expect(state.checks).toHaveLength(1)
})

test('responsive themes, labelled 44px controls and screenshots without page overflow', async ({ page }, info) => {
  const first = batch()
  first.inspection.sheets[0].name = 'ОченьДлинноеНазваниеИсторическогоИсточника'.repeat(8)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await setup(page, { batches: [first] })
  await openBatch(page)
  const widths = info.project.name.includes('mobile') ? [390, 320] : [1440, 1920, 1024]
  for (const width of widths) {
    const height = width === 320 ? 700 : width === 390 ? 844 : width === 1920 ? 1080 : width === 1024 ? 768 : 900
    await page.setViewportSize({ width, height })
    await page.getByRole('heading', { name: 'Исторический импорт', exact: true }).scrollIntoViewIfNeeded()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const section = page.getByRole('region', { name: 'Исторический импорт', exact: true })
    const tooSmall = await section.locator('button:visible, input:visible, select:visible').evaluateAll((elements) => elements.filter((element) => element.getBoundingClientRect().height < 44).map((element) => element.outerHTML))
    expect(tooSmall).toEqual([])
    await page.screenshot({ path: info.outputPath(`staging-${width}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: 'Проверить сопоставление' }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath(`mapping-${width}.png`), animations: 'disabled' })
  }
  expect(errors).toEqual([])
})
