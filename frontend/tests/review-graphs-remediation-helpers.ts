import { readFileSync } from 'node:fs'
import { expect, type Page, type Route } from '@playwright/test'

export const ownerId = '77777777-7777-4777-8777-777777777777'
export const workspaceName = `dpms-graphs-workspace-v3:${ownerId}`
const timestamp = '2026-10-03T10:00:00Z'

export function graphFixture(id = 'local-a', title = 'Локальный A') {
  return {
    version: 3, id, title, createdAt: timestamp, updatedAt: timestamp,
    viewport: { x: 0, y: 0, scale: 1 }, groups: [], views: [], activeViewId: '', audit: [],
    nodes: ['source', 'target'].map((nodeId, index) => ({
      id: nodeId, type: 'note', title: nodeId, shape: 'rounded', radius: 8, scale: 1,
      autoSize: false, width: 120, height: 80, pinned: false, color: '#2F6BFF',
      x: index * 300, y: 0, items: [], customTypeLabel: '', sourceRef: '', description: '',
    })),
    edges: [{ id: 'edge-a', source: 'source', target: 'target', label: 'Маршрут',
      routing: 'curve', points: [{ x: 160, y: 20 }, { x: 250, y: 100 }] }],
  }
}

export function documentFixture(id: string, revision = 1) {
  const payload = graphFixture(id, `Снимок ${id}`)
  return {
    id: `document-${id}`, client_id: id, title: payload.title, revision,
    payload_bytes: JSON.stringify(payload).length, node_count: 2, edge_count: 1,
    created_at: timestamp, updated_at: timestamp, payload,
  }
}

export const workspaceFrame = (page: Page) => page.frameLocator('iframe[title="Рабочее пространство графов"]')

export async function readWorkspace(page: Page) {
  return page.evaluate((name) => JSON.parse(localStorage.getItem(name) || '{}') as {
    activeGraphId: string
    graphs: ReturnType<typeof graphFixture>[]
    storage: Record<string, { revision: number | null; publishState: string }>
  }, workspaceName)
}

type PendingRequest = {
  clientId: string
  revision: number
  reply: (status: number, body: unknown) => Promise<void>
}

export async function installGraphFixture(page: Page, options: {
  local?: ReturnType<typeof graphFixture>[]
  remote?: ReturnType<typeof documentFixture>[]
  bridgeTimeoutMs?: number
} = {}) {
  const local = options.local || [graphFixture()]
  const remote = options.remote || []
  const lists: PendingRequest[] = []
  const deletes: PendingRequest[] = []
  const unexpectedWrites: string[] = []
  // Opt-in source-only QA before main rebuilds; normal runs always test the served runtime.
  const sourceHtml = process.env.DPMS_REVIEW_GRAPH_SOURCE === '1'
    ? readFileSync(new URL('../public/graph-workspace/index.html', import.meta.url), 'utf8') : null
  await page.addInitScript(({ local, remote, workspaceName, bridgeTimeoutMs }) => {
    localStorage.setItem('dpms_token', 'synthetic-review-graphs')
    if (!localStorage.getItem(workspaceName)) {
      localStorage.setItem(workspaceName, JSON.stringify({
        version: 3, activeGraphId: local[0].id, graphs: local,
        storage: Object.fromEntries(local.map((graph) => {
          const document = remote.find((item) => item.client_id === graph.id)
          return [graph.id, { mode: 'local', revision: document?.revision || null,
            serverUpdatedAt: document?.updated_at || null,
            publishState: document ? 'published' : 'local', error: '' }]
        })),
      }))
    }
    const state = window as typeof window & { __reviewGraphResponses?: number }
    state.__reviewGraphResponses = 0
    window.addEventListener('message', (event) => {
      if (event.origin === location.origin && event.data?.type === 'dpms-graphs-storage-response') {
        state.__reviewGraphResponses = (state.__reviewGraphResponses || 0) + 1
      }
    })
    if (bridgeTimeoutMs && window.parent !== window) {
      const nativeTimeout = window.setTimeout.bind(window)
      window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: unknown[]) =>
        nativeTimeout(handler, delay === 32000 ? bridgeTimeoutMs : delay, ...args)) as typeof window.setTimeout
    }
  }, { local, remote, workspaceName, bridgeTimeoutMs: options.bridgeTimeoutMs })

  await page.context().routeWebSocket('**/*', (socket) => socket.close())
  const hold = (route: Route, target: PendingRequest[]) => new Promise<void>((resolve) => {
    const url = new URL(route.request().url())
    const onClose = () => resolve()
    page.once('close', onClose)
    target.push({
      clientId: decodeURIComponent(url.pathname.split('/').at(-1) || ''),
      revision: Number(url.searchParams.get('base_revision')),
      async reply(status, body) {
        try {
          await route.fulfill({ status, json: body })
        } finally {
          page.off('close', onClose)
          resolve()
        }
      },
    })
  })
  await page.context().route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin !== 'http://localhost:55177') return route.abort()
    if (!url.pathname.startsWith('/api/')) {
      if (sourceHtml && request.method() === 'GET' && url.pathname === '/graph-workspace/index.html') {
        return route.fulfill({ contentType: 'text/html', body: sourceHtml })
      }
      if (request.method() === 'GET') return route.continue()
      unexpectedWrites.push(`${request.method()} ${url.pathname}`)
      return route.abort()
    }
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: {
      id: ownerId, full_name: 'Проверка графов', email: 'graphs-review@example.invalid',
      league: 'A', role: 'executor', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0,
      quality_score: 100, is_active: true, is_new_employee: false,
      task_workspace_enabled: false, can_link_queue_tasks_to_projects: false,
      feedback_enabled: false, audit_enabled: false, audit_calendar_enabled: false,
      competency_development_enabled: false, competency_constructor_enabled: false,
      plan_started_at: null, onboarding_started_at: null, onboarding_until: null,
      sidebar_menu_order: null, needs_password_change: false, created_at: timestamp, updated_at: timestamp,
    } })
    if (url.pathname === '/api/graphs' && request.method() === 'GET') return hold(route, lists)
    if (url.pathname.startsWith('/api/graphs/') && request.method() === 'DELETE') return hold(route, deletes)
    if (url.pathname.startsWith('/api/graphs/') && request.method() === 'GET') {
      const document = remote.find((item) => item.client_id === decodeURIComponent(url.pathname.split('/').at(-1)!))
      return route.fulfill({ status: document ? 200 : 404, json: document || { detail: 'Нет снимка' } })
    }
    if (url.pathname === '/api/messages/summary') return route.fulfill({ json: { direct_count: 0, important_count: 0, revision: 0 } })
    if (request.method() !== 'GET') {
      // Usage telemetry is acknowledged locally; no request is forwarded to a real API.
      if (!url.pathname.startsWith('/api/usage/')) unexpectedWrites.push(`${request.method()} ${url.pathname}`)
      return route.fulfill({ json: {} })
    }
    return route.fulfill({ json: [] })
  })
  return {
    lists, deletes, unexpectedWrites,
    async list(index: number) {
      await expect.poll(() => lists.length).toBeGreaterThan(index)
      return lists[index]
    },
    async deletion(index: number) {
      await expect.poll(() => deletes.length).toBeGreaterThan(index)
      return deletes[index]
    },
    async responses(count: number) {
      await expect.poll(() => workspaceFrame(page).locator('body').evaluate(() =>
        (window as typeof window & { __reviewGraphResponses?: number }).__reviewGraphResponses || 0
      )).toBeGreaterThanOrEqual(count)
    },
  }
}
