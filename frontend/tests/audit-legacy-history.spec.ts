import { expect, test, type Page } from '@playwright/test'
import type { AuditAggregateTrendPoint } from '../src/api/types'

const caseId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
const sourceId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const transferId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const userId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const sourceUrl = `/audit?view=legacy-imports&batch=${sourceId}`
const importedAt = '2026-09-08T09:00:00Z'
const casePayload = {
  id: caseId, case_number: 'AUD-0001', code: 'AUD-0001', title: 'Исторический аудит',
  digital_product: 'Тестовый продукт', status: 'atomization', workflow_stage: 'alpha_review',
  atoms_count: 0, ready_atoms_count: 0, draft_atoms_count: 0, excluded_atoms_count: 0,
  alpha_passed_count: 0, commission_passed_count: 0, documents_count: 0,
  created_at: importedAt, updated_at: importedAt, atoms: [], contract_reference_revealable: false,
}

function statistics(aggregate = true) {
  return {
    date_from: '2026-09-01', date_to: '2026-09-08', undated_legacy_atoms: 2,
    trend: [
      { date: '2026-09-01', verified_count: 0, cumulative_verified_count: 1 },
      { date: '2026-09-02', verified_count: 1, cumulative_verified_count: 2 },
      { date: '2026-09-08', verified_count: 0, cumulative_verified_count: 2 },
    ],
    aggregate_trend: aggregate ? [
      { date: '2026-09-01', verified_count: 0, alpha_reviewed_count: 0, commission_reviewed_count: 0 },
      { date: '2026-09-02', verified_count: 90, alpha_reviewed_count: 70, commission_reviewed_count: 50 },
      { date: '2026-09-08', verified_count: 0, alpha_reviewed_count: 0, commission_reviewed_count: 0 },
    ] : [],
    contracts: { total: 1, in_progress: 1, alpha_review_completed: 0, alpha_commission_completed: 0, beta_commission_completed: 0 },
    atoms: { total: 4, excluded: 0, verified: 4, alpha_review_completed: 3, alpha_review_needs_work: 1,
      alpha_commission_completed: 1, alpha_commission_needs_work: 0, beta_commission_completed: 0 },
  }
}

function history() {
  const common = { case_id: caseId, atom_id: null, import_batch_id: null, payload_json: null, created_at: importedAt }
  return [
    { ...common, id: 'undated', event_type: 'legacy_atom_snapshot', message: 'Состояние из исторического реестра',
      origin: 'legacy_import', occurred_at: null, imported_at: importedAt, legacy_transfer_id: transferId,
      historical_actor_name: null, actor_id: userId, actor_name: 'Импортирующий администратор', legacy_source_url: sourceUrl },
    { ...common, id: 'dated', event_type: 'atom_status_changed', message: 'Историческая верификация',
      origin: 'legacy_import', occurred_at: '2026-09-01T21:00:00Z', imported_at: importedAt, legacy_transfer_id: transferId,
      historical_actor_name: 'Исторический исполнитель', actor_id: userId, actor_name: 'Импортирующий администратор', legacy_source_url: sourceUrl },
    { ...common, id: 'live', event_type: 'atom_status_changed', message: 'Текущая верификация',
      origin: 'live', occurred_at: '2026-09-07T09:00:00Z', imported_at: null, legacy_transfer_id: null,
      historical_actor_name: null, actor_id: userId, actor_name: 'Текущий исполнитель', legacy_source_url: null },
  ]
}

async function setup(page: Page, options: { role?: string; aggregate?: boolean; legacy?: boolean; conflicts?: number; aggregatePoints?: AuditAggregateTrendPoint[] } = {}) {
  const writes: string[] = []
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-history-fixture'))
  await page.routeWebSocket(/.*/, () => {})
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') writes.push(path)
    const reply = (value: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
    if (path === '/api/auth/me') return reply({
      id: userId, full_name: 'Участник аудита', email: 'history@example.test', role: options.role ?? 'admin',
      is_active: true, audit_enabled: true, task_workspace_enabled: true, needs_password_change: false,
      competency_development_enabled: true, feedback_enabled: true, league: 'A', mpw: 0, wip_limit: 5,
      wallet_main: 0, wallet_karma: 0, quality_score: 1,
    })
    if (path === '/api/messages/summary') return reply({ direct_count: 0, important_count: 0 })
    if (path === '/api/audit/statistics') {
      const result = statistics(options.aggregate)
      if (options.legacy === false) {
        return reply({ date_from: result.date_from, date_to: result.date_to, trend: result.trend,
          contracts: result.contracts, atoms: result.atoms })
      }
      return reply({ ...result, aggregate_trend: options.aggregatePoints ?? result.aggregate_trend,
        aggregate_conflict_count: options.conflicts ?? 0 })
    }
    if (path === '/api/audit/cases') return reply([casePayload])
    if (path === `/api/audit/cases/${caseId}`) return reply(casePayload)
    if (path === `/api/audit/cases/${caseId}/events`) return reply(options.legacy === false ? [{
      id: 'old-live', case_id: caseId, event_type: 'case_created', message: 'Создан договор', actor_name: 'Прежний исполнитель', created_at: '2026-09-01T21:00:00Z',
    }] : history())
    if (path.endsWith('/model-registries') || path.endsWith('/runs') || path.endsWith('/skills')) return reply({ items: [] })
    return reply([])
  })
  return writes
}

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => localStorage.setItem('dpms-theme', theme), info.project.name.includes('dark') ? 'dark' : 'light')
})

test('business dates, unknown legacy executor, order and permission-scoped source link', async ({ page }, info) => {
  for (const role of ['admin', 'executor', 'teamlead']) {
    const writes = await setup(page, { role })
    await page.goto(`/audit?view=case&case=${caseId}`)
    await page.getByRole('tab', { name: 'История', exact: true }).click()
    const panel = page.getByRole('tabpanel', { name: 'История', exact: true })
    const events = panel.getByTestId('audit-history-event')
    await expect(events).toHaveCount(3)
    await expect(events.nth(0)).toContainText('Текущий исполнитель')
    await expect(events.nth(1)).toContainText('Исторический исполнитель')
    await expect(events.nth(1)).toContainText('Событие: 02.09.2026, 00:00 МСК')
    await expect(events.nth(1)).toContainText('Импортировано: 08.09.2026, 12:00 МСК')
    await expect(events.nth(2)).toContainText('Дата события неизвестна')
    await expect(events.nth(2)).toContainText('Исполнитель неизвестен')
    await expect(panel).not.toContainText('Импортирующий администратор')
    await expect(panel.getByText('Исторический импорт', { exact: true })).toHaveCount(2)
    await expect(panel.getByRole('link', { name: 'Источник импорта' })).toHaveCount(role === 'admin' ? 2 : 0)
    if (role === 'admin') await expect(panel.getByRole('link', { name: 'Источник импорта' }).first()).toHaveAttribute('href', sourceUrl)
    expect(writes).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await expect(events.nth(1)).toContainText('Перенос: bbbbbbbb')
    if (role === 'admin') {
      await panel.scrollIntoViewIfNeeded()
      await panel.screenshot({ path: info.outputPath('legacy-history.png') })
    }
    await page.unrouteAll({ behavior: 'wait' })
  }
})

test('aggregate series remains separate from atoms and unknown snapshots are visible', async ({ page }, info) => {
  const writes = await setup(page)
  await page.goto('/audit?view=dashboard')
  await expect(page.getByText('Исторические атомы без даты: 2. Дата верификации неизвестна.')).toBeVisible()
  const aggregate = page.getByRole('region', { name: 'Агрегированная история', exact: true })
  await expect(aggregate).toBeVisible()
  await expect(aggregate.getByRole('img', { name: 'Агрегированная история по дням' })).toBeVisible()
  await expect(aggregate.getByText('Альфа-проверка', { exact: true })).toBeVisible()
  await expect(aggregate.getByText('Альфа-комиссия', { exact: true })).toBeVisible()
  const atoms = page.getByRole('region', { name: 'Атомы', exact: true })
  await expect(atoms.getByText('4', { exact: true }).first()).toBeVisible()
  await expect(atoms).not.toContainText('90')
  await expect(page.getByRole('img', { name: 'График подтверждённых атомов по дням и накопительным итогом' })).toBeVisible()
  await expect.poll(() => aggregate.locator('.recharts-bar-rectangle path').count()).toBeGreaterThan(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await page.screenshot({ path: info.outputPath('legacy-statistics.png'), fullPage: true })
  await aggregate.scrollIntoViewIfNeeded()
  await aggregate.screenshot({ path: info.outputPath('aggregate-series.png') })
  expect(writes).toEqual([])
})

test('live-only old response keeps history and hides aggregate/undated indicators', async ({ page }) => {
  await setup(page, { legacy: false })
  await page.goto('/audit?view=dashboard')
  await expect(page.getByRole('heading', { name: 'Статистика аудита' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Агрегированная история', exact: true })).toHaveCount(0)
  await expect(page.getByText(/Исторические атомы без даты/)).toHaveCount(0)
  await page.goto(`/audit?view=case&case=${caseId}`)
  await page.getByRole('tab', { name: 'История', exact: true }).click()
  const panel = page.getByRole('tabpanel', { name: 'История', exact: true })
  await expect(panel).toContainText('Прежний исполнитель')
  await expect(panel).toContainText('02.09.2026, 00:00 МСК')
  await expect(panel).not.toContainText('Импортировано:')
  await expect(panel.getByText('Исторический импорт', { exact: true })).toHaveCount(0)
})

test('all conflicting aggregate values stay hidden with an explicit resolution warning', async ({ page }) => {
  const writes = await setup(page, { conflicts: 2, aggregatePoints: [
    { date: '2026-09-01', verified_count: null, alpha_reviewed_count: null, commission_reviewed_count: null },
    { date: '2026-09-02', verified_count: null, alpha_reviewed_count: null, commission_reviewed_count: null },
  ] })
  await page.goto('/audit?view=dashboard')
  const aggregate = page.getByRole('region', { name: 'Агрегированная история', exact: true })
  await expect(aggregate.getByRole('alert')).toContainText('Конфликтующие показатели: 2.')
  await expect(aggregate.getByRole('alert')).toContainText('Требуется сверка с историей атомов.')
  await expect(aggregate.getByRole('img')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Атомы', exact: true }).getByText('4', { exact: true }).first()).toBeVisible()
  expect(writes).toEqual([])
})

test('aggregate gaps and partial sums are not zero while explicit zero remains visible', async ({ page }, info) => {
  const writes = await setup(page, { conflicts: 2, aggregatePoints: [
    { date: '2026-09-01', verified_count: null, alpha_reviewed_count: 11, commission_reviewed_count: null },
    { date: '2026-09-02', verified_count: 7, alpha_reviewed_count: null, commission_reviewed_count: null },
    { date: '2026-09-03', verified_count: 0, alpha_reviewed_count: null, commission_reviewed_count: null },
    { date: '2026-09-04', verified_count: null, alpha_reviewed_count: null, commission_reviewed_count: null },
  ] })
  await page.goto('/audit?view=dashboard')
  const aggregate = page.getByRole('region', { name: 'Агрегированная история', exact: true })
  await expect(aggregate.getByRole('alert')).toContainText('Затронутые дневные суммы неполны и не показаны.')
  const chart = aggregate.getByRole('img', { name: 'Агрегированная история по дням' })
  await chart.scrollIntoViewIfNeeded()
  const ticks = chart.locator('.recharts-xAxis .recharts-cartesian-axis-tick')
  await expect(ticks).toHaveCount(4)
  for (const [index, expected] of ['Нет полных данных', '7', '0', 'Нет полных данных'].entries()) {
    const tick = ticks.nth(index)
    await tick.scrollIntoViewIfNeeded()
    const tickBox = await tick.boundingBox()
    const chartBox = await chart.boundingBox()
    if (!tickBox || !chartBox) throw new Error('Aggregate chart is not laid out')
    await page.mouse.move(tickBox.x + tickBox.width / 2, chartBox.y + 80)
    const tooltip = aggregate.getByRole('tooltip')
    await expect(tooltip).toBeVisible()
    await expect(tooltip.getByText(`Верифицировано: ${expected}`, { exact: true })).toBeVisible()
    await expect(tooltip.getByText('Альфа-комиссия: Нет полных данных', { exact: true })).toBeVisible()
    if (index === 0) {
      await expect(tooltip.getByText('Альфа-проверка: 11', { exact: true })).toBeVisible()
      await aggregate.screenshot({ path: info.outputPath('aggregate-gap.png') })
    }
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  expect(writes).toEqual([])
})
