import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

type StoredGraph = {
  id: string
  client_id: string
  title: string
  revision: number
  payload_bytes: number
  node_count: number
  edge_count: number
  created_at: string
  updated_at: string
  payload: Record<string, unknown> & { id: string; title: string; nodes: unknown[]; edges: unknown[] }
}

const userId = '11111111-1111-4111-8111-111111111111'
const testUser = {
  id: userId,
  full_name: 'Проверка графов',
  email: 'graphs-test@example.com',
  league: 'A',
  role: 'executor',
  mpw: 0,
  wip_limit: 5,
  wallet_main: 0,
  wallet_karma: 0,
  quality_score: 100,
  is_active: true,
  is_new_employee: false,
  task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false,
  feedback_enabled: false,
  audit_enabled: false,
  audit_calendar_enabled: false,
  competency_development_enabled: false,
  competency_constructor_enabled: false,
  plan_started_at: null,
  onboarding_started_at: null,
  onboarding_until: null,
  sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-09-22T00:00:00Z',
  updated_at: '2026-09-22T00:00:00Z',
}

function serverGraph(clientId = 'server-graph', title = 'Граф из системы'): StoredGraph {
  const now = '2026-09-22T12:00:00Z'
  const payload: StoredGraph['payload'] = {
    version: 2,
    id: clientId,
    title,
    createdAt: now,
    updatedAt: now,
    viewport: { x: 0, y: 0, scale: 1 },
    nodes: [{
      id: 'server-node', type: 'note', title: 'Серверный элемент', customTypeLabel: '',
      sourceRef: '', description: '', shape: 'rounded', radius: 8, scale: 1,
      pinned: false, color: '#7C55C7', x: 0, y: 0,
    }],
    edges: [],
    groups: [],
    views: [{
      id: 'server-view', name: 'Основной вид', layout: 'radial',
      positions: { 'server-node': { x: 0, y: 0 } },
      viewport: { x: 0, y: 0, scale: 1 }, focusNodeId: null, focusDepth: 0,
    }],
    activeViewId: 'server-view',
    audit: [{ id: 'server-audit', at: now, action: 'Сохранён в системе' }],
  }
  return {
    id: `document-${clientId}`,
    client_id: clientId,
    title,
    revision: 1,
    payload_bytes: JSON.stringify(payload).length,
    node_count: 1,
    edge_count: 0,
    created_at: now,
    updated_at: now,
    payload,
  }
}

async function installApiMock(page: Page, initialGraphs: StoredGraph[] = []) {
  const serverGraphs = new Map(initialGraphs.map((graph) => [graph.client_id, structuredClone(graph)]))
  const stats = { puts: 0, deletes: 0, gets: 0 }
  const behavior = { failPuts: false, putDelayMs: 0 }
  await page.addInitScript(() => {
    window.localStorage.setItem('dpms_token', 'graphs-smoke-token')
  })
  await page.routeWebSocket('**/api/messages/live', (socket) => {
    socket.onMessage((message) => {
      try {
        const event = JSON.parse(String(message)) as { type?: string }
        socket.send(JSON.stringify({ type: event.type === 'ping' ? 'pong' : 'ready' }))
      } catch {
        socket.close({ code: 1003, reason: 'Malformed synthetic message' })
      }
    })
  })
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    const method = route.request().method()
    if (pathname === '/api/auth/me') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(testUser) })
      return
    }
    if (pathname === '/api/messages/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ direct_count: 0, important_count: 0, revision: 0 }),
      })
      return
    }
    if (pathname === '/api/graphs' && method === 'GET') {
      const summaries = [...serverGraphs.values()].map((graph) => ({
        client_id: graph.client_id,
        title: graph.title,
        revision: graph.revision,
        payload_bytes: graph.payload_bytes,
        node_count: graph.node_count,
        edge_count: graph.edge_count,
        created_at: graph.created_at,
        updated_at: graph.updated_at,
      }))
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(summaries) })
      return
    }
    if (pathname.startsWith('/api/graphs/')) {
      const clientId = decodeURIComponent(pathname.slice('/api/graphs/'.length))
      const existing = serverGraphs.get(clientId)
      if (method === 'GET') {
        stats.gets += 1
        await route.fulfill({
          status: existing ? 200 : 404,
          contentType: 'application/json',
          body: JSON.stringify(existing || { detail: { code: 'graph_not_found', message: 'Граф не найден' } }),
        })
        return
      }
      if (method === 'PUT') {
        stats.puts += 1
        if (behavior.putDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, behavior.putDelayMs))
        }
        if (behavior.failPuts) {
          await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Сервис временно недоступен' }) })
          return
        }
        const body = route.request().postDataJSON() as {
          base_revision: number | null
          payload: StoredGraph['payload']
        }
        if (existing && body.base_revision !== existing.revision) {
          await route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({ detail: {
              code: body.base_revision === null ? 'graph_already_exists' : 'graph_revision_conflict',
              message: 'Граф изменился в другой вкладке',
              server_revision: existing.revision,
            } }),
          })
          return
        }
        const now = new Date().toISOString()
        const stored: StoredGraph = {
          id: existing?.id || `server-${clientId}`,
          client_id: clientId,
          title: body.payload.title,
          revision: (existing?.revision || 0) + 1,
          payload_bytes: JSON.stringify(body.payload).length,
          node_count: body.payload.nodes.length,
          edge_count: body.payload.edges.length,
          created_at: existing?.created_at || now,
          updated_at: now,
          payload: structuredClone(body.payload),
        }
        serverGraphs.set(clientId, stored)
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(stored) })
        return
      }
      if (method === 'DELETE') {
        stats.deletes += 1
        if (!existing) {
          await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'graph_not_found', message: 'Граф не найден' } }) })
          return
        }
        const baseRevision = Number(url.searchParams.get('base_revision'))
        if (baseRevision !== existing.revision) {
          await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'graph_revision_conflict', message: 'Конфликт версии' } }) })
          return
        }
        serverGraphs.delete(clientId)
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true, client_id: clientId }) })
        return
      }
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  return { serverGraphs, stats, behavior }
}

test('Graphs open as a DPMS section without losing the standalone workspace', async ({ page }, testInfo) => {
  const runtimeErrors: string[] = []
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })

  await installApiMock(page)
  await page.goto('/graphs')

  const frameElement = page.getByTitle('Рабочее пространство графов')
  await expect(frameElement).toBeVisible()
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await expect(frame.locator('.app')).toBeVisible()
  await expect(frame.locator('.graph-node')).toHaveCount(4)
  await expect(page.getByRole('status')).toBeHidden()
  await expect(page.locator('header.app-header')).toBeHidden()

  const viewport = page.viewportSize()
  const workspaceBox = await frameElement.boundingBox()
  expect(workspaceBox).not.toBeNull()
  expect(viewport).not.toBeNull()
  const reservedMobileNavigation = viewport!.width < 1024 ? 70 : 2
  expect(workspaceBox!.height).toBeGreaterThanOrEqual(viewport!.height - reservedMobileNavigation)
  expect(workspaceBox!.height).toBeLessThanOrEqual(viewport!.height + 1)

  if (viewport && viewport.width < 1024) {
    const menuButton = page.getByRole('button', { name: 'Меню' })
    await expect(menuButton).toBeVisible()
    const menuBox = await menuButton.boundingBox()
    const brandBox = await frame.locator('.brand').boundingBox()
    expect(menuBox).not.toBeNull()
    expect(brandBox).not.toBeNull()
    expect(brandBox!.x).toBeGreaterThanOrEqual(menuBox!.x + menuBox!.width + 4)
    await menuButton.click()
  }

  await expect(page.getByRole('link', { name: 'Графы', exact: true })).toBeVisible()

  if (viewport && viewport.width < 1024) {
    const menuButton = page.getByRole('button', { name: 'Меню' })
    await menuButton.click()
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false')
    await expect.poll(async () => {
      const box = await page.locator('.app-sidebar').boundingBox()
      return box ? box.x + box.width : 0
    }).toBeLessThanOrEqual(1)
  }

  await expect.poll(async () => page.evaluate((id) => (
    window.localStorage.getItem(`dpms-graphs-workspace-v2:${id}`) !== null
  ), userId)).toBe(true)

  const frameSource = await frameElement.getAttribute('src')
  expect(frameSource).toContain(`owner=${encodeURIComponent(userId)}`)

  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }))
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1)

  mkdirSync('test-results/graphs', { recursive: true })
  await page.screenshot({
    path: `test-results/graphs/${testInfo.project.name}.png`,
    fullPage: false,
  })
  expect(runtimeErrors).toEqual([])
})

test('A graph stays local until explicitly moved to DPMS storage', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Storage workflow is covered once on desktop')
  const { serverGraphs, stats } = await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const storageButton = frame.getByRole('button', { name: /Хранение графа:/ })
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: На устройстве')
  expect(stats.puts).toBe(0)

  await storageButton.click()
  await frame.getByText('В системе DPMS', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: В системе')
  await expect.poll(() => stats.puts).toBe(1)
  expect(serverGraphs.has('graph-demo')).toBe(true)

  await frame.locator('#graphTitle').fill('Синхронизированный граф')
  await frame.locator('#graphTitle').press('Enter')
  await expect.poll(() => stats.puts, { timeout: 5_000 }).toBeGreaterThanOrEqual(2)
  await expect.poll(() => serverGraphs.get('graph-demo')?.title).toBe('Синхронизированный граф')

  const changedElsewhere = structuredClone(serverGraphs.get('graph-demo')!)
  changedElsewhere.revision += 1
  changedElsewhere.title = 'Изменён на другом устройстве'
  changedElsewhere.payload.title = changedElsewhere.title
  changedElsewhere.updated_at = '2026-09-22T13:00:00Z'
  serverGraphs.set('graph-demo', changedElsewhere)
  await page.reload()
  await expect(frame.locator('#graphTitle')).toHaveValue('Изменён на другом устройстве')

  await storageButton.click()
  await frame.getByText('На этом устройстве', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: На устройстве')
  expect(stats.deletes).toBe(1)
  expect(serverGraphs.has('graph-demo')).toBe(false)
})

test('A server graph can be opened on another browser session', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Cross-device flow is covered once on desktop')
  await installApiMock(page, [serverGraph()])
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await frame.getByRole('button', { name: 'Открыть список графов' }).click()
  const row = frame.locator('[data-server-graph-id="server-graph"]')
  await expect(row).toContainText('Граф из системы')
  await row.getByRole('button', { name: 'Открыть' }).click()
  await expect(frame.locator('#graphTitle')).toHaveValue('Граф из системы')
  await expect(frame.getByRole('button', { name: /Хранение графа:/ })).toHaveAttribute('aria-label', 'Хранение графа: В системе')
})

test('Import creates a separate local graph and never uploads it implicitly', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Import privacy is covered once on desktop')
  const { stats } = await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const storageButton = frame.getByRole('button', { name: /Хранение графа:/ })
  await storageButton.click()
  await frame.getByText('В системе DPMS', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: В системе')
  const putsBeforeImport = stats.puts

  const imported = serverGraph('external-file-id', 'Импортированный граф').payload
  await frame.locator('#importInput').setInputFiles({
    name: 'imported-graph.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(imported)),
  })

  await expect(frame.locator('#graphTitle')).toHaveValue('Импортированный граф')
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: На устройстве')
  await page.waitForTimeout(1_100)
  expect(stats.puts).toBe(putsBeforeImport)

  const stored = await page.evaluate((ownerId) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v2:${ownerId}`) || '{}'
  ), userId) as {
    activeGraphId: string
    graphs: Array<{ id: string; title: string }>
    storage: Record<string, { mode: string }>
  }
  expect(stored.graphs).toHaveLength(2)
  expect(stored.activeGraphId).not.toBe('external-file-id')
  expect(stored.storage[stored.activeGraphId]?.mode).toBe('local')
})

test('Storage cannot be removed while a server save is still running', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Save race is covered once on desktop')
  const { behavior, serverGraphs, stats } = await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const storageButton = frame.getByRole('button', { name: /Хранение графа:/ })
  await storageButton.click()
  await frame.getByText('В системе DPMS', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: В системе')

  behavior.putDelayMs = 3_000
  await frame.locator('#graphTitle').fill('Изменение в процессе записи')
  await frame.locator('#graphTitle').press('Enter')
  await expect.poll(() => stats.puts, { timeout: 5_000 }).toBeGreaterThanOrEqual(2)
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: Сохраняем…')

  await storageButton.click()
  await frame.getByText('На этом устройстве', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(frame.locator('#storageDialogStatus')).toContainText('Дождитесь завершения')
  expect(serverGraphs.has('graph-demo')).toBe(true)

  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: В системе', { timeout: 5_000 })
  behavior.putDelayMs = 0
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: На устройстве')
  expect(serverGraphs.has('graph-demo')).toBe(false)
})

test('Opening a server graph never overflows the local cache', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Cache limit is covered once on desktop')
  const { stats } = await installApiMock(page, [serverGraph()])
  await page.addInitScript(({ ownerId }) => {
    const now = '2026-09-22T12:00:00Z'
    const graphs = Array.from({ length: 100 }, (_, index) => {
      const graphId = `local-${index + 1}`
      const viewId = `view-${index + 1}`
      return {
        version: 2,
        id: graphId,
        title: `Локальный граф ${index + 1}`,
        createdAt: now,
        updatedAt: now,
        viewport: { x: 0, y: 0, scale: 1 },
        nodes: [],
        edges: [],
        groups: [],
        views: [{
          id: viewId,
          name: 'Основной вид',
          layout: 'radial',
          positions: {},
          viewport: { x: 0, y: 0, scale: 1 },
          focusNodeId: null,
          focusDepth: 0,
        }],
        activeViewId: viewId,
        audit: [],
      }
    })
    const storage = Object.fromEntries(graphs.map((graph) => [graph.id, {
      mode: 'local', revision: null, serverUpdatedAt: null, syncState: 'local', error: '',
    }]))
    window.localStorage.setItem(`dpms-graphs-workspace-v2:${ownerId}`, JSON.stringify({
      version: 2,
      activeGraphId: graphs[0].id,
      graphs,
      storage,
    }))
  }, { ownerId: userId })
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await frame.getByRole('button', { name: 'Открыть список графов' }).click()
  await frame.locator('[data-server-graph-id="server-graph"]').getByRole('button', { name: 'Открыть' }).click()
  await expect(frame.locator('.toast')).toContainText('Локальный кэш содержит 100 графов')
  expect(stats.gets).toBe(0)
  const cachedCount = await page.evaluate((ownerId) => {
    const stored = JSON.parse(window.localStorage.getItem(`dpms-graphs-workspace-v2:${ownerId}`) || '{}')
    return Array.isArray(stored.graphs) ? stored.graphs.length : 0
  }, userId)
  expect(cachedCount).toBe(100)
})

test('A failed server save keeps a recoverable local copy', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Offline fallback is covered once on desktop')
  const { behavior } = await installApiMock(page)
  behavior.failPuts = true
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const storageButton = frame.getByRole('button', { name: /Хранение графа:/ })
  await storageButton.click()
  await frame.getByText('В системе DPMS', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(storageButton).toHaveAttribute('aria-label', 'Хранение графа: Локальные изменения')
  await expect(frame.locator('#storageDialogStatus')).toContainText('Сервис временно недоступен')

  const stored = await page.evaluate((id) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v2:${id}`) || '{}'
  ), userId) as { graphs?: Array<{ id: string }>; storage?: Record<string, { mode: string; syncState: string }> }
  expect(stored.graphs?.some((graph) => graph.id === 'graph-demo')).toBe(true)
  expect(stored.storage?.['graph-demo']).toMatchObject({ mode: 'system', syncState: 'offline' })
})

test('A revision conflict preserves local work as a separate graph', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Conflict flow is covered once on desktop')
  await installApiMock(page, [serverGraph('graph-demo', 'Серверная версия')])
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await frame.getByRole('button', { name: /Хранение графа:/ }).click()
  await frame.getByText('В системе DPMS', { exact: true }).click()
  await frame.getByRole('button', { name: 'Применить' }).click()
  await expect(frame.locator('#graphTitle')).toHaveValue('Карта работы — локальная версия')
  await expect(frame.getByRole('button', { name: /Хранение графа:/ })).toHaveAttribute('aria-label', 'Хранение графа: На устройстве')
  await expect(frame.locator('.toast')).toContainText('Ваши правки сохранены отдельным локальным графом')

  await frame.getByRole('button', { name: 'Открыть список графов' }).click()
  await expect(frame.locator('.graph-list-row')).toHaveCount(2)
  await expect(frame.locator('.graph-list')).toContainText('Серверная версия')
  await expect(frame.locator('.graph-list')).toContainText('Карта работы — локальная версия')
})
