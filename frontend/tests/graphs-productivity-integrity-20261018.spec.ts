import { createHash } from 'node:crypto'
import { expect, test, type CDPSession, type Page, type TestInfo } from '@playwright/test'

const origin = 'http://localhost:55177'
const timestamp = '2026-10-18T12:00:00Z'
const owner = 'integrity-regression-20261018'
const workspaceKey = `dpms-graphs-workspace-v3:${owner}`

function graph(id = 'integrity-a', title = 'A') {
  const nodes = ['a', 'b'].map((id, index) => ({
    id, type: 'note', title: title + id, shape: 'rounded', radius: 8, scale: 1,
    autoSize: false, width: 160, height: 100, pinned: false, color: '#2F6BFF',
    x: 60 + index * 310, y: 80 + index * 170, items: [] as string[],
    customTypeLabel: '', sourceRef: '', description: '',
  }))
  const viewport = { x: 40, y: 50, scale: 1 }
  return {
    version: 3, id, title, createdAt: timestamp, updatedAt: timestamp, viewport, nodes,
    edges: [{ id: 'e', source: 'a', target: 'b', sourcePort: 'e:2', targetPort: 'w:2',
      label: 'edge', routing: 'curve', points: [{ x: 285, y: 180 }] }],
    groups: [], activeViewId: 'view-a', audit: [] as Array<{ id: string; at: string; action: string }>,
    views: [{ id: 'view-a', name: 'View', layout: 'radial', viewport: { ...viewport },
      positions: Object.fromEntries(nodes.map(({ id, x, y }) => [id, { x, y }])),
      focusNodeId: null, focusDepth: 0, connectionLensEnabled: false }],
  }
}

type Graph = ReturnType<typeof graph>
function documentFor(payload: Graph, revision = 1) {
  return {
    id: `document-${payload.id}`, client_id: payload.id, title: payload.title, revision,
    payload_bytes: JSON.stringify(payload).length, node_count: payload.nodes.length,
    edge_count: payload.edges.length, created_at: timestamp, updated_at: timestamp, payload,
  }
}
type ServerDocument = ReturnType<typeof documentFor>
type Metadata = { mode: string; revision: number | null; serverUpdatedAt: string | null; publishState: string; error: string }
type Workspace = { version: number; activeGraphId: string; graphs: Graph[]; storage: Record<string, Metadata> }
type Request = { requestId: string; operation: string; clientId?: string; baseRevision?: number | null; payload?: Graph }
type FixtureWindow = Window & typeof globalThis & {
  __integrityBridge: { requests: Request[]; documents: Record<string, ServerDocument> }
  __integrityQuota?: { rejected: number; restore: () => void }
}

function graphContent(value: Graph) {
  return { id: value.id, title: value.title, nodes: value.nodes, edges: value.edges, groups: value.groups,
    activeViewId: value.activeViewId, positions: value.views.map(({ id, positions }) => ({ id, positions })), audit: value.audit }
}

async function installFixture(page: Page, testInfo: TestInfo, revision: number | null = null, options: { holdGeometry?: boolean } = {}) {
  if (process.env.DPMS_REVIEW_GRAPH_SOURCE === '1') throw new Error('Integrity tests require the rebuilt served candidate')
  const local = graph()
  const remote = documentFor(graph('integrity-b', 'B'))
  const documents = new Map<string, ServerDocument>([[remote.client_id, remote]])
  if (revision !== null) documents.set(local.id, documentFor(local, revision))
  const seed: Workspace = { version: 3, activeGraphId: local.id, graphs: [local], storage: {
    [local.id]: { mode: 'local', revision, serverUpdatedAt: revision === null ? null : timestamp,
      publishState: revision === null ? 'local' : 'published', error: '' },
  } }
  const errors: string[] = []
  const blocked: string[] = []
  let geometryRequests = 0
  let releaseGeometry = () => {}
  const geometryGate = options.holdGeometry ? new Promise<void>(resolve => { releaseGeometry = resolve }) : Promise.resolve()
  page.on('pageerror', error => errors.push(error.message))
  await page.context().addInitScript(({ origin, workspaceKey, seed }) => {
    if (location.origin === origin && !localStorage.getItem(workspaceKey)) {
      localStorage.setItem(workspaceKey, JSON.stringify(seed))
    }
  }, { origin, workspaceKey, seed })
  await page.context().routeWebSocket('**/*', socket => socket.close())
  await page.context().route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === origin && request.method() === 'GET' && url.pathname === '/graphs') {
      const serialized = JSON.stringify(Object.fromEntries(documents)).replace(/</g, '\\u003c')
      return route.fulfill({ contentType: 'text/html', body: `<!doctype html>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>body{margin:0}iframe{width:100vw;height:100vh;border:0;display:block}</style>
        <iframe title="Integrity fixture" src="/graph-workspace/index.html?embedded=1&owner=${owner}"
          onload="this.contentWindow.postMessage({type:'dpms-graphs-host-ready',version:1},location.origin)"></iframe>
        <script>
          window.__integrityBridge = {requests:[],documents:${serialized}};
          window.addEventListener('message', event => {
            if (event.origin !== location.origin || event.source !== document.querySelector('iframe').contentWindow
              || event.data?.type !== 'dpms-graphs-storage-request') return;
            const state = window.__integrityBridge;
            state.requests.push(event.data);
            if (event.data.operation === 'list') event.source.postMessage({
              type:'dpms-graphs-storage-response',version:1,requestId:event.data.requestId,
              ok:true,data:Object.values(state.documents)
            },location.origin);
          });
        </script>` })
    }
    if (url.origin === origin && request.method() === 'GET' && url.pathname.startsWith('/graph-workspace/')) {
      if (options.holdGeometry && url.pathname.endsWith('/arrangement-geometry.mjs')) {
        geometryRequests += 1
        const response = await route.fetch()
        await geometryGate
        return route.fulfill({ response })
      }
      if (url.pathname.endsWith('/index.html')) {
        const response = await route.fetch()
        const body = await response.body()
        testInfo.annotations.push({ type: 'served-index-sha256', description: createHash('sha256').update(body).digest('hex') })
        return route.fulfill({ response, body })
      }
      return route.continue()
    }
    blocked.push(`${request.method()} ${url.pathname}`)
    return route.abort()
  })
  await page.goto('/graphs', { waitUntil: options.holdGeometry ? 'commit' : 'load' })
  const frame = page.frameLocator('iframe[title="Integrity fixture"]')
  await frame.locator('#graphTitle').waitFor({ state: 'attached' })
  if (!options.holdGeometry) await expect(frame.locator('#graphTitle')).toHaveValue('A')
  const read = () => page.evaluate(key => JSON.parse(localStorage.getItem(key) || '{}') as Workspace, workspaceKey)
  const open = async () => {
    await frame.locator('#graphManagerButton').click()
    await expect(frame.locator('[data-server-graph-open="integrity-b"]')).toBeVisible()
  }
  const close = () => frame.locator('[data-close-dialog="graphsDialog"]').click()
  const requests = (operation: string) => page.evaluate(operation =>
    (window as FixtureWindow).__integrityBridge.requests.filter(request => request.operation === operation), operation)
  const waitRequest = async (operation: string, index = 0) => {
    await expect.poll(async () => (await requests(operation)).length).toBeGreaterThan(index)
    return (await requests(operation))[index]
  }
  const reply = async (request: Request, data: ServerDocument) => {
    if (request.operation === 'put') documents.set(data.client_id, data)
    await page.evaluate(({ requestId, data }) => {
      const state = (window as FixtureWindow).__integrityBridge
      state.documents[data.client_id] = data
      document.querySelector('iframe')!.contentWindow!.postMessage({
        type: 'dpms-graphs-storage-response', version: 1, requestId, ok: true, data,
      }, location.origin)
    }, { requestId: request.requestId, data })
  }
  const live = () => frame.locator('#nodeLayer [data-node-id="a"]').evaluate(element => ({
    x: parseFloat((element as HTMLElement).style.left), y: parseFloat((element as HTMLElement).style.top),
    width: parseFloat((element as HTMLElement).style.width),
  }))
  const beginResize = async () => {
    await frame.locator('#nodeLayer [data-node-id="a"]').dispatchEvent('click')
    const handle = frame.locator('#nodeLayer [data-node-id="a"] [data-resize-handle="se"]')
    const box = await handle.boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
    await page.mouse.down()
    await page.mouse.move(box!.x + box!.width / 2 + 60, box!.y + box!.height / 2 + 20, { steps: 4 })
    await expect.poll(async () => (await live()).width).toBe(220)
  }
  const clean = async () => {
    expect(errors, 'Uncaught workspace errors').toEqual([])
    expect(blocked, 'Only the fixture host and local graph assets may be requested').toEqual([])
    expect(await requests('delete'), 'No server deletion is authorized by this fixture').toEqual([])
  }
  // Persist the normalized document before comparing rollback and gesture snapshots.
  if (!options.holdGeometry) { await open(); await close() }
  return { page, frame, remote, read, open, close, requests, waitRequest, reply, live, beginResize, clean,
    releaseGeometry, geometryRequests: () => geometryRequests }
}

async function singleTouchDrag(h: Awaited<ReturnType<typeof installFixture>>, cdp: CDPSession) {
  const before = (await h.read()).graphs[0]
  const box = await h.frame.locator('#nodeLayer [data-node-id="a"]').boundingBox()
  expect(box).not.toBeNull()
  const first = { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2, id: 17 }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...first, x: first.x + 28, y: first.y + 24 }] })
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await expect.poll(async () => (await h.read()).graphs[0].nodes[0].x).toBeCloseTo(before.nodes[0].x + 28 / before.viewport.scale, 6)
  const after = (await h.read()).graphs[0]
  expect(after.nodes[0].y).toBeCloseTo(before.nodes[0].y + 24 / before.viewport.scale, 6)
  expect(after.views[0].positions.a).toEqual({ x: after.nodes[0].x, y: after.nodes[0].y })
  expect(after.nodes[1]).toEqual(before.nodes[1])
  expect(after.edges).toEqual(before.edges)
  expect(after.audit).toHaveLength(before.audit.length + 1)
  expect(after.viewport).toEqual(before.viewport)
  return after
}

test('Loading: title stays disabled until the real geometry module and initial render finish', async ({ page }, testInfo) => {
  const h = await installFixture(page, testInfo, null, { holdGeometry: true })
  try {
    await expect.poll(h.geometryRequests).toBeGreaterThan(0)
    await expect(h.frame.locator('#graphTitle')).toBeDisabled()
    await expect(h.frame.locator('.app')).toHaveAttribute('inert', '')
    await expect(h.frame.locator('.app')).toHaveAttribute('aria-busy', 'true')
  } finally {
    h.releaseGeometry()
  }
  const title = h.frame.locator('#graphTitle')
  await expect(title).toBeEnabled()
  await expect(title).toHaveValue('A')
  await expect(h.frame.locator('.app')).not.toHaveAttribute('inert', '')
  await expect(h.frame.locator('.app')).toHaveAttribute('aria-busy', 'false')
  await title.fill('Title after module readiness')
  await title.press('Enter')
  await expect.poll(async () => (await h.read()).graphs[0].title).toBe('Title after module readiness')
  await page.reload()
  await expect(title).toBeEnabled()
  await expect(title).toHaveValue('Title after module readiness')
  expect((await h.read()).graphs[0].title).toBe('Title after module readiness')
  await h.clean()
})

for (const initialRevision of [null, 7]) {
  test(`INT-03: quota rollback during PUT retains revision and next baseRevision (${initialRevision ?? 'new'})`, async ({ page }, testInfo) => {
    const h = await installFixture(page, testInfo, initialRevision)
    await h.open()
    await h.frame.locator('[data-graph-publish="integrity-a"]').click()
    const request = await h.waitRequest('put')
    expect(request.baseRevision).toBe(initialRevision)
    await h.close()
    const before = (await h.read()).graphs[0]
    await h.frame.locator('body').evaluate((_body, key) => {
      const native = Storage.prototype.setItem
      const quota = { rejected: 0, restore: () => { Storage.prototype.setItem = native } }
      ;(window as FixtureWindow).__integrityQuota = quota
      Storage.prototype.setItem = function(name, value) {
        if (name === key) { quota.rejected += 1; throw new DOMException('Synthetic quota', 'QuotaExceededError') }
        return native.call(this, name, value)
      }
    }, workspaceKey)
    try {
      await h.frame.locator('#nodeLayer [data-node-id="a"]').dispatchEvent('click')
      await h.frame.locator('#nodeLayer [data-node-id="a"]').focus()
      await page.keyboard.press('ArrowRight')
      await expect.poll(() => h.frame.locator('body').evaluate(() => (window as FixtureWindow).__integrityQuota!.rejected)).toBeGreaterThan(0)
      expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(before))
      expect(await h.live()).toMatchObject({ x: before.nodes[0].x, y: before.nodes[0].y })
    } finally {
      await h.frame.locator('body').evaluate(() => (window as FixtureWindow).__integrityQuota!.restore())
    }
    const publishedRevision = (initialRevision ?? 0) + 1
    await h.reply(request, documentFor(request.payload!, publishedRevision))
    await expect.poll(async () => (await h.read()).storage['integrity-a']).toMatchObject({
      revision: publishedRevision, publishState: 'published', error: '', serverUpdatedAt: timestamp,
    })
    await page.reload()
    await expect(h.frame.locator('#graphTitle')).toHaveValue('A')
    expect((await h.read()).storage['integrity-a'].revision).toBe(publishedRevision)
    expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(before))
    await h.open()
    await h.frame.locator('[data-graph-publish="integrity-a"]').click()
    const next = await h.waitRequest('put')
    expect(next.baseRevision).toBe(publishedRevision)
    await h.reply(next, documentFor(next.payload!, publishedRevision + 1))
    await expect.poll(async () => (await h.read()).storage['integrity-a'].revision).toBe(publishedRevision + 1)
    await h.clean()
  })
}

test('INT-01: completing PUT never persists a resize preview canceled with Escape', async ({ page }, testInfo) => {
  const h = await installFixture(page, testInfo)
  await h.open()
  await h.frame.locator('[data-graph-publish="integrity-a"]').click()
  const request = await h.waitRequest('put')
  await h.close()
  const before = (await h.read()).graphs[0]
  await h.beginResize()
  await h.reply(request, documentFor(request.payload!))
  await expect.poll(async () => (await h.read()).storage['integrity-a'].revision).toBe(1)
  expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(before))
  await page.keyboard.press('Escape')
  await page.mouse.up()
  expect((await h.live()).width).toBe(160)
  await page.reload()
  await expect(h.frame.locator('#graphTitle')).toHaveValue('A')
  expect((await h.live()).width).toBe(160)
  expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(before))
  await h.clean()
})

test('INT-02: GET completion during resize keeps both source and destination intact', async ({ page }, testInfo) => {
  const h = await installFixture(page, testInfo)
  const before = (await h.read()).graphs[0]
  await h.open()
  await h.frame.locator('[data-server-graph-open="integrity-b"]').click()
  const request = await h.waitRequest('get')
  await h.close()
  await h.beginResize()
  await h.reply(request, h.remote)
  await expect(h.frame.locator('#graphTitle')).toHaveValue('B')
  await page.keyboard.press('Escape')
  await page.mouse.up()
  await expect(h.frame.locator('#graphTitle')).toHaveValue('B')
  await h.open()
  const stored = await h.read()
  expect(stored.activeGraphId).toBe('integrity-b')
  expect(graphContent(stored.graphs.find(value => value.id === 'integrity-a')!)).toEqual(graphContent(before))
  expect(graphContent(stored.graphs.find(value => value.id === 'integrity-b')!)).toEqual(graphContent(h.remote.payload))
  await page.reload()
  await expect(h.frame.locator('#graphTitle')).toHaveValue('B')
  expect((await h.read()).graphs).toEqual(stored.graphs)
  await h.clean()
})

test.describe('INT-05 native Chromium touch arbitration', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

  for (const preview of [false, true]) {
    for (const releaseFirst of ['primary', 'secondary'] as const) {
      test(`second contact ${preview ? 'after' : 'before'} preview; release ${releaseFirst} first`, async ({ page, browserName }, testInfo) => {
        test.skip(browserName !== 'chromium', 'Native CDP touch is Chromium-only; not physical iPhone coverage')
        const h = await installFixture(page, testInfo)
        const before = (await h.read()).graphs[0]
        const box = await h.frame.locator('#nodeLayer [data-node-id="a"]').boundingBox()
        expect(box).not.toBeNull()
        let first = { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2, id: 17 }
        const cdp = await page.context().newCDPSession(page)
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first] })
        if (preview) {
          first = { ...first, x: first.x + 12, y: first.y + 8 }
          await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [first] })
          await expect.poll(async () => (await h.live()).x).toBe(before.nodes[0].x + 12)
          expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(before))
        }
        const second = { x: first.x + 85, y: first.y + 25, id: 29 }
        expect(second.x + 38).toBeLessThan(390)
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [first, second] })
        await expect.poll(async () => (await h.live()).x).toBe(before.nodes[0].x)
        const moved = [first, second].map(point => ({ ...point, x: point.x + 28, y: point.y + 24 }))
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: moved })
        const remaining = moved[releaseFirst === 'primary' ? 1 : 0]
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [remaining] })
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ ...remaining, x: remaining.x + 10, y: remaining.y + 8 }] })
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
        // Cover the delayed viewport save, not only the immediate DOM rollback.
        await page.waitForTimeout(240)
        const after = (await h.read()).graphs[0]
        expect(graphContent(after)).toEqual(graphContent(before))
        expect(after.viewport.scale).toBeCloseTo(before.viewport.scale, 6)
        expect(after.viewport.x).toBeCloseTo(before.viewport.x + 28, 6)
        expect(after.viewport.y).toBeCloseTo(before.viewport.y + 24, 6)
        expect(await h.live()).toMatchObject({ x: before.nodes[0].x, y: before.nodes[0].y })
        // Reuse the same native session: a lost pointerup must not leave a stale contact.
        const recovered = await singleTouchDrag(h, cdp)
        await page.reload()
        await expect(h.frame.locator('#graphTitle')).toHaveValue('A')
        expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(recovered))
        await h.clean()
      })
    }
  }

  test('single-touch drag still commits nodes and active-view positions once', async ({ page, browserName }, testInfo) => {
    test.skip(browserName !== 'chromium', 'Native CDP touch is Chromium-only')
    const h = await installFixture(page, testInfo)
    const cdp = await page.context().newCDPSession(page)
    const after = await singleTouchDrag(h, cdp)
    await page.reload()
    await expect(h.frame.locator('#graphTitle')).toHaveValue('A')
    expect(graphContent((await h.read()).graphs[0])).toEqual(graphContent(after))
    await h.clean()
  })
})
