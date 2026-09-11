import { expect, test, type Page } from '@playwright/test'
import type { AuditAtomProvenance, AuditAIModelRegistry, AuditAtomizationSkillVersion, AuditTZRun } from '../src/api/types'

const caseId = '22222222-2222-4222-8222-222222222222'
const userId = '11111111-1111-4111-8111-111111111111'
const date = '2026-09-08T09:00:00Z'
const base = `/api/audit/cases/${caseId}`
const refs = [{ source_unit_id: 'U000001', locator: 'Раздел 2.1', excerpt: 'Система должна сохранять предложения.' }]

function skill(id: string, format: AuditAtomizationSkillVersion['package_format'], name: string): AuditAtomizationSkillVersion {
  return {
    id, skill_id: `method-${id}`, slug: id, name, description: null, version: id === 'rules' ? `sha256-${'b'.repeat(64)}` : '2.0', schema_version: '1.0',
    content_sha256: id === 'rules' ? 'b'.repeat(64) : 'c'.repeat(64), source_filename: `${id}.skill`,
    package_format: format, package_manifest: {}, runtime_status: 'ready', runtime_ready: true,
    runtime_checked_at: null, runtime_error_code: null, runtime_selftest: {}, is_trusted_archive: format === 'trusted_skill_archive',
    is_enabled: true, is_active: true, created_at: date, activated_at: date,
  }
}

function registry(id: string, skillId: string, name: string, count: number, published: number): AuditAIModelRegistry {
  return {
    id, case_id: caseId, canonical_run_id: `run-${skillId}`, provider_config_id: `provider-${id}`,
    provider_config_version: 3, provider_name: `Провайдер ${id}`, model_name: `model-${id}`, atom_count: count,
    document_id: 'doc-1', document_sha256: 'a'.repeat(64), document_created_at: date,
    skill_version_id: skillId, skill_name: name, skill_slug: skillId, skill_version: skillId === 'rules' ? `sha256-${'b'.repeat(64)}` : '2.0', skill_sha256: 'b'.repeat(64),
    published_atom_count: published, coverage_summary: {}, warnings: [], created_at: date,
    items: Array.from({ length: count }, (_, i) => ({ id: `${id}-item-${i + 1}`, title: 'Одинаковое предложение', digital_product: 'Продукт', work_type: null, object_type: null, source_clause: '2.1', notes: null, confidence_percent: null, sort_order: i, source_refs: refs })),
  }
}

function origin(reg: AuditAIModelRegistry, item = 1): AuditAtomProvenance {
  return { ...reg, kind: 'ai', label: `ИИ · ${reg.skill_name}`, source_register_id: reg.id, source_register_created_at: date, registry_item_id: `${reg.id}-item-${item}` }
}

function atom(id: string, origins: AuditAtomProvenance[], state: 'ready' | 'draft' = 'draft') {
  return {
    id, case_id: caseId, item_code: id, title: id.startsWith('AI') ? 'Одинаковое предложение' : `Атом ${id}`,
    digital_product: 'Продукт', source_clause: '2.1', state, provenance: origins,
    work_type: 'Разработка', object_type: 'Экран', source_refs_json: refs,
    alpha_result: null, created_at: date, updated_at: date,
  }
}

async function setup(page: Page, options: { lateStage?: boolean; delayPreview?: boolean; legacyPending?: boolean } = {}) {
  const registries = [registry('R1', 'rules', 'Основная методика', 2, 2), registry('R2', 'json', 'Другая методика', 1, 1), registry('R3', 'rules', 'Старый результат', 1, 0)]
  const atoms = [
    atom('HIST', [{ kind: 'historical_import', label: 'Архив 2020', source_sheet: 'Лист 1', source_row: 9, historical_effective_at: '2020-01-02T09:00:00Z' }], 'ready'),
    atom('REGISTER', [{ kind: 'manual_register', label: 'Реестр аудитора', source_row: 12 }], 'ready'),
    atom('MANUAL', [{ kind: 'manual', label: 'Создан аудитором' }], 'ready'),
    atom('AI1', [origin(registries[0])]),
    atom('AI2', [origin(registries[0], 2), origin(registries[1])]),
    atom('UNKNOWN', []),
  ]
  const skills = [skill('rules', 'declarative_archive', 'Основная методика'), skill('json', 'declarative_json', 'Другая методика'), skill('trusted', 'trusted_skill_archive', 'Runtime методика')]
  const runs: AuditTZRun[] = []
  const writes: Array<{ path: string; body: Record<string, unknown> | null }> = []
  const errors: string[] = []
  const external: string[] = []
  const comparisons: unknown[] = []
  let comparison: Record<string, unknown> | null = null
  let holdPreview = options.delayPreview ?? false
  let releasePreview: (() => void) | undefined
  const documents = [1, 2].map((n) => ({ id: `doc-${n}`, case_id: caseId, kind: 'technical_spec', display_name: `ТЗ ${n}.docx`, original_filename: `spec-${n}.docx`, content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', size_bytes: 512, sha256: (n === 1 ? 'a' : 'd').repeat(64), created_at: date }))
  documents.push({ ...documents[0], id: 'doc-pdf', display_name: 'ТЗ.pdf', original_filename: 'spec.pdf', content_type: 'application/pdf' })
  const legacyAttempt = { id: 'legacy-attempt', case_id: caseId, document_id: 'doc-pdf', skill_version_id: 'json', skill_name: 'Другая методика', skill_version: '1.0', status: 'draft_ready',
    config_version: 4, provider_config_id: 'A', provider_name: 'Профиль A', model_name: 'model-A', document_sha256: 'a'.repeat(64), skill_sha256: 'c'.repeat(64), coverage_summary: {}, warnings: [], error_code: null,
    drafts: [{ ...registries[0].items[0], id: 'legacy-draft', review_status: 'pending' }], created_at: date, committed_at: null }
  const payload = () => ({
    id: caseId, case_number: 'AUD-0001', code: 'AUD-0001', title: 'Аудит источников', digital_product: 'Продукт',
    status: 'atomization', workflow_stage: options.lateStage ? 'alpha_review' : 'atomization',
    responsible_user_id: userId, atoms_count: atoms.length, ready_atoms_count: atoms.filter((a) => a.state === 'ready').length,
    draft_atoms_count: atoms.filter((a) => a.state === 'draft').length, excluded_atoms_count: 0,
    alpha_passed_count: 0, commission_passed_count: 0, documents_count: 2, contract_reference_revealable: false,
    contract_reference_mask: null, created_at: date, updated_at: date, atoms,
  })
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-audit-provenance'))
  await page.routeWebSocket(/.*/, () => {})
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (url.hostname !== '127.0.0.1') { external.push(url.hostname); return route.abort() }
    if (!path.startsWith('/api/')) return route.continue()
    const method = request.method()
    const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (method !== 'GET' && !path.startsWith('/api/client-events')) writes.push({ path, body: request.headers()['content-type']?.includes('application/json') && request.postData() ? request.postDataJSON() : null })
    if (path === '/api/auth/me') return reply({ id: userId, full_name: 'Аудитор', email: 'audit@example.test', role: 'admin', is_active: true, audit_enabled: true, task_workspace_enabled: true, needs_password_change: false, league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 1 })
    if (path === '/api/messages/summary') return reply({ direct_count: 0, important_count: 0 })
    if (path === '/api/audit/cases') return reply([payload()])
    if (path === base) return reply(payload())
    if (path === `${base}/documents`) return reply(documents)
    if (path === `${base}/events`) return reply([])
    if (path === `${base}/model-registries`) return reply({ items: registries })
    if (path === `${base}/ai-atomization/attempts`) return reply(method === 'GET' ? options.legacyPending ? [legacyAttempt] : [] : legacyAttempt)
    if (path === `${base}/ai-atomization/privacy-preview`) return reply({ privacy_token: 'synthetic-legacy-consent', expires_at: '2026-09-09T09:00:00Z', provider_name: 'Профиль A', model_name: 'model-A', pseudonym: 'DOC', identifier_count: 1, replacement_count: 1, source_unit_count: 1, character_count: 100, outbound_fields: [], samples: [], payload_sha256: 'e'.repeat(64), warnings: [] })
    if (path === `${base}/ai-atomization/attempts/legacy-attempt/commit`) {
      atoms.push(atom('LEGACY-DRAFT', [{ kind: 'ai', provider_name: 'Профиль A', model_name: 'model-A', skill_name: 'Другая методика', skill_version: '1.0' }]))
      return reply({ attempt_id: 'legacy-attempt', case_id: caseId, atoms_created: 1, atom_ids: ['LEGACY-DRAFT'], already_committed: false })
    }
    if (path === `${base}/model-comparisons`) {
      if (method === 'GET') return reply(comparisons)
      const ids = request.postDataJSON().registry_ids as string[]
      const selected = registries.filter((reg) => ids.includes(reg.id))
      comparison = { id: 'comparison-1', case_id: caseId, canonical_run_id: 'run-rules', status: 'draft_ready', config_version: 1, review_only: true,
        registry_ids: ids, registry_snapshot: selected.map((reg) => ({ ...reg, registry_id: reg.id, provider_config_version: 9 })), created_at: date, committed_at: null,
        drafts: [{ id: 'draft-1', title: 'Сопоставленное предложение', digital_product: 'Продукт', work_type: '', object_type: '', source_clause: '2.1', notes: null,
          confidence_percent: null, agreement_count: 2, registry_count: 2, review_status: 'pending', sort_order: 0, source_refs: refs,
          model_variants: selected.map((reg) => ({ registry_id: reg.id, registry_item_id: `${reg.id}-item-1`, provider_name: reg.provider_name, model_name: reg.model_name, title: 'Вариант модели', skill_version_id: reg.skill_version_id, skill_name: `Снимок ${reg.skill_name}`, skill_version: '2.1', skill_sha256: reg.skill_sha256 })) }] }
      comparisons.push(comparison)
      return reply(comparison)
    }
    if (path === `${base}/model-comparisons/comparison-1/commit`) {
      if (comparison) comparison.status = 'committed'
      return reply({ comparison_id: 'comparison-1', case_id: caseId, atoms_created: 0, atom_ids: [], review_only: true, already_committed: false })
    }
    if (path === `${base}/model-registries/R3/publish`) {
      if (options.lateStage) return reply({ detail: 'Верните этап Атомизация' }, 409)
      const reg = registries[2]
      const already = reg.published_atom_count === 1
      if (!already) atoms.push(atom('PUBLISHED', [origin(reg)]))
      reg.published_atom_count = 1
      return reply({ registry_id: reg.id, atoms_created: already ? 0 : 1, atom_ids: ['PUBLISHED'], already_published: already })
    }
    if (path === '/api/audit/ai-atomization/skills' || path === '/api/admin/integrations/ai/skills') return reply({ items: skills })
    if (path === '/api/admin/integrations/ai/skills/import') {
      const added = skill('installed', 'declarative_archive', 'Установленная методика')
      skills.push(added)
      return reply(added)
    }
    if (path === '/api/admin/integrations/ai/providers' || path === '/api/audit/synology/connections') return reply({ items: [], allowed_origins_configured: true, encryption_key_configured: true })
    if (path === '/api/audit/ai-providers') return reply({ items: ['A', 'B'].map((id) => ({ id, display_name: `Профиль ${id}`, model_name: `model-${id}`, config_version: 4 })) })
    if (path === `${base}/canonical-preflight/runs`) {
      if (method === 'GET') return reply({ items: runs })
      const body = request.postDataJSON()
      const run: AuditTZRun = { id: `test-run-${runs.length}`, case_id: caseId, document_id: body.document_id, skill_version_id: body.skill_version_id,
        skill_name: 'Методика', skill_version: '2.0', status: 'preflight_pass', current_phase: 'preflight', source_unit_count: 4,
        warning_count: 0, atom_count: 0, completed_batch_count: 0, total_batch_count: 0, safe_summary: {}, error_code: null,
        artifacts: [], external_ai_called: false, ai_attempt_id: null, pause_requested: false, priority: 0, paused_at: null, created_at: date, started_at: date, finished_at: date }
      runs.push(run)
      return reply(run)
    }
    if (path.endsWith('/atomization-preview')) {
      const id = url.searchParams.get('provider_id')!
      if (holdPreview && id === 'A') { holdPreview = false; await new Promise<void>((resolve) => { releasePreview = resolve }) }
      return reply({ consent_token: `synthetic-consent-${id}`, provider_id: id, provider_name: `Профиль ${id}`, model_name: `model-${id}`, source_unit_count: 4, outbound_fields: ['Обезличенные фрагменты'], warnings: [] })
    }
    if (path.endsWith('/atomization') && method === 'POST') return reply({ ...runs[runs.length - 1], status: 'atomization_queued' })
    if (path.includes('/canonical-preflight/runs/') && method === 'GET') return reply(runs.find((run) => path.endsWith(run.id)))
    if (path === '/api/audit/team') return reply([{ id: 'member', user_id: userId, full_name: 'Аудитор', email: 'audit@example.test', role: 'leader', is_active: true, audit_enabled: true }])
    if (path.startsWith('/api/client-events')) return reply({})
    if (method !== 'GET') { errors.push(`Unexpected mutation: ${method} ${path}`); return reply({}, 500) }
    return reply([])
  })
  return { atoms, registries, writes, errors, external, releasePreview: () => releasePreview?.() }
}

async function openAudit(page: Page) {
  await page.goto(`/audit?view=case&case=${caseId}`)
  await page.getByRole('tab', { name: 'Атомы', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Генеральный реестр атомов' })).toBeVisible()
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1)
}

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript((theme) => localStorage.setItem('dpms-theme', theme), info.project.name.includes('dark') ? 'dark' : info.project.name.includes('rose') ? 'rose' : 'light')
})

test('mixed provenance remains visible, filter preserves duplicate proposals and URL scope', async ({ page }, info) => {
  const state = await setup(page)
  await openAudit(page)
  await expect(page.getByRole('status').filter({ hasText: 'Показано:' })).toContainText('6 из 6')
  await page.getByLabel('Источник атомов').selectOption('ai')
  await expect(page.getByRole('status').filter({ hasText: 'Показано:' })).toContainText('2 из 6')
  await expect(page.locator('input[aria-label^="Выбрать атом"]:visible')).toHaveCount(2)
  await page.reload()
  await expect(page.getByLabel('Источник атомов')).toHaveValue('ai')
  await page.locator('button[aria-label="Изменить атом AI2"]:visible').click()
  const dialog = page.getByRole('dialog', { name: 'Изменить атом' })
  await expect(dialog.getByText('Источник · 2', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Провайдер R1 · model-R1 · конфигурация v3', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Провайдер R2 · model-R2 · конфигурация v3', { exact: true })).toBeVisible()
  await dialog.getByRole('region', { name: 'Происхождение атома' }).scrollIntoViewIfNeeded()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('provenance-edit.png') })
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click()
  for (const kind of ['historical_import', 'manual_register', 'manual', 'unknown']) {
    await page.getByLabel('Источник атомов').selectOption(kind)
    await expect(page.getByRole('status').filter({ hasText: 'Показано:' })).toContainText('1 из 6')
  }
  await page.getByLabel('Источник атомов').selectOption('all')
  await page.getByLabel('Источник атомов').scrollIntoViewIfNeeded()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('general-registry.png') })
  await page.getByLabel('Источник атомов').selectOption('ai')
  await page.locator('table').evaluateAll((tables) => tables.forEach((table) => { if (table.parentElement) table.parentElement.scrollLeft = 0 }))
  await page.locator('summary:visible').filter({ hasText: 'Источников: 2' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('general-ai-sources.png') })
  expect(state.writes).toEqual([])
  expect(state.errors).toEqual([])
  expect(state.external).toEqual([])
})

test('comparison saves only review decisions and shows every model origin', async ({ page }, info) => {
  const state = await setup(page)
  const original = JSON.stringify(state.atoms)
  await openAudit(page)
  await page.getByLabel('Выбрать реестр Провайдер R1', { exact: true }).check()
  await page.getByLabel('Выбрать реестр Провайдер R2', { exact: true }).check()
  await page.getByRole('button', { name: 'Сравнить выбранные', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Сравнительный анализ моделей' })
  await expect(dialog.getByRole('button', { name: 'Сохранить сравнение' })).toBeEnabled()
  await expect(dialog.getByText('Провайдер R1 · model-R1 · конфигурация v9', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Провайдер R2 · model-R2 · конфигурация v9', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Методика: Снимок Основная методика · v2.1', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Методика: Снимок Другая методика · v2.1', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/Согласие|Полное согласие/)).toHaveCount(0)
  await dialog.getByLabel('Название атома').fill('Решение только в сравнении')
  await dialog.getByRole('region', { name: 'Происхождение атома' }).scrollIntoViewIfNeeded()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('comparison-review.png') })
  await dialog.getByRole('button', { name: 'Сохранить сравнение' }).click()
  await expect(dialog).toHaveCount(0)
  expect(JSON.stringify(state.atoms)).toBe(original)
  expect(state.writes.map((write) => write.path)).toEqual([`${base}/model-comparisons`, `${base}/model-comparisons/comparison-1/commit`])
  expect(state.errors).toEqual([])
})

test('old result publishes explicitly as draft without removing human atoms', async ({ page }) => {
  const state = await setup(page)
  await openAudit(page)
  const card = page.locator('details').filter({ has: page.getByLabel('Выбрать реестр Провайдер R3', { exact: true }) })
  await card.locator('summary').click()
  await card.getByRole('button', { name: 'Добавить в генеральный реестр' }).click()
  await expect(card).toContainText('В генеральном: 1/1')
  await expect(card).toContainText('Результаты уже в генеральном реестре')
  expect(state.atoms).toHaveLength(7)
  expect(state.atoms.find((atom) => atom.id === 'PUBLISHED')?.state).toBe('draft')
  expect(state.atoms.filter((atom) => atom.state === 'ready')).toHaveLength(3)
  expect(state.writes).toEqual([{ path: `${base}/model-registries/R3/publish`, body: null }])
  await page.reload()
  await expect(card.getByRole('button', { name: 'Добавить в генеральный реестр' })).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('late-phase publication conflict preserves atoms and names the existing stage recovery', async ({ page }) => {
  const state = await setup(page, { lateStage: true })
  await openAudit(page)
  const card = page.locator('details').filter({ has: page.getByLabel('Выбрать реестр Провайдер R3', { exact: true }) })
  await card.locator('summary').click()
  await card.getByRole('button', { name: 'Добавить в генеральный реестр' }).click()
  await expect(page.getByText(/Верните договор на этап «Атомизация» через редактирование/)).toBeVisible()
  await expect(page.getByLabel('Выбрать реестр Провайдер R1', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Добавить в генеральный реестр' })).toBeEnabled()
  expect(state.atoms).toHaveLength(6)
  expect(state.writes).toHaveLength(1)
})

test('all skill formats use durable preflight; document skill provider changes invalidate consent', async ({ page }, info) => {
  const state = await setup(page, { delayPreview: true })
  await openAudit(page)
  await page.getByRole('button', { name: 'Запустить другую модель' }).click()
  const dialog = page.getByRole('dialog', { name: 'Атомизация технического задания' })
  const methodology = dialog.getByLabel('Проверенная методика', { exact: true })
  const document = dialog.getByLabel('Неизменяемое ТЗ', { exact: true })
  const provider = dialog.getByLabel('ИИ-подключение для этого прогона', { exact: true })
  await expect(methodology).toHaveValue('rules')
  await expect(dialog.getByLabel(/Номер договора/)).toHaveCount(0)
  await methodology.selectOption('json')
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(dialog.getByText('Документ подготовлен', { exact: true })).toBeVisible()
  await provider.selectOption('B')
  const consent = dialog.getByRole('region', { name: 'Подтверждение внешней атомизации' })
  await expect(consent).toContainText('Профиль B · model-B')
  state.releasePreview()
  await expect(consent).not.toContainText('Профиль A')
  await consent.getByRole('checkbox').check()
  await document.selectOption('doc-2')
  await expect(consent).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(consent.getByRole('checkbox')).not.toBeChecked()
  await consent.getByRole('checkbox').check()
  await methodology.selectOption('trusted')
  await expect(consent).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(dialog.getByText('Доверенный runtime · self-test пройден')).toBeVisible()
  await methodology.selectOption('rules')
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(consent.getByRole('checkbox')).not.toBeChecked()
  await expect(dialog.getByText('Доверенный runtime · self-test пройден')).toHaveCount(0)
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('canonical-method-selection.png') })
  await consent.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: 'Запустить атомизацию', exact: true }).click()
  await expect(dialog.getByRole('button', { name: /очеред/ }).first()).toBeDisabled()
  const preflights = state.writes.filter((write) => write.path.endsWith('/runs'))
  expect(preflights.map((write) => [write.body?.skill_version_id, write.body?.document_id])).toEqual([['json', 'doc-1'], ['json', 'doc-2'], ['trusted', 'doc-2'], ['rules', 'doc-2']])
  expect(state.writes.at(-1)?.body).toMatchObject({ provider_id: 'B', consent_token: 'synthetic-consent-B', data_transfer_confirmed: true })
  expect(state.writes.some((write) => 'contract_identifiers' in (write.body ?? {}))).toBe(false)
  expect(state.errors).toEqual([])
  expect(state.external).toEqual([])
})

test('admin installs data-only skill without runtime self-test claims and retains other methodologies', async ({ page }, info) => {
  const state = await setup(page)
  await page.goto('/admin/integrations')
  await page.getByRole('tab', { name: 'ИИ', exact: true }).click()
  const section = page.getByRole('region', { name: 'Skills атомизации аудита' })
  await expect(section.getByText('.skill · методика', { exact: true })).toBeVisible()
  await expect(section.getByText('.skill · доверенный runtime', { exact: true })).toBeVisible()
  await section.locator('input[type=file]').setInputFiles({ name: 'method.skill', mimeType: 'application/zip', buffer: Buffer.from('synthetic data-only archive fixture') })
  await section.getByRole('button', { name: 'Установить версию' }).click()
  await expect(section.getByText('Установленная методика', { exact: true })).toBeVisible()
  const row = section.locator('div.grid').filter({ has: page.getByText('Установленная методика', { exact: true }) }).last()
  await expect(row).not.toContainText(/self-test|Self-test/)
  await expect(section.getByText('.skill · методика', { exact: true })).toHaveCount(2)
  await section.scrollIntoViewIfNeeded()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('admin-skills.png') })
  expect(state.writes.map((write) => write.path)).toEqual(['/api/admin/integrations/ai/skills/import'])
  expect(state.errors).toEqual([])
  expect(state.external).toEqual([])
})

test('native PDF is available for both declarative formats, trusted archive remains DOCX-only', async ({ page }, info) => {
  const state = await setup(page)
  await openAudit(page)
  await page.getByRole('button', { name: 'Запустить другую модель' }).click()
  const dialog = page.getByRole('dialog', { name: 'Атомизация технического задания' })
  const method = dialog.getByLabel('Проверенная методика', { exact: true })
  const document = dialog.getByLabel('Неизменяемое ТЗ', { exact: true })
  await expect(method.locator('option[value=rules]')).toContainText('SHA bbbbbbbbbbbb')
  await expect(method.locator('option[value=rules]')).not.toContainText('sha256-')
  await document.selectOption('doc-pdf')
  await expect(dialog.getByRole('button', { name: 'Подготовить документ' })).toBeEnabled()
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(dialog.getByText('Документ подготовлен', { exact: true })).toBeVisible()
  await method.selectOption('json')
  await expect(document).toHaveValue('doc-pdf')
  await dialog.getByRole('button', { name: 'Подготовить документ' }).click()
  await expect(dialog.getByText('Документ подготовлен', { exact: true })).toBeVisible()
  await expect(dialog.getByLabel(/Номер договора/)).toHaveCount(0)
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('native-pdf.png') })
  await method.selectOption('trusted')
  await expect(document.locator('option[value=doc-pdf]')).toHaveCount(0)
  await expect(document).toHaveValue('doc-1')
  expect(state.writes.map((write) => write.body?.document_id)).toEqual(['doc-pdf', 'doc-pdf'])
  expect(state.errors).toEqual([])
})

test('previous pending attempt can be reopened without calling a model', async ({ page }) => {
  const state = await setup(page, { legacyPending: true })
  await openAudit(page)
  await page.getByRole('button', { name: 'Запустить другую модель' }).click()
  const dialog = page.getByRole('dialog', { name: 'Атомизация технического задания' })
  await dialog.getByLabel('Прежние черновики', { exact: true }).selectOption('legacy-attempt')
  await expect(dialog.getByRole('textbox', { name: 'Название атома', exact: true })).toBeEditable()
  await dialog.getByRole('textbox', { name: 'Название атома', exact: true }).fill('Доработанный сохраненный черновик')
  await dialog.getByRole('button', { name: 'Записать в реестр', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes.map((write) => write.path)).toEqual([`${base}/ai-atomization/attempts/legacy-attempt/commit`])
  expect(state.errors).toEqual([])
})
