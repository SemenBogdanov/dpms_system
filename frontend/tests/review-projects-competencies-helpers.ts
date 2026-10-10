import type { Page, Route } from '@playwright/test'
import { fixture, stamp, user } from './review-main-helpers'

export const projectA = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
export const projectB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
export const operationId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
export const competencyId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
export const future = '2099-12-01T12:00:00Z'

export function project(id = projectA) {
  return {
    id, owner_id: user.id, owner_name: user.full_name, owner_email: user.email,
    entity_type: 'project', title: id === projectA ? 'Проект А' : 'Проект Б',
    description: 'Синтетический проект', outcome_statement: 'Проверяемый результат',
    success_criteria: 'Критерий '.repeat(12), constraints: 'Ж'.repeat(200),
    baseline_outcome_statement: null, baseline_success_criteria: null, baseline_constraints: null,
    status: 'active', visibility: 'private', starts_at: stamp, due_at: future,
    target_due_at: future, forecast_starts_at: stamp, forecast_due_at: future,
    actual_starts_at: null, actual_due_at: null, planning_mode: 'manual',
    methodology_title: null, methodology_version: null, methodology_snapshot: null,
    baseline_locked_at: stamp, baseline_locked_by_id: user.id, schedule_revision: 1,
    tags: [], details_json: null, archived_at: null, access_role: 'owner',
    members_count: 1, links_count: 0, stages_count: 0, tasks_count: 1,
    milestones_count: 0, artifacts_count: 0, created_at: stamp, updated_at: stamp,
  }
}

export const summary = (id: string, overdue = 0) => ({
  entity_id: id, total_links: 0, accessible_links: 0, restricted_links: 0,
  native_tasks: 1, artifacts: 0, work_items_total: 1, work_items_done: 0,
  overdue_items: overdue, next_due_at: future, counts_by_type: {}, counts_by_status: {},
})

export const operation = {
  id: operationId, entity_id: projectA, task_number: 1, stage_id: null, stage_title: null,
  target_milestone_id: null, title: 'Проверить результат', description: null,
  status: 'planned', priority: 'medium', assignee_id: null, assignee_name: null,
  assignee_email: null, created_by_id: user.id, created_by_name: user.full_name,
  acceptance_criteria: 'Результат проверен', next_step: null, waiting_for: null,
  baseline_starts_at: stamp, baseline_due_at: future, forecast_starts_at: stamp,
  forecast_due_at: future, actual_starts_at: null, actual_due_at: null,
  introduced_after_baseline: false, introduced_at_revision: null, variance_days: 0,
  position: 0, predecessor_ids: [], can_manage: true, can_execute: true,
  can_manage_execution_contract: true, execution_contract: null,
  created_at: stamp, updated_at: stamp,
}

export const workspace = (id: string) => ({
  entity_id: id, current_access_role: 'owner', participants: [], stages: [],
  tasks: [{ ...operation, entity_id: id }], milestones: [], dependencies: [], artifacts: [],
})

export const competency = {
  id: competencyId, title: 'Синтетический опрос', description: 'Описание опроса',
  source: 'custom', visibility: 'assigned', questions_count: 1, status: 'not_started',
  can_edit_content: true, active_attempt_id: null, latest_attempt_id: null,
  score_ib: null, score_ich: null, is_overused: false, completed_at: null, retake_allowed_at: null,
}

export const qOption = (id: string) => ({
  task_id: id, task_number: id === 'qa' ? 11 : 12, title: `Q-задача ${id}`,
  status: 'in_queue', estimated_q: 1, priority: 'medium', due_date: future,
  acceptance_mode: 'full', acceptance_state: 'none', assignee_name: null,
})

export const qContract = {
  id: 'contract', entity_id: projectA, operation_id: operationId,
  ...qOption('qb'), task_title: 'Q-задача qb', task_status: 'in_queue',
  source: 'linked_existing', status: 'active', assignee_id: null,
  planned_starts_at: stamp, planned_due_at: future, acceptance_total_count: 0,
  acceptance_accepted_count: 0, acceptance_required_count: 0,
  acceptance_required_accepted_count: 0, result_url: null, result_comment: null,
  created_at: stamp, can_release: true,
}

export async function respond(route: Route, json: unknown, status = 200) {
  await route.fulfill({ status, json })
  return true
}

export async function install(page: Page, override: (route: Route, url: URL) => Promise<boolean> = async () => false) {
  await fixture(page, async (route, url) => {
    if (await override(route, url)) return true
    const path = url.pathname
    if (path === '/api/auth/me') return respond(route, {
      ...user, competency_development_enabled: true, competency_constructor_enabled: true,
      can_link_queue_tasks_to_projects: true,
    })
    if (route.request().method() !== 'GET') return false
    if (path === '/api/work-entities') return respond(route, [project(), project(projectB)])
    const match = path.match(/^\/api\/work-entities\/([^/]+)\/(summary|readiness|workspace|map|links|members|events)$/)
    if (match) {
      const [, id, kind] = match
      if (kind === 'summary') return respond(route, summary(id))
      if (kind === 'readiness') return respond(route, { entity_id: id, can_activate: true, blocking_count: 0, warning_count: 0, issues: [] })
      if (kind === 'workspace') return respond(route, workspace(id))
      if (kind === 'map') return respond(route, { entity_id: id, range_start: stamp, range_end: future, nodes: [], edges: [], generated_at: stamp })
      return respond(route, [])
    }
    if (path.endsWith('/execution-contract-options')) return respond(route, [qOption(url.searchParams.get('search') || 'qa')])
    if (path.endsWith('/execution-contract')) return respond(route, null)
    if (path === '/api/competencies/access') return respond(route, { development_enabled: true, constructor_enabled: true, is_admin: true })
    if (path === '/api/competencies/my') return respond(route, { competencies: [competency] })
    if (path === '/api/competencies/development-plan/my') return respond(route, [])
    if (path === '/api/competencies/constructor') return respond(route, [competency])
    if (path === `/api/competencies/constructor/${competencyId}/report`) return respond(route, {
      competency, rows: [{ user_id: user.id, full_name: user.full_name, assignment_status: 'assigned' }],
    })
    return false
  })
}

export function deferred() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => { release = resolve })
  return { promise, release }
}
