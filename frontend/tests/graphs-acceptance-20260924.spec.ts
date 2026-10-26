import { expect, test, type FrameLocator, type Locator, type Page } from '@playwright/test'

// Run against the user's existing instance; do not start another preview server.
test.use({ baseURL: 'http://localhost:55177', viewport: { width: 1440, height: 1000 } })
test.setTimeout(45_000)
test.beforeEach(({ isMobile }) => {
  test.skip(isMobile, 'These acceptance cases exercise desktop mouse and keyboard interactions')
})

const userId = '11111111-1111-4111-8111-111111111111'
const frameSelector = 'iframe[title="Рабочее пространство графов"]'
const graphId = 'acceptance-20260924'
const testUser = {
  id: userId, full_name: 'Graph acceptance QA', email: 'graphs-test@example.invalid',
  league: 'A', role: 'executor', mpw: 0, wip_limit: 5, wallet_main: 0, wallet_karma: 0,
  quality_score: 100, is_active: true, is_new_employee: false, task_workspace_enabled: false,
  can_link_queue_tasks_to_projects: false, feedback_enabled: false, audit_enabled: false,
  audit_calendar_enabled: false, competency_development_enabled: false,
  competency_constructor_enabled: false, plan_started_at: null, onboarding_started_at: null,
  onboarding_until: null, sidebar_menu_order: null, needs_password_change: false,
  created_at: '2026-09-24T00:00:00Z', updated_at: '2026-09-24T00:00:00Z',
}

type GraphNode = {
  id: string; title: string; type: 'note' | 'sticker' | 'list'
  x: number; y: number; width: number; height: number; autoSize: boolean
  shape: 'rounded' | 'circle'; radius: number; scale: number; items: string[]
  customTypeLabel: string; sourceRef: string; description: string; pinned: boolean; color: string
}
type GraphEdge = {
  id: string; source: string; target: string; label: string
  routing: 'curve' | 'orthogonal' | 'straight'; points: Array<{ x: number; y: number }>
  sourcePort?: string | null; targetPort?: string | null
}

function node(id: string, x: number, y: number, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id, title: id, type: 'note', x, y, width: 180, height: 140, autoSize: false,
    shape: 'rounded', radius: 8, scale: 1, items: [], customTypeLabel: '', sourceRef: '',
    description: '', pinned: false, color: '#38756A', ...overrides,
  }
}

function makeGraph(nodes: GraphNode[], edges: GraphEdge[] = [], viewport = { x: 24, y: 24, scale: 1 }) {
  return {
    version: 3, id: graphId, title: 'Acceptance 2026-09-24',
    createdAt: '2026-09-24T00:00:00Z', updatedAt: '2026-09-24T00:00:00Z',
    viewport, nodes, edges, groups: [], activeViewId: 'acceptance-view', audit: [],
    views: [{
      id: 'acceptance-view', name: 'Acceptance', layout: 'radial', viewport,
      positions: Object.fromEntries(nodes.map(({ id, x, y }) => [id, { x, y }])),
      focusNodeId: null, focusDepth: 0, connectionLensEnabled: false,
    }],
  }
}

async function openWorkspace(page: Page, nodes: GraphNode[], edges: GraphEdge[] = [], viewport?: { x: number; y: number; scale: number }) {
  // Same isolated owner, API boundary and workspace envelope as graphs-integration.spec.ts.
  // Seeding only once is essential: reload assertions must observe edits, not a reset fixture.
  await page.addInitScript(({ ownerId, graph }) => {
    if (window !== window.top) return
    window.localStorage.setItem('dpms_token', 'graphs-acceptance-synthetic-token')
    const key = `dpms-graphs-workspace-v3:${ownerId}`
    if (window.localStorage.getItem(key) !== null) return
    window.localStorage.setItem(key, JSON.stringify({
      version: 3, activeGraphId: graph.id, graphs: [graph],
      storage: { [graph.id]: {
        mode: 'local', revision: null, serverUpdatedAt: null, publishState: 'local', error: '',
      } },
    }))
  }, { ownerId: userId, graph: makeGraph(nodes, edges, viewport) })
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
    const pathname = new URL(route.request().url()).pathname
    const body = pathname === '/api/auth/me' ? testUser
      : pathname === '/api/messages/summary' ? { direct_count: 0, important_count: 0, revision: 0 }
        : []
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto('/graphs')
  const frame = page.frameLocator(frameSelector)
  await expect(page.locator(frameSelector)).toBeVisible()
  await expect(frame.locator('#graphTitle')).toHaveValue('Acceptance 2026-09-24')
  await expect(frame.locator('.graph-node')).toHaveCount(nodes.length)
  await expect(frame.locator('#zoomValue')).toHaveText(`${Math.round((viewport?.scale ?? 1) * 100)}%`)
  return frame
}

async function storedGraph(page: Page) {
  const graph = await page.evaluate((ownerId) => {
    const workspace = JSON.parse(window.localStorage.getItem(`dpms-graphs-workspace-v3:${ownerId}`) || '{}') as {
      activeGraphId?: string; graphs?: Array<ReturnType<typeof makeGraph>>
    }
    return workspace.graphs?.find((item) => item.id === workspace.activeGraphId)
  }, userId)
  expect(graph, 'The UI must persist its active graph locally').toBeTruthy()
  return graph!
}

async function box(locator: Locator) {
  const bounds = await locator.boundingBox()
  expect(bounds, 'The pointer target must have a rendered bounding box').not.toBeNull()
  return bounds!
}

async function dragBy(page: Page, handle: Locator, dx: number, dy: number) {
  await expect(handle).toBeVisible()
  const bounds = await box(handle)
  const x = bounds.x + bounds.width / 2
  const y = bounds.y + bounds.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  try {
    await page.mouse.move(x + dx, y + dy, { steps: 12 })
  } finally {
    await page.mouse.up()
  }
}

async function framePortAttachment(node: Locator, port: string) {
  return node.evaluate((element, id) => {
    const bounds = element.getBoundingClientRect()
    const [side, index] = id.split(':')
    const fraction = (Number(index) + 0.5) / 5
    return {
      x: bounds.left + bounds.width * (side === 'w' ? 0 : side === 'e' ? 1 : fraction),
      y: bounds.top + bounds.height * (side === 'n' ? 0 : side === 's' ? 1 : fraction),
    }
  }, port)
}

async function svgGeometry(locator: Locator) {
  // All returned coordinates are in the iframe viewport, not the outer page viewport.
  return locator.evaluate((element) => {
    const path = element as SVGPathElement
    const length = path.getTotalLength()
    const matrix = path.getScreenCTM()
    if (!matrix || !Number.isFinite(length) || length <= 0) throw new Error('SVG path is not rendered')
    const at = (distance: number) => {
      const point = path.getPointAtLength(distance).matrixTransform(matrix)
      return { x: point.x, y: point.y }
    }
    const start = at(0)
    const end = at(length)
    const previous = at(Math.max(0, length - 0.5))
    const tangentLength = Math.hypot(end.x - previous.x, end.y - previous.y)
    const markerId = path.getAttribute('marker-end')?.match(/#([^)'"\s]+)/)?.[1]
    const marker = markerId ? path.ownerDocument.querySelector<SVGMarkerElement>(`marker#${CSS.escape(markerId)}`) : null
    const triangle = marker?.querySelector('path')?.getBBox()
    const style = getComputedStyle(path)
    return {
      start, end, length,
      tangent: { x: (end.x - previous.x) / tangentLength, y: (end.y - previous.y) / tangentLength },
      painted: !path.closest('[hidden]') && style.display !== 'none' && style.visibility === 'visible'
        && Number(style.opacity) > 0 && Number(style.strokeOpacity) > 0 && style.stroke !== 'none'
        && Number.parseFloat(style.strokeWidth) > 0,
      marker: marker && triangle ? {
        refX: marker.refX.baseVal.value, refY: marker.refY.baseVal.value,
        tipX: triangle.x + triangle.width, tipY: triangle.y + triangle.height / 2,
        orient: marker.getAttribute('orient'),
      } : null,
    }
  })
}

function expectSamePoint(actual: { x: number; y: number }, expected: { x: number; y: number }) {
  // Allow subpixel differences between browser SVG metrics and the rendered node boundary.
  expect(Math.hypot(actual.x - expected.x, actual.y - expected.y)).toBeLessThan(2)
}

test('2.2 palette sticker + Add Center keeps Tab in the inline sticker sequence', async ({ page }) => {
  const frame = await openWorkspace(page, [])
  await frame.locator('[data-entity-type="sticker"]').click()
  await frame.locator('#addCenterButton').click()
  const editor = frame.locator('#inlineNodeEditor')
  await expect(editor).toBeVisible()
  await expect(editor).toBeFocused()
  await expect(frame.locator('.graph-node.sticker')).toHaveCount(1)
  await editor.fill('Acceptance sticker one')
  await editor.press('Tab')
  await expect(frame.locator('.graph-node.sticker')).toHaveCount(2)
  await expect(editor).toBeVisible()
  await expect(editor).toBeFocused()
  await expect(frame.locator('#nodeTitleField')).not.toBeFocused()
  await editor.fill('Acceptance sticker two')
  await editor.press('Enter')
  await expect(editor).toBeHidden()
  await expect(frame.locator('.graph-node.sticker .node-title')).toHaveText(['Acceptance sticker one', 'Acceptance sticker two'])
  const first = await box(frame.locator('.graph-node.sticker').nth(0))
  const second = await box(frame.locator('.graph-node.sticker').nth(1))
  expect(second.x).toBeGreaterThan(first.x + first.width)
  expect(second.y).toBeCloseTo(first.y, 0)
  await page.reload()
  await expect(frame.locator('.graph-node.sticker .node-title')).toHaveText(['Acceptance sticker one', 'Acceptance sticker two'])
  expect((await storedGraph(page)).nodes).toHaveLength(2)
})

test('2.4 manual rectangle exposes twenty ports and north/west drags preserve the opposite edges', async ({ page }, testInfo) => {
  const original = node('resizable', 180, 240)
  const frame = await openWorkspace(page, [original])
  const target = frame.locator('[data-node-id="resizable"]')
  await target.click()
  await expect(frame.locator('#autoSizeField')).not.toBeChecked()
  const ports = target.locator('[data-port-id]')
  await expect(ports).toHaveCount(20)
  expect((await ports.evaluateAll((elements) => elements.map((element) => element.getAttribute('data-port-id')))).sort())
    .toEqual(['n', 'e', 's', 'w'].flatMap((side) => Array.from({ length: 5 }, (_, index) => `${side}:${index}`)).sort())
  const portLayout = await ports.evaluateAll((elements) => elements.map((element) => {
    const bounds = element.closest('[data-node-id]')!.getBoundingClientRect()
    const point = element.getBoundingClientRect()
    return {
      id: element.getAttribute('data-port-id')!,
      x: (point.left + point.width / 2 - bounds.left) / bounds.width,
      y: (point.top + point.height / 2 - bounds.top) / bounds.height,
    }
  }))
  for (const point of portLayout) {
    const [side, index] = point.id.split(':')
    const fraction = (Number(index) + 0.5) / 5
    expect(Math.abs(point.x - (side === 'w' ? 0 : side === 'e' ? 1 : fraction))).toBeLessThan(0.015)
    expect(Math.abs(point.y - (side === 'n' ? 0 : side === 's' ? 1 : fraction))).toBeLessThan(0.015)
  }
  for (const side of ['n', 'e', 's', 'w']) {
    const sidePorts = target.locator(`[data-port-id^="${side}:"]`)
    await expect(sidePorts).toHaveCount(5)
    for (const port of await sidePorts.all()) {
      await expect(port).toBeVisible()
      await expect(port).toHaveCSS('opacity', '1')
      await expect(port).toHaveAttribute('data-resize-handle', /.+/)
    }
  }
  const before = await box(target)
  await dragBy(page, target.locator('[data-port-id="n:1"]'), 0, -60)
  await expect.poll(async () => (await box(target)).height).toBeCloseTo(before.height + 60, 0)
  const north = await box(target)
  expect(north.y).toBeCloseTo(before.y - 60, 0)
  expect(north.y + north.height).toBeCloseTo(before.y + before.height, 0)
  expect(north.width).toBeCloseTo(before.width, 0)
  await dragBy(page, target.locator('[data-port-id="w:3"]'), -50, 0)
  const west = await box(target)
  expect(west.x).toBeCloseTo(before.x - 50, 0)
  expect(west.width).toBeCloseTo(before.width + 50, 0)
  expect(west.x + west.width).toBeCloseTo(before.x + before.width, 0)
  expect(west.y).toBeCloseTo(north.y, 0)
  expect(west.height).toBeCloseTo(north.height, 0)
  await expect.poll(async () => (await storedGraph(page)).nodes[0]).toMatchObject({
    x: original.x - 50, y: original.y - 60, width: original.width + 50, height: original.height + 60,
  })
  await page.reload()
  await expect(target).toBeVisible()
  const reloaded = await box(target)
  for (const dimension of ['x', 'y', 'width', 'height'] as const) expect(reloaded[dimension]).toBeCloseTo(west[dimension], 0)
  await target.click()
  const portsScreenshot = testInfo.outputPath('2.4-twenty-ports.png')
  await page.screenshot({ path: portsScreenshot })
  await testInfo.attach('2.4 resized node with twenty ports', { path: portsScreenshot, contentType: 'image/png' })
  await frame.locator('#autoSizeField').check()
  await expect(target.locator('[data-resize-handle]')).toHaveCount(0)
})

test('2.4 Shift-drag between explicit ports persists both attachments across reload', async ({ page }) => {
  const frame = await openWorkspace(page, [node('source', 60, 220), node('target', 400, 260)])
  const source = frame.locator('[data-node-id="source"]')
  const target = frame.locator('[data-node-id="target"]')
  await source.click()
  const sourcePort = source.locator('[data-port-id="e:4"]')
  const targetPort = target.locator('[data-port-id="n:1"]')
  const from = await box(sourcePort)
  await target.hover()
  await expect(targetPort).toBeVisible()
  const to = await box(targetPort)
  await page.keyboard.down('Shift')
  try {
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 16 })
    await expect(targetPort).toHaveClass(/snap-port/)
  } finally {
    await page.mouse.up()
    await page.keyboard.up('Shift')
  }
  await expect(frame.locator('.edge-group')).toHaveCount(1)
  await expect.poll(async () => (await storedGraph(page)).edges).toEqual([expect.objectContaining({
    source: 'source', target: 'target', sourcePort: 'e:4', targetPort: 'n:1',
  })])
  await page.reload()
  await expect(frame.locator('.edge-group')).toHaveCount(1)
  const geometry = await svgGeometry(frame.locator('.edge-line'))
  expectSamePoint(geometry.start, await framePortAttachment(source, 'e:4'))
  expectSamePoint(geometry.end, await framePortAttachment(target, 'n:1'))
  expect((await storedGraph(page)).edges[0]).toMatchObject({ sourcePort: 'e:4', targetPort: 'n:1' })
})

for (const shape of ['rounded', 'circle'] as const) {
  for (const side of ['n', 's'] as const) {
    for (const routing of ['curve', 'orthogonal', 'straight'] as const) {
      for (const editable of [false, true]) {
        test(`2.5 ${shape} target ${side}, ${routing}, ${editable ? 'editable points' : 'no points'}: tangent and triangle tip`, async ({ page }) => {
          const source = node('source', 220, side === 'n' ? 70 : 470, { shape, width: 180, height: 180 })
          const target = node('target', 220, side === 'n' ? 370 : 170, { shape, width: 180, height: 180 })
          const middleY = side === 'n' ? 310 : 410
          const edge: GraphEdge = {
            id: 'tangent-edge', source: source.id, target: target.id, label: 'Attachment QA', routing: 'curve',
            points: editable ? [{ x: 340, y: middleY }, { x: 310, y: middleY }] : [],
            sourcePort: shape === 'circle' ? null : `${side === 'n' ? 's' : 'n'}:2`,
            targetPort: shape === 'circle' ? null : `${side}:2`,
          }
          const frame = await openWorkspace(page, [source, target], [edge])
          await frame.locator('[data-edge-id="tangent-edge"] .edge-label-bg').click()
          await frame.locator('#edgeRoutingField').selectOption(routing)
          await expect(frame.locator('#edgeRoutingField')).toHaveValue(routing)
          const geometry = await svgGeometry(frame.locator('[data-edge-id="tangent-edge"] .edge-line'))
          const targetBounds = await frame.locator('[data-node-id="target"]').evaluate((element) => {
            const bounds = element.getBoundingClientRect()
            return { x: bounds.left + bounds.width / 2, top: bounds.top, bottom: bounds.bottom }
          })
          expect(geometry.painted).toBe(true)
          expectSamePoint(geometry.end, { x: targetBounds.x, y: side === 'n' ? targetBounds.top : targetBounds.bottom })
          expect.soft(geometry.tangent.x, 'Arrow must not arrive sideways').toBeCloseTo(0, 3)
          expect.soft(geometry.tangent.y, 'Final tangent points into the target').toBeCloseTo(side === 'n' ? 1 : -1, 3)
          expect(geometry.marker).not.toBeNull()
          expect.soft(geometry.marker!.refX, 'Marker reference must be the triangle tip, not its body').toBeCloseTo(geometry.marker!.tipX, 5)
          expect.soft(geometry.marker!.refY).toBeCloseTo(geometry.marker!.tipY, 5)
          expect(geometry.marker!.orient).toMatch(/^auto(?:-start-reverse)?$/)
        })
      }
    }
  }
}

test('2.6 Shift-drag paints a live SVG preview and softly snaps before release outside the target', async ({ page }, testInfo) => {
  const frame = await openWorkspace(page, [node('source', 60, 240), node('target', 400, 240)])
  const source = frame.locator('[data-node-id="source"]')
  const target = frame.locator('[data-node-id="target"]')
  await source.click()
  const from = await box(source.locator('[data-port-id="e:2"]'))
  const targetBounds = await box(target)
  const preview = frame.locator('#edgePreview')
  await expect(preview).toBeHidden()
  await page.keyboard.down('Shift')
  try {
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(targetBounds.x - 45, targetBounds.y + targetBounds.height / 2 - 40, { steps: 10 })
    await expect(preview).toBeVisible()
    expect((await svgGeometry(preview)).painted).toBe(true)
    expect((await svgGeometry(preview)).length).toBeGreaterThan(50)
    await expect(target).not.toHaveClass(/magnet-target/)
    await expect(frame.locator('.edge-group')).toHaveCount(0)
    expect((await storedGraph(page)).edges).toHaveLength(0)
    const unsnapped = await preview.getAttribute('d')

    await page.mouse.move(targetBounds.x - 10, targetBounds.y + targetBounds.height / 2, { steps: 8 })
    await expect(target).toHaveClass(/magnet-target/)
    await expect(target.locator('[data-port-id="w:2"]')).toHaveClass(/snap-port/)
    await expect(preview).not.toHaveAttribute('d', unsnapped!)
    expectSamePoint((await svgGeometry(preview)).end, await framePortAttachment(target, 'w:2'))
    await expect.soft(target.locator('[data-port-id="w:2"]'), 'The snapped port must be visible even while the pointer is outside the node').toBeVisible()
    expect(await target.evaluate((element) => {
      const bounds = element.getBoundingClientRect()
      return element.ownerDocument.elementFromPoint(bounds.left - 10, bounds.top + bounds.height / 2)?.closest('[data-node-id]')?.getAttribute('data-node-id') || null
    }), 'The release point must be outside every node, so only magnetism can connect').toBeNull()
    await expect(frame.locator('.edge-group')).toHaveCount(0)
    const previewScreenshot = testInfo.outputPath('2.6-live-snapped-preview.png')
    await page.screenshot({ path: previewScreenshot })
    await testInfo.attach('2.6 live snapped preview before release', { path: previewScreenshot, contentType: 'image/png' })
  } finally {
    await page.mouse.up()
    await page.keyboard.up('Shift')
  }
  await expect(preview).toBeHidden()
  await expect(frame.locator('.edge-group')).toHaveCount(1)
  expectSamePoint((await svgGeometry(frame.locator('.edge-line'))).end, await framePortAttachment(target, 'w:2'))
  await expect.poll(async () => (await storedGraph(page)).edges).toEqual([expect.objectContaining({
    source: 'source', target: 'target', sourcePort: 'e:2', targetPort: 'w:2',
  })])
  const connectedScreenshot = testInfo.outputPath('2.6-connected.png')
  await page.screenshot({ path: connectedScreenshot })
  await testInfo.attach('2.6 committed connection after release', { path: connectedScreenshot, contentType: 'image/png' })
})

test('2.7 enlarging a seven-item list reveals every item without clipping or an ellipsis', async ({ page }, testInfo) => {
  const items = Array.from({ length: 7 }, (_, index) => `Acceptance item ${index + 1}`)
  const frame = await openWorkspace(page, [node('list', 160, 160, { type: 'list', width: 260, height: 138, items })])
  const list = frame.locator('[data-node-id="list"]')
  await list.click()
  await expect(list.locator('.node-list-items li')).toHaveCount(7)
  await expect(list.locator('.node-list-more')).toBeVisible()
  expect(await list.locator('.node-list-items li:visible').count()).toBeLessThan(7)
  const before = await box(list)
  await dragBy(page, list.locator('[data-port-id="s:2"]'), 0, 250)
  await expect.poll(async () => (await box(list)).height).toBeCloseTo(before.height + 250, 0)
  expect((await box(list)).y).toBeCloseTo(before.y, 0)
  await expect(list.locator('.node-list-items li:visible')).toHaveText(items)
  await expect(list.locator('.node-list-more')).toBeHidden()
  const allItemsFit = () => list.evaluate((element) => {
    const region = element.querySelector('.node-list-region')!.getBoundingClientRect()
    const content = element.querySelector('.node-list-items')!.getBoundingClientRect()
    const reference = element.querySelector('.node-ref')!.getBoundingClientRect()
    return Array.from(element.querySelectorAll('li')).every((item) => {
      const bounds = item.getBoundingClientRect()
      return !item.hidden && bounds.height > 0 && bounds.top >= Math.max(region.top, content.top) - 0.5
        && bounds.bottom <= Math.min(region.bottom, content.bottom, reference.top) + 0.5
        && bounds.left >= region.left - 0.5 && bounds.right <= region.right + 0.5
    })
  })
  await expect.poll(allItemsFit, { message: 'Visible list rows must actually fit within their clipping region' }).toBe(true)
  await expect.poll(async () => (await storedGraph(page)).nodes[0]).toMatchObject({ items, height: 388 })
  await page.reload()
  await expect(list.locator('.node-list-items li:visible')).toHaveText(items)
  await expect(list.locator('.node-list-more')).toBeHidden()
  await expect.poll(allItemsFit).toBe(true)
  const listScreenshot = testInfo.outputPath('2.7-seven-items-after-reload.png')
  await page.screenshot({ path: listScreenshot })
  await testInfo.attach('2.7 all seven list items after resize and reload', { path: listScreenshot, contentType: 'image/png' })
})

async function renderedScale(frame: FrameLocator) {
  return frame.locator('#world').evaluate((element) => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)
}

async function plainWheel(page: Page, frame: FrameLocator, deltaY: number) {
  const canvas = await box(frame.locator('#canvas'))
  await page.mouse.move(canvas.x + canvas.width * 0.6, canvas.y + canvas.height * 0.75)
  await page.mouse.wheel(0, deltaY)
}

test('2.8 plain wheel zooms both ways and the inversion checkbox persists across reload', async ({ page }) => {
  const frame = await openWorkspace(page, [])
  const invert = frame.locator('#wheelInvertField')
  await expect(invert).toBeVisible()
  await expect(invert).not.toBeChecked()
  const initial = await renderedScale(frame)
  await plainWheel(page, frame, 120)
  await expect.poll(() => renderedScale(frame), { message: 'Plain wheel must change scale, not just pan' }).toBeLessThan(initial)
  const normalDown = await renderedScale(frame)
  await plainWheel(page, frame, -120)
  await expect.poll(() => renderedScale(frame)).toBeGreaterThan(normalDown)

  await invert.check()
  const beforeInverted = await renderedScale(frame)
  await plainWheel(page, frame, 120)
  await expect.poll(() => renderedScale(frame)).toBeGreaterThan(beforeInverted)
  const invertedDown = await renderedScale(frame)
  // CSS matrix serialization rounds to fewer significant digits than persisted JS numbers.
  await expect.poll(async () => Math.abs((await storedGraph(page)).viewport.scale - invertedDown)).toBeLessThan(1e-5)
  const persistedScale = (await storedGraph(page)).viewport.scale
  await page.reload()
  await expect(invert).toBeChecked()
  await expect.poll(async () => (await storedGraph(page)).viewport.scale).toBe(persistedScale)
  await expect.poll(async () => Math.abs(await renderedScale(frame) - persistedScale)).toBeLessThan(1e-5)
  await plainWheel(page, frame, -120)
  await expect.poll(() => renderedScale(frame)).toBeLessThan(invertedDown)
  await invert.uncheck()
  const beforeNormal = await renderedScale(frame)
  await plainWheel(page, frame, 120)
  await expect.poll(() => renderedScale(frame)).toBeLessThan(beforeNormal)
})

test('2.4 R1: NW resize cannot cross -100000 coordinates, including after reload', async ({ page }) => {
  const original = node('bounded', -100000, -100000)
  // Both viewport offsets remain within the storage contract; the corner renders at (200, 200).
  const frame = await openWorkspace(page, [original], [], { x: 100000, y: 100000, scale: 0.998 })
  const target = frame.locator('[data-node-id="bounded"]')
  await target.click()
  const before = await box(target)
  const handle = await box(target.locator('[data-resize-handle="nw"]'))
  const x = handle.x + handle.width / 2
  const y = handle.y + handle.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  try {
    await page.mouse.move(x - 60, y - 60, { steps: 12 })
    const during = await box(target)
    for (const dimension of ['x', 'y', 'width', 'height'] as const) {
      expect(during[dimension], 'The leading bounds must hold during the drag, not only on save').toBeCloseTo(before[dimension], 0)
    }
  } finally {
    await page.mouse.up()
  }
  await expect.poll(async () => (await storedGraph(page)).nodes[0]).toMatchObject({
    id: original.id, x: -100000, y: -100000, width: original.width, height: original.height,
  })
  await page.reload()
  await expect(frame.locator('#storageRecoveryDialog')).toBeHidden()
  await expect(target).toBeVisible()
  const after = await box(target)
  for (const dimension of ['x', 'y', 'width', 'height'] as const) expect(after[dimension]).toBeCloseTo(before[dimension], 0)
  expect((await storedGraph(page)).nodes[0]).toMatchObject({
    id: original.id, x: -100000, y: -100000, width: original.width, height: original.height,
  })
})

test('2.4 R1: legacy 1000x900 circle at x=100000 rejects NW resize but allows east shrink', async ({ page }) => {
  const original = node('legacy-circle', 100000, 0, { shape: 'circle', width: 1000, height: 900 })
  // Local x=80 clears the tool rail; both handles stay visible above semantic zoom.
  const viewport = { x: -59920, y: 40, scale: 0.6 }
  const frame = await openWorkspace(page, [original], [], viewport)
  const target = frame.locator('[data-node-id="legacy-circle"]')
  await target.click()
  await expect(frame.locator('#autoSizeField')).not.toBeChecked()
  const before = await box(target)
  const originalGeometry = { x: original.x, y: original.y, width: original.width, height: original.height }

  async function expectRenderedCircle(diameter: number) {
    await expect(target).toHaveCSS('left', `${original.x}px`)
    await expect(target).toHaveCSS('top', `${original.y}px`)
    await expect(target).toHaveCSS('width', `${diameter}px`)
    // A legacy circle renders square even when its stored height differs from its width.
    await expect(target).toHaveCSS('height', `${diameter}px`)
    const bounds = await box(target)
    expect(bounds.x).toBeCloseTo(before.x, 1)
    expect(bounds.y).toBeCloseTo(before.y, 1)
    expect(bounds.width).toBeCloseTo(diameter * viewport.scale, 1)
    expect(bounds.height).toBeCloseTo(diameter * viewport.scale, 1)
  }

  await expectRenderedCircle(1000)
  expect((await storedGraph(page)).nodes[0]).toMatchObject(originalGeometry)
  const nw = target.locator('[data-resize-handle="nw"]')
  await expect(nw).toBeInViewport()
  await nw.hover()
  const handle = await box(nw)
  const x = handle.x + handle.width / 2
  const y = handle.y + handle.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  try {
    // No feasible diameter can preserve the opposite edges and keep x <= 100000.
    await page.mouse.move(x - 1, y)
    await expectRenderedCircle(1000)
  } finally {
    await page.mouse.up()
  }
  await expectRenderedCircle(1000)
  await expect.poll(async () => (await storedGraph(page)).nodes[0]).toMatchObject(originalGeometry)
  await page.reload()
  await expect(frame.locator('#storageRecoveryDialog')).toBeHidden()
  await expectRenderedCircle(1000)
  expect((await storedGraph(page)).nodes[0]).toMatchObject(originalGeometry)

  await target.click()
  const east = target.locator('[data-resize-handle="e"]')
  await expect(east).toBeInViewport()
  await dragBy(page, east, -100 * viewport.scale, 0)
  await expectRenderedCircle(900)
  const shrunkGeometry = { ...originalGeometry, width: 900, height: 900 }
  await expect.poll(async () => (await storedGraph(page)).nodes[0]).toMatchObject(shrunkGeometry)
  await page.reload()
  await expect(frame.locator('#storageRecoveryDialog')).toBeHidden()
  await expectRenderedCircle(900)
  expect((await storedGraph(page)).nodes[0]).toMatchObject(shrunkGeometry)
})

test('2.7 R2: auto-size list with twenty items stays 224x108 at scale one and its port matches the edge', async ({ page }) => {
  const items = Array.from({ length: 20 }, (_, index) => `Auto list item ${index + 1}`)
  const frame = await openWorkspace(page, [
    node('source', 40, 200),
    node('auto-list', 340, 220, { type: 'list', autoSize: true, width: 260, height: 138, items }),
  ], [{
    id: 'auto-list-edge', source: 'source', target: 'auto-list', label: 'Auto list attachment',
    routing: 'curve', points: [], sourcePort: 'e:2', targetPort: 'w:2',
  }])
  const list = frame.locator('[data-node-id="auto-list"]')
  await list.click()
  await expect(frame.locator('#autoSizeField')).toBeChecked()
  const bounds = await box(list)
  expect(bounds.width).toBeCloseTo(224, 1)
  expect(bounds.height).toBeCloseTo(108, 1)
  expect(await list.evaluate((element) => new DOMMatrixReadOnly(getComputedStyle(element).transform).a)).toBe(1)
  await expect(list.locator('.node-list-items li')).toHaveCount(20)
  await expect(list.locator('.node-list-more')).toBeVisible()
  const port = list.locator('[data-port-id="w:2"]')
  await expect(port).toBeVisible()
  const portCenter = await port.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return { x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }
  })
  const geometry = await svgGeometry(frame.locator('[data-edge-id="auto-list-edge"] .edge-line'))
  expect(geometry.painted).toBe(true)
  expectSamePoint(geometry.end, await framePortAttachment(list, 'w:2'))
  expectSamePoint(geometry.end, portCenter)
  expect((await storedGraph(page)).nodes.find((item) => item.id === 'auto-list')?.items).toEqual(items)
})

test('2.6 R4: the (5,5) corner of a 200px circle box is outside its 18px magnet range', async ({ page }) => {
  const frame = await openWorkspace(page, [
    node('source', 60, 240), node('circle', 400, 240, { shape: 'circle', width: 200, height: 200 }),
  ])
  const source = frame.locator('[data-node-id="source"]')
  const circle = frame.locator('[data-node-id="circle"]')
  const from = await box(source)
  const target = await box(circle)
  expect(target.width).toBeCloseTo(200, 1)
  expect(target.height).toBeCloseTo(200, 1)
  expect(Math.hypot(target.width / 2 - 5, target.height / 2 - 5) - target.width / 2).toBeGreaterThan(18)
  await page.keyboard.down('Shift')
  try {
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(target.x + 100, target.y + 100, { steps: 10 })
    await expect(circle).toHaveClass(/magnet-target/)
    await page.mouse.move(target.x + 5, target.y + 5, { steps: 10 })
    await expect(frame.locator('#edgePreview')).toBeVisible()
    await expect(circle).not.toHaveClass(/magnet-target/)
  } finally {
    await page.mouse.up()
    await page.keyboard.up('Shift')
  }
  await expect(frame.locator('#edgePreview')).toBeHidden()
  await expect(frame.locator('.edge-group')).toHaveCount(0)
  expect((await storedGraph(page)).edges).toEqual([])
})

test('2.6 R4: pointer x=201 hits overlapping B (180..380), not the nearby port of A (0..200)', async ({ page }) => {
  const frame = await openWorkspace(page, [
    node('source', 440, 40, { width: 140, height: 108 }),
    node('overlap-a', 0, 240, { width: 200, height: 200 }),
    node('overlap-b', 180, 240, { width: 200, height: 200 }),
  ])
  const source = frame.locator('[data-node-id="source"]')
  const a = frame.locator('[data-node-id="overlap-a"]')
  const b = frame.locator('[data-node-id="overlap-b"]')
  const from = await box(source)
  const bounds = await box(a)
  expect(bounds.width).toBeCloseTo(200, 1)
  expect((await box(b)).x - bounds.x).toBeCloseTo(180, 1)
  await page.keyboard.down('Shift')
  try {
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(bounds.x + 170, bounds.y + 100, { steps: 10 })
    await expect(a).toHaveClass(/magnet-target/)
    await page.mouse.move(bounds.x + 201, bounds.y + 100, { steps: 6 })
    expect(await b.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return element.ownerDocument.elementFromPoint(rect.left + 21, rect.top + 100)?.closest('[data-node-id]')?.getAttribute('data-node-id')
    })).toBe('overlap-b')
    await expect(b).toHaveClass(/magnet-target/)
    await expect(a).not.toHaveClass(/magnet-target/)
  } finally {
    await page.mouse.up()
    await page.keyboard.up('Shift')
  }
  await expect(frame.locator('#edgePreview')).toBeHidden()
  await expect(frame.locator('.edge-group')).toHaveCount(1)
  await expect.poll(async () => (await storedGraph(page)).edges).toEqual([expect.objectContaining({
    source: 'source', target: 'overlap-b',
  })])
})
