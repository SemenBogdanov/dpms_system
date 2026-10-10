import type { Page } from '@playwright/test'

export const id = (n: number) => `44444444-4444-4444-8444-${String(n).padStart(12, '0')}`
export const user = {
  id: id(1), full_name: 'Проверка задач', email: 'tasks@example.test', role: 'admin', league: 'A',
  mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0, quality_score: 100, is_active: true,
  is_new_employee: false, task_workspace_enabled: true, needs_password_change: false,
  feedback_enabled: false, audit_enabled: false, competency_development_enabled: false,
  competency_constructor_enabled: false, sidebar_menu_order: null,
}
const dates = { created_at: '2026-09-01T09:00:00Z', updated_at: '2026-09-01T09:00:00Z' }
export function personalTask(n: number) {
  return {
    ...dates, id: id(n), task_key: `PT-${n}`, task_number: n, owner_id: user.id, title: `Личная ${n}`,
    description: null, notes: null, status: 'planned', priority: 'medium', category: 'other', project: null,
    context: null, responsible: null, tags: [], acceptance_criteria: null, next_step: null, next_step_at: null,
    start_at: '2026-09-01T09:00:00Z', due_at: '2027-12-01T09:00:00Z', waiting_for: null,
    blocked_reason: null, impact: null, effort: null, source_quick_note_id: null,
    promoted_task_id: null, linked_task_id: null, promoted_at: null, promoted_task: null, execution_task: null,
  }
}
export function task(n: number, status = 'review', owner = id(2)) {
  return {
    ...dates, id: id(n), task_number: n, title: `Q-задача ${n}`, description: 'Контекст задачи',
    status, priority: 'medium', tags: [], task_type: 'regular', complexity: 'S', estimated_q: 10,
    min_league: 'A', assignee_id: id(3), creator_id: user.id, validator_id: null, acceptance_owner_id: owner,
    acceptance_mode: 'legacy', acceptance_revision: 0, acceptance_state: 'not_started',
    acceptance_required_count: 0, acceptance_required_accepted_count: 0, acceptance_accepted_count: 0,
    acceptance_returned_count: 0, acceptance_criteria: null, started_at: null, completed_at: null,
    deadline_zone: 'green', submitted_at: null, due_date: '2027-02-01T09:00:00Z', result_url: null, result_comment: null,
    rejection_count: 0, rejection_comment: null, brief_rating: null, brief_feedback: null,
    parent_task_id: null, catalog_item_id: null, focus_started_at: null, active_seconds: 0,
    can_pull: false, locked: false, is_proactive: false,
  }
}
export function tracker(n: number) {
  return {
    ...dates, id: id(n), owner_id: user.id, title: `Трекер ${n}`, description: null, tracker_type: 'other',
    status: 'active', starts_at: '2026-09-01T09:00:00Z', due_at: '2027-01-01T09:00:00Z',
    shifted_due_at: '2027-01-01T09:00:00Z', pause_started_at: null, paused_seconds: 0, total_pause_seconds: 0,
    next_action: null, responsible: null, tags: [], personal_task_id: null, linked_task_id: null,
    personal_task_key: null, personal_task_title: null, completed_at: null, group_id: null,
    category_id: null, url: null, recurrence: null, reminders: [], source: 'standalone', source_available: true,
  }
}
export function gate() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => { release = resolve })
  return { promise, release }
}
export type Call = { path: string; method: string; query: URLSearchParams; body: Record<string, unknown> }
export type Reply = { body: unknown; status?: number }

export async function fixture(page: Page) {
  const state = {
    personal: [personalTask(11), personalTask(12)],
    queue: [task(21, 'in_queue'), task(22, 'in_queue')],
    review: [task(31)],
    trackers: [tracker(41)],
    calls: [] as Call[],
    errors: [] as string[],
    intercept: undefined as undefined | ((call: Call) => Promise<Reply | undefined> | Reply | undefined),
  }
  page.on('pageerror', (error) => state.errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error' && /(?:Type|Reference|Syntax)Error|ErrorBoundary/.test(message.text())) state.errors.push(message.text())
  })
  await page.routeWebSocket(/.*/, () => {})
  await page.addInitScript(() => localStorage.setItem('dpms_token', 'synthetic-review-tasks-only'))
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') return route.abort('blockedbyclient')
    if (!url.pathname.startsWith('/api/')) return route.continue()
    const request = route.request()
    const call: Call = { path: url.pathname, method: request.method(), query: url.searchParams, body: request.postData() ? request.postDataJSON() : {} }
    state.calls.push(call)
    const send = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    const reply = await state.intercept?.(call)
    if (reply) return send(reply.body, reply.status)
    if (call.path === '/api/auth/me') return send(user)
    if (call.path === '/api/messages/summary') return send({ direct_count: 0, important_count: 0 })
    if (call.path === '/api/storage-quota/me') return send({ quota_bytes: 50000000, used_bytes: 0, usage_percent: 0, warning_level: 'normal', pending_request: null })
    if (call.path === '/api/users') return send([user, { ...user, id: id(2), full_name: 'Владелец приёмки' }, { ...user, id: id(3), full_name: 'Исполнитель' }])
    if (call.path === '/api/note-groups/backlinks') return send({ notes: [], groups: [] })
    if (/\/(progress|run-rate)$/.test(call.path)) return send(null)
    if (call.path === '/api/personal-tasks') {
      const search = call.query.get('search') || ''
      const status = call.query.get('status')
      return send(state.personal.filter((row) => row.title.includes(search) && (!status || ['all', 'active'].includes(status) || row.status === status)))
    }
    if (call.path === '/api/queue') return send(state.queue)
    if (call.path === '/api/tasks') return send(call.query.get('review_inbox') ? state.review : [])
    const deadlineTask = state.queue.find((row) => call.path === `/api/tasks/${row.id}/due-date`)
    if (deadlineTask && call.method === 'PATCH') {
      deadlineTask.due_date = String(call.body.due_date)
      return send(deadlineTask)
    }
    const q = state.queue.find((row) => call.path === `/api/tasks/${row.id}`)
    if (q) return send(q)
    const p = state.personal.find((row) => call.path === `/api/personal-tasks/${row.id}`)
    if (p) return send(p)
    if (call.path === '/api/deadline-trackers') {
      const offset = Number(call.query.get('offset') || 0)
      return send(state.trackers.slice(offset, offset + 300))
    }
    const t = state.trackers.find((row) => call.path === `/api/deadline-trackers/${row.id}`)
    if (t) return send(call.method === 'PATCH' ? Object.assign(t, call.body) : t)
    return send(call.method === 'GET' ? [] : {})
  })
  return state
}
