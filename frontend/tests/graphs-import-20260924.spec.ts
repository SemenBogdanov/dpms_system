import { expect, test as base, type FrameLocator, type Page } from '@playwright/test'

// Fixtures follow graphs-integration.spec.ts without importing its registered tests.
// After the main build: playwright test --config ./tests graphs-import-20260924.spec.ts --workers=1
const userId = '11111111-1111-4111-8111-111111111111'
const workspaceKey = `dpms-graphs-workspace-v3:${userId}`
const frameSelector = 'iframe[title="Рабочее пространство графов"]'

type GraphNode = { id: string; title: string; sourceRef: string; description: string; [key: string]: unknown }
type GraphEdge = { id: string; source: string; target: string; label: string; [key: string]: unknown }
type Graph = {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  [key: string]: unknown
}
type Workspace = {
  version: number
  activeGraphId: string
  graphs: Graph[]
  storage: Record<string, { mode: string; publishState: string; revision: number | null; [key: string]: unknown }>
}
type ImportMode = 'native' | 'cubes' | 'tree' | 'records' | 'edges'
type QuotaTestWindow = Window & typeof globalThis & {
  __importQuota?: { enabled: boolean; rejected: number; restore: () => void }
}
type ApiMock = {
  puts: Array<{ path: string; payload: Graph; baseRevision: number | null }>
  unexpectedWrites: string[]
  expectedPublishId: string | null
  documents: Map<string, Record<string, unknown>>
}

const testUser = {
  id: userId,
  full_name: 'Проверка JSON-импорта',
  email: 'graphs-import-test@example.com',
  league: 'A', role: 'executor', mpw: 0, wip_limit: 5,
  wallet_main: 0, wallet_karma: 0, quality_score: 100,
  is_active: true, is_new_employee: false, task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false, feedback_enabled: false, audit_enabled: false,
  audit_calendar_enabled: false, competency_development_enabled: false,
  competency_constructor_enabled: false, plan_started_at: null,
  onboarding_started_at: null, onboarding_until: null, sidebar_menu_order: null,
  needs_password_change: false,
  created_at: '2026-09-24T00:00:00Z', updated_at: '2026-09-24T00:00:00Z',
}

function nativeGraph(id = 'qa-existing-graph', title = 'Существующий граф QA'): Graph {
  const nodes = ['Первый узел QA', 'Второй узел QA'].map((name, index) => ({
    id: `${id}-node-${index + 1}`, type: 'note', title: name,
    customTypeLabel: '', sourceRef: `/fixture/${index}`, description: `Данные ${index + 1}`,
    shape: 'rounded', radius: 8, scale: 1, autoSize: true,
    width: 224, height: 108, items: [], pinned: false, color: '#7C55C7',
    x: index * 300, y: 100,
  }))
  const viewId = `${id}-view`
  return {
    version: 3, id, title,
    createdAt: '2026-09-24T10:00:00.000Z', updatedAt: '2026-09-24T10:00:00.000Z',
    viewport: { x: 0, y: 0, scale: 1 }, nodes,
    edges: [{ id: `${id}-edge`, source: nodes[0].id, target: nodes[1].id, sourcePort: null, targetPort: null, label: 'проверяет', routing: 'curve', points: [] }],
    groups: [],
    views: [{
      id: viewId, name: 'Основной вид', layout: 'compact',
      positions: Object.fromEntries(nodes.map((node) => [node.id, { x: node.x, y: node.y }])),
      viewport: { x: 0, y: 0, scale: 1 }, focusNodeId: null, focusDepth: 0,
      connectionLensEnabled: false,
    }],
    activeViewId: viewId, audit: [],
  }
}

async function installApiMock(page: Page): Promise<ApiMock> {
  const api: ApiMock = { puts: [], unexpectedWrites: [], expectedPublishId: null, documents: new Map() }
  const graph = nativeGraph()
  const seed: Workspace = {
    version: 3, activeGraphId: graph.id, graphs: [graph],
    storage: { [graph.id]: { mode: 'local', revision: null, serverUpdatedAt: null, publishState: 'local', error: '' } },
  }
  await page.addInitScript(({ key, initial }) => {
    window.localStorage.setItem('dpms_token', 'graphs-import-synthetic-token')
    if (window.localStorage.getItem(key) === null) window.localStorage.setItem(key, JSON.stringify(initial))
  }, { key: workspaceKey, initial: seed })
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
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    const expectedPath = api.expectedPublishId === null ? null : `/api/graphs/${encodeURIComponent(api.expectedPublishId)}`
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !(method === 'PUT' && path === expectedPath)) {
      api.unexpectedWrites.push(`${method} ${path}`)
    }
    if (path === '/api/auth/me' && method === 'GET') return json(testUser)
    if (path === '/api/messages/summary' && method === 'GET') return json({ direct_count: 0, important_count: 0, revision: 0 })
    if (path === '/api/graphs' && method === 'GET') {
      return json([...api.documents.values()].map((document) => {
        const summary = { ...document }
        delete summary.payload
        return summary
      }))
    }
    if (path.startsWith('/api/graphs/')) {
      const clientId = decodeURIComponent(path.slice('/api/graphs/'.length))
      if (method === 'PUT') {
        const body = request.postDataJSON() as { base_revision: number | null; payload: Graph }
        api.puts.push({ path, payload: structuredClone(body.payload), baseRevision: body.base_revision })
        const now = new Date().toISOString()
        const document = {
          id: `document-${clientId}`, client_id: clientId, title: body.payload.title,
          revision: Number(api.documents.get(clientId)?.revision || 0) + 1,
          payload_bytes: Buffer.byteLength(JSON.stringify(body.payload)),
          node_count: body.payload.nodes.length, edge_count: body.payload.edges.length,
          created_at: now, updated_at: now, payload: structuredClone(body.payload),
        }
        api.documents.set(clientId, document)
        return json(document)
      }
      if (method === 'GET') return json(api.documents.get(clientId) || { detail: 'Граф не найден' }, api.documents.has(clientId) ? 200 : 404)
    }
    return json([])
  })
  return api
}

const test = base.extend<{ api: ApiMock }>({
  api: async ({ page }, runTest) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    const api = await installApiMock(page)
    await runTest(api)
    expect(api.unexpectedWrites, 'Preview, cancellation and local import must never write to any API').toEqual([])
    expect(errors, 'Import must not cause uncaught runtime errors').toEqual([])
  },
})

test.use({ baseURL: 'http://localhost:55177', viewport: { width: 1440, height: 900 } })

test.beforeEach(async ({ page, api }) => {
  expect(api.puts).toEqual([])
  await page.goto('/graphs')
  const frame = page.frameLocator(frameSelector)
  await expect(frame.locator('#graphTitle')).toHaveValue('Существующий граф QA')
  await expect(frame.locator('#nodeLayer .graph-node')).toHaveCount(2)
})

async function readWorkspace(page: Page): Promise<Workspace> {
  return page.evaluate((key) => {
    const raw = window.localStorage.getItem(key)
    if (!raw) throw new Error('Локальный workspace отсутствует')
    return JSON.parse(raw) as Workspace
  }, workspaceKey)
}

async function expectUnchanged(page: Page, before: Workspace, api: ApiMock) {
  expect(await readWorkspace(page)).toEqual(before)
  await expect(page.frameLocator(frameSelector).locator('#graphTitle')).toHaveValue(before.graphs.find((graph) => graph.id === before.activeGraphId)!.title)
  expect(api.puts).toHaveLength(0)
  expect(api.unexpectedWrites).toEqual([])
}

async function openImport(page: Page) {
  const frame = page.frameLocator(frameSelector)
  await frame.locator('#importButton').click()
  await expect(frame.locator('#importDialog')).toBeVisible()
  return frame
}

async function chooseFile(page: Page, frame: FrameLocator, raw: string, name = 'qa-import.json') {
  const chooserEvent = page.waitForEvent('filechooser')
  await frame.locator('#chooseImportFileButton').click()
  const chooser = await chooserEvent
  expect(await chooser.element().getAttribute('id')).toBe('importInput')
  await chooser.setFiles({ name, mimeType: 'application/json', buffer: Buffer.from(raw) })
  // setFiles dispatches change but does not await the application's file.text().
  await expect.poll(async () => {
    const error = await frame.locator('#importError').textContent()
    return Boolean(error?.trim()) || await frame.locator('#importFileName').textContent() === name
  }, { message: 'Wait for JSON read/detection before editing mode or mapping' }).toBe(true)
}

function countPattern(kind: 'nodes' | 'edges', count: number) {
  const label = kind === 'nodes' ? '(?:узлов|узла|узел|узлы|элементов|элемента|элемент|элементы)' : '(?:связей|связи|связь|р[её]бер|р[её]бра|ребро)'
  return new RegExp(`(?:${label}\\s*[:=]?[ \\t]*${count}(?!\\d)|(?:^|\\D)${count}\\s*${label})`, 'i')
}

async function expectPreview(frame: FrameLocator, mode: ImportMode, nodes: number, edges: number, title?: string) {
  await expect(frame.locator('#importModeField')).toHaveValue(mode)
  await expect(frame.locator('#confirmImportButton')).toBeEnabled()
  const preview = frame.locator('#importPreview')
  await expect(preview).toBeVisible()
  await expect(preview).toContainText(countPattern('nodes', nodes), { useInnerText: true })
  await expect(preview).toContainText(countPattern('edges', edges), { useInnerText: true })
  if (title) await expect(preview).toContainText(title)
  await expect(frame.locator('#importError')).toHaveText('')
}

async function fillMapping(frame: FrameLocator, fields: Record<string, string>) {
  for (const [name, value] of Object.entries(fields)) {
    const field = frame.locator(`#import-${name}`)
    await field.fill(value)
    await field.press('Tab')
  }
}

async function confirmImport(page: Page, frame: FrameLocator, before: Workspace, nodes: number, edges: number) {
  await frame.locator('#confirmImportButton').click()
  await expect(frame.locator('#importDialog')).not.toBeVisible()
  await expect.poll(async () => (await readWorkspace(page)).graphs.length).toBe(before.graphs.length + 1)
  const after = await readWorkspace(page)
  expect(after.activeGraphId).not.toBe(before.activeGraphId)
  expect(before.graphs.some((graph) => graph.id === after.activeGraphId)).toBe(false)
  expect(after.graphs.filter((graph) => graph.id !== after.activeGraphId)).toEqual(before.graphs)
  expect(after.storage[before.activeGraphId]).toEqual(before.storage[before.activeGraphId])
  expect(after.storage[after.activeGraphId]).toMatchObject({ mode: 'local', publishState: 'local' })
  const imported = after.graphs.find((graph) => graph.id === after.activeGraphId)!
  expect(imported.nodes).toHaveLength(nodes)
  expect(imported.edges).toHaveLength(edges)
  await expect(frame.locator('#graphTitle')).toHaveValue(imported.title)
  await expect(frame.locator('#nodeLayer .graph-node')).toHaveCount(nodes)
  return imported
}

async function expectImportError(frame: FrameLocator, message: RegExp) {
  const error = frame.locator('#importError')
  await expect(error).toHaveAttribute('role', 'alert')
  await expect(error).toBeVisible()
  await expect(error).toContainText(message)
  await expect(error).toContainText(/[А-Яа-яЁё]/)
  await expect(frame.locator('#confirmImportButton')).toBeDisabled()
}

async function expectNoDelayedUpload(page: Page, api: ApiMock) {
  // Deliberate observation window: detect an accidental debounced autosave to the API.
  await page.waitForTimeout(1100)
  expect(api.puts).toHaveLength(0)
  expect(api.unexpectedWrites).toEqual([])
}

test('[2.12] import button opens a dialog with all five modes and requires a chosen file', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await expect(frame.locator('#chooseImportFileButton')).toBeVisible()
  await expect(frame.locator('#confirmImportButton')).toBeDisabled()
  const values = await frame.locator('#importModeField option').evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))
  expect(values.sort()).toEqual(['cubes', 'edges', 'native', 'records', 'tree'])
  await expectUnchanged(page, before, api)
})

const examples: Array<{ mode: ImportMode; data: unknown; nodes: number; edges: number; preview: string }> = [
  { mode: 'native', data: nativeGraph('native-file-id', 'Граф из файла QA'), nodes: 2, edges: 1, preview: 'Первый узел QA' },
  { mode: 'cubes', data: { cubes: [
    { task: { task_id: 101, description: 'Первый кубик QA' }, params: [], related_tasks: [{ task_id: 102, type: 'следует' }] },
    { task: { task_id: 102, description: 'Второй кубик QA' }, params: [], related_tasks: [] },
  ] }, nodes: 2, edges: 1, preview: 'Первый кубик QA' },
  { mode: 'tree', data: { name: 'Произвольный JSON QA', count: 0, enabled: false, meta: null }, nodes: 5, edges: 4, preview: 'Произвольный JSON QA' },
  { mode: 'records', data: [{ id: 'r1', name: 'Родитель QA', parentId: null, count: 0 }, { id: 'r2', name: 'Ребёнок QA', parentId: 'r1', enabled: false }], nodes: 2, edges: 1, preview: 'Родитель QA' },
  { mode: 'edges', data: [{ source: 'Команда QA', target: 'Релиз QA', label: 'готовит' }, { source: 'Релиз QA', target: 'Проверка QA' }, { source: 'Команда QA', target: 'Проверка QA' }], nodes: 3, edges: 3, preview: 'Команда QA' },
]

for (const example of examples) {
  test(`[2.12] ${example.mode}: autodetection, preview and explicit confirmation create one new local graph`, async ({ page, api }, testInfo) => {
    const before = await readWorkspace(page)
    const frame = await openImport(page)
    await chooseFile(page, frame, JSON.stringify(example.data), `${example.mode}-qa.json`)
    await expectPreview(frame, example.mode, example.nodes, example.edges, example.preview)
    await frame.locator('#importDialog').screenshot({ path: testInfo.outputPath(`import-${example.mode}-preview.png`), animations: 'disabled' })
    await expectUnchanged(page, before, api)
    await expectNoDelayedUpload(page, api)
    const imported = await confirmImport(page, frame, before, example.nodes, example.edges)
    if (example.mode === 'native') {
      expect(imported.id).not.toBe('native-file-id')
      expect(imported.title).toBe('Граф из файла QA')
      expect(imported.nodes.map((node) => node.title)).toEqual(['Первый узел QA', 'Второй узел QA'])
    }
    if (example.mode === 'records') {
      expect(JSON.parse(imported.nodes[0].description).count).toBe(0)
      expect(JSON.parse(imported.nodes[1].description).enabled).toBe(false)
      expect(imported.edges[0]).toMatchObject({ source: imported.nodes[0].id, target: imported.nodes[1].id })
    }
    await expectNoDelayedUpload(page, api)
    await page.reload()
    await expect(page.frameLocator(frameSelector).locator('#graphTitle')).toHaveValue(imported.title)
    const reloaded = await readWorkspace(page)
    expect(reloaded.activeGraphId).toBe(imported.id)
    expect(reloaded.graphs).toHaveLength(before.graphs.length + 1)
    expect(reloaded.graphs.find((graph) => graph.id === imported.id)?.nodes).toEqual(imported.nodes)
    expect(api.puts).toHaveLength(0)
  })
}

for (const value of [0, false, null, [0, false, null, [1]]]) {
  test(`[2.12] custom JSON ${JSON.stringify(value)} is valid data, not an invalid graph`, async ({ page, api }) => {
    const before = await readWorkspace(page)
    const frame = await openImport(page)
    await chooseFile(page, frame, JSON.stringify(value))
    const count = Array.isArray(value) ? 6 : 1
    await expectPreview(frame, 'tree', count, count - 1)
    await expectUnchanged(page, before, api)
    const imported = await confirmImport(page, frame, before, count, count - 1)
    expect(imported.nodes[0].sourceRef).toBe('')
    expect(JSON.parse(imported.nodes[0].description)).toEqual(value)
  })
}

test('[2.12] records mapping selects an escaped nested array and preserves parent links and attributes', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const rows = [{ key: 'root', caption: 'Mapped root QA', parentKey: null, detail: { count: 0 } }, { key: 'child', caption: 'Mapped child QA', parentKey: 'root', active: false }]
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify({ payload: { 'a/b': { '~rows': rows } }, ignored: 'Not imported' }))
  await expect(frame.locator('#importModeField')).toHaveValue('tree')
  await frame.locator('#importModeField').selectOption('records')
  await fillMapping(frame, { recordPath: '/payload/a~1b/~0rows', idField: 'key', titleField: 'caption', parentField: 'parentKey' })
  await expectPreview(frame, 'records', 2, 1, 'Mapped root QA')
  await expect(frame.locator('#importPreview')).toContainText(/только массив|остальн.*не включ/)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 2, 1)
  expect(imported.nodes.map((node) => node.sourceRef)).toEqual(['/payload/a~1b/~0rows/0', '/payload/a~1b/~0rows/1'])
  expect(imported.nodes.map((node) => JSON.parse(node.description))).toEqual(rows)
  expect(imported.edges[0]).toMatchObject({ source: imported.nodes[0].id, target: imported.nodes[1].id })
})

test('[2.12] edges mapping uses custom endpoint and label fields in a nested array', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify({ links: [{ left: 0, right: false, verb: 'проверяет', count: 0 }, { left: false, right: 'third', verb: 'продолжает' }] }))
  await frame.locator('#importModeField').selectOption('edges')
  await fillMapping(frame, { recordPath: '/links', sourceField: 'left', targetField: 'right', labelField: 'verb' })
  await expectPreview(frame, 'edges', 3, 2)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 3, 2)
  expect(imported.nodes.map((node) => node.title)).toEqual(['0', 'false', 'third'])
  expect(imported.edges.map((edge) => edge.label)).toEqual(['проверяет', 'продолжает'])
  expect(imported.edges[0].target).toBe(imported.edges[1].source)
  expect(imported.nodes[0].description).toContain('"count":0')
})

test('[2.12] clearing mapping fields restores autodetection and preview follows mode changes', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const data = [{ id: 0, title: 'Default root QA', parentId: null }, { id: 1, title: 'Default child QA', parentId: 0 }]
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify(data))
  await fillMapping(frame, { idField: 'id', titleField: 'title', parentField: 'parentId' })
  await expectPreview(frame, 'records', 2, 1, 'Default root QA')
  await fillMapping(frame, { recordPath: '', idField: '', titleField: '', parentField: '' })
  await expectPreview(frame, 'records', 2, 1, 'Default root QA')
  await frame.locator('#importModeField').selectOption('tree')
  await expectPreview(frame, 'tree', 9, 8)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 9, 8)
  expect(imported.nodes.map((node) => node.sourceRef)).toContain('/1/parentId')
})

for (const cancel of ['button', 'escape'] as const) {
  test(`[2.12] cancel by ${cancel} discards preview without modifying the current graph`, async ({ page, api }) => {
    const before = await readWorkspace(page)
    const frame = await openImport(page)
    await chooseFile(page, frame, JSON.stringify([{ id: 'new', name: 'Cancelled row QA' }]))
    await expectPreview(frame, 'records', 1, 0, 'Cancelled row QA')
    if (cancel === 'escape') await page.keyboard.press('Escape')
    else await frame.locator('#importDialog').getByRole('button', { name: /^(Отмена|Отменить(?: импорт)?)$/ }).click()
    await expect(frame.locator('#importDialog')).not.toBeVisible()
    await expectNoDelayedUpload(page, api)
    await expectUnchanged(page, before, api)
    await frame.locator('#importButton').click()
    await expect(frame.locator('#confirmImportButton')).toBeDisabled()
    await expect(frame.locator('#importPreview')).not.toContainText('Cancelled row QA')
  })
}

test('[2.12] malformed JSON clears a previous candidate, alerts in Russian and allows a corrected file', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, '[{"id":1,"name":"Previous candidate QA"}]')
  await expectPreview(frame, 'records', 1, 0, 'Previous candidate QA')
  await chooseFile(page, frame, '{"broken":', 'broken.json')
  await expectImportError(frame, /JSON|синтакси|прочита|разобра/)
  await expect(frame.locator('#importPreview')).not.toContainText('Previous candidate QA')
  await expectUnchanged(page, before, api)
  await chooseFile(page, frame, '[{"id":2,"name":"Corrected candidate QA"}]', 'corrected.json')
  await expectPreview(frame, 'records', 1, 0, 'Corrected candidate QA')
  const imported = await confirmImport(page, frame, before, 1, 0)
  expect(imported.nodes[0].title).toBe('Corrected candidate QA')
})

const invalidData = [
  { name: 'duplicate IDs', data: [{ id: 'duplicate' }, { id: 'duplicate' }], error: /Повторяющийся ID/ },
  { name: 'missing ID', data: [{ id: 1 }, { name: 'Missing ID' }], error: /отсутствует ID/ },
  { name: 'dangling parent', data: [{ id: 'child', parentId: 'missing' }], error: /родитель.*не найден/ },
  { name: 'missing target', data: [{ source: 'a', target: 'b' }, { source: 'c' }], error: /target.*отсутствует ID/ },
]
for (const example of invalidData) {
  test(`[2.12] ${example.name} rejects the candidate without silently dropping data`, async ({ page, api }) => {
    const before = await readWorkspace(page)
    const frame = await openImport(page)
    await chooseFile(page, frame, JSON.stringify(example.data))
    await expectImportError(frame, example.error)
    await expectUnchanged(page, before, api)
  })
}

test('[2.12] native graph with a dangling edge is rejected instead of silently normalized', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const data = nativeGraph('invalid-native', 'Некорректный native QA')
  data.edges[0].target = 'missing-node'
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify(data), 'invalid-native.json')
  await expect(frame.locator('#importModeField')).toHaveValue('native')
  await expectImportError(frame, /отсутствующ|некорректн|edges/i)
  await expectUnchanged(page, before, api)
})

test('[2.12] invalid recordPath reports an error and does not leave the old candidate confirmable', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, '{"rows":[{"id":1,"name":"Valid path QA"}]}')
  await frame.locator('#importModeField').selectOption('records')
  await fillMapping(frame, { recordPath: '/rows' })
  await expectPreview(frame, 'records', 1, 0, 'Valid path QA')
  await fillMapping(frame, { recordPath: '/~2' })
  await expectImportError(frame, /Pointer|экранирован/)
  await expect(frame.locator('#importPreview')).not.toContainText('Valid path QA')
  await expectUnchanged(page, before, api)
})

const limits = [
  { name: '1501 records', raw: () => JSON.stringify(Array.from({ length: 1501 }, (_, id) => ({ id }))), error: /1500|лимит/i },
  { name: '1501 tree nodes including root', raw: () => JSON.stringify(Array.from({ length: 1500 }, () => 0)), error: /1500|лимит/i },
  { name: '3001 edge rows even when duplicates', raw: () => JSON.stringify(Array.from({ length: 3001 }, () => ({ source: 'a', target: 'b' }))), error: /3000|лимит/i },
  { name: 'file over 5 MB', raw: () => ' '.repeat(5 * 1024 * 1024) + '{}', error: /5\s*МБ|лимит/i },
  { name: 'deep JSON without stack overflow', raw: () => '['.repeat(600) + '0' + ']'.repeat(600), error: /глубин|512|sourceRef|300/i },
]
for (const example of limits) {
  test(`[2.12] ${example.name} rejects the whole candidate with no partial import`, async ({ page, api }) => {
    const before = await readWorkspace(page)
    const frame = await openImport(page)
    await chooseFile(page, frame, example.raw(), 'over-limit.json')
    await expectImportError(frame, example.error)
    await expectUnchanged(page, before, api)
  })
}

test('[2.12] preview distinguishes full counts from the prefix of displayed nodes', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify(Array.from({ length: 150 }, (_, id) => ({ id, title: `Preview row ${id}` }))))
  await expectPreview(frame, 'records', 150, 0, 'Preview row 0')
  await expect(frame.locator('#importPreview')).not.toContainText('Preview row 149')
  await expectUnchanged(page, before, api)
})

test('[2.12] duplicate edges, self references and truncated descriptions are disclosed in preview', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify([
    { source: 'First QA', target: 'Second QA', label: 'first', detail: 'x'.repeat(2500) },
    { source: 'First QA', target: 'Second QA', label: 'duplicate' },
    { source: 'First QA', target: 'First QA', label: 'self' },
  ]))
  await expectPreview(frame, 'edges', 2, 1, 'First QA')
  await expect(frame.locator('#importPreview')).toContainText(/Повторная.*связь/)
  await expect(frame.locator('#importPreview')).toContainText(/Самоссылка/)
  await expect(frame.locator('#importPreview')).toContainText(/сокращено/)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 2, 1)
  expect(imported.edges[0].label).toBe('first')
  expect(imported.edges[0].source).not.toBe(imported.edges[0].target)
  expect(imported.nodes[0].description).toContain('Описание сокращено')
})

test('[2.12] every preview issue is displayed and HTML-like paths are escaped, not executed', async ({ page, api }, testInfo) => {
  const before = await readWorkspace(page)
  const key = '<img src=x onerror="globalThis.__graphImportIssueXss=1">'
  const path = `/${key}`
  const rows = Array.from({ length: 12 }, () => ({ source: 'A', target: 'A' }))
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify({ [key]: rows }), 'all-issues.json')
  await frame.locator('#importModeField').selectOption('edges')
  await fillMapping(frame, { recordPath: path })
  await expectPreview(frame, 'edges', 1, 0, 'A')
  const preview = frame.locator('#importPreview')
  const issues = preview.locator('li').filter({ hasText: /^Самоссылка / })
  await expect(issues).toHaveCount(rows.length)
  for (let index = 0; index < rows.length; index += 1) {
    await expect(issues.nth(index)).toContainText(`${path}/${index}:`)
    await expect(issues.nth(index)).toContainText('ребро не добавлено')
  }
  await expect(preview).toContainText(`Импортирован только массив ${path}`)
  await expect(preview.locator('img, script, iframe, [onerror]')).toHaveCount(0)
  expect(await preview.evaluate(() => (globalThis as typeof globalThis & { __graphImportIssueXss?: number }).__graphImportIssueXss ?? 0)).toBe(0)
  await expectUnchanged(page, before, api)
  const screenshot = testInfo.outputPath('import-all-issues-escaped.png')
  await frame.locator('#importDialog').screenshot({ path: screenshot, animations: 'disabled' })
  await testInfo.attach('JSON importer: all issues escaped', { path: screenshot, contentType: 'image/png' })
})

test('[2.12] markup in data, filename and mapping errors stays text in preview and the imported graph', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const markup = '<img src=x onerror="globalThis.__graphImportXss=1">'
  const row = JSON.parse(`{"id":"safe-id","name":${JSON.stringify(markup)},"__proto__":{"polluted":true},"constructor":{"prototype":{"polluted":true}}}`) as Record<string, unknown>
  const frame = await openImport(page)
  await chooseFile(page, frame, JSON.stringify([row]), `${markup}.json`)
  await expectPreview(frame, 'records', 1, 0, markup)
  await expect(frame.locator('#importDialog img, #importDialog script, #importDialog [onerror]')).toHaveCount(0)
  await fillMapping(frame, { idField: markup })
  await expectImportError(frame, /не найдено/)
  await expect(frame.locator('#importError')).toContainText(markup)
  await expect(frame.locator('#importError img, #importError [onerror]')).toHaveCount(0)
  await fillMapping(frame, { idField: '' })
  await expectPreview(frame, 'records', 1, 0, markup)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 1, 0)
  expect(imported.nodes[0].title).toBe(markup)
  expect(JSON.parse(imported.nodes[0].description)).toEqual(row)
  await expect(frame.locator('#nodeLayer .node-title')).toContainText(markup)
  await expect(frame.locator('#nodeLayer img, #nodeLayer script, #nodeLayer [onerror]')).toHaveCount(0)
  await frame.locator('#graphManagerButton').click()
  const graphRow = frame.locator(`[data-graph-id="${imported.id}"]`)
  await expect(graphRow).toContainText(markup)
  await expect(graphRow.locator('img, script, [onerror]')).toHaveCount(0)
  expect(await frame.locator('body').evaluate(() => ({
    executed: (globalThis as typeof globalThis & { __graphImportXss?: number }).__graphImportXss ?? 0,
    polluted: ({} as Record<string, unknown>).polluted ?? null,
  }))).toEqual({ executed: 0, polluted: null })
  expect(api.puts).toHaveLength(0)
})

test('[2.12] importing the same file again requires confirmation and assigns a fresh graph ID', async ({ page, api }) => {
  const initial = await readWorkspace(page)
  const raw = '[{"id":1,"name":"Repeated file QA"}]'
  const frame = await openImport(page)
  await chooseFile(page, frame, raw, 'same-file.json')
  await expectPreview(frame, 'records', 1, 0, 'Repeated file QA')
  const first = await confirmImport(page, frame, initial, 1, 0)
  const beforeSecond = await readWorkspace(page)
  await frame.locator('#importButton').click()
  await expect(frame.locator('#confirmImportButton')).toBeDisabled()
  await chooseFile(page, frame, raw, 'same-file.json')
  await expectPreview(frame, 'records', 1, 0, 'Repeated file QA')
  await expectUnchanged(page, beforeSecond, api)
  const second = await confirmImport(page, frame, beforeSecond, 1, 0)
  expect(second.id).not.toBe(first.id)
  expect(second.nodes).toEqual(first.nodes)
  expect(api.puts).toHaveLength(0)
})

test('[2.11/2.12] import quota failure preserves the edited graph, selection and working undo', async ({ page, api }) => {
  const original = await readWorkspace(page)
  const originalGraph = original.graphs.find((graph) => graph.id === original.activeGraphId)!
  const originalNode = originalGraph.nodes[0]
  const frame = page.frameLocator(frameSelector)
  const node = frame.locator(`#nodeLayer [data-node-id="${originalNode.id}"]`)
  const editedTitle = 'Сохранённая правка перед отказом импорта QA'
  await node.click()
  await frame.locator('#nodeTitleField').fill(editedTitle)
  await frame.locator('#nodeTitleField').press('Tab')
  await expect(node.locator('.node-title')).toHaveText(editedTitle)
  await expect.poll(async () => {
    const stored = await readWorkspace(page)
    return stored.graphs.find((graph) => graph.id === originalGraph.id)?.nodes.find((item) => item.id === originalNode.id)?.title
  }).toBe(editedTitle)
  // Reselect after committing the edit so the toolbar reflects the undo entry.
  await node.click()
  await expect(node).toHaveAttribute('aria-pressed', 'true')
  await expect(frame.locator('#undoButton')).toBeEnabled()
  const beforeImport = await readWorkspace(page)
  const worldStyle = await frame.locator('#world').getAttribute('style')

  await openImport(page)
  await chooseFile(page, frame, '[{"id":1,"title":"Отклонённый импорт QA"}]', 'quota-import.json')
  await expectPreview(frame, 'records', 1, 0, 'Отклонённый импорт QA')
  await expectUnchanged(page, beforeImport, api)

  await frame.locator('body').evaluate((_element, key) => {
    const state = window as QuotaTestWindow
    const prototype = Object.getPrototypeOf(window.localStorage) as Storage
    const originalSetItem = prototype.setItem
    const failure = { enabled: true, rejected: 0, restore: () => { prototype.setItem = originalSetItem } }
    state.__importQuota = failure
    prototype.setItem = function setItem(storageKey: string, value: string) {
      if (failure.enabled && this === window.localStorage && storageKey === key) {
        failure.rejected += 1
        throw new DOMException('Synthetic import quota failure', 'QuotaExceededError')
      }
      return originalSetItem.call(this, storageKey, value)
    }
  }, workspaceKey)
  try {
    await frame.locator('#confirmImportButton').click()
    await expect.poll(() => frame.locator('body').evaluate(() => (window as QuotaTestWindow).__importQuota?.rejected ?? 0)).toBeGreaterThan(0)
    await expect(frame.locator('#toastRegion')).toContainText('Локальное хранилище заполнено')
    await expect(frame.locator('#importDialog')).toBeVisible()
    await expect(frame.locator('#confirmImportButton')).toBeEnabled()
    await expectUnchanged(page, beforeImport, api)
    await expect(frame.locator('#nodeLayer .graph-node')).toHaveCount(originalGraph.nodes.length)
    await expect(node).toHaveAttribute('aria-pressed', 'true')
    await expect(node).toHaveClass(/\bselected\b/)
    await expect(node.locator('.node-title')).toHaveText(editedTitle)
    await expect(frame.locator('#nodeTitleField')).toHaveValue(editedTitle)
    await expect(frame.locator('#undoButton')).toBeEnabled()
    expect(await frame.locator('#world').getAttribute('style')).toBe(worldStyle)

    await frame.locator('body').evaluate(() => { (window as QuotaTestWindow).__importQuota!.enabled = false })
    await frame.locator('#importDialog').getByRole('button', { name: 'Отмена', exact: true }).click()
    await expect(frame.locator('#importDialog')).not.toBeVisible()
    await expect(node).toHaveAttribute('aria-pressed', 'true')
    await frame.locator('#undoButton').click()
    await expect(node.locator('.node-title')).toHaveText(originalNode.title)
    await expect.poll(async () => {
      const stored = await readWorkspace(page)
      return stored.graphs.find((graph) => graph.id === originalGraph.id)?.nodes.find((item) => item.id === originalNode.id)?.title
    }).toBe(originalNode.title)
    const restored = await readWorkspace(page)
    const restoredGraph = restored.graphs.find((graph) => graph.id === originalGraph.id)!
    expect(restored.activeGraphId).toBe(original.activeGraphId)
    expect(restored.graphs).toHaveLength(original.graphs.length)
    expect(restored.storage).toEqual(beforeImport.storage)
    expect(restoredGraph.nodes).toEqual(originalGraph.nodes)
    expect(restoredGraph.edges).toEqual(originalGraph.edges)
    expect(restoredGraph.views).toEqual(originalGraph.views)
    expect(restoredGraph.groups).toEqual(originalGraph.groups)
    await expect(frame.locator('#redoButton')).toBeEnabled()
    expect(api.puts).toHaveLength(0)
    expect(api.unexpectedWrites).toEqual([])
  } finally {
    await frame.locator('body').evaluate(() => {
      const state = window as QuotaTestWindow
      state.__importQuota?.restore()
      delete state.__importQuota
    })
  }
})

test('[2.12] only an explicit Publish after local confirmation sends one graph PUT', async ({ page, api }) => {
  const before = await readWorkspace(page)
  const frame = await openImport(page)
  await chooseFile(page, frame, '[{"id":1,"title":"Publish boundary QA"}]', 'publish-boundary.json')
  await expectPreview(frame, 'records', 1, 0, 'Publish boundary QA')
  await expectNoDelayedUpload(page, api)
  await expectUnchanged(page, before, api)
  const imported = await confirmImport(page, frame, before, 1, 0)
  await expectNoDelayedUpload(page, api)
  await frame.locator('#graphManagerButton').click()
  const row = frame.locator(`[data-graph-id="${imported.id}"]`)
  const publish = row.locator('[data-graph-publish]')
  await expect(publish).toBeEnabled()
  expect(api.puts).toHaveLength(0)
  expect(api.unexpectedWrites).toEqual([])
  api.expectedPublishId = imported.id
  await publish.click()
  await expect.poll(() => api.puts.length).toBe(1)
  await expect(row).toContainText('Опубликован')
  expect(api.puts[0].baseRevision).toBeNull()
  expect(api.puts[0].payload.id).toBe(imported.id)
  expect(api.puts[0].payload.nodes).toEqual(imported.nodes)
  expect(api.documents.has(before.activeGraphId)).toBe(false)
  expect(api.documents.size).toBe(1)
  const after = await readWorkspace(page)
  expect(after.graphs.find((graph) => graph.id === before.activeGraphId)).toEqual(before.graphs[0])
  expect(after.storage[imported.id]).toMatchObject({ publishState: 'published', revision: 1 })
  await page.waitForTimeout(1100)
  expect(api.puts).toHaveLength(1)
})

test.describe('[2.12] mobile import 390x844', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  async function openMobileImport(frame: FrameLocator) {
    const inspectorOpen = await frame.locator('body').evaluate((body) => body.classList.contains('show-inspector'))
    if (!inspectorOpen) await frame.locator('#inspectorToggle').tap()
    await frame.locator('#mobileFileButton').tap()
    await expect(frame.locator('#fileDialog')).toBeVisible()
    await frame.locator('#fileImportButton').tap()
    await expect(frame.locator('#fileDialog')).not.toBeVisible()
    await expect(frame.locator('#importDialog')).toBeVisible()
  }

  async function expectMobileFit(page: Page, frame: FrameLocator) {
    expect(page.viewportSize()).toEqual({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    const size = await frame.locator('#importDialog').evaluate((dialog) => {
      const bounds = dialog.getBoundingClientRect()
      const controls = [...dialog.querySelectorAll('input, select, button, label')]
        .filter((element) => element.getClientRects().length > 0)
        .map((element) => ({ id: element.id || element.tagName, left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right }))
      const containers = [dialog, ...dialog.querySelectorAll('.dialog-body, .dialog-actions, #importMapping, #importPreview')]
        .map((element) => ({ id: element.id || element.className, width: element.clientWidth, scrollWidth: element.scrollWidth }))
      return {
        width: innerWidth, height: innerHeight,
        pageWidth: document.documentElement.scrollWidth,
        left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom,
        controls, containers,
      }
    })
    expect(size.width, 'The iframe must actually be 390 CSS pixels, not the desktop override').toBe(390)
    expect(size.pageWidth).toBeLessThanOrEqual(size.width + 1)
    expect(size.left).toBeGreaterThanOrEqual(-1)
    expect(size.right).toBeLessThanOrEqual(size.width + 1)
    expect(size.top).toBeGreaterThanOrEqual(-1)
    expect(size.bottom).toBeLessThanOrEqual(size.height + 1)
    for (const control of size.controls) {
      expect(control.left, `${control.id}: left edge`).toBeGreaterThanOrEqual(size.left - 1)
      expect(control.right, `${control.id}: right edge`).toBeLessThanOrEqual(size.right + 1)
    }
    for (const container of size.containers) {
      expect(container.scrollWidth, `${container.id}: no horizontal overflow`).toBeLessThanOrEqual(container.width + 1)
    }
  }

  test('touch file actions, five modes and mapping fit; tree preview cancels and confirms locally', async ({ page, api }, testInfo) => {
    const before = await readWorkspace(page)
    const frame = page.frameLocator(frameSelector)
    await frame.locator('body').evaluate((body) => {
      body.addEventListener('touchstart', () => { body.dataset.importTouchObserved = 'true' }, { once: true })
    })
    await openMobileImport(frame)
    await expect(frame.locator('body')).toHaveAttribute('data-import-touch-observed', 'true')
    const values = await frame.locator('#importModeField option').evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))
    expect(values.sort()).toEqual(['cubes', 'edges', 'native', 'records', 'tree'])
    for (const mode of ['native', 'cubes', 'tree', 'records', 'edges']) {
      await frame.locator('#importModeField').selectOption(mode)
      await expect(frame.locator('#importModeField')).toHaveValue(mode)
      await expect(frame.locator('#confirmImportButton')).toBeDisabled()
      if (mode === 'records' || mode === 'edges') {
        const fields = mode === 'records' ? ['recordPath', 'idField', 'titleField', 'parentField'] : ['recordPath', 'sourceField', 'targetField', 'labelField']
        for (const field of fields) await expect(frame.locator(`#import-${field}`)).toBeVisible()
      }
      await expectMobileFit(page, frame)
      if (mode === 'records' || mode === 'edges') {
        await page.screenshot({ path: testInfo.outputPath(`import-mobile-390-${mode}.png`), scale: 'css', animations: 'disabled' })
      }
    }

    const raw = JSON.stringify({ name: 'Мобильный JSON QA', ready: false, count: 0, owner: null })
    await chooseFile(page, frame, raw, 'mobile-tree.json')
    await expectPreview(frame, 'tree', 5, 4, 'Мобильный JSON QA')
    await expectMobileFit(page, frame)
    const screenshot = testInfo.outputPath('import-mobile-390-tree-preview.png')
    await page.screenshot({ path: screenshot, scale: 'css', animations: 'disabled' })
    await testInfo.attach('JSON import at 390x844', { path: screenshot, contentType: 'image/png' })
    await expectUnchanged(page, before, api)
    await frame.locator('#importDialog').getByRole('button', { name: 'Отмена', exact: true }).tap()
    await expect(frame.locator('#importDialog')).not.toBeVisible()
    await expectUnchanged(page, before, api)

    await openMobileImport(frame)
    await expect(frame.locator('#confirmImportButton')).toBeDisabled()
    await chooseFile(page, frame, raw, 'mobile-tree.json')
    await expectPreview(frame, 'tree', 5, 4)
    const imported = await confirmImport(page, frame, before, 5, 4)
    expect(imported.nodes[0].sourceRef).toBe('')
    expect(JSON.parse(imported.nodes[0].description)).toEqual(JSON.parse(raw))
    await expectNoDelayedUpload(page, api)
  })
})
