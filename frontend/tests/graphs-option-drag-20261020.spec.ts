import { expect, test as base, type Locator, type Page } from '@playwright/test'
import {
  graphFixture, installGraphFixture, readWorkspace, workspaceFrame, workspaceName,
} from './review-graphs-remediation-helpers'

type Point = { x: number; y: number }
type Node = Omit<ReturnType<typeof graphFixture>['nodes'][number], 'items'> & { items: string[] }
type Edge = ReturnType<typeof graphFixture>['edges'][number] & {
  sourcePort: string | null; targetPort: string | null
}
type Group = { id: string; title: string; color: string; nodeIds: string[]; collapsed: boolean }
type View = {
  id: string; name: string; layout: string; viewport: Point & { scale: number }
  positions: Record<string, Point>; focusNodeId: string | null; focusDepth: number
  connectionLensEnabled: boolean
}
type Graph = Omit<ReturnType<typeof graphFixture>, 'nodes' | 'edges' | 'groups' | 'views' | 'audit'> & {
  nodes: Node[]; edges: Edge[]; groups: Group[]; views: View[]
  audit: Array<{ id: string; at: string; action: string }>
}
type Workspace = Omit<Awaited<ReturnType<typeof readWorkspace>>, 'graphs'> & { graphs: Graph[] }
type ApiMock = Awaited<ReturnType<typeof installGraphFixture>>
type ObservedWindow = Window & typeof globalThis & {
  __optionDragWrites?: string[]
  __optionDragQuota?: { rejected: number; restore: () => void }
}
type Subject = 'node' | 'group'
type Drag = { id: number; start: Point; local: Point; current: Point }

function node(id: string, x: number, y: number, overrides: Partial<Node> = {}): Node {
  return { ...graphFixture().nodes[0], id, title: id, x, y, ...overrides }
}

function edge(id: string, source: string, target: string, routing = 'orthogonal'): Edge {
  return {
    id, source, target, routing, label: `Route ${id}`, sourcePort: 'e:4', targetPort: 'w:1',
    points: [{ x: 242.5, y: 187.25 }, { x: 296.75, y: 247.5 }],
  }
}

function graph(options: { grouped?: boolean; collapsed?: boolean; scale?: number; simple?: boolean } = {}): Graph {
  const nodes = options.simple
    ? [node('alpha', 80, 110), node('beta', 250, 110), node('outside', 680, 340)]
    : [
      node('alpha', 80, 110, {
        type: 'custom', title: 'Rich alpha', customTypeLabel: 'QA entity',
        sourceRef: 'QA:source/<alpha>', description: 'First line\nSecond line <detail>',
        shape: 'rounded', radius: 17, scale: 1.1, width: 148, height: 96,
        autoSize: false, pinned: true, color: '#238A63', items: ['Preserved hidden item'],
      }),
      node('beta', 320, 260, {
        type: 'list', title: 'Rich beta', items: ['First <item>', 'Second & item', 'Third item'],
        sourceRef: 'QA:list/beta', description: 'List details', radius: 5,
        width: 180, height: 140, scale: 0.9, color: '#C74870',
      }),
      node('outside', 680, 110),
    ]
  const viewport = { x: 60, y: 100, scale: options.scale ?? 1 }
  return {
    ...graphFixture('option-drag', 'Option drag QA'), nodes, viewport, activeViewId: 'view-a', audit: [],
    edges: [edge('internal', 'alpha', 'beta'), edge('outgoing', 'alpha', 'outside', 'curve'),
      edge('incoming', 'outside', 'beta', 'straight')],
    groups: options.grouped ? [{ id: 'team', title: 'QA team', color: '#238A63',
      nodeIds: ['alpha', 'beta'], collapsed: Boolean(options.collapsed) }] : [],
    views: ['view-a', 'view-b', 'view-c'].map((id, index) => ({
      id, name: id, layout: index === 1 ? 'hierarchy' : 'radial', viewport: { ...viewport },
      // Different per-node offsets detect copying current-view coordinates into inactive views.
      positions: Object.fromEntries(nodes.map((item, ordinal) => [item.id, {
        x: item.x + index * (850 + ordinal * 73),
        y: item.y - index * (410 + ordinal * 29),
      }])),
      focusNodeId: index === 1 ? 'alpha' : null, focusDepth: index === 1 ? 1 : 0,
      connectionLensEnabled: index === 2,
    })),
  }
}

const test = base.extend<{ openWorkspace: (value?: Graph) => Promise<ApiMock> }>({
  openWorkspace: async ({ page }, run) => {
    const errors: string[] = []
    let mock: ApiMock | undefined
    page.on('pageerror', (error) => errors.push(error.message))
    await run(async (value = graph()) => {
      if (mock) throw new Error('Seed each isolated browser context only once')
      if (process.env.DPMS_REVIEW_GRAPH_SOURCE === '1') throw new Error('Served candidate only')
      // Observe only the synthetic workspace, preserving the native storage operation.
      await page.addInitScript((name) => {
        const state = window as ObservedWindow
        state.__optionDragWrites = []
        const original = Storage.prototype.setItem
        Storage.prototype.setItem = function (field: string, value: string) {
          original.call(this, field, value)
          if (this === window.localStorage && field === name) state.__optionDragWrites!.push(value)
        }
      }, workspaceName)
      const untouched = { ...graph(), id: 'untouched-graph', title: 'Untouched graph' }
      mock = await installGraphFixture(page, {
        local: [value, untouched] as unknown as ReturnType<typeof graphFixture>[],
      })
      await page.goto('http://localhost:55177/graphs')
      await expect(page).toHaveURL('http://localhost:55177/graphs')
      await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue(value.title)
      await closePanels(page)
      await settle(page)
      return mock
    })
    expect(errors, 'Uncaught workspace errors').toEqual([])
    expect(mock?.unexpectedWrites, 'Duplication must not publish or mutate any API').toEqual([])
    expect(mock?.deletes, 'Duplication must not delete system snapshots').toEqual([])
  },
})

async function stored(page: Page): Promise<Workspace> {
  return await readWorkspace(page) as unknown as Workspace
}

async function active(page: Page): Promise<Graph> {
  const state = await stored(page)
  const value = state.graphs.find((item) => item.id === state.activeGraphId)
  expect(value).toBeTruthy()
  return value!
}

function content(value: Graph) {
  return Object.fromEntries(Object.entries(value).filter(([field]) => !['audit', 'updatedAt'].includes(field)))
}

async function closePanels(page: Page) {
  const frame = workspaceFrame(page)
  const desktopToggle = frame.locator('#togglePanelsButton')
  if (await desktopToggle.isVisible()) {
    if (await desktopToggle.getAttribute('aria-pressed') !== 'true') await desktopToggle.click()
    await expect(frame.locator('body')).toHaveClass(/panels-hidden/)
    return
  }
  for (const name of ['inspector', 'library']) {
    if (await frame.locator('body').evaluate((body, panel) => body.classList.contains(`show-${panel}`), name)) {
      await frame.locator(`#${name}Toggle`).click()
    }
  }
}

async function settle(page: Page) {
  await workspaceFrame(page).locator('body').evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 240)))
  }))
}

async function writes(page: Page) {
  const shell = await page.evaluate(() => [...((window as ObservedWindow).__optionDragWrites || [])])
  const workspace = await workspaceFrame(page).locator('body').evaluate(() =>
    [...((window as ObservedWindow).__optionDragWrites || [])])
  return { shell, workspace }
}

const nodeElement = (page: Page, id: string) =>
  workspaceFrame(page).locator(`#nodeLayer [data-node-id="${id}"]`)
const dragTarget = (page: Page, subject: Subject) => subject === 'node'
  ? nodeElement(page, 'alpha') : workspaceFrame(page).locator('[data-group-drag="team"]')

async function selection(page: Page) {
  const frame = workspaceFrame(page)
  return {
    nodes: await frame.locator('.graph-node.selected').evaluateAll((elements) =>
      elements.map((element) => element.getAttribute('data-node-id')!).sort()),
    groups: await frame.locator('.group-frame.selected').evaluateAll((elements) =>
      elements.map((element) => element.getAttribute('data-group-id')!).sort()),
  }
}

async function selectNodes(page: Page, ids: string[]) {
  await closePanels(page)
  await workspaceFrame(page).locator('#canvas').focus()
  await page.keyboard.press('Escape')
  for (let index = 0; index < ids.length; index += 1) {
    await nodeElement(page, ids[index]).click({ modifiers: index ? ['ControlOrMeta'] : [] })
  }
  expect(await selection(page)).toEqual({ nodes: [...ids].sort(), groups: [] })
}

async function toggle(page: Page, id: string, enabled: boolean) {
  const control = workspaceFrame(page).locator(`#${id}`)
  if (await control.getAttribute('aria-pressed') !== String(enabled)) await control.click()
  await expect(control).toHaveAttribute('aria-pressed', String(enabled))
}

async function withoutSnap(page: Page) {
  await toggle(page, 'snapObjectsButton', false)
  await toggle(page, 'snapGridButton', false)
}

async function startDrag(page: Page, target: Locator): Promise<Drag> {
  await expect(target).toBeInViewport()
  // Resolve native hit-testing/hover updates before measuring and observing pointerdown.
  await target.hover({ timeout: 5000 })
  const outer = await target.boundingBox()
  expect(outer).not.toBeNull()
  const local = await target.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }
  })
  const start = { x: outer!.x + outer!.width / 2, y: outer!.y + outer!.height / 2 }
  await target.evaluate((element) => {
    const root = element.ownerDocument.documentElement
    delete root.dataset.optionDragPointer
    root.addEventListener('pointerdown', (event) => {
      root.dataset.optionDragPointer = String(event.pointerId)
    }, { once: true, capture: true })
  })
  await page.mouse.move(start.x, start.y)
  await page.mouse.down()
  const id = Number(await workspaceFrame(page).locator('html').getAttribute('data-option-drag-pointer'))
  expect(id).toBeGreaterThan(0)
  return { id, start, local, current: local }
}

async function moveDrag(page: Page, drag: Drag, dx: number, dy: number) {
  drag.current = { x: drag.local.x + dx, y: drag.local.y + dy }
  await page.mouse.move(drag.start.x + dx, drag.start.y + dy, { steps: 5 })
}

async function release(page: Page) {
  await page.mouse.up()
  for (const modifier of ['Alt', 'Shift', 'Space']) await page.keyboard.up(modifier)
}

async function liveIds(page: Page) {
  return workspaceFrame(page).locator('body').evaluate(() => {
    const ids = (selector: string, attribute: string) =>
      [...new Set([...document.querySelectorAll(selector)].map((element) => element.getAttribute(attribute)!))].sort()
    return {
      nodes: ids('#nodeLayer [data-node-id]', 'data-node-id'),
      edges: ids('#edgeLayer [data-edge-id]', 'data-edge-id'),
      groups: ids('.group-frame[data-group-id]', 'data-group-id'),
    }
  })
}

async function livePositions(page: Page, ids: string[]) {
  return workspaceFrame(page).locator('#nodeLayer').evaluate((layer, values) => Object.fromEntries(values.map((id) => {
    const element = layer.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(id)}"]`)!
    return [id, { x: parseFloat(element.style.left), y: parseFloat(element.style.top) }]
  })), ids)
}

function positions(value: Graph, ids = value.nodes.map((item) => item.id)) {
  return Object.fromEntries(value.nodes.filter((item) => ids.includes(item.id)).map(({ id, x, y }) => [id, { x, y }]))
}

function expectPoint(actual: Point, expected: Point) {
  expect(actual.x).toBeCloseTo(expected.x, 5)
  expect(actual.y).toBeCloseTo(expected.y, 5)
}

function expectCopies(before: Graph, after: Graph, sourceIds: string[], delta: Point, groupId?: string) {
  const originals = new Set(before.nodes.map((item) => item.id))
  const copies = after.nodes.filter((item) => !originals.has(item.id))
  expect(copies).toHaveLength(sourceIds.length)
  expect(after.nodes.filter((item) => originals.has(item.id)), 'All original node fields remain unchanged').toEqual(before.nodes)
  const mapping = new Map<string, string>()
  for (const id of sourceIds) {
    const source = before.nodes.find((item) => item.id === id)!
    const matches = copies.filter((item) => item.title === source.title)
    expect(matches, `Exactly one full copy of ${id}`).toHaveLength(1)
    const copy = matches[0]
    expect(copy).toEqual({ ...source, id: copy.id, x: copy.x, y: copy.y })
    expectPoint(copy, { x: source.x + delta.x, y: source.y + delta.y })
    mapping.set(id, copy.id)
  }
  const originalEdges = new Set(before.edges.map((item) => item.id))
  const copiedEdges = after.edges.filter((item) => !originalEdges.has(item.id))
  const internal = before.edges.filter((item) => sourceIds.includes(item.source) && sourceIds.includes(item.target))
  expect(after.edges.filter((item) => originalEdges.has(item.id))).toEqual(before.edges)
  expect(copiedEdges, 'Only internal edges are copied').toHaveLength(internal.length)
  for (const source of internal) {
    const matches = copiedEdges.filter((item) => item.source === mapping.get(source.source) && item.target === mapping.get(source.target))
    expect(matches).toHaveLength(1)
    expect(matches[0]).toEqual({ ...source, id: matches[0].id,
      source: mapping.get(source.source), target: mapping.get(source.target), points: matches[0].points })
    expect(matches[0].points).toHaveLength(source.points.length)
    source.points.forEach((point, index) =>
      expectPoint(matches[0].points[index], { x: point.x + delta.x, y: point.y + delta.y }))
  }
  const copiedGroups = after.groups.filter((item) => !before.groups.some((original) => original.id === item.id))
  expect(after.groups.filter((item) => before.groups.some((original) => original.id === item.id))).toEqual(before.groups)
  expect(copiedGroups).toHaveLength(groupId ? 1 : 0)
  if (groupId) {
    const original = before.groups.find((item) => item.id === groupId)!
    expect(copiedGroups[0]).toEqual({ ...original, id: copiedGroups[0].id,
      nodeIds: original.nodeIds.map((id) => mapping.get(id)) })
  }
  expect(after.views.map((view) => view.id)).toEqual(before.views.map((view) => view.id))
  for (const original of before.views) {
    const view = after.views.find((item) => item.id === original.id)!
    expect({ ...view, positions: original.positions }).toEqual(original)
    expect(Object.keys(view.positions).sort()).toEqual([...Object.keys(original.positions), ...mapping.values()].sort())
    for (const [id, point] of Object.entries(original.positions)) expect(view.positions[id]).toEqual(point)
    for (const [id, copyId] of mapping) expectPoint(view.positions[copyId], {
      x: original.positions[id].x + delta.x, y: original.positions[id].y + delta.y,
    })
  }
  const newIds = [...copies, ...copiedEdges, ...copiedGroups].map((item) => item.id)
  const oldIds = new Set([...before.nodes, ...before.edges, ...before.groups].map((item) => item.id))
  expect(newIds.every((id) => id.length > 0 && !oldIds.has(id))).toBe(true)
  expect(new Set(newIds).size).toBe(newIds.length)
  expect({ ...content(after), nodes: before.nodes, edges: before.edges, groups: before.groups, views: before.views })
    .toEqual(content(before))
  return { nodes: [...mapping.values()].sort(), groups: copiedGroups.map((item) => item.id).sort() }
}

async function expectUntouchedGraph(page: Page, before: Workspace) {
  const after = await stored(page)
  expect(after.activeGraphId).toBe(before.activeGraphId)
  expect(after.graphs.filter((item) => item.id !== before.activeGraphId))
    .toEqual(before.graphs.filter((item) => item.id !== before.activeGraphId))
}

async function undoRedo(page: Page, before: Graph, after: Graph) {
  const frame = workspaceFrame(page)
  await frame.locator('#undoButton').click()
  await expect.poll(async () => content(await active(page)), 'One Undo removes the complete copy').toEqual(content(before))
  await expect(frame.locator('#undoButton')).toBeDisabled()
  await frame.locator('#redoButton').click()
  await expect.poll(async () => content(await active(page)), 'Redo restores the same IDs and payload').toEqual(content(after))
}

test('3.2 Option-drag copies one rich node, commits only on pointerup and survives undo/redo/reload', async ({ page, openWorkspace }) => {
  await openWorkspace()
  await selectNodes(page, ['alpha'])
  const workspace = await stored(page)
  const before = await active(page)
  const journal = await writes(page)
  await page.keyboard.down('Alt')
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try {
    await moveDrag(page, drag, 137, 53)
    await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(4)
    expect(await livePositions(page, ['alpha', 'beta', 'outside'])).toEqual(positions(before))
    await settle(page)
    expect(await stored(page)).toEqual(workspace)
    expect(await writes(page), 'No workspace writes during preview').toEqual(journal)
  } finally { await release(page) }
  await expect.poll(async () => (await active(page)).nodes.length).toBe(4)
  const after = await active(page)
  const copies = expectCopies(before, after, ['alpha'], { x: 137, y: 53 })
  expect(await selection(page)).toEqual(copies)
  await expectUntouchedGraph(page, workspace)
  await undoRedo(page, before, after)
  await page.reload()
  await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue(before.title)
  expect(content(await active(page))).toEqual(content(after))
})

test('3.2 Option-drag copies the current multi-selection and internal ports/routes without changing groups', async ({ page, openWorkspace }) => {
  await openWorkspace(graph({ grouped: true }))
  await selectNodes(page, ['alpha', 'beta'])
  const workspace = await stored(page)
  const before = await active(page)
  await page.keyboard.down('Alt')
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
  await expect.poll(async () => (await active(page)).nodes.length).toBe(5)
  const after = await active(page)
  expect(await selection(page)).toEqual(expectCopies(before, after, ['alpha', 'beta'], { x: 137, y: 53 }))
  expect(after.groups).toEqual(before.groups)
  await page.screenshot({ path: test.info().outputPath('option-drag-multi-selection.png'), fullPage: true })
  await expectUntouchedGraph(page, workspace)
  await undoRedo(page, before, after)
})

for (const collapsed of [false, true]) {
  test(`3.2 Option-drag clones ${collapsed ? 'collapsed' : 'expanded'} group header, members and internal edges`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true, collapsed }))
    await selectNodes(page, ['outside'])
    const before = await active(page)
    await page.keyboard.down('Alt')
    const drag = await startDrag(page, dragTarget(page, 'group'))
    try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
    await expect.poll(async () => (await active(page)).groups.length).toBe(2)
    const after = await active(page)
    const copies = expectCopies(before, after, ['alpha', 'beta'], { x: 137, y: 53 }, 'team')
    expect((await selection(page)).groups).toEqual(copies.groups)
    expect((await selection(page)).nodes.every((id) => copies.nodes.includes(id))).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`option-drag-group-${collapsed ? 'collapsed' : 'expanded'}.png`), fullPage: true })
    await undoRedo(page, before, after)
  })
}

for (const subject of ['node', 'group'] as const) {
  test(`3.2 ${subject}: Option-click and sub-threshold movement never create or persist copies`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true }))
    await selectNodes(page, ['outside'])
    const before = await stored(page)
    const journal = await writes(page)
    for (const distance of [0, 2]) {
      await page.keyboard.down('Alt')
      const drag = await startDrag(page, dragTarget(page, subject))
      try { if (distance) await moveDrag(page, drag, distance, 0) } finally { await release(page) }
      await settle(page)
      expect(await stored(page)).toEqual(before)
      expect(await writes(page)).toEqual(journal)
      expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
      await expect(workspaceFrame(page).locator('#undoButton')).toBeDisabled()
    }
  })

  test(`3.2 ${subject}: Alt at activation is sampled after pointerdown`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true }))
    await selectNodes(page, subject === 'node' ? ['alpha', 'beta'] : ['outside'])
    const before = await active(page)
    const drag = await startDrag(page, dragTarget(page, subject))
    try {
      await moveDrag(page, drag, 2, 0)
      expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
      await page.keyboard.down('Alt')
      await moveDrag(page, drag, 91, 47)
    } finally { await release(page) }
    await expect.poll(async () => (await active(page)).nodes.length).toBe(5)
    expectCopies(before, await active(page), ['alpha', 'beta'], { x: 91, y: 47 }, subject === 'group' ? 'team' : undefined)
  })

  test(`3.2 ${subject}: late Alt switches move/copy repeatedly and reuses all copy IDs`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true }))
    await withoutSnap(page)
    await selectNodes(page, subject === 'node' ? ['alpha', 'beta'] : ['outside'])
    const before = await active(page)
    const workspace = await stored(page)
    const journal = await writes(page)
    const drag = await startDrag(page, dragTarget(page, subject))
    let copyIds: Awaited<ReturnType<typeof liveIds>> | undefined
    try {
      await moveDrag(page, drag, 37, 19)
      expect((await liveIds(page)).nodes).toHaveLength(3)
      expectPoint((await livePositions(page, ['alpha'])).alpha, { x: 117, y: 129 })
      await page.keyboard.down('Alt')
      await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(5)
      expect(await livePositions(page, ['alpha', 'beta', 'outside'])).toEqual(positions(before))
      await moveDrag(page, drag, 71, 37)
      await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(5)
      await expect.poll(async () => (await liveIds(page)).edges.length).toBe(4)
      copyIds = await liveIds(page)
      expect(copyIds.edges).toHaveLength(4)
      expect(copyIds.groups).toHaveLength(subject === 'group' ? 2 : 1)
      expect(await livePositions(page, ['alpha', 'beta', 'outside'])).toEqual(positions(before))
      await page.keyboard.up('Alt')
      expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
      expectPoint((await livePositions(page, ['alpha'])).alpha, { x: 151, y: 147 })
      await moveDrag(page, drag, 103, 43)
      expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
      expectPoint((await livePositions(page, ['alpha'])).alpha, { x: 183, y: 153 })
      await page.keyboard.down('Alt')
      await expect.poll(async () => liveIds(page)).toEqual(copyIds)
      await moveDrag(page, drag, 137, 53)
      expect(await liveIds(page)).toEqual(copyIds)
      expect(await livePositions(page, ['alpha', 'beta', 'outside'])).toEqual(positions(before))
      await settle(page)
      expect(await stored(page)).toEqual(workspace)
      expect(await writes(page)).toEqual(journal)
    } finally { await release(page) }
    await expect.poll(async () => (await active(page)).nodes.length).toBe(5)
    const after = await active(page)
    const copies = expectCopies(before, after, ['alpha', 'beta'], { x: 137, y: 53 }, subject === 'group' ? 'team' : undefined)
    expect(after.nodes.map((item) => item.id).sort()).toEqual(copyIds!.nodes)
    expect(after.edges.map((item) => item.id).sort()).toEqual(copyIds!.edges)
    expect(after.groups.map((item) => item.id).sort()).toEqual(copyIds!.groups)
    if (subject === 'node') expect(await selection(page)).toEqual(copies)
    else expect((await selection(page)).groups).toEqual(copies.groups)
    await undoRedo(page, before, after)
  })

  test(`3.2 ${subject}: stationary Alt release before drop commits only the original move`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true }))
    await withoutSnap(page)
    await selectNodes(page, subject === 'node' ? ['alpha', 'beta'] : ['outside'])
    const before = await active(page)
    await page.keyboard.down('Alt')
    const drag = await startDrag(page, dragTarget(page, subject))
    try {
      await moveDrag(page, drag, 61, 31)
      await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(5)
      await page.keyboard.up('Alt')
    } finally { await release(page) }
    const after = await active(page)
    expect(after.nodes).toEqual(before.nodes.map((item) => item.id === 'outside'
      ? item : { ...item, x: item.x + 61, y: item.y + 31 }))
    expect(after.edges).toEqual(before.edges)
    expect(after.groups).toEqual(before.groups)
    expect(after.views.filter((view) => view.id !== after.activeViewId))
      .toEqual(before.views.filter((view) => view.id !== before.activeViewId))
    expect(after.views.find((view) => view.id === after.activeViewId)!.positions).toEqual(positions(after))
    await undoRedo(page, before, after)
  })

  for (const cancel of ['Escape', 'pointercancel', 'lostpointercapture'] as const) {
    test(`3.2 ${subject}: ${cancel} restores pre-pointerdown selection and ignores late pointer events`, async ({ page, openWorkspace }) => {
      await openWorkspace(graph({ grouped: true }))
      await selectNodes(page, ['outside'])
      const before = await stored(page)
      const selected = await selection(page)
      const journal = await writes(page)
      await page.keyboard.down('Alt')
      const drag = await startDrag(page, dragTarget(page, subject))
      try {
        await moveDrag(page, drag, 61, 31)
        await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(subject === 'group' ? 5 : 4)
        await settle(page)
        expect(await stored(page)).toEqual(before)
        expect(await writes(page)).toEqual(journal)
        if (cancel === 'Escape') await page.keyboard.press('Escape')
        else if (cancel === 'lostpointercapture') {
          await workspaceFrame(page).locator('#canvas').evaluate((canvas, id) => canvas.releasePointerCapture(id), drag.id)
          // Releasing native capture delivers lostpointercapture on the next pointer event.
          await moveDrag(page, drag, 62, 31)
        }
        else await workspaceFrame(page).locator('#canvas').dispatchEvent('pointercancel', {
          pointerId: drag.id, pointerType: 'mouse', isPrimary: true, buttons: 0,
          clientX: drag.current.x, clientY: drag.current.y,
        })
        expect(await selection(page)).toEqual(selected)
        expect(await livePositions(page, ['alpha', 'beta', 'outside']))
          .toEqual(positions(before.graphs.find((item) => item.id === before.activeGraphId)!))
        await moveDrag(page, drag, 137, 53)
      } finally { await release(page) }
      await settle(page)
      expect(await stored(page)).toEqual(before)
      expect(await writes(page)).toEqual(journal)
      expect(await selection(page)).toEqual(selected)
      expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
      expect((await liveIds(page)).groups).toEqual(['team'])
      await expect(workspaceFrame(page).locator('.graph-node.dragging')).toHaveCount(0)
      await expect(workspaceFrame(page).locator('#undoButton')).toBeDisabled()
      await page.reload()
      await expect(workspaceFrame(page).locator('#graphTitle')).toHaveValue('Option drag QA')
      expect(await stored(page)).toEqual(before)
    })
  }
}

for (const scale of [0.5, 1, 2]) {
  test(`3.2 Alt bypasses object and grid snapping at zoom ${scale}`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ simple: true, scale }))
    await toggle(page, 'snapObjectsButton', true)
    await toggle(page, 'snapGridButton', true)
    await selectNodes(page, ['alpha'])
    const before = await active(page)
    // Five screen pixels from beta's left edge, inside the object-snap tolerance.
    const dx = 170 * scale - 5
    await page.keyboard.down('Alt')
    const drag = await startDrag(page, nodeElement(page, 'alpha'))
    try { await moveDrag(page, drag, dx, 13) } finally { await release(page) }
    await expect.poll(async () => (await active(page)).nodes.length).toBe(4)
    expectCopies(before, await active(page), ['alpha'], { x: dx / scale, y: 13 / scale })
  })
}

for (const alt of [false, true]) {
  test(`3.2 Shift pressed after pointerdown locks the ${alt ? 'copy' : 'plain move'} axis`, async ({ page, openWorkspace }) => {
    await openWorkspace()
    await withoutSnap(page)
    await selectNodes(page, ['alpha'])
    const before = await active(page)
    if (alt) await page.keyboard.down('Alt')
    const drag = await startDrag(page, nodeElement(page, 'alpha'))
    try {
      await moveDrag(page, drag, 2, 0)
      await page.keyboard.down('Shift')
      await moveDrag(page, drag, 137, 53)
    } finally { await release(page) }
    const after = await active(page)
    if (alt) expectCopies(before, after, ['alpha'], { x: 137, y: 0 })
    else {
      expect(after.nodes).toEqual(before.nodes.map((item) => item.id === 'alpha' ? { ...item, x: item.x + 137 } : item))
      expect(after.edges).toEqual(before.edges)
      expect(after.groups).toEqual(before.groups)
    }
    await undoRedo(page, before, after)
  })
}

test('3.2 plain drag without modifiers remains one move with no copies', async ({ page, openWorkspace }) => {
  await openWorkspace()
  await withoutSnap(page)
  await selectNodes(page, ['alpha'])
  const before = await active(page)
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
  const after = await active(page)
  expect(after.nodes).toEqual(before.nodes.map((item) => item.id === 'alpha' ? { ...item, x: item.x + 137, y: item.y + 53 } : item))
  expect(after.edges).toEqual(before.edges)
  expect(after.groups).toEqual(before.groups)
  expect(after.views.filter((view) => view.id !== before.activeViewId)).toEqual(before.views.filter((view) => view.id !== before.activeViewId))
  await undoRedo(page, before, after)
})

for (const subject of ['node', 'group'] as const) {
  test(`3.2 Space+Alt over ${subject} still pans without copying`, async ({ page, openWorkspace }) => {
    await openWorkspace(graph({ grouped: true }))
    await selectNodes(page, ['outside'])
    await workspaceFrame(page).locator('#canvas').focus()
    const before = await active(page)
    await page.keyboard.down('Space')
    await page.keyboard.down('Alt')
    const drag = await startDrag(page, dragTarget(page, subject))
    try { await moveDrag(page, drag, 97, 43) } finally { await release(page) }
    await settle(page)
    const after = await active(page)
    expect(after.nodes).toEqual(before.nodes)
    expect(after.edges).toEqual(before.edges)
    expect(after.groups).toEqual(before.groups)
    expectPoint(after.viewport, { x: before.viewport.x + 97, y: before.viewport.y + 43 })
    expect(after.viewport.scale).toBe(before.viewport.scale)
    for (const view of after.views) expect(view.positions).toEqual(before.views.find((item) => item.id === view.id)!.positions)
    expect(after.views.filter((view) => view.id !== before.activeViewId)).toEqual(before.views.filter((view) => view.id !== before.activeViewId))
    expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
  })
}

test('3.2 duplicate quota failure rolls back the whole copy and preserves subsequent undo', async ({ page, openWorkspace }) => {
  await openWorkspace(graph({ grouped: true }))
  await selectNodes(page, ['alpha', 'beta'])
  const before = await active(page)
  const workspace = await stored(page)
  const selected = await selection(page)
  await workspaceFrame(page).locator('body').evaluate((_body, name) => {
    const original = Storage.prototype.setItem
    const state = { rejected: 0, restore: () => { Storage.prototype.setItem = original } }
    ;(window as ObservedWindow).__optionDragQuota = state
    Storage.prototype.setItem = function (field: string, value: string) {
      if (this === window.localStorage && field === name) {
        state.rejected += 1
        throw new DOMException('Synthetic option-drag quota failure', 'QuotaExceededError')
      }
      original.call(this, field, value)
    }
  }, workspaceName)
  try {
    await page.keyboard.down('Alt')
    const drag = await startDrag(page, nodeElement(page, 'alpha'))
    try {
      await moveDrag(page, drag, 137, 53)
      await expect(workspaceFrame(page).locator('.graph-node')).toHaveCount(5)
    } finally { await release(page) }
    expect(await workspaceFrame(page).locator('body').evaluate(() =>
      (window as ObservedWindow).__optionDragQuota!.rejected)).toBeGreaterThan(0)
    expect(await stored(page)).toEqual(workspace)
    expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
    expect(await livePositions(page, ['alpha', 'beta', 'outside'])).toEqual(positions(before))
    expect(await selection(page)).toEqual(selected)
    await expect(workspaceFrame(page).locator('#undoButton')).toBeDisabled()
    await expect(workspaceFrame(page).locator('#toastRegion')).not.toBeEmpty()
  } finally {
    await workspaceFrame(page).locator('body').evaluate(() => (window as ObservedWindow).__optionDragQuota!.restore())
  }
  await page.keyboard.down('Alt')
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
  const after = await active(page)
  expectCopies(before, after, ['alpha', 'beta'], { x: 137, y: 53 })
  await undoRedo(page, before, after)
})

test('3.2 inactive-view coordinate limit clamps the complete copied subgraph uniformly', async ({ page, openWorkspace }) => {
  const value = graph({ grouped: true })
  value.views[1].positions.alpha = { x: 99_980, y: 99_970 }
  await openWorkspace(value)
  await selectNodes(page, ['alpha', 'beta'])
  const before = await active(page)
  await page.keyboard.down('Alt')
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
  const after = await active(page)
  expectCopies(before, after, ['alpha', 'beta'], { x: 20, y: 30 })
  for (const view of after.views) {
    for (const point of Object.values(view.positions)) {
      expect(Math.abs(point.x)).toBeLessThanOrEqual(100_000)
      expect(Math.abs(point.y)).toBeLessThanOrEqual(100_000)
    }
  }
  await undoRedo(page, before, after)
})

test('3.2 node-count limit rejects duplication without partial copies or history', async ({ page, openWorkspace }) => {
  const value = graph()
  const fillers = Array.from({ length: 1497 }, (_, index) => node(`filler-${index}`, 5000 + index % 50 * 140, 5000 + Math.floor(index / 50) * 100))
  value.nodes.push(...fillers)
  value.groups = [0, 1, 2].map((index) => ({
    id: `hidden-${index}`, title: `Hidden ${index}`, color: '#238A63', collapsed: true,
    nodeIds: fillers.slice(index * 499, (index + 1) * 499).map((item) => item.id),
  }))
  for (const view of value.views) {
    for (const item of fillers) view.positions[item.id] = { x: item.x, y: item.y }
  }
  await openWorkspace(value)
  await selectNodes(page, ['alpha'])
  const before = await stored(page)
  const journal = await writes(page)
  await page.keyboard.down('Alt')
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try { await moveDrag(page, drag, 137, 53) } finally { await release(page) }
  await settle(page)
  expect(await stored(page)).toEqual(before)
  expect(await writes(page)).toEqual(journal)
  expect((await liveIds(page)).nodes).toEqual(['alpha', 'beta', 'outside'])
  expectPoint((await livePositions(page, ['alpha'])).alpha, { x: 80, y: 110 })
  expect(await selection(page)).toEqual({ nodes: ['alpha'], groups: [] })
  await expect(workspaceFrame(page).locator('#undoButton')).toBeDisabled()
  await expect(workspaceFrame(page).locator('#toastRegion')).not.toBeEmpty()
})

test('3.2 diagnostic highlighting survives stationary Alt transitions and drag cancellation', async ({ page, openWorkspace }) => {
  await openWorkspace(graph({ grouped: true }))
  await withoutSnap(page)
  await selectNodes(page, ['alpha', 'beta'])
  const frame = workspaceFrame(page)
  await frame.locator('#diagnosticsButton').click()
  await frame.locator('[data-diagnostic-category="deadEnds"]').click()
  await frame.locator('[data-close-dialog="diagnosticsDialog"]').first().click()
  const diagnosticState = async () => frame.locator('#nodeLayer [data-node-id]').evaluateAll((elements) =>
    Object.fromEntries(elements.filter((element) => ['alpha', 'beta', 'outside'].includes(element.getAttribute('data-node-id')!))
      .map((element) => [element.getAttribute('data-node-id'), {
        highlighted: element.classList.contains('diagnostic-highlight'),
        muted: element.classList.contains('diagnostic-muted'),
      }])))
  const expected = {
    alpha: { highlighted: false, muted: true },
    beta: { highlighted: true, muted: false },
    outside: { highlighted: false, muted: true },
  }
  expect(await diagnosticState()).toEqual(expected)
  const before = await stored(page)
  const drag = await startDrag(page, nodeElement(page, 'alpha'))
  try {
    await moveDrag(page, drag, 97, 43)
    for (const alt of [true, false, true]) {
      if (alt) await page.keyboard.down('Alt')
      else await page.keyboard.up('Alt')
      await expect(frame.locator('.graph-node')).toHaveCount(alt ? 5 : 3)
      expect(await diagnosticState()).toEqual(expected)
      await expect(frame.locator('#diagnosticsButton')).toHaveAttribute('aria-pressed', 'true')
    }
    await page.keyboard.press('Escape')
    expect(await diagnosticState()).toEqual(expected)
  } finally { await release(page) }
  expect(await stored(page)).toEqual(before)
  expect(await selection(page)).toEqual({ nodes: ['alpha', 'beta'], groups: [] })
  await frame.locator('#diagnosticsButton').click()
  await expect(frame.locator('[data-diagnostic-category="deadEnds"]')).toHaveAttribute('aria-pressed', 'true')
})
