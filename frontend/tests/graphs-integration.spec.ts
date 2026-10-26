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
  const behavior = { failPuts: false, putDelayMs: 0, listDelayMs: 0, getDelayMs: 0 }
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
      if (behavior.listDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, behavior.listDelayMs))
      }
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
        if (behavior.getDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, behavior.getDelayMs))
        }
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

type LayoutGraph = {
  activeViewId: string
  nodes: Array<{ id: string; title: string; x: number; y: number; autoSize: boolean; pinned: boolean }>
  edges: Array<{ id: string; source: string; target: string }>
  views: Array<{ id: string; layout: string; positions: Record<string, { x: number; y: number }> }>
}

async function readActiveStoredGraph(page: Page): Promise<LayoutGraph> {
  const graph = await page.evaluate((ownerId) => {
    const stored = JSON.parse(window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}') as {
      activeGraphId: string
      graphs?: Array<LayoutGraph & { id: string }>
    }
    return stored.graphs?.find((item) => item.id === stored.activeGraphId)
  }, userId)
  expect(graph, 'The active graph must be persisted locally').toBeTruthy()
  return graph!
}

function graphPositions(graph: LayoutGraph) {
  return graph.nodes.map(({ id, x, y }) => ({ id, x, y }))
}

async function selectGraphLayout(page: Page, layout: 'radial' | 'compact' | 'hierarchy') {
  const before = graphPositions(await readActiveStoredGraph(page))
  const field = page.frameLocator('iframe[title="Рабочее пространство графов"]').locator('#viewLayoutField')
  await field.selectOption(layout)
  await expect(field).toHaveValue(layout)
  await expect.poll(async () => {
    const graph = await readActiveStoredGraph(page)
    return graph.views.find((view) => view.id === graph.activeViewId)?.layout
  }).toBe(layout)
  await expect.poll(async () => graphPositions(await readActiveStoredGraph(page)), {
    message: 'Selecting a layout must move nodes without a separate Arrange action',
  }).not.toEqual(before)
  return readActiveStoredGraph(page)
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
    window.localStorage.getItem(`dpms-graphs-workspace-v3:${id}`) !== null
  ), userId)).toBe(true)

  const frameSource = await frameElement.getAttribute('src')
  expect(frameSource).toContain(`owner=${encodeURIComponent(userId)}`)

  if (testInfo.project.name === 'chromium-desktop') {
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
    await expect(frame.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect(frame.locator('#themeButton')).toHaveCount(0)
  }

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

test('Connection lens is opt-in and persists for the active view', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Connection lens interaction is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const lens = frame.getByRole('checkbox', { name: 'Линза связей' })
  const origin = frame.locator('[data-node-id="demo-task"]')
  const unrelated = frame.locator('[data-node-id="demo-tracker"]')

  await expect(lens).not.toBeChecked()
  await origin.hover()
  await expect(origin).not.toHaveClass(/hover-origin/)
  await expect(unrelated).not.toHaveClass(/hover-muted/)

  await lens.check()
  await origin.hover()
  await expect(origin).toHaveClass(/hover-origin/)
  await expect(unrelated).toHaveClass(/hover-muted/)
  await expect(frame.locator('#canvas')).toHaveClass(/has-connection-lens/)

  await page.reload()
  const reloadedFrame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await expect(reloadedFrame.getByRole('checkbox', { name: 'Линза связей' })).toBeChecked()
  await reloadedFrame.locator('[data-node-id="demo-task"]').hover()
  await expect(reloadedFrame.locator('[data-node-id="demo-tracker"]')).toHaveClass(/hover-muted/)

  await reloadedFrame.getByRole('checkbox', { name: 'Линза связей' }).uncheck()
  await expect(reloadedFrame.locator('[data-node-id="demo-tracker"]')).not.toHaveClass(/hover-muted/)
  await expect(reloadedFrame.locator('#canvas')).not.toHaveClass(/has-connection-lens/)
})

test('Editing is local-only and cloud snapshots require an explicit upload', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Storage workflow is covered once on desktop')
  const { serverGraphs, stats } = await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const storageButton = frame.getByRole('button', { name: /Локальное хранение:/ })
  await expect(storageButton).toContainText('Локально')

  await frame.locator('#graphTitle').fill('Локальный рабочий граф')
  await frame.locator('#graphTitle').press('Enter')
  await page.waitForTimeout(1_000)
  expect(stats.puts).toBe(0)

  await frame.locator('#graphManagerButton').click()
  const localRow = frame.locator('[data-graph-id="graph-demo"]')
  await localRow.locator('[data-graph-publish]').click()
  await expect.poll(() => stats.puts).toBe(1)
  expect(serverGraphs.get('graph-demo')?.title).toBe('Локальный рабочий граф')
  await expect(localRow).toContainText('Опубликован')

  await frame.getByRole('button', { name: 'Закрыть список графов' }).click()
  await frame.locator('#graphTitle').fill('Новая локальная версия')
  await frame.locator('#graphTitle').press('Enter')
  await page.waitForTimeout(1_000)
  expect(stats.puts).toBe(1)
  await expect(storageButton).toContainText('есть изменения')

  await storageButton.click()
  await frame.locator('[data-graph-id="graph-demo"] [data-graph-publish]').click()
  await expect.poll(() => stats.puts).toBe(2)
  expect(serverGraphs.get('graph-demo')?.title).toBe('Новая локальная версия')

  await frame.locator('[data-graph-id="graph-demo"] [data-graph-duplicate]').click()
  await expect(frame.locator('[data-graph-id]')).toHaveCount(2)
  page.once('dialog', (dialog) => dialog.accept())
  await frame.locator('[data-graph-id="graph-demo"] [data-graph-delete]').click()
  await expect(frame.locator('[data-graph-id="graph-demo"]')).toHaveCount(0)
  expect(stats.deletes).toBe(0)
  expect(serverGraphs.get('graph-demo')?.title).toBe('Новая локальная версия')
})

test('Edits made during a slow publish stay marked as newer local work', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Publish races are covered once on desktop')
  const { behavior, serverGraphs, stats } = await installApiMock(page)
  behavior.putDelayMs = 700
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await frame.locator('#graphManagerButton').click()
  await frame.locator('[data-graph-id="graph-demo"] [data-graph-publish]').click()
  await expect.poll(() => stats.puts).toBe(1)
  await frame.getByRole('button', { name: 'Закрыть список графов' }).click()
  await frame.locator('#graphTitle').fill('Изменено во время публикации')
  await frame.locator('#graphTitle').press('Enter')

  await expect.poll(() => serverGraphs.get('graph-demo')?.title).toBe('Карта работы')
  await expect(frame.getByRole('button', { name: /Локальное хранение:/ })).toContainText('есть изменения')
  await page.reload()
  await expect(frame.locator('#graphTitle')).toHaveValue('Изменено во время публикации')
  await expect(frame.getByRole('button', { name: /Локальное хранение:/ })).toContainText('есть изменения')
})

test('A rejected localStorage write rolls the visible edit back', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Storage quota rollback is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await expect(frame.locator('#canvas')).toBeVisible()
  const workspaceFrame = page.frames().find((item) => item.url().includes('/graph-workspace/index.html'))
  expect(workspaceFrame).toBeTruthy()

  await frame.locator('[data-node-id="demo-note"]').click()
  await frame.locator('#nodeTitleField').fill('Сохранённое название')
  await frame.locator('#nodeTitleField').press('Tab')
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Сохранённое название')
  await workspaceFrame!.evaluate(() => {
    const state = window as typeof window & { __rejectGraphWrites?: boolean }
    const prototype = Object.getPrototypeOf(window.localStorage) as Storage
    const original = prototype.setItem
    state.__rejectGraphWrites = true
    prototype.setItem = function setItem(key: string, value: string) {
      if (state.__rejectGraphWrites && key.startsWith('dpms-graphs-workspace-v3')) throw new DOMException('Quota exceeded', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  await frame.locator('#nodeTitleField').fill('Несохранённое название')
  await frame.locator('#nodeTitleField').press('Tab')

  await expect(frame.locator('#toastRegion')).toContainText('Локальное хранилище заполнено')
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Сохранённое название')

  const storedBeforeLayout = await readActiveStoredGraph(page)
  const layoutField = frame.locator('#viewLayoutField')
  const modeBeforeLayout = await layoutField.inputValue()
  expect(modeBeforeLayout).not.toBe('compact')
  const worldStyleBeforeLayout = await frame.locator('#world').getAttribute('style')
  expect(worldStyleBeforeLayout).not.toBeNull()
  const readVisibleNodePositions = () => frame.locator('.graph-node').evaluateAll((nodes) => nodes.map((node) => ({
    id: node.getAttribute('data-node-id'),
    left: (node as HTMLElement).style.left,
    top: (node as HTMLElement).style.top,
  })))
  const positionsBeforeLayout = await readVisibleNodePositions()

  await layoutField.selectOption('compact')
  // Let any deferred fit-to-graph run before asserting the rollback is stable.
  await workspaceFrame!.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
  await expect(layoutField).toHaveValue(modeBeforeLayout)
  expect(await readVisibleNodePositions()).toEqual(positionsBeforeLayout)
  await expect(frame.locator('#world')).toHaveAttribute('style', worldStyleBeforeLayout!)
  expect(await readActiveStoredGraph(page)).toEqual(storedBeforeLayout)
  await expect(frame.locator('#toastRegion')).toContainText('Локальное хранилище заполнено')
  await expect(frame.locator('#toastRegion')).not.toContainText('Граф упорядочен и показан целиком')

  await frame.locator('#canvas').focus()
  await page.keyboard.press('Control+z')
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Сохранённое название')
  await workspaceFrame!.evaluate(() => {
    const state = window as typeof window & { __rejectGraphWrites?: boolean }
    state.__rejectGraphWrites = false
  })
  await page.keyboard.press('Control+z')
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Заметка: идея нового процесса')
  await workspaceFrame!.evaluate(() => {
    const state = window as typeof window & { __rejectGraphWrites?: boolean }
    state.__rejectGraphWrites = true
  })
  await page.keyboard.press('Control+y')
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Заметка: идея нового процесса')
  await page.reload()
  await expect(frame.locator('[data-node-id="demo-note"]')).toContainText('Заметка: идея нового процесса')
})

test('A cloud snapshot downloads as a local graph and never overwrites local work', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Cross-device flow is covered once on desktop')
  const { stats } = await installApiMock(page, [serverGraph('graph-demo')])
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await frame.locator('#graphManagerButton').click()
  const row = frame.locator('[data-server-graph-id="graph-demo"]')
  await expect(row).toContainText('Граф из системы')
  await row.getByRole('button', { name: 'Скачать копию' }).click()
  await expect(frame.locator('#graphTitle')).toHaveValue('Граф из системы — облачная копия')
  await expect(frame.getByRole('button', { name: /Локальное хранение:/ })).toContainText('Локально')
  expect(stats.gets).toBe(1)

  const copiedWorkspace = await page.evaluate((ownerId) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}'
  ), userId) as { activeGraphId: string; graphs: Array<{ id: string; title: string }> }
  expect(copiedWorkspace.graphs).toHaveLength(2)
  expect(copiedWorkspace.activeGraphId).not.toBe('graph-demo')
  expect(copiedWorkspace.graphs).toContainEqual(expect.objectContaining({ id: 'graph-demo', title: 'Карта работы' }))

  await frame.locator('#graphTitle').fill('Изменено только на устройстве')
  await frame.locator('#graphTitle').press('Enter')
  await page.waitForTimeout(900)
  expect(stats.puts).toBe(0)
})

test('Import creates a separate local graph and never uploads it implicitly', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Import privacy is covered once on desktop')
  const { stats } = await installApiMock(page)
  await page.goto('/graphs')

  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const imported = serverGraph('external-file-id', 'Импортированный граф').payload
  await frame.locator('#importInput').setInputFiles({
    name: 'imported-graph.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)),
  })
  await frame.locator('#confirmImportButton').click()

  await expect(frame.locator('#graphTitle')).toHaveValue('Импортированный граф')
  await page.waitForTimeout(1_000)
  expect(stats.puts).toBe(0)
  const stored = await page.evaluate((ownerId) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}'
  ), userId) as { activeGraphId: string; graphs: Array<{ id: string }>; storage: Record<string, { mode: string; publishState: string }> }
  expect(stored.graphs).toHaveLength(2)
  expect(stored.storage[stored.activeGraphId]).toMatchObject({ mode: 'local', publishState: 'local' })
})

test('Failed publishing keeps the editable local graph intact', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Failure paths are covered once on desktop')
  const { behavior, stats } = await installApiMock(page)
  behavior.failPuts = true
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await frame.locator('#graphTitle').fill('Не потерять этот граф')
  await frame.locator('#graphTitle').press('Enter')
  await frame.locator('#graphManagerButton').click()
  await frame.locator('[data-graph-id="graph-demo"] [data-graph-publish]').click()
  await expect.poll(() => stats.puts).toBe(1)
  await expect(frame.locator('[data-graph-id="graph-demo"]')).toContainText('Сервис временно недоступен')

  await page.reload()
  await expect(frame.locator('#graphTitle')).toHaveValue('Не потерять этот граф')
  const stored = await page.evaluate((ownerId) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}'
  ), userId) as { graphs: Array<{ id: string; title: string }> }
  expect(stored.graphs).toContainEqual(expect.objectContaining({ id: 'graph-demo', title: 'Не потерять этот граф' }))
})

test('A real revision conflict never overwrites either local or server data', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Conflict handling is covered once on desktop')
  const remote = serverGraph('graph-demo', 'Серверная версия')
  const { behavior, serverGraphs, stats } = await installApiMock(page, [remote])
  behavior.listDelayMs = 700
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await frame.locator('#graphTitle').fill('Локальная версия')
  await frame.locator('#graphTitle').press('Enter')
  await frame.locator('#graphManagerButton').click()
  await frame.locator('[data-graph-id="graph-demo"] [data-graph-publish]').click()
  await expect.poll(() => stats.puts).toBe(1)
  await expect(frame.locator('[data-graph-id="graph-demo"]')).toContainText('Граф изменился в другой вкладке')
  expect(serverGraphs.get('graph-demo')?.title).toBe('Серверная версия')

  await page.reload()
  await expect(frame.locator('#graphTitle')).toHaveValue('Локальная версия')
})

test('An interrupted publish is reconciled to a retryable local state on reload', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Interrupted upload recovery is covered once on desktop')
  await installApiMock(page)
  const interruptedGraph = serverGraph('graph-demo', 'Прерванная публикация').payload
  await page.addInitScript(({ ownerId, graph }) => {
    window.localStorage.setItem(`dpms-graphs-workspace-v3:${ownerId}`, JSON.stringify({
      version: 3,
      activeGraphId: graph.id,
      graphs: [graph],
      storage: {
        [graph.id]: { mode: 'local', revision: null, serverUpdatedAt: null, publishState: 'publishing', error: '' },
      },
    }))
  }, { ownerId: userId, graph: interruptedGraph })
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await expect(frame.getByRole('button', { name: /Локальное хранение:/ })).toContainText('ошибка облака')
  await frame.locator('#graphManagerButton').click()
  const row = frame.locator('[data-graph-id="graph-demo"]')
  await expect(row).toContainText('Предыдущая публикация была прервана')
  await expect(row.locator('[data-graph-publish]')).toBeEnabled()
})

test('Version 2 local graphs migrate to the isolated version 3 workspace', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Local schema migration is covered once on desktop')
  await installApiMock(page)
  const legacyGraph = serverGraph('legacy-graph', 'Старый локальный граф').payload
  await page.addInitScript(({ ownerId, graph }) => {
    window.localStorage.setItem(`dpms-graphs-workspace-v2:${ownerId}`, JSON.stringify({
      version: 2,
      activeGraphId: graph.id,
      graphs: [graph],
      storage: { [graph.id]: { mode: 'local', revision: null, publishState: 'local' } },
    }))
  }, { ownerId: userId, graph: legacyGraph })
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await expect(frame.locator('#graphTitle')).toHaveValue('Старый локальный граф')
  const migrated = await page.evaluate((ownerId) => JSON.parse(
    window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}'
  ), userId) as { version: number; graphs: Array<{ version: number; nodes: Array<{ autoSize: boolean; width: number }> }> }
  expect(migrated.version).toBe(3)
  expect(migrated.graphs[0].version).toBe(3)
  expect(migrated.graphs[0].nodes[0]).toEqual(expect.objectContaining({ autoSize: true, width: 224 }))
})

test('Concurrent cloud downloads cannot overflow the local graph limit', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Download capacity is covered once on desktop')
  const { behavior, stats } = await installApiMock(page, [
    serverGraph('remote-a', 'Облачный A'),
    serverGraph('remote-b', 'Облачный B'),
  ])
  behavior.getDelayMs = 250
  const localGraphs = Array.from({ length: 99 }, (_, index) => serverGraph(`local-${index}`, `Локальный ${index}`).payload)
  await page.addInitScript(({ ownerId, graphs }) => {
    window.localStorage.setItem(`dpms-graphs-workspace-v3:${ownerId}`, JSON.stringify({
      version: 3,
      activeGraphId: graphs[0].id,
      graphs,
      storage: Object.fromEntries(graphs.map((graph: { id: string }) => [graph.id, {
        mode: 'local', revision: null, serverUpdatedAt: null, publishState: 'local', error: '',
      }])),
    }))
  }, { ownerId: userId, graphs: localGraphs })
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await frame.locator('#graphManagerButton').click()
  await expect(frame.locator('[data-server-graph-id="remote-a"]')).toBeVisible()
  await frame.locator('[data-server-graph-id="remote-a"] [data-server-graph-open]').click()
  await frame.locator('[data-server-graph-id="remote-b"] [data-server-graph-open]').click()
  await expect.poll(() => stats.gets).toBe(2)
  await expect.poll(async () => page.evaluate((ownerId) => {
    const stored = JSON.parse(window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}')
    return stored.graphs?.length || 0
  }, userId)).toBe(100)

  await page.reload()
  await expect(frame.locator('.app')).toBeVisible()
  await expect(frame.locator('#storageRecoveryDialog')).not.toBeVisible()
})

test('UI creation stops at the graph capacity instead of corrupting the workspace', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Graph capacity is covered once on desktop')
  await installApiMock(page)
  const capacityGraph = serverGraph('capacity-graph', 'Предельный граф').payload
  capacityGraph.version = 3
  capacityGraph.nodes = Array.from({ length: 1500 }, (_, index) => ({
    id: `capacity-node-${index}`,
    type: 'atom',
    title: `Атом ${index + 1}`,
    customTypeLabel: '', sourceRef: '', description: '', shape: 'rounded', radius: 8, scale: 1,
    autoSize: true, width: 190, height: 96, items: [], pinned: false, color: '#2F6BFF',
    x: (index % 50) * 220, y: Math.floor(index / 50) * 120,
  }))
  capacityGraph.edges = []
  capacityGraph.views = []
  await page.addInitScript(({ ownerId, graph }) => {
    window.localStorage.setItem(`dpms-graphs-workspace-v3:${ownerId}`, JSON.stringify({
      version: 3,
      activeGraphId: graph.id,
      graphs: [graph],
      storage: { [graph.id]: { mode: 'local', revision: null, serverUpdatedAt: null, publishState: 'local', error: '' } },
    }))
  }, { ownerId: userId, graph: capacityGraph })
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await expect(frame.locator('.graph-node')).toHaveCount(1500)
  await frame.locator('#railAddButton').click()
  await expect(frame.locator('#toastRegion')).toContainText('не более 1500 элементов')
  await expect(frame.locator('.graph-node')).toHaveCount(1500)
  await page.reload()
  await expect(frame.locator('#storageRecoveryDialog')).not.toBeVisible()
})

test('Hierarchy wizard preserves outline order across immediate layouts, undo and reload', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Hierarchy layout regression is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  await expect(frame.locator('.graph-node')).toHaveCount(4)
  const existing = await readActiveStoredGraph(page)
  const existingIds = new Set(existing.nodes.map((node) => node.id))
  const rows = [
    { title: 'Z root', depth: 0, parent: null },
    { title: 'Z short branch', depth: 1, parent: 0 },
    { title: 'Z short leaf', depth: 2, parent: 1 },
    { title: 'A long branch', depth: 1, parent: 0 },
    { title: 'Z deep branch', depth: 2, parent: 3 },
    { title: 'Z deepest leaf', depth: 3, parent: 4 },
    { title: 'A deepest leaf', depth: 3, parent: 4 },
    { title: 'A wide leaf', depth: 2, parent: 3 },
    { title: 'M wide leaf', depth: 2, parent: 3 },
    { title: 'M root leaf', depth: 1, parent: 0 },
    { title: 'A root', depth: 0, parent: null },
    { title: 'Z second leaf', depth: 1, parent: 10 },
    { title: 'A second leaf', depth: 1, parent: 10 },
  ]
  await frame.getByRole('button', { name: 'Мастер иерархий' }).click()
  await frame.locator('#hierarchySource').fill(rows.map(({ title, depth }) => `${'\t'.repeat(depth)}${title}`).join('\n'))
  await frame.locator('#hierarchyNodeType').selectOption('atom')
  await frame.getByRole('button', { name: 'Построить граф', exact: true }).click()
  await expect(frame.locator('#hierarchyDialog')).toBeHidden()
  await expect(frame.locator('.graph-node')).toHaveCount(existing.nodes.length + rows.length)
  await expect(frame.locator('#viewLayoutField')).toHaveValue('hierarchy')

  const initial = await readActiveStoredGraph(page)
  const outlineNodes = initial.nodes.filter((node) => !existingIds.has(node.id))
  const outlineIds = outlineNodes.map((node) => node.id)
  expect(outlineNodes.map((node) => node.title)).toEqual(rows.map((row) => row.title))
  expect(outlineNodes.every((node) => node.autoSize)).toBe(true)
  expect(graphPositions(initial).filter((node) => existingIds.has(node.id))).toEqual(graphPositions(existing))
  const expectedEdges = rows.flatMap((row, index) => row.parent === null ? [] : [{
    source: outlineIds[row.parent], target: outlineIds[index],
  }])
  expect(initial.edges.filter((edge) => outlineIds.includes(edge.source) || outlineIds.includes(edge.target))
    .map(({ source, target }) => ({ source, target }))).toEqual(expectedEdges)
  expect(initial.edges).toHaveLength(existing.edges.length + expectedEdges.length)
  await expect(frame.locator('.edge-group')).toHaveCount(initial.edges.length)

  function expectOutline(graph: LayoutGraph) {
    expect(graph.nodes.map((node) => node.id)).toEqual(initial.nodes.map((node) => node.id))
    expect(graph.edges).toEqual(initial.edges)
    const view = graph.views.find((item) => item.id === graph.activeViewId)!
    expect(view.layout).toBe('hierarchy')
    const nodes = graph.nodes.filter((node) => outlineIds.includes(node.id))
    nodes.forEach((node, index) => {
      expect(Number.isFinite(node.x) && Number.isFinite(node.y), node.title).toBe(true)
      expect(view.positions[node.id]).toEqual({ x: node.x, y: node.y })
      expect(node.x - nodes[0].x, `${node.title}: relative x`).toBeCloseTo(outlineNodes[index].x - outlineNodes[0].x, 0)
      expect(node.y - nodes[0].y, `${node.title}: relative y`).toBeCloseTo(outlineNodes[index].y - outlineNodes[0].y, 0)
      if (index > 0) expect(node.y, `${node.title}: preorder row`).toBeGreaterThan(nodes[index - 1].y)
      const parent = rows[index].parent
      if (parent !== null) expect(node.x, `${node.title}: indentation`).toBeGreaterThan(nodes[parent].x)
      else expect(node.x).toBe(nodes[0].x)
    })
  }

  async function expectNoOutlineOverlap() {
    // Fit-to-graph can hide full-sized cards behind semantic-zoom circles.
    for (let attempt = 0; attempt < 20 && (await frame.locator('#canvas').getAttribute('class'))?.includes('semantic-compact'); attempt += 1) {
      await frame.locator('#zoomInButton').click()
    }
    await expect(frame.locator('#canvas')).not.toHaveClass(/semantic-compact/)
    const boxes = await frame.locator('.graph-node').evaluateAll((elements, ids) => elements
      .filter((element) => ids.includes(element.getAttribute('data-node-id') || ''))
      .map((element) => {
        const { x, y, width, height } = element.getBoundingClientRect()
        return { id: element.getAttribute('data-node-id'), x, y, width, height }
      }), outlineIds)
    expect(boxes).toHaveLength(rows.length)
    expect(new Set(boxes.map((box) => Math.round(box.width))).size, 'Different degrees must exercise dynamic sizes').toBeGreaterThan(1)
    boxes.forEach((box, index) => {
      expect(box.width).toBeGreaterThan(0)
      expect(box.height).toBeGreaterThan(0)
      boxes.slice(index + 1).forEach((other) => {
        const overlapX = Math.min(box.x + box.width, other.x + other.width) - Math.max(box.x, other.x)
        const overlapY = Math.min(box.y + box.height, other.y + other.height) - Math.max(box.y, other.y)
        expect(Math.min(overlapX, overlapY), `Cards ${box.id} and ${other.id} overlap`).toBeLessThanOrEqual(0.5)
      })
    })
  }

  expectOutline(initial)
  await expectNoOutlineOverlap()
  const radial = await selectGraphLayout(page, 'radial')
  const compact = await selectGraphLayout(page, 'compact')
  await frame.locator('#undoButton').click()
  await expect(frame.locator('#viewLayoutField')).toHaveValue('radial')
  await expect.poll(async () => graphPositions(await readActiveStoredGraph(page))).toEqual(graphPositions(radial))
  await frame.locator('#redoButton').click()
  await expect(frame.locator('#viewLayoutField')).toHaveValue('compact')
  await expect.poll(async () => graphPositions(await readActiveStoredGraph(page))).toEqual(graphPositions(compact))

  const restored = await selectGraphLayout(page, 'hierarchy')
  expectOutline(restored)
  await expectNoOutlineOverlap()
  await frame.locator('#fitButton').click()
  mkdirSync('test-results/graphs', { recursive: true })
  await page.screenshot({ path: 'test-results/graphs/hierarchy-restored.png', fullPage: false })
  await page.reload()
  await expect(frame.locator('.graph-node')).toHaveCount(initial.nodes.length)
  await expect(frame.locator('.edge-group')).toHaveCount(initial.edges.length)
  await expect(frame.locator('#viewLayoutField')).toHaveValue('hierarchy')
  const reloaded = await readActiveStoredGraph(page)
  expect(reloaded.activeViewId).toBe(initial.activeViewId)
  expect(graphPositions(reloaded)).toEqual(graphPositions(restored))
  expectOutline(reloaded)
  await expectNoOutlineOverlap()
})

test('Hierarchy layout keeps imported cycles, multiple parents and pinned positions deterministic', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Cyclic hierarchy regression is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const imported = serverGraph('cyclic-outline', 'Cyclic hierarchy fixture').payload
  const baseNode = imported.nodes[0] as Record<string, unknown>
  const nodes = ['z-cycle', 'a-cycle', 'm-cycle', 'second-parent', 'pinned', 'isolated'].map((id, index) => ({
    ...baseNode, id, title: id, autoSize: true, pinned: id === 'pinned', x: 900 + index * 310, y: -600 + index * 140,
  }))
  const edges = [
    ['z-cycle', 'a-cycle'], ['a-cycle', 'm-cycle'], ['m-cycle', 'z-cycle'],
    ['second-parent', 'a-cycle'], ['pinned', 'm-cycle'],
  ].map(([source, target], index) => ({ id: `cycle-edge-${index}`, source, target, label: 'дочерний' }))
  Object.assign(imported, { version: 3, nodes, edges, views: [], activeViewId: '' })
  await frame.locator('#importInput').setInputFiles({
    name: 'cyclic-outline.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)),
  })
  await frame.locator('#confirmImportButton').click()
  await expect(frame.locator('#graphTitle')).toHaveValue(imported.title)
  await expect(frame.locator('.graph-node')).toHaveCount(nodes.length)
  const before = await readActiveStoredGraph(page)
  const pinned = nodes.find((node) => node.pinned)!

  function expectIntact(graph: LayoutGraph) {
    expect(graph.nodes.map((node) => node.id)).toEqual(nodes.map((node) => node.id))
    expect(graph.edges).toEqual(before.edges)
    expect(graph.edges.map(({ id, source, target }) => ({ id, source, target })))
      .toEqual(edges.map(({ id, source, target }) => ({ id, source, target })))
    expect(graph.nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y))).toBe(true)
    expect(graph.nodes.find((node) => node.id === pinned.id)).toMatchObject({ pinned: true, x: pinned.x, y: pinned.y })
  }

  async function expectHierarchyMode() {
    await expect(frame.locator('#viewLayoutField')).toHaveValue('hierarchy')
    const graph = await readActiveStoredGraph(page)
    expect(graph.views.find((view) => view.id === graph.activeViewId)?.layout).toBe('hierarchy')
  }

  expectIntact(before)
  const first = await selectGraphLayout(page, 'hierarchy')
  expectIntact(first)
  for (const button of ['#arrangeButton', '#railArrangeButton']) {
    await frame.locator(button).click()
    await expectHierarchyMode()
    await expect.poll(async () => graphPositions(await readActiveStoredGraph(page))).toEqual(graphPositions(first))
    expectIntact(await readActiveStoredGraph(page))
  }
  expectIntact(await selectGraphLayout(page, 'compact'))
  const repeated = await selectGraphLayout(page, 'hierarchy')
  await expectHierarchyMode()
  expectIntact(repeated)
  expect(graphPositions(repeated)).toEqual(graphPositions(first))
  await expect(frame.locator('.graph-node')).toHaveCount(nodes.length)
  await expect(frame.locator('.edge-group')).toHaveCount(edges.length)
})

test('A large binary hierarchy stays inside coordinate limits and survives reload unchanged', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Hierarchy coordinate limits are covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const imported = serverGraph('binary-outline', 'Binary hierarchy bounds fixture').payload
  const baseNode = imported.nodes[0] as Record<string, unknown>
  const nodes = Array.from({ length: 1023 }, (_, index) => ({
    ...baseNode, id: `tree-node-${index}`, title: `Branch ${index}`, autoSize: false,
    width: 224, height: 108, pinned: false, x: (index % 32) * 300, y: Math.floor(index / 32) * 140,
  }))
  const edges = nodes.slice(1).map((node, index) => ({
    id: `tree-edge-${index}`, source: nodes[Math.floor(index / 2)].id, target: node.id, label: 'дочерний',
  }))
  Object.assign(imported, { version: 3, nodes, edges, views: [], activeViewId: '' })
  await frame.locator('#importInput').setInputFiles({
    name: 'binary-outline.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(imported)),
  })
  await frame.locator('#confirmImportButton').click()
  await expect(frame.locator('#graphTitle')).toHaveValue(imported.title)
  await expect(frame.locator('.graph-node')).toHaveCount(nodes.length)
  const before = await readActiveStoredGraph(page)
  const arranged = await selectGraphLayout(page, 'hierarchy')
  expect(arranged.nodes.map((node) => node.id)).toEqual(nodes.map((node) => node.id))
  expect(arranged.edges).toEqual(before.edges)
  expect(arranged.edges).toHaveLength(edges.length)
  expect(arranged.nodes.filter((node) => !Number.isFinite(node.x) || !Number.isFinite(node.y)
    || Math.abs(node.x) > 100_000 || Math.abs(node.y) > 100_000), 'No coordinate may be clamped on reload').toEqual([])
  const ys = arranged.nodes.map((node) => node.y)
  expect(Math.max(...ys) - Math.min(...ys), 'The fixture must require translation into the allowed range').toBeGreaterThan(100_000)
  const view = arranged.views.find((item) => item.id === arranged.activeViewId)!
  expect(view.positions).toEqual(Object.fromEntries(arranged.nodes.map(({ id, x, y }) => [id, { x, y }])))

  await page.reload()
  await expect(frame.locator('.graph-node')).toHaveCount(nodes.length)
  await expect(frame.locator('.edge-group')).toHaveCount(edges.length)
  await expect(frame.locator('#viewLayoutField')).toHaveValue('hierarchy')
  const reloaded = await readActiveStoredGraph(page)
  expect(reloaded.activeViewId).toBe(arranged.activeViewId)
  expect(reloaded.views.find((item) => item.id === reloaded.activeViewId)).toMatchObject({ layout: 'hierarchy', positions: view.positions })
  expect(reloaded.edges).toEqual(arranged.edges)
  // Exact absolute coordinates also preserve every root-relative offset.
  expect(graphPositions(reloaded)).toEqual(graphPositions(arranged))
})

test('Sticker flow, hierarchy builder, list atoms, resizing and edge routing work together', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Dense canvas interactions are covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  await frame.getByRole('button', { name: 'Создать стикер' }).click()
  await frame.locator('#canvas').click({ position: { x: 280, y: 680 } })
  await expect(frame.locator('#inlineNodeEditor')).toBeVisible()
  await frame.locator('#inlineNodeEditor').fill('Первый стикер')
  await frame.locator('#inlineNodeEditor').press('Tab')
  await frame.locator('#inlineNodeEditor').fill('Второй стикер')
  await frame.locator('#inlineNodeEditor').press('Enter')
  await expect(frame.locator('#inlineNodeEditor')).toBeHidden()
  await page.reload()
  await expect(frame.locator('.graph-node.sticker')).toHaveCount(2)
  await expect(frame.locator('.graph-node.sticker').nth(0)).toContainText('Первый стикер')
  await expect(frame.locator('.graph-node.sticker').nth(1)).toContainText('Второй стикер')

  await frame.getByRole('button', { name: 'Выбор и перемещение' }).click()
  const secondSticker = frame.locator('.graph-node.sticker').nth(1)
  await secondSticker.click()
  const before = await secondSticker.boundingBox()
  const handle = secondSticker.locator('[data-resize-handle="se"]')
  const handleBox = await handle.boundingBox()
  expect(before).not.toBeNull()
  expect(handleBox).not.toBeNull()
  await page.mouse.move(handleBox!.x + handleBox!.width / 2, handleBox!.y + handleBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(handleBox!.x + 85, handleBox!.y + 45)
  await page.mouse.up()
  const after = await secondSticker.boundingBox()
  expect(after!.width).toBeGreaterThan(before!.width + 40)

  await frame.locator('#autoSizeField').check()
  await expect(secondSticker.locator('[data-resize-handle]')).toHaveCount(0)

  const circleNode = frame.locator('[data-node-id="demo-tracker"]')
  await circleNode.click()
  await frame.locator('#autoSizeField').uncheck()
  await frame.locator('#nodeWidthField').fill('132')
  await frame.locator('#nodeWidthField').press('Tab')
  await expect(frame.locator('#nodeWidthField')).toHaveValue('132')
  const circleBefore = await circleNode.boundingBox()
  const circleHandle = circleNode.locator('[data-resize-handle="e"]')
  const circleHandleBox = await circleHandle.boundingBox()
  expect(circleBefore).not.toBeNull()
  expect(circleHandleBox).not.toBeNull()
  await page.mouse.move(circleHandleBox!.x + circleHandleBox!.width / 2, circleHandleBox!.y + circleHandleBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(circleHandleBox!.x - 45, circleHandleBox!.y + circleHandleBox!.height / 2)
  await page.mouse.up()
  const circleAfter = await circleNode.boundingBox()
  expect(circleAfter!.width).toBeLessThan(circleBefore!.width - 20)

  const circlePanHandleBox = await circleHandle.boundingBox()
  const transformBeforeHandlePan = await frame.locator('#world').getAttribute('style')
  await page.keyboard.down('Space')
  await page.mouse.move(circlePanHandleBox!.x + circlePanHandleBox!.width / 2, circlePanHandleBox!.y + circlePanHandleBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(circlePanHandleBox!.x + 55, circlePanHandleBox!.y + 35)
  await page.mouse.up()
  await page.keyboard.up('Space')
  await expect(frame.locator('#world')).not.toHaveAttribute('style', transformBeforeHandlePan || '')
  const circleAfterHandlePan = await circleNode.boundingBox()
  expect(Math.abs(circleAfterHandlePan!.width - circleAfter!.width)).toBeLessThan(1)

  const firstSticker = frame.locator('.graph-node.sticker').nth(0)
  const firstStickerBox = await firstSticker.boundingBox()
  const secondStickerBox = await secondSticker.boundingBox()
  const canvasBox = await frame.locator('#canvas').boundingBox()
  expect(firstStickerBox).not.toBeNull()
  expect(secondStickerBox).not.toBeNull()
  expect(canvasBox).not.toBeNull()
  const marqueeStart = {
    x: Math.max(canvasBox!.x + 4, Math.min(firstStickerBox!.x, secondStickerBox!.x) - 8),
    y: Math.max(canvasBox!.y + 4, Math.min(firstStickerBox!.y, secondStickerBox!.y) - 8),
  }
  const marqueeEnd = {
    x: Math.min(canvasBox!.x + canvasBox!.width - 4, Math.max(firstStickerBox!.x + firstStickerBox!.width, secondStickerBox!.x + secondStickerBox!.width) + 8),
    y: Math.min(canvasBox!.y + canvasBox!.height - 4, Math.max(firstStickerBox!.y + firstStickerBox!.height, secondStickerBox!.y + secondStickerBox!.height) + 8),
  }
  await page.mouse.move(marqueeStart.x, marqueeStart.y)
  await page.mouse.down()
  await page.mouse.move(marqueeEnd.x, marqueeEnd.y, { steps: 8 })
  await page.mouse.up()
  await expect(frame.locator('.graph-node.sticker.selected')).toHaveCount(2)

  await frame.getByRole('button', { name: 'Мастер иерархий' }).click()
  const hierarchyOutline = 'Корень\n\tРаздел A\n\t\tАтом A1\n\tРаздел B'
  const hierarchySource = frame.locator('#hierarchySource')
  await hierarchySource.fill(hierarchyOutline)
  await hierarchySource.evaluate((field: HTMLTextAreaElement) => {
    const position = field.value.indexOf('Атом A1') + 'Атом A1'.length
    field.setSelectionRange(position, position)
  })
  await hierarchySource.press('Shift+Tab')
  await expect(hierarchySource).not.toBeFocused()
  await expect(hierarchySource).toHaveValue(hierarchyOutline)
  await hierarchySource.focus()
  await hierarchySource.evaluate((field: HTMLTextAreaElement) => field.setSelectionRange(field.value.length, field.value.length))
  await hierarchySource.press('Tab')
  await expect(frame.locator('#hierarchyNodeType')).toBeFocused()
  await hierarchySource.focus()
  await hierarchySource.press('Control+Enter')
  await expect(frame.locator('.graph-node')).toHaveCount(10)
  await expect(frame.locator('.edge-group')).toHaveCount(6)

  await frame.locator('[data-entity-type="list"]').click()
  await frame.locator('#addCenterButton').click()
  await frame.locator('#nodeItemsField').fill('Пункт один\nПункт два\nПункт три')
  await frame.locator('#convertListButton').click()
  await expect(frame.locator('.graph-node[data-node-id]')).toHaveCount(14)
  await expect(frame.locator('.graph-node[data-node-type="atom"]').filter({ hasText: 'Пункт один' })).toHaveCount(1)

  const firstEdge = frame.locator('.edge-group').first()
  await firstEdge.locator('.edge-hit').click({ force: true })
  await frame.locator('#edgeRoutingField').selectOption('orthogonal')
  await firstEdge.locator('.edge-hit').dblclick({ force: true })
  await expect(frame.locator('.edge-control-point')).toHaveCount(1)
  const pathBeforePointDrag = await firstEdge.locator('.edge-line').getAttribute('d')
  const orthogonalCoordinates = [...(pathBeforePointDrag || '').matchAll(/[ML]\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)/g)]
    .map((match) => ({ x: Number(match[1]), y: Number(match[2]) }))
  expect(orthogonalCoordinates.length).toBeGreaterThan(2)
  // Compact circles keep radial terminal stubs; all interior segments remain axial.
  orthogonalCoordinates.slice(1, -1).forEach((point, index) => {
    if (index === 0) return
    const previous = orthogonalCoordinates[index]
    expect(Math.abs(point.x - previous.x) < 0.001 || Math.abs(point.y - previous.y) < 0.001).toBe(true)
  })
  const edgePoint = frame.locator('.edge-control-point').first()
  const edgePointBox = await edgePoint.boundingBox()
  expect(edgePointBox).not.toBeNull()
  await page.mouse.move(edgePointBox!.x + edgePointBox!.width / 2, edgePointBox!.y + edgePointBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(edgePointBox!.x + 32, edgePointBox!.y + 24)
  await page.mouse.up()
  await expect(firstEdge.locator('.edge-line')).not.toHaveAttribute('d', pathBeforePointDrag || '')
  await expect(frame.locator('#connectionLens')).toHaveCount(0)
})

test('Custom shortcuts persist and Space plus drag pans the canvas', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Keyboard interaction is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')

  const helpButton = frame.getByRole('button', { name: 'Открыть справку' })
  await helpButton.focus()
  await helpButton.press('Space')
  await expect(frame.locator('#helpDialog')).toBeVisible()
  await frame.getByRole('button', { name: 'Закрыть справку' }).click()

  await expect(frame.locator('.graph-node')).toHaveCount(4)
  await expect(frame.locator('.edge-group')).toHaveCount(3)
  const initialNodeCount = await frame.locator('.graph-node').count()
  const initialEdgeCount = await frame.locator('.edge-group').count()
  await frame.locator('[data-node-id="demo-note"]').click()
  await page.keyboard.press('Shift+Tab')
  await expect(frame.locator('#inlineNodeEditor')).toBeVisible()
  await frame.locator('#inlineNodeEditor').fill('Дочерний элемент')
  await frame.locator('#inlineNodeEditor').press('Enter')
  await page.keyboard.down('Shift')
  await page.keyboard.down('s')
  await page.keyboard.press('Tab')
  await page.keyboard.up('s')
  await page.keyboard.up('Shift')
  await expect(frame.locator('#inlineNodeEditor')).toBeVisible()
  await frame.locator('#inlineNodeEditor').fill('Соседний элемент')
  await frame.locator('#inlineNodeEditor').press('Enter')
  await expect(frame.locator('.graph-node')).toHaveCount(initialNodeCount + 2)
  await expect(frame.locator('.edge-group')).toHaveCount(initialEdgeCount + 2)
  await expect(frame.locator('.edge-group').filter({ hasText: 'дочерний' })).toHaveCount(1)
  await expect(frame.locator('.edge-group').filter({ hasText: 'следующий' })).toHaveCount(1)

  await frame.getByRole('button', { name: 'Открыть справку' }).click()
  await frame.getByRole('button', { name: 'Настроить сочетания' }).click()
  const hierarchyShortcut = frame.locator('[data-shortcut-capture="hierarchy"]')
  await hierarchyShortcut.click()
  await hierarchyShortcut.press('h')
  await expect(frame.locator('#shortcutSettingsMessage')).toContainText('фиксированной командой холста')
  await hierarchyShortcut.click()
  await hierarchyShortcut.press('Alt+H')
  const panelsShortcut = frame.locator('[data-shortcut-capture="panels"]')
  await panelsShortcut.click()
  await panelsShortcut.press('a')
  await frame.getByRole('button', { name: 'Закрыть настройки' }).click()
  await frame.locator('#graphTitle').focus()
  await frame.locator('#graphTitle').press('End')
  await frame.locator('#graphTitle').press('a')
  await expect(frame.locator('#graphTitle')).toHaveValue(/a$/)
  await frame.locator('#graphTitle').press('Enter')
  await frame.locator('#canvas').press('Alt+H')
  await expect(frame.locator('#hierarchyDialog')).toBeVisible()
  await frame.getByRole('button', { name: 'Закрыть мастер' }).click()

  const transformBefore = await frame.locator('#world').getAttribute('style')
  const canvasBox = await frame.locator('#canvas').boundingBox()
  expect(canvasBox).not.toBeNull()
  await frame.locator('#canvas').focus()
  await page.keyboard.down('Space')
  await page.mouse.move(canvasBox!.x + 90, canvasBox!.y + 680)
  await page.mouse.down()
  await page.mouse.move(canvasBox!.x + 150, canvasBox!.y + 730)
  await page.mouse.up()
  await page.keyboard.up('Space')
  const transformAfter = await frame.locator('#world').getAttribute('style')
  expect(transformAfter).not.toBe(transformBefore)

  await page.reload()
  await frame.getByRole('button', { name: 'Открыть справку' }).click()
  await expect(frame.locator('#shortcutHelpList')).toContainText('Alt + H')
  await expect(frame.locator('#shortcutHelpList')).toContainText('A')
})

test('Connection drag softly snaps to a nearby node', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Pointer magnetism is covered once on desktop')
  await installApiMock(page)
  await page.goto('/graphs')
  const frame = page.frameLocator('iframe[title="Рабочее пространство графов"]')
  const source = frame.locator('[data-node-id="demo-note"]')
  const target = frame.locator('[data-node-id="demo-tracker"]')
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  expect(sourceBox).not.toBeNull()
  expect(targetBox).not.toBeNull()
  const edgeCount = await frame.locator('.edge-group').count()

  await page.keyboard.down('Shift')
  await page.mouse.move(sourceBox!.x + sourceBox!.width / 2, sourceBox!.y + sourceBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(targetBox!.x + targetBox!.width / 2 + 24, targetBox!.y + targetBox!.height / 2, { steps: 8 })
  await expect(target).toHaveClass(/magnet-target/)
  await page.mouse.up()
  await page.keyboard.up('Shift')
  await expect(frame.locator('.edge-group')).toHaveCount(edgeCount + 1)
})
