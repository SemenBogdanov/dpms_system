import { expect, test, type Page, type Route } from '@playwright/test'

const userId = '11111111-1111-4111-8111-111111111111'
const caseId = '22222222-2222-4222-8222-222222222222'
const secondCaseId = '66666666-6666-4666-8666-666666666666'
const firstAtomId = '33333333-3333-4333-8333-333333333333'
const secondAtomId = '44444444-4444-4444-8444-444444444444'

const testUser = {
  id: userId,
  full_name: 'Руководитель аудита',
  email: 'audit@example.test',
  league: 'A',
  role: 'admin',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 1,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: true,
  can_link_queue_tasks_to_projects: true,
  feedback_enabled: true,
  competency_development_enabled: true,
  competency_constructor_enabled: true,
  audit_enabled: true,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

type Atom = {
  id: string
  case_id: string
  item_code: string
  title: string
  digital_product: string
  work_type: string
  object_type: string
  source_clause: string
  source_evidence_text: string
  source_refs_json: Array<{ source_unit_id: string; locator: string; excerpt: string }>
  system_url: string | null
  notes: string | null
  state: 'draft' | 'ready' | 'excluded'
  source_sheet: string | null
  source_row: number | null
  source_fingerprint: string | null
  import_batch_id: string | null
  alpha_result: 'present' | 'not_present' | 'needs_clarification' | null
  alpha_result_raw: string | null
  alpha_comment: string | null
  alpha_date: string | null
  commission_result: null
  commission_result_raw: null
  commission_date: null
  sort_order: number
  created_at: string
  updated_at: string
}

type MockState = {
  atoms: Atom[]
  workflowStage: 'atomization' | 'alpha_review'
  patchCalls: number
  failNextPatch: boolean
}

function atom(id: string, code: string, title: string, order: number): Atom {
  return {
    id,
    case_id: caseId,
    item_code: code,
    title,
    digital_product: 'OPEC',
    work_type: 'Разработка',
    object_type: 'Экран',
    source_clause: `Раздел 2.${order}`,
    source_evidence_text: `Система должна поддерживать ${title.toLowerCase()}.`,
    source_refs_json: [{
      source_unit_id: `source-${order}`,
      locator: `ТЗ, раздел 2.${order}`,
      excerpt: `Система должна поддерживать ${title.toLowerCase()}.`,
    }],
    system_url: null,
    notes: null,
    state: 'draft',
    source_sheet: null,
    source_row: null,
    source_fingerprint: null,
    import_batch_id: null,
    alpha_result: null,
    alpha_result_raw: null,
    alpha_comment: null,
    alpha_date: null,
    commission_result: null,
    commission_result_raw: null,
    commission_date: null,
    sort_order: order,
    created_at: '2026-08-24T08:00:00Z',
    updated_at: `2026-08-24T08:00:0${order}Z`,
  }
}

function casePayload(state: MockState) {
  const readyCount = state.atoms.filter((item) => item.state === 'ready').length
  const draftCount = state.atoms.filter((item) => item.state === 'draft').length
  const excludedCount = state.atoms.filter((item) => item.state === 'excluded').length
  const alphaPassedCount = state.atoms.filter((item) => item.alpha_result === 'present').length
  return {
    id: caseId,
    case_number: 'AUD-0042',
    code: 'AUD-0042',
    created_by_id: userId,
    responsible_user_id: userId,
    responsible_name: testUser.full_name,
    responsible_email: testUser.email,
    title: 'Проверка цифрового продукта',
    digital_product: 'OPEC',
    contract_reference_mask: '12****42',
    contract_date: '2026-08-01',
    status: 'atomization',
    workflow_stage: state.workflowStage,
    notes: 'Выполняется аудит каждого элемента технического задания.',
    atoms_count: state.atoms.length,
    ready_atoms_count: readyCount,
    draft_atoms_count: draftCount,
    excluded_atoms_count: excludedCount,
    alpha_passed_count: alphaPassedCount,
    commission_passed_count: 0,
    documents_count: 1,
    created_at: '2026-08-24T08:00:00Z',
    updated_at: '2026-08-24T08:00:00Z',
    atoms: state.atoms,
  }
}

async function installApiMock(page: Page, state: MockState) {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'audit-review-test-token'))
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const path = new URL(request.url()).pathname
    const respond = async (body: unknown, status = 200) => {
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    }

    if (path === '/api/auth/me') return respond(testUser)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/audit/cases' && method === 'GET') {
      const summary: Partial<ReturnType<typeof casePayload>> = { ...casePayload(state) }
      delete summary.atoms
      return respond([summary])
    }
    if (path === `/api/audit/cases/${caseId}` && method === 'GET') return respond(casePayload(state))
    if (path === `/api/audit/cases/${caseId}/events` && method === 'GET') return respond([])
    if (path === `/api/audit/cases/${caseId}/documents` && method === 'GET') return respond([])
    if (path === `/api/audit/cases/${caseId}/model-registries` && method === 'GET') return respond({ items: [] })
    if (path === `/api/audit/cases/${caseId}/model-comparisons` && method === 'GET') return respond([])
    if (path === '/api/audit/team' && method === 'GET') {
      return respond([{ id: '55555555-5555-4555-8555-555555555555', user_id: userId, full_name: testUser.full_name, email: testUser.email, role: 'leader', is_active: true, audit_enabled: true, added_by_id: null, created_at: '2026-08-24T08:00:00Z' }])
    }
    if (path === '/api/audit/team/candidates' && method === 'GET') return respond([])
    if (path === `/api/audit/cases/${caseId}/alpha-review/start` && method === 'POST') {
      state.workflowStage = 'alpha_review'
      return respond(casePayload(state))
    }
    const atomMatch = path.match(new RegExp(`^/api/audit/cases/${caseId}/atoms/([^/]+)$`))
    if (atomMatch && method === 'PATCH') {
      state.patchCalls += 1
      if (state.failNextPatch) {
        state.failNextPatch = false
        return respond({ detail: 'Атом уже изменен другим пользователем. Обновите данные и повторите решение.' }, 409)
      }
      const current = state.atoms.find((item) => item.id === atomMatch[1])
      if (!current) return respond({ detail: 'Атом не найден' }, 404)
      const payload = JSON.parse(request.postData() || '{}') as Record<string, unknown>
      if (payload.expected_updated_at !== current.updated_at) {
        return respond({ detail: `Атом ${current.item_code} уже изменен другим пользователем. Обновите данные и повторите решение.` }, 409)
      }
      delete payload.expected_updated_at
      Object.assign(current, payload, { updated_at: `2026-08-24T08:01:${String(state.patchCalls).padStart(2, '0')}Z` })
      return respond(current)
    }
    if (path.startsWith('/api/client-events')) return respond({})
    return respond(method === 'GET' ? [] : {})
  })
}

function newState(): MockState {
  return {
    atoms: [
      atom(firstAtomId, 'ATOM-001', 'Экран списка заявок', 1),
      atom(secondAtomId, 'ATOM-002', 'Фильтр по периоду', 2),
    ],
    workflowStage: 'atomization',
    patchCalls: 0,
    failNextPatch: false,
  }
}

async function openAudit(page: Page, state: MockState) {
  await installApiMock(page, state)
  await page.goto(`/audit?view=case&case=${caseId}`)
  await expect(page.getByText('Проверка цифрового продукта', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Проверить черновики' })).toBeVisible()
}

test('contract header keeps the audit identity, process and controls scannable', async ({ page }, testInfo) => {
  const state = newState()
  await openAudit(page, state)

  await expect(page.getByText('AUD-0042', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('OPEC', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Не завершено · 2 атома', { exact: true })).toBeVisible()
  const progress = page.getByRole('group', { name: 'Прогресс аудита' })
  await expect(progress).toBeVisible()
  await expect(page.getByRole('button', { name: 'Редактировать договор' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Изменить ответственного' })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await progress.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('audit-contract-header.png') })
})

test('one AI model registry can populate the working atom table', async ({ page }, testInfo) => {
  const state = newState()
  state.atoms = []
  const registryId = '77777777-7777-4777-8777-777777777777'
  const comparisonId = '88888888-8888-4888-8888-888888888888'
  const modelAtomCount = 140
  let selectedRegistryIds: string[] = []
  let comparisonCreated = false

  const modelItems = Array.from({ length: modelAtomCount }, (_, index) => {
    const number = index + 1
    const sourceRef = {
      source_unit_id: `source-${number}`,
      locator: `ТЗ, раздел 2.${number}`,
      excerpt: `Система должна отображать элемент ${number}.`,
    }
    return {
      id: `registry-item-${number}`,
      title: number === 1 ? 'Экран списка заявок' : `Элемент ${number}`,
      digital_product: 'OPEC',
      work_type: 'Разработка',
      object_type: 'Экран',
      source_clause: sourceRef.locator,
      notes: null,
      confidence_percent: 91,
      sort_order: number * 10,
      source_refs: [sourceRef],
    }
  })
  const registry = {
    id: registryId,
    case_id: caseId,
    canonical_run_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    provider_config_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    provider_config_version: 1,
    provider_name: 'ROX-1',
    model_name: 'test-model',
    atom_count: modelAtomCount,
    coverage_summary: {},
    warnings: [],
    items: modelItems,
    created_at: '2026-08-24T08:00:00Z',
  }
  const comparison = {
    id: comparisonId,
    case_id: caseId,
    canonical_run_id: registry.canonical_run_id,
    status: 'draft_ready' as 'draft_ready' | 'committed',
    config_version: 1,
    registry_ids: [registryId],
    registry_snapshot: [],
    drafts: modelItems.map((item, index) => ({
      id: `comparison-draft-${index + 1}`,
      title: item.title,
      digital_product: item.digital_product,
      work_type: item.work_type,
      object_type: item.object_type,
      source_clause: item.source_clause,
      notes: item.notes,
      confidence_percent: item.confidence_percent,
      agreement_count: 1,
      registry_count: 1,
      review_status: 'pending',
      sort_order: item.sort_order,
      source_refs: item.source_refs,
      model_variants: [{
        registry_id: registryId,
        registry_item_id: item.id,
        provider_name: registry.provider_name,
        model_name: registry.model_name,
        title: item.title,
        object_type: item.object_type,
        work_type: item.work_type,
        confidence_percent: item.confidence_percent,
      }],
    })),
    created_at: '2026-08-24T08:01:00Z',
    committed_at: null as string | null,
  }

  await page.addInitScript(() => localStorage.setItem('dpms_token', 'audit-review-test-token'))
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const path = new URL(request.url()).pathname
    const respond = async (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
    if (path === '/api/auth/me') return respond(testUser)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/audit/cases' && method === 'GET') {
      const summary: Partial<ReturnType<typeof casePayload>> = { ...casePayload(state) }
      delete summary.atoms
      return respond([summary])
    }
    if (path === `/api/audit/cases/${caseId}` && method === 'GET') return respond(casePayload(state))
    if (path === `/api/audit/cases/${caseId}/events` && method === 'GET') return respond([])
    if (path === `/api/audit/cases/${caseId}/documents` && method === 'GET') return respond([])
    if (path === `/api/audit/cases/${caseId}/model-registries` && method === 'GET') return respond({ items: [registry] })
    if (path === `/api/audit/cases/${caseId}/model-comparisons` && method === 'GET') {
      return respond(comparisonCreated ? [comparison] : [])
    }
    if (path === `/api/audit/cases/${caseId}/model-comparisons` && method === 'POST') {
      const body = JSON.parse(request.postData() || '{}') as { registry_ids?: string[] }
      selectedRegistryIds = body.registry_ids ?? []
      comparisonCreated = true
      return respond(comparison, 201)
    }
    if (path === `/api/audit/cases/${caseId}/model-comparisons/${comparisonId}/commit` && method === 'POST') {
      state.atoms = modelItems.map((item, index) => atom(
        `working-atom-${index + 1}`,
        `ITEM-${String(index + 1).padStart(3, '0')}`,
        item.title,
        index + 1
      ))
      comparison.status = 'committed'
      comparison.committed_at = '2026-08-24T08:02:00Z'
      return respond({
        comparison_id: comparisonId,
        case_id: caseId,
        atoms_created: modelAtomCount,
        atom_ids: state.atoms.map((item) => item.id),
        already_committed: false,
      })
    }
    if (path === '/api/audit/team' && method === 'GET') {
      return respond([{ id: '55555555-5555-4555-8555-555555555555', user_id: userId, full_name: testUser.full_name, email: testUser.email, role: 'leader', is_active: true, audit_enabled: true, added_by_id: null, created_at: '2026-08-24T08:00:00Z' }])
    }
    if (path === '/api/audit/team/candidates' && method === 'GET') return respond([])
    if (path.startsWith('/api/client-events')) return respond({})
    return respond(method === 'GET' ? [] : {})
  })

  await page.goto(`/audit?view=case&case=${caseId}`)
  await expect(page.getByRole('heading', { name: 'Модельный реестр готов' })).toBeVisible()
  await expect(page.getByText(`ИИ сформировал ${modelAtomCount} атомов.`, { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Подготовить рабочий реестр' }).last().click()

  const dialog = page.getByRole('dialog', { name: 'Подготовка рабочего реестра' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('Название атома').first()).toHaveValue('Экран списка заявок')
  expect(selectedRegistryIds).toEqual([registryId])
  await dialog.getByRole('button', { name: 'Записать рабочий реестр' }).click()

  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Проверить черновики' })).toBeVisible()
  await expect(page.locator('input[aria-label="Выбрать атом ITEM-001"]:visible')).toHaveCount(1)
  await page.getByRole('button', { name: 'Проверить черновики' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('single-model-working-registry.png') })
})

test('late detail response cannot replace the currently selected contract', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'audit-review-test-token'))
  const base = casePayload(newState())
  const oldCase = {
    ...base,
    title: 'Старый договор',
    digital_product: 'OLD',
  }
  const currentCase = {
    ...base,
    id: secondCaseId,
    case_number: 'AUD-0043',
    code: 'AUD-0043',
    title: 'Выбранный договор',
    digital_product: 'CURRENT',
    atoms: [],
    atoms_count: 0,
    ready_atoms_count: 0,
    draft_atoms_count: 0,
    excluded_atoms_count: 0,
  }

  await page.route('**/api/**', async (route: Route) => {
    const path = new URL(route.request().url()).pathname
    const respond = async (body: unknown) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
    if (path === '/api/auth/me') return respond(testUser)
    if (path === '/api/messages/summary') return respond({ direct_count: 0, important_count: 0 })
    if (path === '/api/audit/cases') {
      const oldSummary = { ...oldCase } as Partial<typeof oldCase>
      const currentSummary = { ...currentCase } as Partial<typeof currentCase>
      delete oldSummary.atoms
      delete currentSummary.atoms
      return respond([oldSummary, currentSummary])
    }
    if (path === `/api/audit/cases/${caseId}`) {
      await new Promise((resolve) => setTimeout(resolve, 250))
      return respond(oldCase)
    }
    if (path === `/api/audit/cases/${secondCaseId}`) return respond(currentCase)
    if (path === '/api/audit/team') {
      return respond([{ id: '55555555-5555-4555-8555-555555555555', user_id: userId, full_name: testUser.full_name, email: testUser.email, role: 'leader', is_active: true, audit_enabled: true, added_by_id: null, created_at: '2026-08-24T08:00:00Z' }])
    }
    if (path === '/api/audit/team/candidates') return respond([])
    if (path.endsWith('/model-registries')) return respond({ items: [] })
    return respond([])
  })

  const firstDetailRequest = page.waitForRequest((request) => new URL(request.url()).pathname === `/api/audit/cases/${caseId}`)
  await page.goto(`/audit?view=case&case=${caseId}`)
  await firstDetailRequest
  await page.evaluate((nextCaseId) => {
    window.history.pushState({}, '', `/audit?view=case&case=${nextCaseId}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, secondCaseId)

  await expect(page.getByText('Выбранный договор', { exact: true })).toBeVisible()
  await page.waitForTimeout(300)
  await expect(page.getByText('Выбранный договор', { exact: true })).toBeVisible()
  await expect(page.getByText('Старый договор', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Редактировать договор' }).click()
  await expect(page.getByLabel('Название аудита')).toHaveValue('Выбранный договор')
})

test('sequential draft and alpha review saves every decision before advancing', async ({ page }) => {
  const state = newState()
  await openAudit(page, state)

  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  const draftDialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await expect(draftDialog).toBeVisible()
  await expect(draftDialog.getByRole('heading', { name: 'Экран списка заявок' })).toBeVisible()

  await page.mouse.click(4, 4)
  await expect(draftDialog).toBeVisible()

  await page.keyboard.press('Space')
  await expect(draftDialog.getByRole('heading', { name: 'Фильтр по периоду' })).toBeVisible()
  expect(state.atoms[0].state).toBe('ready')

  await page.keyboard.press('ArrowDown')
  await expect(draftDialog.getByRole('heading', { name: 'Черновики разобраны' })).toBeVisible()
  expect(state.atoms[1].state).toBe('excluded')
  await draftDialog.getByRole('button', { name: 'Закрыть проверку' }).click()

  await page.getByRole('button', { name: 'Альфа-проверка', exact: true }).click()
  const alphaDialog = page.getByRole('dialog', { name: 'Альфа-проверка атомов' })
  await expect(alphaDialog.getByRole('heading', { name: 'Экран списка заявок' })).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await alphaDialog.getByLabel('Почему элемент не найден или требует уточнения').fill('Экран отсутствует в проверяемой версии')
  await alphaDialog.getByRole('button', { name: 'Нет в системе' }).click()

  await expect(alphaDialog.getByRole('heading', { name: 'Альфа-проверка заполнена' })).toBeVisible()
  expect(state.atoms[0].state).toBe('ready')
  expect(state.atoms[0].alpha_result).toBe('not_present')
  expect(state.atoms[0].alpha_comment).toBe('Экран отсутствует в проверяемой версии')

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('failed save keeps the current atom and allows a retry', async ({ page }) => {
  const state = newState()
  state.failNextPatch = true
  await openAudit(page, state)

  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  const dialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await page.keyboard.press('Space')

  await expect(dialog.getByText('Атом уже изменен другим пользователем. Обновите данные и повторите решение.')).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Экран списка заявок' })).toBeVisible()
  expect(state.atoms[0].state).toBe('draft')

  await page.keyboard.press('Space')
  await expect(dialog.getByRole('heading', { name: 'Фильтр по периоду' })).toBeVisible()
  expect(state.atoms[0].state).toBe('ready')
})

test('undo uses the captured version and cannot overwrite a later edit', async ({ page }) => {
  const state = newState()
  await openAudit(page, state)

  await page.getByRole('button', { name: 'Проверить черновики' }).click()
  const dialog = page.getByRole('dialog', { name: 'Проверка черновиков атомов' })
  await page.keyboard.press('Space')
  await expect(dialog.getByRole('heading', { name: 'Фильтр по периоду' })).toBeVisible()

  state.atoms[0].updated_at = '2026-08-24T08:05:00Z'
  await dialog.getByRole('button', { name: 'Отменить последнее' }).click()

  await expect(dialog.getByText(/уже изменен другим пользователем/)).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Отменить последнее' })).toHaveCount(0)
  expect(state.atoms[0].state).toBe('ready')
})
