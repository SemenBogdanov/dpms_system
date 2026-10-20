import test from 'node:test';
import assert from 'node:assert/strict';
import { createDragCopies, translateDragCopies } from '../public/graph-workspace/drag-duplication.mjs';

const fixture = () => ({
  nodes: [
    { id: 'a', x: 10, y: 20, title: 'First', items: ['one'], pinned: true, sourceRef: 'doc:1' },
    { id: 'b', x: 60, y: 90, title: 'Second', items: [] },
    { id: 'c', x: 90, y: 150, title: 'Outside', items: [] }
  ],
  edges: [
    { id: 'ab', source: 'a', target: 'b', label: 'internal', sourcePort: 'e:4', targetPort: 'w:1', points: [{ x: 12, y: 25 }] },
    { id: 'bc', source: 'b', target: 'c', label: 'outside', points: [] }
  ],
  groups: [{ id: 'team', title: 'Team', nodeIds: ['a', 'b'], collapsed: true, color: '#123456' }],
  views: [
    { id: 'current', positions: { a: { x: 10, y: 20 }, b: { x: 60, y: 90 }, c: { x: 90, y: 150 } } },
    { id: 'other', positions: { a: { x: -100, y: -200 }, b: { x: -50, y: -130 } } }
  ]
});
const makeCopies = (source, ids = ['a', 'b'], groupId) => {
  let id = 0;
  return createDragCopies(source, ids, groupId, (prefix) => `${prefix}-${++id}`);
};

test('copies every node field, only internal edges, and a group only on explicit group drag', () => {
  const source = fixture();
  const before = structuredClone(source);
  const copies = makeCopies(source);
  assert.equal(copies.nodes.length, 2);
  assert.equal(copies.edges.length, 1);
  assert.deepEqual(copies.groups, []);
  copies.nodes.forEach((node, i) => assert.deepEqual(node, { ...source.nodes[i], id: node.id }));
  assert.deepEqual(copies.edges[0], {
    ...source.edges[0], id: copies.edges[0].id, source: copies.nodeMap.get('a'), target: copies.nodeMap.get('b')
  });
  copies.nodes[0].items.push('copy only');
  copies.edges[0].points[0].x = 999;
  assert.deepEqual(source, before);
  const grouped = makeCopies(source, ['a', 'b'], 'team');
  assert.deepEqual(grouped.groups[0], {
    ...source.groups[0], id: grouped.groups[0].id, nodeIds: grouped.nodes.map((node) => node.id)
  });
});

test('translation preserves spacing, edge ports, routes and per-view origins without drift', () => {
  const source = fixture();
  const before = structuredClone(source);
  const copies = makeCopies(source);
  for (const [dx, dy] of [[40, -10], [100, 200], [0, 0], [-15, 25]]) {
    assert.deepEqual(translateDragCopies(copies, dx, dy, 100000), { dx, dy });
    copies.origins.forEach(({ point, x, y }) => assert.deepEqual({ x: point.x, y: point.y }, { x: x + dx, y: y + dy }));
  }
  assert.deepEqual(source, before);
  assert.equal(copies.edges[0].sourcePort, 'e:4');
});

test('the entire copied set including inactive view positions and edge points stays bounded', () => {
  const copies = makeCopies(fixture());
  copies.origins.push({ point: {}, x: 99998, y: -99999 });
  assert.deepEqual(translateDragCopies(copies, 200, -200, 100000), { dx: 2, dy: -1 });
  for (const { point, x, y } of copies.origins) {
    assert.equal(point.x - x, 2);
    assert.equal(point.y - y, -1);
    assert.ok(Math.abs(point.x) <= 100000 && Math.abs(point.y) <= 100000);
  }
});

test('unknown IDs and an empty selection add no nodes, edges or groups', () => {
  const copies = makeCopies(fixture(), ['missing']);
  assert.deepEqual(copies.nodes, []);
  assert.deepEqual(copies.edges, []);
  assert.deepEqual(copies.groups, []);
  assert.deepEqual(translateDragCopies(copies, 50, 40, 100000), { dx: 0, dy: 0 });
});
