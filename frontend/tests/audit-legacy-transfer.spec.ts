import { expect, test, type Page } from '@playwright/test'
import type { LegacyBatch } from '../src/api/auditLegacy'
import type { LegacyTransfer, TransferConfig, TransferOptions, TransferPreview } from '../src/api/auditLegacyTransfer'

const root = '/api/audit/legacy-transfers'
const sourceRoot = '/api/audit/legacy-imports'
const sourceId = '11111111-1111-4111-8111-111111111111'
const transferId = '22222222-2222-4222-8222-222222222222'
const userId = '33333333-3333-4333-8333-333333333333'
const caseId = '44444444-4444-4444-8444-444444444444'
const caseRef = 'c'.repeat(64)
const actor = 'Исторический сотрудник'
const url = `/audit?view=legacy-imports&batch=${sourceId}`
const columns = [
  { column: 'A', label: 'Договор' }, { column: 'B', label: 'Продукт' }, { column: 'C', label: 'Код атома' },
  { column: 'D', label: 'Название' }, { column: 'E', label: 'Статус' }, { column: 'F', label: 'Фактическая дата' },
  { column: 'G', label: 'Сотрудник' }, { column: 'H', label: 'Количество' },
]
function source(): LegacyBatch {
  return { id: sourceId, sha256: 'a'.repeat(64), size_bytes: 2048, status: 'uploaded', revision: 1,
    created_at: '2026-09-08T10:00:00Z', updated_at: '2026-09-08T10:00:00Z', mapping: null, report: null,
    inspection: { parser_version: 'fixture', sheets: [
      { id: 'sheet-1', name: 'Исходный реестр', header_row: 1, row_count: 610, column_count: 8, formula_count: 0, columns, suggested_mapping: { kind: 'cases', fields: { case_key: 'A', digital_product: 'B' } } },
      { id: 'sheet-2', name: 'События', header_row: 2, row_count: 5, column_count: 8, formula_count: 0, columns, suggested_mapping: { kind: 'events', fields: { case_key: 'A', event_key: 'C', event_type: 'E', occurred_at: 'F' } } },
    ] },
  }
}
function configuration(): TransferConfig {
  return { namespace: 'AuditA1.9', datasets: [
    { sheet_id: 'sheet-1', header_row: 1, kind: 'cases', fields: { case_key: 'A', digital_product: 'B', contract_reference: 'A' }, defaults: {}, value_maps: {}, atom_key_mode: 'column' },
    { sheet_id: 'sheet-1', header_row: 1, kind: 'atoms', fields: { case_key: 'A', atom_key: 'C', title: 'D', state: 'E' }, defaults: {}, value_maps: {}, atom_key_mode: 'column' },
  ], cases: { [caseRef]: { mode: 'existing', target_case_id: caseId } }, actors: { [actor]: { mode: 'user', user_id: userId } }, row_decisions: {}, apply_current_assignments: false }
}
function saved(): LegacyTransfer {
  return { id: transferId, source_id: sourceId, namespace: 'AuditA1.9', status: 'draft', revision: 1, config: configuration(), preview: null, summary: {}, committed_at: null, rolled_back_at: null, created_at: '2026-09-08T10:00:00Z', updated_at: '2026-09-08T10:00:00Z' }
}
const options: TransferOptions = {
  source_id: sourceId, inspection: source().inspection,
  cases: [{ id: caseId, case_sequence: 65, title: 'Договор проверки', digital_product: 'Цифровой продукт', contract_date: null, status: 'draft' }],
  users: [{ id: userId, full_name: 'Сотрудник проверки', email: 'employee@example.test', is_active: true, audit_enabled: true, eligible_current_assignment: true }],
  kinds: ['cases', 'atoms', 'assignments', 'events', 'daily_totals'], fields: [],
  canonical_labels: { state: ['draft', 'ready', 'excluded'], previous_state: ['draft', 'ready', 'excluded'], alpha_result: ['present', 'not_present', 'partial', 'not_applicable', 'needs_clarification'], commission_result: ['confirmed', 'not_confirmed', 'deferred', 'not_applicable'], event_type: ['atom_status_changed', 'alpha_reviewed', 'commission_reviewed', 'assignment'], metric_type: ['verified', 'alpha_reviewed', 'commission_reviewed'] },
}
type State = {
  transfers: LegacyTransfer[]; role: string; calls: Array<{ method: string; path: string; body: unknown }>
  failOptions: number; failGet: number; failAction: string; failStatus: number; delay: number; lostCommit: boolean; criticalLast: boolean; rowMismatch: boolean
  holdCommit?: boolean; releaseCommit?: () => void
}
function preview(transfer: LegacyTransfer, state: State): TransferPreview {
  const missing = !transfer.config.cases[caseRef]
  const rows: TransferPreview['rows'] = Array.from({ length: 610 }, (_, index) => ({
    row_key: `${index ? 'atoms' : 'cases'}:${String(index).padStart(64, '0')}`, kind: index ? 'atoms' : 'cases',
    sheet_id: 'sheet-1', row: index + 2, source_key: String(index).padStart(64, '0'),
    outcome: missing || (state.criticalLast && index === 609) ? 'blocked' : 'create',
    target_id: index === 2 ? caseId : null,
    changes: { case_mapping_key: caseRef, source_case_mask: '***1234', source_digital_product: 'Цифровой продукт', source_title: `Строка источника ${index + 2}`, ...(index === 3 ? { actor_mapping_key: actor } : {}) },
    issues: missing && index === 0 ? [{ code: 'case_mapping_required', severity: 'error', message: 'Выберите существующий договор или создание.' }] : state.criticalLast && index === 609 ? [{ code: 'late_critical_issue', severity: 'error', message: 'Критическая ошибка строки 611' }] : [],
  }))
  return { revision: transfer.revision, preview_hash: 'b'.repeat(64), ready: !missing && !state.criticalLast, counts: { total: rows.length, errors: Number(missing) + Number(state.criticalLast), warnings: 0, create: rows.length - Number(missing) }, issues: rows[0].issues, rows, total_rows: rows.length, next_offset: null }
}
function response(transfer: LegacyTransfer) {
  return { ...transfer, preview: transfer.preview ? { ...transfer.preview, rows: transfer.preview.rows.slice(0, 500), next_offset: transfer.preview.rows.length > 500 ? 500 : null } : null }
}
async function setup(page: Page, overrides: Partial<State> = {}) {
  const state: State = { transfers: [saved()], role: 'admin', calls: [], failOptions: 0, failGet: 0, failAction: '', failStatus: 409, delay: 0, lostCommit: false, criticalLast: false, rowMismatch: false, ...overrides }
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-transfer-fixture'))
  await page.routeWebSocket(/.*/, () => {})
  await page.route('**/api/**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method()
    if (!path.startsWith('/api/')) return route.continue()
    const body: unknown = method === 'GET' ? null : request.postDataJSON()
    state.calls.push({ path, method, body })
    const reply = (data: unknown, status = 200) => route.fulfill({ json: data, status })
    if (path === '/api/auth/me') return reply({ id: userId, full_name: 'Администратор', email: 'admin@example.test', role: state.role, is_active: true, audit_enabled: true, task_workspace_enabled: true, needs_password_change: false, competency_development_enabled: true, feedback_enabled: true, league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 1 })
    if (path === '/api/messages/summary') return reply({ direct_count: 0, important_count: 0 })
    if (path === sourceRoot) return reply([source()])
    if (path === `${sourceRoot}/${sourceId}`) return reply(source())
    if (path === `${sourceRoot}/${sourceId}/source`) return route.fulfill({ body: Buffer.from('synthetic-source'), contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    if (path === `${root}/options`) return state.failOptions ? reply({ detail: 'Не удалось загрузить варианты' }, state.failOptions) : reply(options)
    if (path === root && method === 'GET') return reply(state.transfers.map(response))
    if (path === root && method === 'POST') {
      const payload = body as { source_id: string; config: TransferConfig }
      expect(payload.source_id).toBe(sourceId)
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay))
      const item = { ...saved(), config: payload.config }; state.transfers.push(item)
      return reply(response(item))
    }
    if (path.startsWith(root + '/')) {
      const [, action, subaction] = path.slice(root.length + 1).split('/')
      const item = state.transfers[0]
      if (!item) return reply({ detail: 'Перенос не найден' }, 404)
      if (method === 'GET' && !action) return state.failGet ? reply({ detail: 'Ошибка загрузки переноса' }, state.failGet) : reply(response(item))
      if (method === 'GET' && action === 'preview' && subaction === 'rows') {
        const query = new URL(request.url()).searchParams; const offset = Number(query.get('offset')); const limit = Number(query.get('limit'))
        expect(limit).toBeLessThanOrEqual(500)
        const report = item.preview!
        return reply({ revision: report.revision, preview_hash: state.rowMismatch ? 'd'.repeat(64) : report.preview_hash, rows: report.rows.slice(offset, offset + limit), total_rows: report.total_rows, next_offset: offset + limit < report.total_rows ? offset + limit : null })
      }
      if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay))
      if (state.failAction === action) { state.failAction = ''; return reply({ detail: { code: 'stale_preview', message: 'Данные изменились на сервере' } }, state.failStatus) }
      if (state.holdCommit && action === 'commit') await new Promise<void>((resolve) => { state.releaseCommit = resolve })
      const payload = body as { revision: number; config?: TransferConfig; preview_hash?: string; confirm?: boolean; reason?: string }
      expect(payload.revision).toBe(item.revision)
      if (action === 'config') { item.config = payload.config!; item.namespace = item.config.namespace; item.revision += 1; item.preview = null; item.status = 'draft' }
      if (action === 'preview') { item.preview = preview(item, state); item.status = 'previewed' }
      if (action === 'commit') {
        expect(payload).toEqual({ revision: item.revision, preview_hash: item.preview!.preview_hash, confirm: true })
        expect(item.preview!.ready).toBe(true)
        item.status = 'committed'; item.revision += 1; item.committed_at = '2026-09-08T11:00:00Z'; item.summary = { counts: item.preview!.counts }
        if (state.lostCommit) { state.lostCommit = false; return route.abort('failed') }
      }
      if (action === 'rollback') { expect(payload.confirm).toBe(true); expect(payload.reason!.trim().length).toBeGreaterThanOrEqual(3); item.status = 'rolled_back'; item.revision += 1; item.rolled_back_at = '2026-09-08T12:00:00Z' }
      return reply(response(item))
    }
    if (method !== 'GET') throw new Error(`Unexpected write: ${method} ${path}`)
    return reply([])
  })
  return state
}
async function open(page: Page, id = transferId) {
  await page.goto(`${url}&transfer=${id}`)
  await expect(page.getByLabel('Код источника')).toBeVisible()
}
async function check(page: Page) {
  await page.getByRole('button', { name: 'Проверить перенос', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Результат проверки переноса' })).toBeVisible()
}
async function commitDialog(page: Page) {
  await page.getByRole('button', { name: 'Перенести в реестр', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Перенос в рабочий реестр' })
  await expect(dialog).toBeVisible()
  return dialog
}
test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => localStorage.setItem('dpms-theme', theme), info.project.name.includes('rose') ? 'rose' : info.project.name.includes('dark') ? 'dark' : 'light')
})

test('admin entry preserves upload and source; denied roles issue no transfer calls', async ({ page }) => {
  const state = await setup(page)
  await page.goto(url)
  await expect(page.getByLabel('Исходный файл XLSX')).toBeVisible()
  await page.getByRole('button', { name: 'Настроить перенос' }).click()
  await expect(page.getByLabel('Код источника')).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Скачать исходник' }).click()
  expect((await download).suggestedFilename()).toBe('audit-legacy-source.xlsx')
  for (const role of ['employee', 'teamlead']) {
    state.role = role; state.calls = []
    await page.goto(`${url}&transfer=${transferId}`)
    await expect(page.getByRole('heading', { name: 'Доступ запрещён' })).toBeVisible()
    expect(state.calls.filter((call) => call.path.startsWith(root))).toHaveLength(0)
  }
})

test('new transfer saves, resolves opaque source case, previews and commits exact digest once', async ({ page }) => {
  const state = await setup(page, { transfers: [], delay: 100 })
  await open(page, 'new')
  await page.getByRole('button', { name: 'Сохранить настройку' }).click()
  await expect(page).toHaveURL(new RegExp(`transfer=${transferId}`))
  await check(page)
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
  await page.getByLabel('Решение исходного договора 1', { exact: true }).selectOption('create')
  await page.getByRole('button', { name: 'Сохранить настройку' }).click()
  await expect(page.getByText(/Статус: Черновик · Ревизия 2/)).toBeVisible()
  expect(state.transfers[0].config.cases[caseRef].mode).toBe('create')
  await check(page)
  const dialog = await commitDialog(page)
  await expect(dialog).toContainText('b'.repeat(64))
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Подтвердите перенос')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).evaluate((node: HTMLButtonElement) => { node.click(); node.click() })
  await expect(page.getByText('Данные перенесены в рабочий реестр.', { exact: true })).toBeVisible()
  expect(state.calls.filter((call) => call.path.endsWith('/commit'))).toHaveLength(1)
  await page.reload()
  await expect(page.getByText(/Статус: Перенесён/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
})

test('multi-dataset same sheet, ranges, duplicate field column, defaults, translations and config reload', async ({ page }) => {
  const state = await setup(page)
  await open(page)
  await page.getByLabel('Первая строка набора 2').fill('3')
  await page.getByLabel('Последняя строка набора 2').fill('610')
  await page.getByRole('group', { name: 'Набор 2: Атомы', exact: true }).getByText('Дополнительные поля набора 2', { exact: true }).click()
  const group = page.getByRole('group', { name: 'Набор 2: Атомы', exact: true })
  await group.getByLabel('По умолчанию: Статус', { exact: true }).selectOption('draft')
  await group.getByText('Переводы меток: Статус (0)', { exact: true }).click()
  const translation = group.locator('details').filter({ has: page.getByText('Переводы меток: Статус (0)', { exact: true }) }).last()
  await translation.getByLabel('Метка источника', { exact: true }).fill('Принят')
  await translation.getByLabel('Значение в реестре: Статус', { exact: true }).selectOption('ready')
  await translation.getByRole('button', { name: 'Добавить перевод: Статус', exact: true }).click()
  for (const [index, kind] of [[3, 'assignments'], [4, 'events'], [5, 'daily_totals']] as const) {
    await page.getByRole('button', { name: 'Добавить набор', exact: true }).click()
    await page.getByRole('combobox', { name: `Тип набора ${index}`, exact: true }).selectOption(kind)
  }
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('combobox', { name: 'Лист набора 4', exact: true }).selectOption('sheet-2')
  await page.getByRole('button', { name: 'Сохранить настройку', exact: true }).click()
  await expect(page.getByText('Настройка переноса сохранена.', { exact: true })).toBeVisible()
  const config = state.transfers[0].config
  expect(config.datasets.map((item) => item.kind)).toEqual(['cases', 'atoms', 'assignments', 'events', 'daily_totals'])
  expect(config.datasets[0].fields.case_key).toBe(config.datasets[0].fields.contract_reference)
  expect(config.datasets[1]).toMatchObject({ row_from: 3, row_to: 610, defaults: { state: 'draft' }, value_maps: { state: { 'Принят': 'ready' } }, atom_key_mode: 'column' })
  expect(config.apply_current_assignments).toBe(false)
  await page.reload()
  await expect(page.getByLabel('Последняя строка набора 2')).toHaveValue('610')
  await expect(page.getByRole('combobox', { name: 'Тип набора 5', exact: true })).toHaveValue('daily_totals')
})

test('all rows include critical issues beyond 500 and explicit row skip; mismatched page blocks commit', async ({ page }) => {
  const state = await setup(page, { criticalLast: true })
  await open(page); await check(page)
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Следующие строки', exact: true }).click()
  await expect(page.getByText('Строки 501–600 из 610', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Следующие строки', exact: true }).click()
  await expect(page.getByText('Строки 601–610 из 610', { exact: true })).toBeVisible()
  await page.getByRole('list', { name: 'Все строки переноса' }).getByText(/Строка 611/, { exact: false }).click()
  await expect(page.getByText('Критическая ошибка строки 611', { exact: false })).toBeVisible()
  await page.getByRole('combobox', { name: 'Решение строки 611', exact: true }).selectOption('skip')
  await page.getByRole('button', { name: 'Сохранить настройку', exact: true }).click()
  await expect(page.getByText('Настройка переноса сохранена.', { exact: true })).toBeVisible()
  expect(Object.values(state.transfers[0].config.row_decisions)).toEqual([{ action: 'skip' }])
  state.criticalLast = false
  await check(page)
  state.rowMismatch = true
  await page.getByRole('button', { name: 'Следующие строки', exact: true }).click()
  await expect(page.getByText('Результат запроса требует сверки с сервером. Повторная запись заблокирована.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
})

test('409 preserves config and requires reload plus fresh preview before committing', async ({ page }) => {
  const state = await setup(page, { failAction: 'commit' })
  await open(page); await check(page)
  const dialog = await commitDialog(page)
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Данные изменились')
  await expect(dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true })).toBeDisabled()
  page.once('dialog', (event) => event.accept())
  await dialog.getByRole('button', { name: 'Закрыть подтверждение' }).click()
  await page.getByRole('button', { name: 'Загрузить актуальный статус', exact: true }).click()
  await expect(page.getByText('Перед подтверждением выполните новую проверку переноса.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
  await check(page)
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toBeVisible()
  expect(state.calls.filter((call) => call.path.endsWith('/commit'))).toHaveLength(1)
})

test('lost commit response is recovered from durable status without resubmission', async ({ page }) => {
  const state = await setup(page, { lostCommit: true })
  await open(page); await check(page)
  const dialog = await commitDialog(page)
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await expect(dialog.getByRole('alert')).toBeVisible()
  page.once('dialog', (event) => event.accept())
  await dialog.getByRole('button', { name: 'Закрыть подтверждение' }).click()
  await page.getByRole('button', { name: 'Загрузить актуальный статус', exact: true }).click()
  await expect(page.getByText(/Статус: Перенесён/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Перенести в реестр', exact: true })).toHaveCount(0)
  expect(state.calls.filter((call) => call.path.endsWith('/commit'))).toHaveLength(1)
})

test('load failure retries and dirty navigation/back/partial translation are guarded', async ({ page }) => {
  const state = await setup(page, { failOptions: 503 })
  await page.goto(`${url}&transfer=${transferId}`)
  await expect(page.getByText('Не удалось загрузить варианты', { exact: true })).toBeVisible()
  state.failOptions = 0
  await page.getByRole('button', { name: 'Повторить загрузку переноса' }).click()
  await expect(page.getByLabel('Код источника')).toBeVisible()
  await page.getByLabel('Код источника').fill('edited')
  page.once('dialog', (event) => event.dismiss())
  await page.getByRole('button', { name: 'Вернуться к проверке файла' }).click()
  await expect(page.getByLabel('Код источника')).toHaveValue('edited')
  expect(await page.evaluate(() => !window.dispatchEvent(new Event('beforeunload', { cancelable: true })))).toBe(true)
  await page.getByRole('button', { name: 'Сохранить настройку' }).click()
  await expect(page.getByText('Настройка переноса сохранена.', { exact: true })).toBeVisible()
  const group = page.getByRole('group', { name: 'Набор 1: Договоры', exact: true })
  await group.getByText('Переводы меток: Код договора (0)', { exact: true }).click()
  await group.getByLabel('Метка источника', { exact: true }).first().fill('Незавершённый перевод')
  await page.getByRole('button', { name: 'Сохранить настройку' }).click()
  await expect(page.getByRole('alert')).toContainText('незавершённые переводы')
  page.once('dialog', (event) => event.dismiss())
  await page.getByRole('navigation', { name: 'Разделы аудита' }).getByRole('button', { name: 'Реестр', exact: true }).click()
  await expect(page).toHaveURL(/transfer=/)
})

test('confirmation traps focus, ignores Escape/backdrop, blocks navigation during request', async ({ page }) => {
  const state = await setup(page, { delay: 400 })
  await open(page); await check(page)
  const dialog = await commitDialog(page)
  await page.keyboard.press('Escape')
  await page.mouse.click(2, 2)
  await expect(dialog).toBeVisible()
  for (let index = 0; index < 8; index++) {
    await page.keyboard.press('Tab')
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  }
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Закрыть подтверждение' })).toBeDisabled()
  await page.getByRole('navigation', { name: 'Разделы аудита' }).getByRole('button', { name: 'Реестр', exact: true }).evaluate((node: HTMLButtonElement) => node.click())
  await expect(page).toHaveURL(/transfer=/)
  await expect(page.getByText(/Статус: Перенесён/)).toBeVisible()
  expect(state.calls.filter((call) => call.path.endsWith('/commit'))).toHaveLength(1)
})

test('quiet responsive themes have no overflow or console errors; screenshot evidence', async ({ page }, info) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await setup(page)
  await open(page)
  const widths = info.project.name.includes('mobile') ? [390, 320] : [1440, 1920, 1024]
  for (const width of widths) {
    await page.setViewportSize({ width, height: width === 320 ? 700 : width === 390 ? 844 : width === 1920 ? 1080 : width === 1024 ? 768 : 900 })
    await page.getByRole('heading', { name: 'Перенос в рабочий реестр', exact: true }).scrollIntoViewIfNeeded()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: info.outputPath(`transfer-${width}.png`), animations: 'disabled' })
  }
  const small = await page.getByRole('region', { name: 'Перенос в рабочий реестр', exact: true }).locator('button:visible, select:visible, input:visible:not([type="checkbox"])').evaluateAll((elements) => elements.filter((element) => element.getBoundingClientRect().height < 44).map((element) => element.outerHTML))
  expect(small).toEqual([])
  await check(page)
  const dialog = await commitDialog(page)
  await page.screenshot({ path: info.outputPath('confirmation.png'), animations: 'disabled' })
  await expect(dialog).toBeVisible()
  expect(errors).toEqual([])
})

test('committed transfer exposes protected reasoned rollback and durable rolled-back status', async ({ page }) => {
  const state = await setup(page)
  await open(page); await check(page)
  const commit = await commitDialog(page)
  await commit.getByRole('checkbox').check()
  await commit.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await page.getByRole('button', { name: 'Отменить перенос', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Откат переноса' })
  await dialog.getByRole('button', { name: 'Подтвердить откат', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Укажите причину')
  await dialog.getByLabel('Причина отката').fill('Проверка отмены исторического переноса')
  await page.keyboard.press('Escape')
  await expect(dialog.getByLabel('Причина отката')).toHaveValue('Проверка отмены исторического переноса')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить откат', exact: true }).evaluate((node: HTMLButtonElement) => { node.click(); node.click() })
  await expect(page.getByText('Перенос отменён.', { exact: true })).toBeVisible()
  const writes = state.calls.filter((call) => call.path.endsWith('/rollback'))
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toEqual({ revision: 2, reason: 'Проверка отмены исторического переноса', confirm: true })
  await page.reload()
  await expect(page.getByText(/Статус: Отменён/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Отменить перенос', exact: true })).toHaveCount(0)
})

test('integration timeout survives 27 seconds of pending commit and prevents a duplicate', async ({ page }) => {
  const state = await setup(page, { holdCommit: true })
  await open(page); await check(page)
  await page.clock.install()
  const dialog = await commitDialog(page)
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).click()
  await expect.poll(() => Boolean(state.releaseCommit)).toBe(true)
  await page.clock.runFor(27_000)
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Подтвердить перенос', exact: true }).evaluate((node: HTMLButtonElement) => node.click())
  expect(state.calls.filter((call) => call.path.endsWith('/commit'))).toHaveLength(1)
  state.releaseCommit?.()
  await expect(page.getByText(/Статус: Перенесён/)).toBeVisible()
})

test('multiple opaque case mappings use source coordinates and never require raw IDs', async ({ page }) => {
  const item = saved(); item.config.cases = {}; item.config.actors = {}
  const state = await setup(page, { transfers: [item] })
  item.preview = preview(item, state); item.status = 'previewed'
  item.preview.rows = Array.from({ length: 65 }, (_, index) => ({ ...item.preview!.rows[1], row_key: `atoms:${index}`, row: index + 2, changes: { case_mapping_key: String(index).padStart(64, '0'), source_case_mask: `***${index + 1000}`, source_digital_product: `Продукт ${index + 1}`, source_title: `Название ${index + 1}` } }))
  item.preview.total_rows = 65
  await open(page)
  await expect(page.getByRole('combobox', { name: /^Решение исходного договора / })).toHaveCount(65)
  await page.getByRole('combobox', { name: 'Решение исходного договора 1', exact: true }).selectOption('existing')
  await page.getByRole('combobox', { name: 'Договор реестра 1', exact: true }).selectOption(caseId)
  await page.getByRole('combobox', { name: 'Решение исходного договора 1', exact: true }).selectOption('create')
  await page.getByRole('button', { name: 'Сохранить настройку', exact: true }).click()
  await expect(page.getByText('Настройка переноса сохранена.', { exact: true })).toBeVisible()
  expect(item.config.cases['0'.repeat(64)]).toMatchObject({ mode: 'existing', target_case_id: caseId })
  expect(item.config.cases['1'.padStart(64, '0')]).toEqual({ mode: 'create' })
  await expect(page.getByText('0'.repeat(64), { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Код договора из источника')).toHaveCount(0)
})

test('rollback denial explains server failure and cannot be resubmitted before status reload', async ({ page }) => {
  const state = await setup(page, { failAction: 'rollback', failStatus: 409 })
  const item = state.transfers[0]; item.preview = preview(item, state); item.status = 'committed'; item.revision = 2
  await open(page)
  await page.getByRole('button', { name: 'Отменить перенос', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Откат переноса' })
  await dialog.getByLabel('Причина отката').fill('Проверка отказа')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Подтвердить откат', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Данные изменились на сервере')
  await expect(dialog.getByRole('button', { name: 'Подтвердить откат', exact: true })).toBeDisabled()
  expect(state.calls.filter((call) => call.path.endsWith('/rollback'))).toHaveLength(1)
})

test('actual backend source metadata distinguishes implicit cases without a cases dataset', async ({ page }, info) => {
  const item = saved(); item.config.cases = {}; item.config.datasets = [item.config.datasets[1]]
  const state = await setup(page, { transfers: [item] })
  item.preview = preview(item, state); item.status = 'previewed'
  item.preview.rows = [
    { ...item.preview.rows[0], sheet_id: 'config', row: null, changes: { case_mapping_key: caseRef, source_case_mask: '***1234', source_title: 'Первый исходный договор', source_digital_product: 'Платформа документов' } },
    { ...item.preview.rows[0], row_key: 'cases:' + 'e'.repeat(64), sheet_id: 'config', row: null, changes: { case_mapping_key: 'f'.repeat(64), source_case_mask: '***5678', source_title: 'Второй исходный договор', source_digital_product: 'Платформа расчётов' } },
  ]
  item.preview.total_rows = 2
  await open(page)
  const resolutions = page.getByRole('region', { name: 'Разрешение договоров и сотрудников' })
  const firstLabel = resolutions.getByRole('combobox', { name: 'Решение исходного договора 1', exact: true }).locator('..')
  const secondLabel = resolutions.getByRole('combobox', { name: 'Решение исходного договора 2', exact: true }).locator('..')
  await expect(firstLabel).toBeVisible()
  await expect(firstLabel).toContainText('***1234 · Платформа документов · Первый исходный договор')
  await expect(secondLabel).toBeVisible()
  await expect(secondLabel).toContainText('***5678 · Платформа расчётов · Второй исходный договор')
  await expect(resolutions.getByRole('combobox', { name: /^Решение исходного договора / })).toHaveCount(2)
  await expect(page.getByText('config · Строка', { exact: false })).toHaveCount(0)
  await expect(page.getByText(caseRef, { exact: true })).toHaveCount(0)
  await resolutions.scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('implicit-case-resolution.png'), animations: 'disabled' })
  await resolutions.getByRole('combobox', { name: 'Решение исходного договора 1', exact: true }).selectOption('create')
  await resolutions.getByRole('combobox', { name: 'Решение исходного договора 1', exact: true }).selectOption('existing')
  await resolutions.getByRole('combobox', { name: 'Договор реестра 2', exact: true }).selectOption(caseId)
  await page.getByRole('button', { name: 'Сохранить настройку', exact: true }).click()
  await expect(page.getByText('Настройка переноса сохранена.', { exact: true })).toBeVisible()
  expect(item.config.cases[caseRef]).toEqual({ mode: 'create' })
  expect(item.config.cases['f'.repeat(64)]).toMatchObject({ mode: 'existing', target_case_id: caseId })
})
