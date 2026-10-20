export function createDragCopies(snapshot, nodeIds, groupId, createId) {
  const selected = new Set(nodeIds);
  const nodeMap = new Map(snapshot.nodes.filter((node) => selected.has(node.id))
    .map((node) => [node.id, createId('node')]));
  const nodes = snapshot.nodes.filter((node) => nodeMap.has(node.id))
    .map((node) => ({ ...structuredClone(node), id: nodeMap.get(node.id) }));
  const edges = snapshot.edges.filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
    .map((edge) => ({
      ...structuredClone(edge), id: createId('edge'),
      source: nodeMap.get(edge.source), target: nodeMap.get(edge.target)
    }));
  const groups = snapshot.groups.filter((group) => group.id === groupId)
    .map((group) => ({
      ...structuredClone(group), id: createId('group'),
      nodeIds: group.nodeIds.map((id) => nodeMap.get(id)).filter(Boolean)
    }));
  const views = snapshot.views.map((view) => ({
    id: view.id,
    positions: Object.fromEntries(snapshot.nodes.filter((node) => nodeMap.has(node.id))
      .map((node) => [nodeMap.get(node.id), { ...(view.positions[node.id] || { x: node.x, y: node.y }) }]))
  }));
  // Keep immutable origins so modifier toggles and repeated moves never accumulate drift.
  const origins = [...nodes, ...edges.flatMap((edge) => edge.points), ...views.flatMap((view) => Object.values(view.positions))]
    .map((point) => ({ point, x: point.x, y: point.y }));
  return { nodeMap, nodes, edges, groups, views, origins };
}

export function translateDragCopies(copies, dx, dy, limit) {
  if (!copies.origins.length) return { dx: 0, dy: 0 };
  const bounds = copies.origins.reduce((result, point) => ({
    minX: Math.min(result.minX, point.x), maxX: Math.max(result.maxX, point.x),
    minY: Math.min(result.minY, point.y), maxY: Math.max(result.maxY, point.y)
  }), { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity });
  dx = Math.max(-limit - bounds.minX, Math.min(limit - bounds.maxX, dx));
  dy = Math.max(-limit - bounds.minY, Math.min(limit - bounds.maxY, dy));
  copies.origins.forEach(({ point, x, y }) => { point.x = x + dx; point.y = y + dy; });
  return { dx, dy };
}
