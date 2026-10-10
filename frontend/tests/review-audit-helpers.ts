import { expect, type Page, type Route } from '@playwright/test'

export const caseId = '22222222-2222-4222-8222-222222222222'
export const otherCaseId = '66666666-6666-4666-8666-666666666666'
export const userId = '11111111-1111-4111-8111-111111111111'
export const base = `/api/audit/cases/${caseId}`
const date = '2026-10-03T08:00:00Z'

export function makeComparison(id = 'comparison-A', owner = caseId) {
  return {
    id, case_id: owner, status: 'draft_ready', config_version: 1, review_only: true,
    registry_ids: ['R1', 'R2'], registry_snapshot: [], created_at: date, committed_at: null,
    drafts: [{
      id: `draft-${id}`, title: `Предложение ${id}`, digital_product: 'Продукт',
      work_type: 'Разработка', object_type: 'Экран', source_clause: '2.1', notes: null,
      confidence_percent: null, agreement_count: 2, registry_count: 2, review_status: 'pending',
      sort_order: 0, source_refs: [{ source_unit_id: 'unit-1', locator: '2.1', excerpt: 'Текст основания' }],
      model_variants: [],
    }],
  }
}

export function makeState() {
  return {
    atoms: [1, 2].map((n) => ({
      id: `atom-${n}`, case_id: caseId, item_code: `ATOM-${n}`, title: `Атом ${n}`,
      digital_product: 'Продукт', work_type: 'Разработка', object_type: 'Экран',
      source_clause: '2.1', source_evidence_text: 'Текст основания',
      source_refs_json: [], notes: null, state: 'draft', alpha_result: null as string | null,
      alpha_comment: null, provenance: [{ kind: 'manual_register', source_register_id: `source-${n}`, document_sha256: 'a'.repeat(64) }],
      created_at: date, updated_at: date,
    })),
    comparisons: [makeComparison()],
    writes: [] as Array<{ path: string; method: string; body: unknown; raw: string }>,
    errors: [] as string[],
    unexpected: [] as string[],
  }
}
export type AuditState = ReturnType<typeof makeState>
export type Intercept = (route: Route) => Promise<boolean>

export function casePayload(state: AuditState, id = caseId) {
  const atoms = id === caseId ? state.atoms : []
  return {
    id, case_number: id === caseId ? 'AUD-A' : 'AUD-B', title: `Договор ${id === caseId ? 'A' : 'B'}`,
    digital_product: id === caseId ? 'Продукт A' : 'Продукт B', status: 'atomization', workflow_stage: 'atomization',
    responsible_user_id: userId, responsible_name: 'Аудитор', contract_reference_mask: null,
    contract_reference_revealable: false, atoms_count: atoms.length,
    ready_atoms_count: atoms.filter((a) => a.state === 'ready').length,
    draft_atoms_count: atoms.filter((a) => a.state === 'draft').length,
    excluded_atoms_count: atoms.filter((a) => a.state === 'excluded').length,
    alpha_passed_count: atoms.filter((a) => a.alpha_result === 'present').length,
    commission_passed_count: 0, documents_count: 0, created_at: date, updated_at: date, atoms,
  }
}

export async function reply(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

// Held routes let each test choose completion order without timing-dependent sleeps.
export function hold() {
  let release!: (value: { body: unknown; status: number }) => void
  const response = new Promise<{ body: unknown; status: number }>((resolve) => { release = resolve })
  return {
    entered: false,
    finished: false,
    url: '',
    async handle(route: Route) {
      this.entered = true
      this.url = route.request().url()
      const result = await response
      await reply(route, result.body, result.status)
      this.finished = true
      return true
    },
    release(body: unknown, status = 200) { release({ body, status }) },
  }
}

export async function finishHeld(page: Page, pending: ReturnType<typeof hold>, body: unknown, status = 200) {
  const response = page.waitForResponse((result) => result.url() === pending.url)
  pending.release(body, status)
  await (await response).finished()
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

export async function install(page: Page, state: AuditState, intercept?: Intercept) {
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-review-audit'))
  await page.routeWebSocket(/.*/, () => {})
  page.on('pageerror', (error) => state.errors.push(error.message))
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== 'http://localhost:55177') {
      state.unexpected.push(`External: ${url.origin}`)
      return route.abort()
    }
    const path = url.pathname
    if (!path.startsWith('/api/')) {
      if (request.method() !== 'GET') {
        state.unexpected.push(`Non-API write: ${path}`)
        return route.abort()
      }
      return route.continue()
    }
    const method = request.method()
    if (method !== 'GET') state.writes.push({
      path, method, raw: request.postData() ?? '',
      body: request.headers()['content-type']?.includes('application/json') && request.postData() ? request.postDataJSON() : null,
    })
    if (intercept && await intercept(route)) return
    if (path === '/api/auth/me') return reply(route, {
      id: userId, full_name: 'Аудитор', email: 'audit@example.test', role: 'admin',
      is_active: true, audit_enabled: true, task_workspace_enabled: true, needs_password_change: false,
      league: 'A', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 1,
    })
    if (path === '/api/messages/summary') return reply(route, { direct_count: 0, important_count: 0 })
    if (path === '/api/web-push/config') return reply(route, { available: false })
    if (path === '/api/users') return reply(route, [])
    if (path === '/api/audit/cases' && method === 'GET') return reply(route, [casePayload(state), casePayload(state, otherCaseId)])
    if (path === base && method === 'GET') return reply(route, casePayload(state))
    if (path === `/api/audit/cases/${otherCaseId}` && method === 'GET') return reply(route, casePayload(state, otherCaseId))
    if (path.endsWith('/model-registries')) return reply(route, { items: [] })
    if (path.endsWith('/model-comparisons') && method === 'GET') {
      return reply(route, state.comparisons.filter((c) => path.includes(c.case_id)))
    }
    if (path.endsWith('/model-comparisons') && method === 'POST') return reply(route, state.comparisons[0])
    if (path.includes('/model-comparisons/') && path.endsWith('/commit')) return reply(route, { review_only: true, atoms_created: 0 })
    if (path.endsWith('/documents') || path.endsWith('/events')) return reply(route, [])
    if (path.endsWith('/canonical-preflight/runs')) return reply(route, { items: [] })
    if (path === '/api/audit/team') return reply(route, [{ id: 'team-1', user_id: userId, full_name: 'Аудитор', email: 'audit@example.test', role: 'leader', is_active: true, audit_enabled: true, created_at: date }])
    if (path === '/api/audit/team/candidates') return reply(route, [])
    if (path === '/api/audit/assignments') return reply(route, { items: [] })
    if (path === '/api/audit/assignments/index') return reply(route, [])
    if (path.endsWith('/alpha-review/start')) return reply(route, casePayload(state))
    if (path.startsWith(`${base}/atoms/`) && method === 'PATCH') {
      const atom = state.atoms.find((a) => path.endsWith(`/${a.id}`))
      if (!atom) return reply(route, { detail: 'Не найдено' }, 404)
      Object.assign(atom, request.postDataJSON(), { updated_at: new Date().toISOString() })
      return reply(route, atom)
    }
    if (path.startsWith('/api/client-events') || path.startsWith('/api/usage/')) return reply(route, {})
    // Unknown API calls are fulfilled locally, never passed through to the backend.
    state.unexpected.push(`${method} ${path}`)
    return reply(route, { detail: 'Unmocked API request' }, 501)
  })
}

export async function openCase(page: Page, id = caseId, query = '') {
  await page.goto(`/audit?view=case&case=${id}${query}`)
  await expect(page.getByRole('button', { name: 'Редактировать договор' })).toBeVisible()
}

export async function switchCase(page: Page, id: string) {
  await page.evaluate((next) => {
    history.pushState({}, '', `/audit?view=case&case=${next}`)
    dispatchEvent(new PopStateEvent('popstate'))
  }, id)
  await expect(page.getByText(id === caseId ? 'Продукт A' : 'Продукт B', { exact: true }).first()).toBeVisible()
}

export async function unloadProtected(page: Page) {
  return page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
}

export function preview(title: string) {
  return { total_rows: 1, valid_rows: 1, error_rows: 0, warning_rows: 0, has_errors: false,
    rows: [{ row_number: 1, item_code: 'IMPORT-1', title, issues: [] }] }
}

export function assignment(day: string, product: string) {
  return { id: `assignment-${product}`, case_id: caseId, case_number: 'AUD-A', case_title: 'Договор A',
    digital_product: product, assignee_id: userId, assignee_name: 'Аудитор', scheduled_date: day,
    workflow_stage: 'atomization', atoms_count: 2, created_at: date, updated_at: date }
}
