import { graphlib, layout } from './vendor/dagre-3.1.1.mjs';
import { outlineLayout } from './outline-layout.mjs';
import { findVacantPosition } from './insertion-geometry.mjs';

// Worker-only module: the UI sends rendered rectangles, never DOM nodes.
const LIMIT = 100000;
const GROUP_PADDING = 26;
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const idKey = (id) => JSON.stringify([typeof id, id]);

function record(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function validId(id) {
  if (typeof id !== 'string' && !(typeof id === 'number' && Number.isFinite(id))) {
    throw new TypeError('IDs must be strings or finite numbers');
  }
}

function finite(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return value;
}

function checked(value) {
  if (!Number.isFinite(value)) throw new RangeError('Layout arithmetic overflow');
  return value === 0 ? 0 : value;
}

function coordinate(value) {
  finite(value, 'Node coordinate');
  if (Math.abs(value) > LIMIT) throw new RangeError('Node coordinates exceed +/-100000');
  return value;
}

function bounds(rects) {
  let x = Infinity;
  let y = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const rect of rects) {
    x = Math.min(x, rect.x);
    y = Math.min(y, rect.y);
    right = Math.max(right, checked(rect.x + rect.width));
    bottom = Math.max(bottom, checked(rect.y + rect.height));
  }
  return { x, y, width: checked(right - x), height: checked(bottom - y) };
}

function selection(scopeIds, nodeIds) {
  if (scopeIds === null) return null;
  if (!Array.isArray(scopeIds) && !(scopeIds instanceof Set)) {
    throw new TypeError('scopeIds must be an array, Set or null');
  }
  const scope = new Set(scopeIds);
  for (const id of scope) {
    validId(id);
    if (!nodeIds.has(id)) throw new RangeError('Unknown scope node');
  }
  return scope;
}

/**
 * Rectangles require positive rendered dimensions and unique string/number IDs.
 * Groups sharing members coalesce transitively, with one 26px padded envelope.
 * Collapsed groups retain the supplied geometry; the caller owns visibility.
 * Partial scope or any pinned member fixes the entire block. Empty groups vanish.
 */
export function buildLayoutBlocks(nodes, groups = [], scopeIds = null) {
  if (!Array.isArray(nodes) || !Array.isArray(groups)) {
    throw new TypeError('nodes and groups must be arrays');
  }
  const byId = new Map();
  for (const node of nodes) {
    record(node, 'Node');
    validId(node.id);
    if (byId.has(node.id)) throw new RangeError('Node IDs must be unique');
    coordinate(node.x);
    coordinate(node.y);
    for (const name of ['width', 'height']) {
      finite(node[name], name);
      if (node[name] <= 0) throw new RangeError('Rendered dimensions must be positive');
    }
    checked(node.x + node.width);
    checked(node.y + node.height);
    if (node.pinned !== undefined && typeof node.pinned !== 'boolean') {
      throw new TypeError('pinned must be boolean');
    }
    byId.set(node.id, { ...node });
  }
  const scope = selection(scopeIds, byId);
  const parents = new Map(nodes.map(({ id }) => [id, id]));
  const find = (id) => {
    let root = id;
    while (parents.get(root) !== root) root = parents.get(root);
    while (parents.get(id) !== root) {
      const next = parents.get(id);
      parents.set(id, root);
      id = next;
    }
    return root;
  };
  const groupIds = new Set();
  for (const group of groups) {
    record(group, 'Group');
    validId(group.id);
    if (groupIds.has(group.id)) throw new RangeError('Group IDs must be unique');
    groupIds.add(group.id);
    if (!Array.isArray(group.nodeIds)) throw new TypeError('Group nodeIds must be an array');
    if (group.collapsed !== undefined && typeof group.collapsed !== 'boolean') {
      throw new TypeError('collapsed must be boolean');
    }
    for (const id of group.nodeIds) {
      validId(id);
      if (!byId.has(id)) throw new RangeError('Unknown group node');
      parents.set(find(id), find(group.nodeIds[0]));
    }
  }
  const components = new Map();
  for (const node of byId.values()) {
    const root = find(node.id);
    if (!components.has(root)) components.set(root, { members: [], groupIds: [] });
    components.get(root).members.push(node);
  }
  for (const group of groups) {
    if (group.nodeIds.length) components.get(find(group.nodeIds[0])).groupIds.push(idKey(group.id));
  }
  const nodeToBlock = new Map();
  const blocks = [...components.values()].map((component) => {
    const members = component.members.sort((a, b) => compare(idKey(a.id), idKey(b.id)));
    const grouped = component.groupIds.length > 0;
    const id = grouped
      ? `group:${JSON.stringify(component.groupIds.sort(compare))}`
      : `node:${idKey(members[0].id)}`;
    const padding = grouped ? GROUP_PADDING : 0;
    const box = bounds(members);
    members.forEach((node) => nodeToBlock.set(node.id, id));
    return {
      id, x: checked(box.x - padding), y: checked(box.y - padding),
      width: checked(box.width + padding * 2), height: checked(box.height + padding * 2),
      members, fixed: members.some((node) => node.pinned || (scope !== null && !scope.has(node.id))),
    };
  }).sort((a, b) => compare(a.id, b.id));
  return { blocks, nodeToBlock };
}

function blockGraph(blocks, nodeToBlock, edges) {
  if (!Array.isArray(edges)) throw new TypeError('edges must be an array');
  const graph = new graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  for (const block of blocks) graph.setNode(block.id, { width: block.width, height: block.height });
  const pairs = new Map();
  for (const edge of edges) {
    record(edge, 'Edge');
    validId(edge.source);
    validId(edge.target);
    if (!nodeToBlock.has(edge.source) || !nodeToBlock.has(edge.target)) {
      throw new RangeError('Unknown edge endpoint');
    }
    const source = nodeToBlock.get(edge.source);
    const target = nodeToBlock.get(edge.target);
    // Internal edges and self-loops cannot constrain a rigid block's placement.
    if (source !== target) pairs.set(JSON.stringify([source, target]), [source, target]);
  }
  for (const [, [source, target]] of [...pairs].sort(([a], [b]) => compare(a, b))) {
    graph.setEdge(source, target);
  }
  return graph;
}

function dagreHierarchy(blocks, graph, direction, gap) {
  graph.setGraph({ rankdir: direction, ranksep: gap, nodesep: gap, edgesep: gap, marginx: 0, marginy: 0 });
  layout(graph);
  return new Map(blocks.map((block) => {
    const node = graph.node(block.id);
    return [block.id, { x: checked(node.x - block.width / 2), y: checked(node.y - block.height / 2) }];
  }));
}

function hierarchy(blocks, graph, direction, gap, nodes, edges, nodeToBlock) {
  // Protected/grouped geometry takes priority over restoring an outline's rows.
  if (blocks.some((block) => block.fixed || block.id.startsWith('group:'))) {
    return dagreHierarchy(blocks, graph, direction, gap);
  }
  const components = graphlib.alg.components(graph).map((ids) => ({ ids: new Set(ids), outline: false, eligible: true }));
  const byBlock = new Map();
  for (const component of components) {
    component.ids.forEach((id) => byBlock.set(id, component));
  }
  for (const edge of edges) {
    const component = byBlock.get(nodeToBlock.get(edge.source));
    if (edge.label === '\u0434\u043e\u0447\u0435\u0440\u043d\u0438\u0439' && edge.source !== edge.target) component.outline = true;
    else component.eligible = false;
  }
  const outlineBlocks = new Set();
  for (const component of components) {
    if (!component.outline || !component.eligible) continue;
    if ([...component.ids].some((id) => graph.inEdges(id).length > 1)) continue;
    if (!graphlib.alg.isAcyclic(graph.filterNodes((id) => component.ids.has(id)))) continue;
    component.ids.forEach((id) => outlineBlocks.add(id));
  }
  if (!outlineBlocks.size) return dagreHierarchy(blocks, graph, direction, gap);

  // Lay out every qualifying tree in one call, using original node order rather
  // than canonical block/UUID order. Keep the general graph outside its envelope.
  const outlineNodes = nodes.filter((node) => outlineBlocks.has(nodeToBlock.get(node.id)));
  const outlineEdges = edges.filter((edge) => outlineBlocks.has(nodeToBlock.get(edge.source)));
  const outlined = outlineLayout(outlineNodes, outlineEdges, { direction, gap });
  const remaining = blocks.filter((block) => !outlineBlocks.has(block.id));
  const positions = new Map();
  let offset = 0;
  if (remaining.length) {
    const arranged = dagreHierarchy(remaining, graph.filterNodes((id) => !outlineBlocks.has(id)), direction, gap);
    const box = bounds(remaining.map((block) => ({ ...block, ...arranged.get(block.id) })));
    for (const block of remaining) {
      const point = arranged.get(block.id);
      positions.set(block.id, { x: checked(point.x - box.x), y: checked(point.y - box.y) });
    }
    offset = checked(box.width + gap);
  }
  for (const [id, point] of outlined) {
    positions.set(nodeToBlock.get(id), { x: checked(point.x + offset), y: point.y });
  }
  return positions;
}

function compact(blocks, gap) {
  const columns = Math.ceil(Math.sqrt(blocks.length));
  const widths = Array(columns).fill(0);
  const heights = Array(Math.ceil(blocks.length / columns)).fill(0);
  blocks.forEach((block, i) => {
    widths[i % columns] = Math.max(widths[i % columns], block.width);
    heights[Math.floor(i / columns)] = Math.max(heights[Math.floor(i / columns)], block.height);
  });
  const offsets = (sizes) => {
    let offset = 0;
    return sizes.map((size) => {
      const result = offset;
      offset = checked(offset + size + gap);
      return result;
    });
  };
  const xs = offsets(widths);
  const ys = offsets(heights);
  return new Map(blocks.map((block, i) => [block.id, { x: xs[i % columns], y: ys[Math.floor(i / columns)] }]));
}

function radial(blocks, graph, direction, gap) {
  const byId = new Map(blocks.map((block) => [block.id, block]));
  const positions = new Map();
  const components = graphlib.alg.components(graph).map((ids) => ids.sort(compare))
    .sort((a, b) => compare(a[0], b[0]));
  const angle = { LR: 0, RL: Math.PI, TB: Math.PI / 2, BT: -Math.PI / 2 }[direction];
  // Inflate both axes by gap so diagonal neighbors also clear the repair margin.
  const clearance = checked(gap * Math.SQRT2);
  let offset = 0;
  for (const ids of components) {
    const sources = ids.filter((id) => graph.inEdges(id).length === 0);
    const root = sources[0] ?? [...ids].sort((a, b) =>
      graph.outEdges(b).length - graph.outEdges(a).length || compare(a, b))[0];
    // Weak-graph shortest paths give stable rings for cycles and multiple roots.
    const paths = graphlib.alg.dijkstra(graph, root, () => 1, (id) => graph.nodeEdges(id));
    const rings = new Map();
    for (const id of ids) {
      const depth = paths[id].distance;
      checked(depth);
      if (!rings.has(depth)) rings.set(depth, []);
      rings.get(depth).push(byId.get(id));
    }
    let radius = 0;
    let previousSize = 0;
    const local = [];
    for (const [depth, ring] of [...rings].sort(([a], [b]) => a - b)) {
      const size = ring.reduce((max, block) => Math.max(max, checked(Math.hypot(block.width, block.height) / 2)), 0);
      if (depth > 0) {
        const circumferenceRadius = ring.length > 1
          ? checked((2 * size + clearance) / (2 * Math.sin(Math.PI / ring.length))) : 0;
        radius = Math.max(checked(radius + previousSize + size + clearance), circumferenceRadius);
      }
      ring.forEach((block, i) => {
        const theta = angle + 2 * Math.PI * i / ring.length;
        local.push({ ...block,
          x: checked(radius * Math.cos(theta) - block.width / 2),
          y: checked(radius * Math.sin(theta) - block.height / 2),
        });
      });
      previousSize = size;
    }
    const box = bounds(local);
    for (const block of local) {
      positions.set(block.id, { x: checked(block.x - box.x + offset), y: checked(block.y - box.y) });
    }
    offset = checked(offset + box.width + gap);
  }
  return positions;
}

function collides(a, b, gap) {
  return a.x < checked(b.x + b.width + gap) && b.x < checked(a.x + a.width + gap)
    && a.y < checked(b.y + b.height + gap) && b.y < checked(a.y + a.height + gap);
}

function nodePoint(node, block, point) {
  return { x: checked(point.x + checked(node.x - block.x)), y: checked(point.y + checked(node.y - block.y)) };
}

function inBounds(block, point) {
  return block.members.every((node) => {
    const translated = nodePoint(node, block, point);
    return Math.abs(translated.x) <= LIMIT && Math.abs(translated.y) <= LIMIT;
  });
}

function fitMovableTranslation(blocks, proposed, anchor) {
  const minimum = { x: Infinity, y: Infinity };
  const maximum = { x: -Infinity, y: -Infinity };
  for (const block of blocks) {
    for (const node of block.members) {
      const point = nodePoint(node, block, proposed.get(block.id));
      for (const axis of ['x', 'y']) {
        minimum[axis] = Math.min(minimum[axis], point[axis]);
        maximum[axis] = Math.max(maximum[axis], point[axis]);
      }
    }
  }
  const translation = {};
  for (const axis of ['x', 'y']) {
    if (checked(maximum[axis] - minimum[axis]) > LIMIT * 2) {
      throw new RangeError('Layout node coordinate span exceeds 200000');
    }
    // Bound member origins, not group padding or rectangle extents. Choose the
    // nearest feasible anchor without scaling or changing relative positions.
    const lower = checked(-LIMIT - minimum[axis]);
    const upper = checked(LIMIT - maximum[axis]);
    translation[axis] = Math.max(lower, Math.min(upper, anchor[axis]));
  }
  return translation;
}

function clearObstacles(block, initial, obstacles, gap) {
  const point = { ...initial };
  // Each right/down shift passes one obstacle forever. At most N shifts suffice.
  for (let step = 0; step <= obstacles.length && inBounds(block, point); step += 1) {
    const hits = obstacles.filter((other) => collides({ ...block, ...point }, other, gap));
    if (!hits.length) return point;
    let next = null;
    let distance = Infinity;
    for (const hit of hits) {
      for (const candidate of [
        { x: checked(hit.x + hit.width + gap), y: point.y },
        { x: point.x, y: checked(hit.y + hit.height + gap) },
      ]) {
        const shift = checked(candidate.x - point.x + candidate.y - point.y);
        if (shift > 0 && shift < distance && inBounds(block, candidate)) {
          next = candidate;
          distance = shift;
        }
      }
    }
    if (!next) break;
    Object.assign(point, next);
  }
  // A failed monotone path does not prove the area is full. Sweep the entire
  // member-origin domain once, from the original proposal, without moving obstacles.
  const originBounds = { minX: -Infinity, maxX: Infinity, minY: -Infinity, maxY: Infinity };
  for (const node of block.members) {
    const x = checked(node.x - block.x);
    const y = checked(node.y - block.y);
    originBounds.minX = Math.max(originBounds.minX, checked(-LIMIT - x));
    originBounds.maxX = Math.min(originBounds.maxX, checked(LIMIT - x));
    originBounds.minY = Math.max(originBounds.minY, checked(-LIMIT - y));
    originBounds.maxY = Math.min(originBounds.maxY, checked(LIMIT - y));
  }
  const vacant = findVacantPosition({ ...block, ...initial }, obstacles, { gap, originBounds });
  if (!vacant || !inBounds(block, vacant)) throw new RangeError('Cannot clear obstacles within +/-100000');
  return vacant;
}

/**
 * Synchronous worker API. Positions include every input node in input order.
 * movedCount counts changed nodes; blockedCount counts in-scope nodes in fixed
 * blocks (pins/partial groups), never unselected obstacle nodes. Fixed/fixed
 * overlaps and existing overlaps inside rigid groups are intentionally retained.
 * The movable anchor shifts as one unit when needed to fit world bounds, before
 * obstacle repair. Geometry is never scaled/clamped; invalid input/output throws.
 */
export function arrangeGraph(input) {
  record(input, 'Layout input');
  const { nodes, edges = [], groups = [], scopeIds = null, mode = 'hierarchy', direction = 'LR', gap = 48 } = input;
  if (!['hierarchy', 'compact', 'radial'].includes(mode)) throw new RangeError('Unknown layout mode');
  if (!['LR', 'RL', 'TB', 'BT'].includes(direction)) throw new RangeError('Unknown layout direction');
  finite(gap, 'gap');
  if (gap < 0) throw new RangeError('gap must be nonnegative');
  const { blocks, nodeToBlock } = buildLayoutBlocks(nodes, groups, scopeIds);
  const graph = blockGraph(blocks, nodeToBlock, edges);
  const scope = selection(scopeIds, nodeToBlock);
  const movable = blocks.filter((block) => !block.fixed);
  const fixed = blocks.filter((block) => block.fixed);
  const blockedCount = fixed.reduce((count, block) => count + block.members
    .filter((node) => scope === null || scope.has(node.id)).length, 0);
  const positions = new Map(nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  if (!movable.length) return { positions: [...positions], movedCount: 0, blockedCount };
  const proposed = mode === 'hierarchy' ? hierarchy(blocks, graph, direction, gap, nodes, edges, nodeToBlock)
    : mode === 'radial' ? radial(blocks, graph, direction, gap) : compact(movable, gap);
  const original = bounds(movable);
  const arranged = bounds(movable.map((block) => ({ ...block, ...proposed.get(block.id) })));
  const translation = fitMovableTranslation(movable, proposed, {
    x: checked(original.x - arranged.x), y: checked(original.y - arranged.y),
  });
  const obstacles = [...fixed];
  // Geometric order reduces repair cascades; IDs settle ties independently of input order.
  const order = [...movable].sort((a, b) => proposed.get(a.id).x - proposed.get(b.id).x
    || proposed.get(a.id).y - proposed.get(b.id).y || compare(a.id, b.id));
  for (const block of order) {
    const point = proposed.get(block.id);
    const repaired = clearObstacles(block, { x: checked(point.x + translation.x), y: checked(point.y + translation.y) }, obstacles, gap);
    for (const node of block.members) {
      const translated = nodePoint(node, block, repaired);
      coordinate(translated.x);
      coordinate(translated.y);
      checked(translated.x + node.width);
      checked(translated.y + node.height);
      positions.set(node.id, translated);
    }
    obstacles.push({ ...block, ...repaired });
  }
  const movedCount = nodes.filter((node) => {
    const point = positions.get(node.id);
    return point.x !== node.x || point.y !== node.y;
  }).length;
  return { positions: [...positions], movedCount, blockedCount };
}
