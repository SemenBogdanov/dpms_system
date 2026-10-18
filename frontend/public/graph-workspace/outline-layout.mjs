import { rectangleBounds } from './arrangement-geometry.mjs';

function checked(value) {
  if (!Number.isFinite(value)) throw new RangeError('Outline layout arithmetic overflow');
  return value === 0 ? 0 : value;
}

/**
 * Pure forest layout, safe to import on the main thread. Roots and siblings follow
 * node input order; edges define parents, not ordering. Local origins ignore x/y.
 * Each tree has size-aware depth columns; every node gets its own preorder row.
 * Coordinates are local and may exceed world bounds: the caller owns translation
 * and final world-bound validation. Cycles/multiple parents are not outlines.
 */
export function outlineLayout(nodes, edges = [], options = {}) {
  rectangleBounds(nodes);
  if (!Array.isArray(edges)) throw new TypeError('edges must be an array');
  if (!options || typeof options !== 'object' || Array.isArray(options)) {
    throw new TypeError('Outline options must be an object');
  }
  const { gap = 48, direction = 'LR' } = options;
  if (typeof gap !== 'number' || !Number.isFinite(gap)) throw new TypeError('gap must be finite');
  if (gap < 0) throw new RangeError('gap must be nonnegative');
  if (!['LR', 'RL', 'TB', 'BT'].includes(direction)) throw new RangeError('Unknown outline direction');
  const byId = new Map();
  const children = new Map();
  for (const node of nodes) {
    if (node.width <= 0 || node.height <= 0) throw new RangeError('Rendered dimensions must be positive');
    byId.set(node.id, node);
    children.set(node.id, []);
  }
  const parents = new Map();
  for (const edge of edges) {
    if (!edge || typeof edge !== 'object' || Array.isArray(edge)) throw new TypeError('Edge must be an object');
    if (!byId.has(edge.source) || !byId.has(edge.target)) throw new RangeError('Unknown outline edge endpoint');
    if (edge.source === edge.target) throw new RangeError('Outline cannot contain self-loops');
    if (parents.has(edge.target) && parents.get(edge.target) !== edge.source) {
      throw new RangeError('Outline nodes cannot have multiple parents');
    }
    parents.set(edge.target, edge.source);
  }
  for (const node of nodes) {
    if (parents.has(node.id)) children.get(parents.get(node.id)).push(node.id);
  }
  const horizontal = direction === 'LR' || direction === 'RL';
  const depthSize = horizontal ? 'width' : 'height';
  const rowSize = horizontal ? 'height' : 'width';
  const columnGap = Math.max(64, gap);
  const rowGap = Math.max(32, gap);
  const arranged = new Map();
  let cursor = 0;
  let depthExtent = 0;
  for (const root of nodes.filter((node) => !parents.has(node.id))) {
    const rows = [];
    const widths = [];
    const stack = [{ id: root.id, depth: 0 }];
    while (stack.length) {
      const { id, depth } = stack.pop();
      const node = byId.get(id);
      rows.push({ node, depth });
      widths[depth] = Math.max(widths[depth] || 0, node[depthSize]);
      const descendants = children.get(id);
      for (let i = descendants.length - 1; i >= 0; i -= 1) {
        stack.push({ id: descendants[i], depth: depth + 1 });
      }
    }
    const columns = [0];
    for (let depth = 0; depth < widths.length - 1; depth += 1) {
      columns.push(checked(columns[depth] + Math.max(280, checked(Math.ceil(widths[depth]) + columnGap))));
    }
    for (const { node, depth } of rows) {
      arranged.set(node.id, { depth: columns[depth], row: cursor });
      depthExtent = Math.max(depthExtent, checked(columns[depth] + node[depthSize]));
      cursor = checked(cursor + Math.max(128, checked(Math.ceil(node[rowSize]) + rowGap)));
    }
    cursor = checked(cursor + Math.max(64, gap));
  }
  if (arranged.size !== nodes.length) throw new RangeError('Outline cannot contain cycles');
  const reversed = direction === 'RL' || direction === 'BT';
  return new Map(nodes.map((node) => {
    const point = arranged.get(node.id);
    const depth = reversed ? checked(depthExtent - point.depth - node[depthSize]) : point.depth;
    return [node.id, horizontal ? { x: depth, y: point.row } : { x: point.row, y: depth }];
  }));
}
