import { expect, test as base, type Locator, type Page } from '@playwright/test'
import {
  graphFixture, installGraphFixture, readWorkspace, workspaceFrame, workspaceName,
} from './review-graphs-remediation-helpers'

type Point = { x: number; y: number }
type Viewport = Point & { scale: number }
type Node = Omit<ReturnType<typeof graphFixture>['nodes'][number], 'items'> & { items: string[] }
type Edge = ReturnType<typeof graphFixture>['edges'][number] & {
  sourcePort: string | null; targetPort: string | null
}
type Group = { id: string; title: string; color: string; nodeIds: string[]; collapsed: boolean }
type View = {
  id: string; name: string; layout: string; viewport: Viewport
  positions: Record<string, Point>; focusNodeId: string | null; focusDepth: number
  connectionLensEnabled: boolean
}
type Graph = Omit<ReturnType<typeof graphFixture>, 'nodes' | 'edges' | 'groups' | 'views' | 'audit'> & {
  nodes: Node[]; edges: Edge[]; groups: Group[]; views: View[]
  audit: Array<{ id: string; at: string; action: string }>
}
type Workspace = Omit<Awaited<ReturnType<typeof readWorkspace>>, 'graphs'> & { graphs: Graph[] }
type ApiMock = Awaited<ReturnType<typeof installGraphFixture>>
type WorkerGate = { hold: boolean; posted: number; received: number; queue: Array<() => void>; delivered: number }
type TestWindow = Window & typeof globalThis & {
  __productivityWorkerGate?: WorkerGate
  __productivityQuota?: { enabled: boolean; rejected: number; restore: () => void }
}
type Command = 'left' | 'center' | 'right' | 'top' | 'middle' | 'bottom'
  | 'distribute-x' | 'distribute-y' | 'row' | 'column' | 'grid'
const alignments: Command[] = ['left', 'center', 'right', 'top', 'middle', 'bottom']
const commands: Command[] = [...alignments, 'distribute-x', 'distribute-y', 'row', 'column', 'grid']
const toolbarCommands = commands.filter((name) => name !== 'row' && name !== 'column')

function node(id: string, x: number, y: number, overrides: Partial<Node> = {}): Node {
  return { ...graphFixture().nodes[0], id, title: id, x, y, ...overrides }
}

function graph(nodes = [node('a', 40, 80), node('b', 270, 250, { width: 180, height: 140 }),
  node('c', 580, 130, { width: 96, height: 96 })], overrides: Partial<Graph> = {}): Graph {
  const viewport = overrides.viewport || { x: 40, y: 100, scale: 1 }
  return {
    ...graphFixture('productivity-a', 'Productivity QA'), nodes, edges: [], groups: [], audit: [],
    viewport, activeViewId: 'view-a',
    views: ['view-a', 'view-b'].map((id, index) => ({
      id, name: id, layout: 'radial', viewport: { ...viewport },
      positions: Object.fromEntries(nodes.map((item) => [item.id, { x: item.x + index * 900, y: item.y - index * 600 }])),
      focusNodeId: null, focusDepth: 0, connectionLensEnabled: index === 1,
    })),
    ...overrides,
  }
}

function edge(source: string, target: string): Edge {
  return { id: `${source}-${target}`, source, target, label: 'QA route', routing: 'curve',
    sourcePort: 'e:4', targetPort: 'w:1', points: [{ x: 215, y: 185 }, { x: 365, y: 210 }] }
}

function group(id: string, nodeIds: string[], collapsed = false): Group {
  return { id, title: id, color: '#2F6BFF', nodeIds, collapsed }
}

const test = base.extend<{ openWorkspace: (graphs?: Graph[]) => Promise<ApiMock> }>({
  openWorkspace: async ({ page }, run) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    let mock: ApiMock | undefined
    await run(async (graphs = [graph()]) => {
      if (mock) throw new Error('Seed this isolated browser context only once')
      if (process.env.DPMS_REVIEW_GRAPH_SOURCE === '1') throw new Error('Productivity acceptance requires the rebuilt served candidate')
      // The old helper infers empty groups/views as never[]; only its seed boundary needs widening.
      mock = await installGraphFixture(page, { local: graphs as unknown as ReturnType<typeof graphFixture>[] })
      await page.goto('/graphs')
      await expect(page).toHaveURL('http://localhost:55177/graphs')
      await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue(graphs[0].title)
      await expect(workspaceFrame(page).locator('#selectionToolbar')).toHaveCount(1)
      await expect(workspaceFrame(page).locator('#layoutProgress')).toHaveAttribute('role', 'status')
      await expect(workspaceFrame(page).locator('#layoutCancelButton')).toBeHidden()
      return mock
    })
    expect(errors, 'Uncaught workspace errors').toEqual([])
    expect(mock?.unexpectedWrites, 'Local arrangement must not publish or mutate any API').toEqual([])
    expect(mock?.deletes, 'Local arrangement must not delete a system snapshot').toEqual([])
  },
})

async function stored(page: Page): Promise<Workspace> {
  return await readWorkspace(page) as unknown as Workspace
}

async function active(page: Page): Promise<Graph> {
  const workspace = await stored(page)
  const current = workspace.graphs.find((item) => item.id === workspace.activeGraphId)
  expect(current).toBeTruthy()
  return current!
}

function positions(value: Graph) {
  return Object.fromEntries(value.nodes.map(({ id, x, y }) => [id, { x, y }]))
}

function content(value: Graph) {
  return Object.fromEntries(Object.entries(value).filter(([field]) => field !== 'audit' && field !== 'updatedAt'))
}

function expectDataIntact(after: Graph, before: Graph) {
  expect(Object.keys(after).sort()).toEqual(Object.keys(before).sort())
  expect(after.id).toBe(before.id)
  expect(after.createdAt).toBe(before.createdAt)
  expect(after.version).toBe(3)
  expect(after.edges).toEqual(before.edges)
  expect(after.groups).toEqual(before.groups)
  const nodeDetails = (value: Node) => Object.fromEntries(Object.entries(value).filter(([field]) => field !== 'x' && field !== 'y'))
  expect(after.nodes.map(nodeDetails)).toEqual(before.nodes.map(nodeDetails))
  const currentView = after.views.find((view) => view.id === after.activeViewId)!
  expect(currentView.positions).toEqual(positions(after))
  expect(after.views.filter((view) => view.id !== after.activeViewId))
    .toEqual(before.views.filter((view) => view.id !== after.activeViewId))
  for (const point of [...after.nodes, ...after.edges.flatMap((item) => item.points), after.viewport]) {
    for (const axis of ['x', 'y'] as const) {
      expect(Number.isFinite(point[axis])).toBe(true)
      expect(Math.abs(point[axis])).toBeLessThanOrEqual(100_000)
    }
  }
}

async function activate(page: Page, control: Locator) {
  await expect(control).toBeVisible()
  if (test.info().project.use.hasTouch) await control.tap()
  else await control.click()
}

async function closePanels(page: Page) {
  const frame = workspaceFrame(page)
  for (const name of ['inspector', 'library']) {
    if (await frame.locator('body').evaluate((body, value) => body.classList.contains(`show-${value}`), name)) {
      await activate(page, frame.locator(`#${name}Toggle`))
    }
  }
}

async function field(page: Page, id: string) {
  const frame = workspaceFrame(page)
  const target = frame.locator(`#${id}`)
  const panel = /^(layout|view|activeView)/.test(id) ? 'library' : 'inspector'
  if (await frame.locator(`.side-panel.${panel}`).getAttribute('aria-hidden') === 'true') {
    await activate(page, frame.locator(`#${panel}Toggle`))
  }
  await expect(target).toBeVisible()
  return target
}

async function option(page: Page, id: string, value: string) {
  await (await field(page, id)).selectOption(value)
  await closePanels(page)
}

async function numberField(page: Page, id: string, value: number) {
  const input = await field(page, id)
  await input.fill(String(value))
  await input.press('Tab')
  await closePanels(page)
}

async function selectNodes(page: Page, ids: string[]) {
  await closePanels(page)
  const frame = workspaceFrame(page)
  await frame.locator('#canvas').focus()
  await page.keyboard.press('Escape')
  // Exercise the real selection handler without panning offscreen mathematical fixtures.
  // Native tap activation and pointer dragging are tested separately below.
  for (let index = 0; index < ids.length; index += 1) {
    await frame.locator(`#nodeLayer [data-node-id="${ids[index]}"]`).dispatchEvent('click', { ctrlKey: index > 0 })
  }
  expect(await frame.locator('.graph-node.selected').evaluateAll((elements) => elements.map((el) => el.getAttribute('data-node-id')).sort()))
    .toEqual([...ids].sort())
}

async function selected(page: Page) {
  return workspaceFrame(page).locator('.graph-node.selected').evaluateAll((elements) =>
    elements.map((el) => el.getAttribute('data-node-id')).sort())
}

async function command(page: Page, name: Command) {
  await closePanels(page)
  const frame = workspaceFrame(page)
  const inspectorOnly = name === 'row' || name === 'column'
  if (inspectorOnly && await frame.locator('#inspector').getAttribute('aria-hidden') === 'true') {
    await activate(page, frame.locator('#inspectorToggle'))
  }
  const button = frame.locator(`${inspectorOnly ? '#inspector' : '#selectionToolbar'} [data-arrange-command="${name}"]`)
  await expect(button).toHaveCount(1)
  await expect(button).toBeEnabled()
  await activate(page, button)
  if (inspectorOnly) await closePanels(page)
}

async function undoTo(page: Page, before: Graph) {
  await activate(page, workspaceFrame(page).locator('#undoButton'))
  await expect.poll(async () => content(await active(page))).toEqual(content(before))
}

async function settle(page: Page) {
  // Covers the existing 180 ms viewport persistence timer and queued paint callbacks.
  await workspaceFrame(page).locator('body').evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 220)))
  }))
}

async function viewport(page: Page) {
  return workspaceFrame(page).locator('#world').evaluate((world) => {
    const matrix = new DOMMatrixReadOnly(getComputedStyle(world).transform)
    return { x: matrix.e, y: matrix.f, scale: matrix.a }
  })
}

async function zoomTo(page: Page, scale: number) {
  const canvas = workspaceFrame(page).locator('#canvas')
  for (let step = 0; step < 5 && Math.abs((await viewport(page)).scale - scale) > 0.00001; step += 1) {
    const current = (await viewport(page)).scale
    await canvas.evaluate((element, deltaY) => {
      const rect = element.getBoundingClientRect()
      element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true,
        clientX: rect.left + 50, clientY: rect.top + 50, ctrlKey: true, deltaY }))
    }, -Math.log(scale / current) / 0.0018)
  }
  await expect.poll(async () => (await viewport(page)).scale).toBeCloseTo(scale, 4)
  await settle(page)
}

async function toggle(page: Page, id: string, enabled: boolean) {
  const button = workspaceFrame(page).locator(`#${id}`)
  if (await button.getAttribute('aria-pressed') !== String(enabled)) await activate(page, button)
  await expect(button).toHaveAttribute('aria-pressed', String(enabled))
}

async function rect(locator: Locator) {
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { x: box.x, y: box.y, width: box.width, height: box.height }
  })
}

type Drag = { touch: boolean; id: number; start: Point; local: Point; current: Point; alt: boolean }
async function startDrag(page: Page, target: Locator, alt = false): Promise<Drag> {
  const touch = Boolean(test.info().project.use.hasTouch)
  const local = await rect(target)
  const outer = await target.boundingBox()
  expect(outer).not.toBeNull()
  const start = { x: outer!.x + outer!.width / 2, y: outer!.y + outer!.height / 2 }
  const localPoint = { x: local.x + local.width / 2, y: local.y + local.height / 2 }
  await target.evaluate((element) => element.addEventListener('pointerdown', (event) => {
    element.ownerDocument.documentElement.dataset.productivityPointer = String((event as PointerEvent).pointerId)
  }, { once: true, capture: true }))
  if (touch) {
    // Handler/cancellation coverage, not a claim about native iOS drag arbitration.
    await target.dispatchEvent('pointerdown', { pointerId: 41, pointerType: 'touch', isPrimary: true,
      button: 0, buttons: 1, clientX: localPoint.x, clientY: localPoint.y, altKey: alt })
  } else {
    if (alt) await page.keyboard.down('Alt')
    await page.mouse.move(start.x, start.y)
    await page.mouse.down()
  }
  const id = Number(await workspaceFrame(page).locator('html').getAttribute('data-productivity-pointer'))
  expect(id).toBeGreaterThan(0)
  return { touch, id, start, local: localPoint, current: localPoint, alt }
}

async function moveDrag(page: Page, drag: Drag, dx: number, dy: number) {
  drag.current = { x: drag.local.x + dx, y: drag.local.y + dy }
  if (drag.touch) {
    await workspaceFrame(page).locator('#canvas').dispatchEvent('pointermove', { pointerId: drag.id,
      pointerType: 'touch', isPrimary: true, button: 0, buttons: 1,
      clientX: drag.current.x, clientY: drag.current.y, altKey: drag.alt })
  } else await page.mouse.move(drag.start.x + dx, drag.start.y + dy, { steps: 8 })
}

async function endDrag(page: Page, drag: Drag) {
  if (drag.touch) await workspaceFrame(page).locator('#canvas').dispatchEvent('pointerup', {
    pointerId: drag.id, pointerType: 'touch', isPrimary: true, button: 0, buttons: 0,
    clientX: drag.current.x, clientY: drag.current.y, altKey: drag.alt,
  })
  else {
    await page.mouse.up()
    if (drag.alt) await page.keyboard.up('Alt')
  }
}

async function dragBy(page: Page, target: Locator, dx: number, dy: number, alt = false) {
  const drag = await startDrag(page, target, alt)
  try { await moveDrag(page, drag, dx, dy) } finally { await endDrag(page, drag) }
}

async function installWorkerGate(page: Page) {
  await page.addInitScript(() => {
    if (window.parent === window) return
    const state: WorkerGate = { hold: true, posted: 0, received: 0, queue: [], delivered: 0 }
    ;(window as TestWindow).__productivityWorkerGate = state
    const postMessage = Worker.prototype.postMessage
    const observed = new WeakSet<Worker>()
    // Keep native construction/handlers and preserve the original send argument list.
    Worker.prototype.postMessage = function (this: Worker, ...args: [unknown, (Transferable[] | StructuredSerializeOptions)?]) {
      state.posted += 1
      if (!observed.has(this)) {
        observed.add(this)
        const handler = this.onmessage
        if (!handler) throw new Error('Layout worker must register its result handler before posting')
        // Worker is an EventTarget: capture alone does not guarantee listener order in Chromium.
        this.onmessage = null
        this.addEventListener('message', (event: MessageEvent) => {
          state.received += 1
          if (!state.hold) return
          event.stopImmediatePropagation()
          const data: unknown = structuredClone(event.data)
          state.queue.push(() => {
            handler.call(this, new MessageEvent('message', { data }))
            state.delivered += 1
          })
        }, { capture: true })
        this.onmessage = handler
      }
      Reflect.apply(postMessage, this, args)
    }
  })
}

async function workerState(page: Page) {
  return workspaceFrame(page).locator('body').evaluate(() => {
    const state = (window as TestWindow).__productivityWorkerGate!
    return { posted: state.posted, received: state.received, queued: state.queue.length, delivered: state.delivered }
  })
}

async function releaseWorker(page: Page) {
  await workspaceFrame(page).locator('body').evaluate(() => {
    const state = (window as TestWindow).__productivityWorkerGate!
    state.hold = false
    state.queue.splice(0).forEach((deliver) => deliver())
  })
  await settle(page)
}

async function holdWorker(page: Page) {
  await workspaceFrame(page).locator('body').evaluate(() => { (window as TestWindow).__productivityWorkerGate!.hold = true })
}

async function awaitHeldLayout(page: Page) {
  await expect(workspaceFrame(page).locator('#layoutCancelButton')).toBeVisible()
  await expect(workspaceFrame(page).locator('#layoutProgress')).toBeVisible()
  await expect.poll(async () => (await workerState(page)).queued).toBeGreaterThan(0)
}

async function installQuota(page: Page) {
  await workspaceFrame(page).locator('body').evaluate((_body, name) => {
    const prototype = Object.getPrototypeOf(localStorage) as Storage
    const original = prototype.setItem
    const state = { enabled: true, rejected: 0, restore: () => { prototype.setItem = original } }
    ;(window as TestWindow).__productivityQuota = state
    prototype.setItem = function (key: string, value: string) {
      if (this === window.localStorage && key === name && state.enabled) {
        state.rejected += 1
        throw new DOMException('Synthetic productivity quota failure', 'QuotaExceededError')
      }
      return original.call(this, key, value)
    }
  }, workspaceName)
}

async function quotaCount(page: Page) {
  return workspaceFrame(page).locator('body').evaluate(() => (window as TestWindow).__productivityQuota!.rejected)
}

function expectNoOverlap(value: Graph) {
  const hidden = new Set(value.groups.filter((item) => item.collapsed).flatMap((item) => item.nodeIds))
  const nodes = value.nodes.filter((item) => !hidden.has(item.id))
  nodes.forEach((a, index) => nodes.slice(index + 1).forEach((b) => {
    const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)
    const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y)
    expect(Math.min(overlapX, overlapY), `${a.id} overlaps ${b.id} at expanded size`).toBeLessThanOrEqual(0.01)
  }))
}

test('3.2 all six bounds alignments are immediate, data-safe and one-step undoable', async ({ page, openWorkspace }) => {
  await openWorkspace([graph(undefined, { edges: [edge('a', 'b'), edge('b', 'c')] })])
  await selectNodes(page, ['a', 'b', 'c'])
  expect(await (await field(page, 'alignmentReferenceField')).inputValue()).toBe('bounds')
  expect(await (await field(page, 'arrangementGapField')).inputValue()).toBe('32')
  const before = await active(page)
  const expected: Record<string, number[]> = {
    left: [40, 40, 40], center: [298, 268, 310], right: [556, 496, 580],
    top: [80, 80, 80], middle: [195, 165, 187], bottom: [310, 250, 294],
  }
  for (const name of alignments) await test.step(name, async () => {
    const axis = ['left', 'center', 'right'].includes(name) ? 'x' : 'y'
    const other = axis === 'x' ? 'y' : 'x'
    const auditCount = (await active(page)).audit.length
    await command(page, name)
    await expect.poll(async () => (await active(page)).nodes.map((item) => item[axis])).toEqual(expected[name])
    const after = await active(page)
    expect(after.nodes.map((item) => item[other])).toEqual(before.nodes.map((item) => item[other]))
    expect(after.viewport).toEqual(before.viewport)
    expect(after.audit).toHaveLength(auditCount + 1)
    expectDataIntact(after, before)
    expect(await selected(page)).toEqual(['a', 'b', 'c'])
    await undoTo(page, before)
  })
})

test('3.2 primary pinned reference and hidden nodes do not expand the immediate selection', async ({ page, openWorkspace }) => {
  const nodes = [node('a', 60, 80), node('b', 280, 230, { width: 180, height: 140 }),
    node('pin', 520, 100, { pinned: true, width: 160, height: 100 }), node('member', 760, 260),
    node('hidden-a', 30, 500), node('hidden-b', 220, 500)]
  await openWorkspace([graph(nodes, { groups: [group('expanded', ['b', 'member']), group('collapsed', ['hidden-a', 'hidden-b'], true)] })])
  await selectNodes(page, ['a', 'b', 'pin'])
  await option(page, 'alignmentReferenceField', 'primary')
  const before = await active(page)
  const expected: Record<string, number[]> = {
    left: [520, 520], center: [540, 510], right: [560, 500],
    top: [100, 100], middle: [110, 80], bottom: [120, 60],
  }
  for (const name of alignments) await test.step(name, async () => {
    await command(page, name)
    const axis = ['left', 'center', 'right'].includes(name) ? 'x' : 'y'
    await expect.poll(async () => (await active(page)).nodes.slice(0, 2).map((item) => item[axis])).toEqual(expected[name])
    const after = await active(page)
    expect(after.nodes.slice(2)).toEqual(before.nodes.slice(2))
    expectDataIntact(after, before)
    await undoTo(page, before)
  })
  await option(page, 'alignmentReferenceField', 'bounds')
  await workspaceFrame(page).locator('#canvas').focus()
  await page.keyboard.press('ControlOrMeta+a')
  await command(page, 'left')
  const after = await active(page)
  expect(after.nodes.find((item) => item.id === 'pin')).toEqual(before.nodes[2])
  expect(after.nodes.filter((item) => item.id.startsWith('hidden'))).toEqual(before.nodes.slice(4))
  await selectNodes(page, ['a'])
  await expect(workspaceFrame(page).locator('#selectionToolbar')).toBeHidden()
})

test('3.2 distribution uses variable-size edge gaps and overlapping input is an exact no-op', async ({ page, openWorkspace }) => {
  await openWorkspace()
  await selectNodes(page, ['a', 'b', 'c'])
  const before = await active(page)
  await command(page, 'distribute-x')
  await expect.poll(async () => (await active(page)).nodes.map((item) => item.x)).toEqual([40, 280, 580])
  const distributed = await active(page)
  expect(distributed.nodes[1].x - distributed.nodes[0].x - distributed.nodes[0].width).toBe(120)
  expect(distributed.nodes[2].x - distributed.nodes[1].x - distributed.nodes[1].width).toBe(120)
  expectDataIntact(distributed, before)
  await undoTo(page, before)
  const beforeNoop = await stored(page)
  await command(page, 'distribute-y')
  await settle(page)
  expect(await stored(page)).toEqual(beforeNoop)
  await expect(workspaceFrame(page).locator('#redoButton')).toBeEnabled()
  await expect(workspaceFrame(page).locator('#toastRegion')).not.toBeEmpty()
})

test('3.2 row, column and grid use size-aware spacing without changing edge routes', async ({ page, openWorkspace }) => {
  const nodes = [node('a', 80, 80), node('b', 330, 180, { width: 180, height: 140 }), node('c', 600, 300, { width: 96, height: 96 })]
  await openWorkspace([graph(nodes, { edges: [edge('a', 'b')] })])
  await selectNodes(page, ['a', 'b', 'c'])
  const before = await active(page)
  for (const gap of [32, 52]) {
    await numberField(page, 'arrangementGapField', gap)
    for (const name of ['row', 'column', 'grid'] as const) await test.step(`${name}, gap=${gap}`, async () => {
      await command(page, name)
      const expected = name === 'row'
        ? { a: { x: 80, y: 80 }, b: { x: 200 + gap, y: 80 }, c: { x: 380 + gap * 2, y: 80 } }
        : name === 'column'
          ? { a: { x: 80, y: 80 }, b: { x: 80, y: 160 + gap }, c: { x: 80, y: 300 + gap * 2 } }
          : { a: { x: 80, y: 80 }, b: { x: 200 + gap, y: 80 }, c: { x: 80, y: 220 + gap } }
      await expect.poll(async () => positions(await active(page))).toEqual(expected)
      const after = await active(page)
      expectNoOverlap(after)
      expectDataIntact(after, before)
      await undoTo(page, before)
    })
  }
})

test('3.2 gap blur retains the first row click and reference changes retain keyboard focus', async ({ page, openWorkspace }) => {
  await openWorkspace([graph([node('a', 80, 80), node('b', 330, 180, { width: 180, height: 140 }), node('c', 600, 300)])])
  await selectNodes(page, ['a', 'b', 'c'])
  const frame = workspaceFrame(page)
  const before = await active(page)
  await (await field(page, 'arrangementGapField')).fill('80')
  // Do not blur or close the inspector first: pointerdown must survive the input change.
  await activate(page, frame.locator('#inspector [data-arrange-command="row"]'))
  await expect.poll(async () => positions(await active(page))).toEqual({
    a: { x: 80, y: 80 }, b: { x: 280, y: 80 }, c: { x: 540, y: 80 },
  })
  const after = await active(page)
  expect(after.audit).toHaveLength(before.audit.length + 1)
  expectDataIntact(after, before)
  const reference = await field(page, 'alignmentReferenceField')
  await reference.focus()
  await reference.selectOption('primary')
  await expect(reference).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(reference).toBeFocused()
  await settle(page)
  expect(content(await active(page))).toEqual(content(after))
  await closePanels(page)
  await undoTo(page, before)
})

test('3.2 search matches all text fields, filters types and safely reveals hidden results', async ({ page, openWorkspace }) => {
  const title = '<b data-injected="yes">needle-title</b>'
  const nodes = [node('title', 40, 80, { title }),
    node('source', 280, 80, { sourceRef: 'REF<&"needle-source>' }),
    node('description', 40, 250, { description: 'needle-description' }),
    node('items', 5000, 4000, { type: 'list', items: ['needle-item'], width: 240, height: 138 }),
    node('member', 5400, 4000)]
  await openWorkspace([graph(nodes, { groups: [group('hidden', ['items', 'member'], true)], edges: [edge('title', 'items')] })])
  const frame = workspaceFrame(page)
  const before = await active(page)
  await expect(frame.locator('#nodeLayer [data-node-id="items"]')).toBeHidden()
  await activate(page, frame.locator('#graphSearchButton'))
  const input = frame.locator('#graphSearchInput')
  const results = frame.locator('#graphSearchResults [data-search-node]')
  await expect(input).toBeFocused()
  for (const [query, id] of [['needle-title', 'title'], ['needle-source', 'source'],
    ['needle-description', 'description'], ['needle-item', 'items']]) {
    await input.fill(query)
    await expect(results).toHaveCount(1)
    await expect(results).toHaveAttribute('data-search-node', id)
    if (id === 'title') await expect(results.locator('strong')).toHaveText(title)
    if (id === 'source') await expect(results).toContainText('REF<&"needle-source>')
    await expect(frame.locator('#graphSearchResults [data-injected]')).toHaveCount(0)
  }
  await input.fill('needle')
  await expect(results).toHaveCount(4)
  await frame.locator('#graphSearchType').selectOption('list')
  await expect(results).toHaveCount(1)
  await expect(results).toHaveAttribute('data-search-node', 'items')
  await input.fill('no-such-qa-result')
  await expect(results).toHaveCount(0)
  await input.fill('needle-item')
  await input.press('ArrowDown')
  await expect(results).toBeFocused()
  await results.press('Enter')
  await expect(frame.locator('#graphSearchDialog')).not.toBeVisible()
  await expect(frame.locator('#nodeLayer [data-node-id="items"]')).toBeVisible()
  expect(await selected(page)).toEqual(['items'])
  const after = await active(page)
  expect(after.nodes).toEqual(before.nodes)
  expect(after.edges).toEqual(before.edges)
  expect(after.groups).toEqual(before.groups.map((item) => ({ ...item, collapsed: false })))
  expect(after.views[1]).toEqual(before.views[1])
  expect(after.viewport).not.toEqual(before.viewport)
  const box = await rect(frame.locator('#nodeLayer [data-node-id="items"]'))
  const canvas = await rect(frame.locator('#canvas'))
  expect(box.x).toBeGreaterThanOrEqual(canvas.x)
  expect(box.y).toBeGreaterThanOrEqual(canvas.y)
  expect(box.x + box.width).toBeLessThanOrEqual(canvas.x + canvas.width + 1)
  expect(box.y + box.height).toBeLessThanOrEqual(canvas.y + canvas.height + 1)
  await page.reload()
  await expect(frame.locator('#nodeLayer [data-node-id="items"]')).toBeVisible()
  expect(content(await active(page))).toEqual(content(after))
})

test('3.2 additive click or tap selection and child insertion preserve existing nodes', async ({ page, openWorkspace }) => {
  await openWorkspace([graph([node('a', 20, 40), node('b', 20, 180), node('c', 200, 40)],
    { viewport: { x: 20, y: 20, scale: 0.6 }, edges: [edge('b', 'c')] })])
  const frame = workspaceFrame(page)
  const before = await active(page)
  const nodeControl = (id: string) => frame.locator(`#nodeLayer [data-node-id="${id}"]`)
  await toggle(page, 'multiSelectButton', true)
  await activate(page, nodeControl('a'))
  await activate(page, nodeControl('b'))
  expect(await selected(page)).toEqual(['a', 'b'])
  await activate(page, nodeControl('a'))
  expect(await selected(page)).toEqual(['b'])
  await toggle(page, 'multiSelectButton', false)
  await activate(page, nodeControl('c'))
  expect(await selected(page)).toEqual(['c'])
  expect(content(await active(page))).toEqual(content(before))
  await activate(page, nodeControl('a'))
  await frame.locator('#canvas').focus()
  await page.keyboard.press('Shift+Tab')
  await expect(frame.locator('#inlineNodeEditor')).toBeVisible()
  await frame.locator('#inlineNodeEditor').press('Enter')
  const after = await active(page)
  expect(after.nodes).toHaveLength(before.nodes.length + 1)
  expect(after.nodes.slice(0, before.nodes.length)).toEqual(before.nodes)
  expect(after.edges.slice(0, before.edges.length)).toEqual(before.edges)
  expect(after.edges).toHaveLength(before.edges.length + 1)
  const child = after.nodes.at(-1)!
  expect(after.edges.at(-1)).toMatchObject({ source: 'a', target: child.id })
  for (const obstacle of before.nodes) {
    const horizontalGap = Math.max(child.x - obstacle.x - obstacle.width, obstacle.x - child.x - child.width)
    const verticalGap = Math.max(child.y - obstacle.y - obstacle.height, obstacle.y - child.y - child.height)
    expect(Math.max(horizontalGap, verticalGap)).toBeGreaterThanOrEqual(24)
  }
  expect(after.viewport).toEqual(before.viewport)
  expect(after.views[1]).toEqual(before.views[1])
  expectNoOverlap(after)
  await undoTo(page, before)
})

test('3.2 undo, redo, reload and switching views preserve exact arrangement and camera', async ({ page, openWorkspace }) => {
  await openWorkspace([graph(undefined, { edges: [edge('a', 'b')] })])
  await selectNodes(page, ['a', 'b', 'c'])
  const before = await active(page)
  await command(page, 'center')
  const after = await active(page)
  await undoTo(page, before)
  await activate(page, workspaceFrame(page).locator('#redoButton'))
  await expect.poll(async () => content(await active(page))).toEqual(content(after))
  await option(page, 'activeViewField', 'view-b')
  expect(positions(await active(page))).toEqual(before.views[1].positions)
  await option(page, 'activeViewField', 'view-a')
  expect(content(await active(page))).toEqual(content(after))
  await page.reload()
  await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue(after.title)
  expect(content(await active(page))).toEqual(content(after))
  await expect(workspaceFrame(page).locator('#undoButton')).toBeDisabled()
  await selectNodes(page, ['a', 'b', 'c'])
  await command(page, 'left')
  await undoTo(page, after)
  await page.reload()
  await expect(workspaceFrame(page).locator('#canvas')).toBeVisible()
  expect(content(await active(page))).toEqual(content(after))
})

test('3.2 object snap uses six screen pixels at semantic/normal zoom; off and Alt copy bypass', async ({ page, openWorkspace }) => {
  await openWorkspace([graph([node('a', 80, 80), node('b', 250, 120, { width: 180, height: 100, pinned: true })], { edges: [edge('a', 'b')] })])
  const frame = workspaceFrame(page)
  await expect(frame.locator('#snapObjectsButton')).toHaveAttribute('aria-pressed', 'true')
  await expect(frame.locator('#snapGridButton')).toHaveAttribute('aria-pressed', 'false')
  for (const scale of [0.5, 1, 2]) {
    await zoomTo(page, scale)
    // Snap references must intersect the canvas, including on a short landscape viewport.
    await frame.locator('#canvas').evaluate((canvas) => {
      const bounds = canvas.getBoundingClientRect()
      const source = document.querySelector('#nodeLayer [data-node-id="a"]')!.getBoundingClientRect()
      canvas.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true,
        deltaX: source.x + source.width / 2 - bounds.x - Math.min(120, bounds.width / 4),
        deltaY: source.y + source.height / 2 - bounds.y - Math.min(120, bounds.height / 2) }))
    })
    await settle(page)
    await expect(frame.locator('#nodeLayer [data-node-id="b"]')).toBeInViewport()
    for (const [enabled, alt, distance] of [[true, false, 5], [true, false, 7], [false, false, 5], [true, true, 5]] as const) {
      await test.step(`scale=${scale}, objects=${enabled}, alt=${alt}, distance=${distance}`, async () => {
        await toggle(page, 'snapObjectsButton', enabled)
        const before = await active(page)
        const source = frame.locator('#nodeLayer [data-node-id="a"]')
        const target = frame.locator('#nodeLayer [data-node-id="b"]')
        const from = await rect(source)
        const to = await rect(target)
        await dragBy(page, source, to.x - from.x - distance, 0, alt)
        const shouldSnap = enabled && !alt && distance <= 6
        const moved = alt ? frame.locator('#nodeLayer .graph-node.selected') : source
        await expect.poll(async () => Math.abs((await rect(moved)).x - to.x)).toBeCloseTo(shouldSnap ? 0 : distance, 0)
        const after = await active(page)
        expect(after.nodes[1]).toEqual(before.nodes[1])
        if (alt) {
          expect(after.nodes.slice(0, before.nodes.length)).toEqual(before.nodes)
          expect(after.nodes).toHaveLength(before.nodes.length + 1)
          expect(after.edges).toEqual(before.edges)
          expect(after.groups).toEqual(before.groups)
        } else expectDataIntact(after, before)
        await undoTo(page, before)
      })
    }
  }
})

test('3.2 grid snapping uses 24 world units and group offsets survive commit, cancel and reload', async ({ page, openWorkspace }) => {
  const nodes = [node('a', 80.25, 90.5), node('b', 250.75, 150.25), node('outside', 570, 350)]
  await openWorkspace([graph(nodes, { edges: [edge('a', 'b'), edge('b', 'outside')], groups: [group('team', ['a', 'b'])] })])
  await toggle(page, 'snapObjectsButton', false)
  await toggle(page, 'snapGridButton', true)
  const before = await active(page)
  const frame = workspaceFrame(page)
  const groupOrigin = await frame.locator('.group-frame[data-group-id="team"]').evaluate((element) => ({
    x: parseFloat((element as HTMLElement).style.left), y: parseFloat((element as HTMLElement).style.top),
  }))
  await dragBy(page, frame.locator('[data-group-drag="team"]'), 37, 29)
  const after = await active(page)
  const delta = { x: after.nodes[0].x - before.nodes[0].x, y: after.nodes[0].y - before.nodes[0].y }
  // Dragging the group header anchors its visible frame, including its padding.
  expect(delta).toEqual({
    x: Math.round((groupOrigin.x + 37 / before.viewport.scale) / 24) * 24 - groupOrigin.x,
    y: Math.round((groupOrigin.y + 29 / before.viewport.scale) / 24) * 24 - groupOrigin.y,
  })
  expect(after.nodes[1].x - before.nodes[1].x).toBe(delta.x)
  expect(after.nodes[1].y - before.nodes[1].y).toBe(delta.y)
  expect(await frame.locator('.group-frame[data-group-id="team"]').evaluate((element) => ({
    x: parseFloat((element as HTMLElement).style.left), y: parseFloat((element as HTMLElement).style.top),
  }))).toEqual({ x: groupOrigin.x + delta.x, y: groupOrigin.y + delta.y })
  expect(after.nodes[2]).toEqual(before.nodes[2])
  expectDataIntact(after, before)
  const drag = await startDrag(page, frame.locator('[data-group-drag="team"]'))
  try {
    await moveDrag(page, drag, 51, 37)
    await page.keyboard.press('Escape')
    await moveDrag(page, drag, 90, 50)
  } finally { await endDrag(page, drag) }
  expect(content(await active(page))).toEqual(content(after))
  await page.reload()
  await expect(frame.locator('[data-group-drag="team"]')).toBeVisible()
  expect(content(await active(page))).toEqual(content(after))
  await expect(frame.locator('#snapObjectsButton')).toHaveAttribute('aria-pressed', 'false')
  await expect(frame.locator('#snapGridButton')).toHaveAttribute('aria-pressed', 'true')
})

test('3.2 cancel cannot persist tentative drag through the pending viewport timer or late pointer events', async ({ page, openWorkspace }) => {
  await openWorkspace([graph([node('a', 80, 100), node('b', 300, 300)])])
  const frame = workspaceFrame(page)
  for (const cancel of ['Escape', 'pointercancel'] as const) await test.step(cancel, async () => {
    const before = await active(page)
    await frame.locator('#canvas').evaluate((canvas) => {
      const bounds = canvas.getBoundingClientRect()
      canvas.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true,
        clientX: bounds.left + 50, clientY: bounds.top + 50, deltaY: -20 }))
    })
    const drag = await startDrag(page, frame.locator('#nodeLayer [data-node-id="a"]'))
    try {
      await moveDrag(page, drag, 45, 35)
      await settle(page)
      expect(positions(await active(page)), 'A viewport timer must not save preview coordinates').toEqual(positions(before))
      if (cancel === 'Escape') await page.keyboard.press('Escape')
      else await frame.locator('#canvas').dispatchEvent('pointercancel', { pointerId: drag.id, pointerType: drag.touch ? 'touch' : 'mouse' })
      await moveDrag(page, drag, 90, 60)
    } finally { await endDrag(page, drag) }
    await settle(page)
    expect(positions(await active(page))).toEqual(positions(before))
    expect((await active(page)).audit).toEqual(before.audit)
    await expect(frame.locator('.graph-node.dragging')).toHaveCount(0)
    await expect(frame.locator('#edgePreview')).toBeHidden()
    await page.reload()
    await expect(frame.locator('#canvas')).toBeVisible()
    expect(positions(await active(page))).toEqual(positions(before))
  })
})

test('3.2 whole layout is size-aware with pinned obstacles, rigid groups and camera in undo history', async ({ page, openWorkspace }) => {
  const nodes = [node('a', 60, 80, { width: 350, height: 190 }), node('b', 540, 80, { width: 210, height: 140 }),
    node('c', 840, 150, { width: 280, height: 180 }), node('pin', 320, 480, { width: 300, height: 180, pinned: true }),
    node('d', 750, 500, { width: 240, height: 120 })]
  await openWorkspace([graph(nodes, { edges: [edge('a', 'b'), edge('b', 'c'), edge('a', 'd')], groups: [group('pair', ['b', 'c'])] })])
  await selectNodes(page, ['a', 'b'])
  expect(await (await field(page, 'layoutGapField')).inputValue()).toBe('48')
  await closePanels(page)
  const before = await active(page)
  for (const mode of ['hierarchy', 'compact', 'radial']) await test.step(mode, async () => {
    const auditCount = (await active(page)).audit.length
    await option(page, 'viewLayoutField', mode)
    await expect.poll(async () => (await active(page)).audit.length).toBe(auditCount + 1)
    await expect(workspaceFrame(page).locator('#layoutCancelButton')).toBeHidden()
    const after = await active(page)
    expect(after.nodes.find((item) => item.id === 'pin')).toEqual(before.nodes[3])
    expect(after.nodes[2].x - after.nodes[1].x).toBe(before.nodes[2].x - before.nodes[1].x)
    expect(after.nodes[2].y - after.nodes[1].y).toBe(before.nodes[2].y - before.nodes[1].y)
    expect(after.views[0].layout).toBe(mode)
    expect(await selected(page)).toEqual(['a', 'b'])
    expectNoOverlap(after)
    expectDataIntact(after, before)
    await undoTo(page, before)
    await activate(page, workspaceFrame(page).locator('#redoButton'))
    await expect.poll(async () => content(await active(page))).toEqual(content(after))
    await undoTo(page, before)
  })
})

test('3.2 selection layout respects four directions, unselected obstacles and the current camera', async ({ page, openWorkspace }) => {
  const nodes = [node('a', 80, 100, { width: 210, height: 120 }), node('b', 390, 300, { width: 170, height: 140 }),
    node('outside', 780, 80, { width: 250, height: 190, pinned: true })]
  await openWorkspace([graph(nodes, { edges: [edge('a', 'b')] })])
  await selectNodes(page, ['a', 'b'])
  await option(page, 'layoutScopeField', 'selection')
  await numberField(page, 'layoutGapField', 64)
  const before = await active(page)
  for (const direction of ['LR', 'TB', 'RL', 'BT']) await test.step(direction, async () => {
    await option(page, 'layoutDirectionField', direction)
    const auditCount = (await active(page)).audit.length
    await option(page, 'viewLayoutField', 'hierarchy')
    await expect.poll(async () => (await active(page)).audit.length).toBe(auditCount + 1)
    const after = await active(page)
    const [a, b] = after.nodes
    if (direction === 'LR') expect(b.x - a.x - a.width).toBeGreaterThanOrEqual(64 - 0.01)
    if (direction === 'RL') expect(a.x - b.x - b.width).toBeGreaterThanOrEqual(64 - 0.01)
    if (direction === 'TB') expect(b.y - a.y - a.height).toBeGreaterThanOrEqual(64 - 0.01)
    if (direction === 'BT') expect(a.y - b.y - b.height).toBeGreaterThanOrEqual(64 - 0.01)
    expect(after.nodes[2]).toEqual(before.nodes[2])
    expect(after.viewport).toEqual(before.viewport)
    expect(await selected(page)).toEqual(['a', 'b'])
    expect(after.views.map(({ id, layout }) => ({ id, layout }))).toEqual(before.views.map(({ id, layout }) => ({ id, layout })))
    await expect(await field(page, 'viewLayoutField')).toHaveValue('hierarchy')
    await closePanels(page)
    expectDataIntact(after, before)
    expectNoOverlap(after)
    await undoTo(page, before)
  })
  await page.reload()
  await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue(before.title)
  await expect(await field(page, 'viewLayoutField')).toHaveValue('hierarchy')
  await option(page, 'layoutScopeField', 'all')
  await expect(await field(page, 'viewLayoutField')).toHaveValue(before.views[0].layout)
  await option(page, 'layoutScopeField', 'selection')
  await expect(await field(page, 'viewLayoutField')).toHaveValue('hierarchy')
  expect(content(await active(page))).toEqual(content(before))
})

test('3.2 cancelled or superseded worker results cannot change another graph or newer edits', async ({ page, openWorkspace }) => {
  await installWorkerGate(page)
  const second = graph([node('a', 130, 120), node('b', 440, 340)], { id: 'productivity-b', title: 'Other graph QA' })
  const mock = await openWorkspace([graph(undefined, { edges: [edge('a', 'b'), edge('b', 'c')] }), second])
  const frame = workspaceFrame(page)
  const before = await active(page)
  await option(page, 'viewLayoutField', 'hierarchy')
  await awaitHeldLayout(page)
  expect(content(await active(page))).toEqual(content(before))
  await activate(page, frame.locator('#layoutCancelButton'))
  await releaseWorker(page)
  expect((await workerState(page)).delivered).toBeGreaterThan(0)
  expect(content(await active(page))).toEqual(content(before))
  await expect(frame.locator('#layoutCancelButton')).toBeHidden()

  await holdWorker(page)
  await option(page, 'viewLayoutField', 'compact')
  await awaitHeldLayout(page)
  await activate(page, frame.locator('#graphManagerButton'))
  await (await mock.list(0)).reply(200, [])
  await activate(page, frame.locator('[data-graph-open="productivity-b"]'))
  const switched = await stored(page)
  await releaseWorker(page)
  expect(await stored(page)).toEqual(switched)
  await expect(frame.locator('#graphTitle')).toHaveValue(second.title)

  await holdWorker(page)
  await option(page, 'viewLayoutField', 'hierarchy')
  await awaitHeldLayout(page)
  await selectNodes(page, ['a'])
  // Escape in selectNodes intentionally cancels an older job; start another for edit invalidation.
  await option(page, 'viewLayoutField', 'hierarchy')
  await expect.poll(async () => (await workerState(page)).queued).toBeGreaterThan(1)
  await frame.locator('#nodeLayer [data-node-id="a"]').focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(async () => (await active(page)).nodes[0].x).toBe(second.nodes[0].x + 2)
  const edited = await stored(page)
  await releaseWorker(page)
  expect(await stored(page)).toEqual(edited)
  await expect(frame.locator('#layoutCancelButton')).toBeHidden()
})

test('3.2 quota failure rolls back alignment, snap and async layout while retaining working undo', async ({ page, openWorkspace }) => {
  await openWorkspace()
  const frame = workspaceFrame(page)
  await selectNodes(page, ['a', 'b', 'c'])
  const original = await active(page)
  await command(page, 'left')
  const saved = await active(page)
  const before = await stored(page)
  await installQuota(page)
  try {
    for (const action of ['alignment', 'drag', 'layout']) await test.step(action, async () => {
      const rejected = await quotaCount(page)
      if (action === 'alignment') await command(page, 'bottom')
      if (action === 'drag') await dragBy(page, frame.locator('#nodeLayer [data-node-id="a"]'), 63, 37)
      if (action === 'layout') await option(page, 'viewLayoutField', 'hierarchy')
      await expect.poll(() => quotaCount(page)).toBeGreaterThan(rejected)
      await expect(frame.locator('#layoutCancelButton')).toBeHidden()
      await settle(page)
      expect(await stored(page)).toEqual(before)
      expect(await frame.locator('.graph-node').evaluateAll((elements) => Object.fromEntries(elements.map((el) => [
        el.getAttribute('data-node-id'), { x: parseFloat((el as HTMLElement).style.left), y: parseFloat((el as HTMLElement).style.top) },
      ])))).toEqual(positions(saved))
      await expect(frame.locator('#undoButton')).toBeEnabled()
      expect(await selected(page)).toEqual(['a', 'b', 'c'])
    })
  } finally {
    await frame.locator('body').evaluate(() => (window as TestWindow).__productivityQuota?.restore())
  }
  await undoTo(page, original)
  await activate(page, frame.locator('#redoButton'))
  await expect.poll(async () => content(await active(page))).toEqual(content(saved))
  await page.reload()
  await expect(frame.locator('#canvas')).toBeVisible()
  expect(content(await active(page))).toEqual(content(saved))
})

test('3.2 toolbar commands remain reachable at narrow/touch viewports with visible accessible names', async ({ page, openWorkspace }, testInfo) => {
  await openWorkspace()
  const frame = workspaceFrame(page)
  for (const size of [{ width: 390, height: 844 }, { width: 320, height: 700 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size)
    await selectNodes(page, ['a', 'b', 'c'])
    const toolbar = frame.locator('#selectionToolbar')
    await expect(toolbar).toBeVisible()
    if (size.width <= 390) await test.step('mobile entry points fit and are not covered, including disabled undo', async () => {
      for (const id of ['graphManagerButton', 'libraryToggle', 'undoButton', 'redoButton', 'inspectorToggle']) {
        const button = frame.locator(`#${id}`)
        await expect(button).toBeVisible()
        const box = await button.boundingBox()
        expect(box, `${id} must have a visible bounding box`).not.toBeNull()
        expect(box!.width, `${id} touch width`).toBeCloseTo(44, 1)
        expect(box!.x, `${id} left edge`).toBeGreaterThanOrEqual(0)
        expect(box!.y, `${id} top edge`).toBeGreaterThanOrEqual(0)
        expect(box!.x + box!.width, `${id} right edge`).toBeLessThanOrEqual(size.width + 0.5)
        expect(box!.y + box!.height, `${id} bottom edge`).toBeLessThanOrEqual(size.height + 0.5)
        expect(await button.evaluate((element) => {
          const rect = element.getBoundingClientRect()
          return element.contains(element.ownerDocument.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2))
        }), `${id} center must not be covered inside the workspace`).toBe(true)
        expect(await frame.owner().evaluate((element, { x, y }) => element.ownerDocument.elementFromPoint(x, y) === element,
        { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 }), `${id} center must not be covered by the parent page`).toBe(true)
      }
    })
    for (const name of toolbarCommands) {
      const button = toolbar.locator(`[data-arrange-command="${name}"]`)
      await expect(button).toHaveCount(1)
      await expect(button).toHaveAccessibleName(/.+/)
      await expect(button).toBeInViewport()
      const visibleHit = await button.evaluate((element) => {
        const rect = element.getBoundingClientRect()
        return element.contains(element.ownerDocument.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2))
      })
      expect(visibleHit, `${name} must not be covered by another control`).toBe(true)
    }
    const dimensions = await toolbar.evaluate((element) => ({ width: innerWidth,
      pageWidth: document.documentElement.scrollWidth, client: element.clientWidth, scroll: element.scrollWidth }))
    expect(dimensions.width).toBe(size.width)
    expect(dimensions.pageWidth).toBeLessThanOrEqual(size.width + 1)
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1)
    const before = await active(page)
    if (test.info().project.use.hasTouch) {
      await toolbar.evaluate((element) => element.addEventListener('touchstart', () => { element.dataset.touchObserved = 'true' }, { once: true }))
    }
    await command(page, 'left')
    if (test.info().project.use.hasTouch) await expect(toolbar).toHaveAttribute('data-touch-observed', 'true')
    await undoTo(page, before)
    await page.screenshot({ path: testInfo.outputPath(`productivity-${size.width}x${size.height}.png`) })
  }
})
