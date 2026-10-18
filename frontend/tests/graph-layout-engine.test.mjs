import test from 'node:test';
import assert from 'node:assert/strict';
import { arrangeGraph, buildLayoutBlocks } from '../public/graph-workspace/layout-engine.mjs';
import { outlineLayout } from '../public/graph-workspace/outline-layout.mjs';

const modes = ['hierarchy', 'compact', 'radial'];
const rect = (id, x = 0, y = 0, width = 80, height = 40, pinned = false) => ({ id, x, y, width, height, pinned });
const edge = (source, target) => ({ source, target });
const group = (id, ...nodeIds) => ({ id, nodeIds });
const childEdge = (source, target) => ({ source, target, label: '\u0434\u043e\u0447\u0435\u0440\u043d\u0438\u0439' });
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
const overlap = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width
  && a.y < b.y + b.height && b.y < a.y + a.height;
const minimum = (items, axis) => Math.min(...items.map((item) => item[axis]));
const placed = (input, result) => {
  const positions = new Map(result.positions);
  return input.nodes.map((node) => ({ ...node, ...positions.get(node.id) }));
};
const orderedPositions = (result) => [...result.positions].sort(([a], [b]) => {
  const ak = JSON.stringify([typeof a, a]);
  const bk = JSON.stringify([typeof b, b]);
  return ak < bk ? -1 : ak > bk ? 1 : 0;
});
const freeze = (value) => {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};

function verify(input, result) {
  assert.deepEqual(result.positions.map(([id]) => id), input.nodes.map(({ id }) => id));
  const positions = new Map(result.positions);
  const original = buildLayoutBlocks(input.nodes, input.groups, input.scopeIds).blocks;
  const output = buildLayoutBlocks(placed(input, result), input.groups, input.scopeIds).blocks;
  let moved = 0;
  let blocked = 0;
  const scope = input.scopeIds == null ? null : new Set(input.scopeIds);
  for (const block of original) {
    const first = block.members[0];
    const anchor = positions.get(first.id);
    for (const node of block.members) {
      const point = positions.get(node.id);
      assert.ok(Number.isFinite(point.x) && Math.abs(point.x) <= 100000);
      assert.ok(Number.isFinite(point.y) && Math.abs(point.y) <= 100000);
      close(point.x - anchor.x, node.x - first.x);
      close(point.y - anchor.y, node.y - first.y);
      if (point.x !== node.x || point.y !== node.y) moved += 1;
      if (block.fixed) {
        assert.deepEqual(point, { x: node.x, y: node.y });
        if (scope === null || scope.has(node.id)) blocked += 1;
      }
    }
  }
  assert.equal(result.movedCount, moved);
  assert.equal(result.blockedCount, blocked);
  for (let i = 0; i < output.length; i += 1) {
    for (let j = i + 1; j < output.length; j += 1) {
      if (output[i].fixed && output[j].fixed) continue;
      assert.equal(overlap(output[i], output[j]), false, `${output[i].id} overlaps ${output[j].id}`);
    }
  }
}

test('blocks: exact padded bounds, typed IDs, no input mutation', () => {
  const nodes = freeze([rect('a', -100, -25, 90, 55), rect('b', 40, 80, 120, 75), rect('g', 9, 8)]);
  const groups = freeze([group('g', 'b', 'a')]);
  const before = JSON.stringify({ nodes, groups });
  const { blocks, nodeToBlock } = buildLayoutBlocks(nodes, groups);
  const rigid = blocks.find((block) => block.members.length === 2);
  assert.deepEqual({ x: rigid.x, y: rigid.y, width: rigid.width, height: rigid.height }, {
    x: -126, y: -51, width: 312, height: 232,
  });
  assert.equal(rigid.fixed, false);
  assert.equal(nodeToBlock.get('a'), nodeToBlock.get('b'));
  assert.notEqual(nodeToBlock.get('a'), nodeToBlock.get('g'));
  assert.equal(JSON.stringify({ nodes, groups }), before);
  rigid.members[0].x = 12;
  assert.equal(nodes[0].x, -100);
});

test('blocks: transitive shared membership, duplicates and collapsed groups remain rigid', () => {
  const nodes = [rect('a'), rect('b', 100), rect('c', 200), rect('d', 300), rect('e', 400)];
  const groups = [group('first', 'a', 'b', 'b'), { ...group('second', 'c', 'b'), collapsed: true }, group('third', 'd', 'c'), group('empty')];
  const { blocks, nodeToBlock } = buildLayoutBlocks(nodes, groups);
  assert.equal(blocks.length, 2);
  assert.equal(new Set(['a', 'b', 'c', 'd'].map((id) => nodeToBlock.get(id))).size, 1);
  assert.equal(blocks.find((block) => block.members.length === 4).width, 432);
  assert.deepEqual(buildLayoutBlocks([...nodes].reverse(), [...groups].reverse()).blocks, blocks);
});

test('blocks: groups that merely overlap geometrically do not merge', () => {
  const { blocks } = buildLayoutBlocks([rect('a'), rect('b')], [group('one', 'a'), group('two', 'b')]);
  assert.equal(blocks.length, 2);
});

test('blocks: pin, partial selection and transitive overlap fix whole groups', () => {
  const nodes = [rect('a'), rect('b', 100, 0, 80, 40, true), rect('c', 200), rect('d', 300), rect('e', 400)];
  const groups = [group('pinned', 'a', 'b'), group('partial', 'c', 'd')];
  const all = buildLayoutBlocks(nodes, groups).blocks;
  assert.equal(all.find((block) => block.members.some((node) => node.id === 'a')).fixed, true);
  const selected = buildLayoutBlocks(nodes, groups, ['a', 'c']).blocks;
  assert.ok(selected.every((block) => block.fixed));
  const fullGroup = buildLayoutBlocks(nodes, groups, new Set(['c', 'd'])).blocks;
  assert.equal(fullGroup.find((block) => block.members.some((node) => node.id === 'c')).fixed, false);
  const transitive = buildLayoutBlocks(nodes, [...groups, group('join', 'b', 'c')], ['a', 'b', 'c', 'e']);
  assert.equal(transitive.blocks.filter((block) => block.fixed).length, 1);
});

for (const mode of modes) {
  test(`${mode}: empty, singleton, empty scope, all pinned`, () => {
    assert.deepEqual(arrangeGraph({ nodes: [], mode }), { positions: [], movedCount: 0, blockedCount: 0 });
    const singleton = { nodes: [rect('one', -723.5, 913.25)], mode };
    assert.deepEqual(arrangeGraph(singleton), { positions: [['one', { x: -723.5, y: 913.25 }]], movedCount: 0, blockedCount: 0 });
    const input = { nodes: [rect('a'), rect('b')], mode, scopeIds: [] };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(result.movedCount, 0);
    assert.equal(result.blockedCount, 0);
    const pinned = { nodes: input.nodes.map((node) => ({ ...node, pinned: true })), mode };
    verify(pinned, arrangeGraph(pinned));
    assert.equal(arrangeGraph(pinned).blockedCount, 2);
  });

  test(`${mode}: mixed rendered sizes, deterministic, original movable bounds anchor`, () => {
    const input = {
      mode, gap: 23,
      nodes: [rect('a', -830, -130, 210, 80), rect('b', -100, 400, 85, 340), rect('c', 30, 50, 405, 170), rect('d', 200, 300, 60, 65)],
      edges: [edge('a', 'b'), edge('a', 'c'), edge('c', 'd')],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.deepEqual(arrangeGraph(input), result);
    const output = placed(input, result);
    close(minimum(output, 'x'), minimum(input.nodes, 'x'));
    close(minimum(output, 'y'), minimum(input.nodes, 'y'));
  });

  test(`${mode}: cycles, self-loops, parallel edges and disconnected components`, () => {
    const input = {
      mode, nodes: Array.from({ length: 12 }, (_, i) => rect(`n${i}`, -40 + i * 13, -90 + i * 27, 50 + i * 7, 25 + i * 11)),
      edges: [edge('n0', 'n1'), edge('n1', 'n2'), edge('n2', 'n0'), edge('n0', 'n1'), edge('n2', 'n2'), edge('n3', 'n4'), edge('n5', 'n6'), edge('n6', 'n5')],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.deepEqual(orderedPositions(arrangeGraph({ ...input, nodes: [...input.nodes].reverse(), edges: [...input.edges].reverse() })), orderedPositions(result));
  });

  test(`${mode}: rigid overlapping membership, pins and selected groups`, () => {
    const input = {
      mode, gap: 19,
      nodes: [rect('a', 300, 300, 200, 50), rect('b', 540, 330, 90, 100), rect('c', 690, 320, 60, 80), rect('d', 300, 300, 140, 300, true), rect('e', 500, 600), rect('f', 550, 670), rect('outside', -12000, -14000)],
      groups: [group('rigid', 'a', 'b'), { ...group('merged', 'b', 'c'), collapsed: true }, group('partial', 'e', 'f')],
      scopeIds: ['a', 'b', 'c', 'd', 'e'],
      edges: [edge('a', 'b'), edge('c', 'd'), edge('d', 'outside')],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(result.blockedCount, 2);
    const before = JSON.stringify(input);
    assert.deepEqual(arrangeGraph(freeze(input)), result);
    assert.equal(JSON.stringify(input), before);
  });

  test(`${mode}: pinned member prevents any member of a coalesced group from moving`, () => {
    const input = {
      mode, nodes: [rect('a'), rect('b', 100), rect('c', 200, 0, 90, 70, true), rect('d')],
      groups: [group('one', 'a', 'b'), group('two', 'b', 'c')],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(result.blockedCount, 3);
    assert.equal(result.movedCount, 1);
  });

  test(`${mode}: collision repair handles restored and overlapping fixed blocks`, () => {
    const input = {
      mode, gap: 13,
      nodes: [rect('moving', 100, 100, 50, 40), rect('p1', 100, 100, 100, 120, true), rect('p2', 180, 100, 150, 100, true), rect('p3', 100, 180, 100, 150, true)],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(result.movedCount, 1);
  });

  test(`${mode}: numeric IDs, prototype names, separators and group/node collisions`, () => {
    const ids = [0, '0', '__proto__', 'constructor', 'a\x01b', 'a\x00b', 'group:["x"]', 'node:["number",0]'];
    const input = {
      mode, nodes: ids.map((id) => rect(id)),
      groups: [group('__proto__', 0, 'constructor'), group(0, '__proto__'), group('0', '0')],
      edges: ids.slice(1).map((id, i) => edge(ids[i], id)),
    };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(new Set(buildLayoutBlocks(input.nodes, input.groups).blocks.map(({ id }) => id)).size, 7);
    assert.deepEqual(arrangeGraph(input), result);
  });

  test(`${mode}: >100 nodes with variable dimensions, cycles, groups, pins and many components`, () => {
    const nodes = Array.from({ length: 160 }, (_, i) => rect(`n${String(i).padStart(3, '0')}`, (i * 31 % 541) - 200, (i * 17 % 421) - 150, 20 + i * 7 % 100, 15 + i * 11 % 90, i % 29 === 0));
    const edges = nodes.flatMap((node, i) => i % 7 !== 0 && i > 0 ? [edge(nodes[i - 1].id, node.id), edge(node.id, nodes[Math.floor(i / 7) * 7].id)] : []);
    const groups = Array.from({ length: 8 }, (_, i) => group(`g${i}`, nodes[i * 10].id, nodes[i * 10 + 1].id));
    const input = { nodes, edges, groups, mode, gap: 12 };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.deepEqual(arrangeGraph(input), result);
  });

  test(`${mode}: near-boundary proposals translate as one unit without clamping or scaling`, () => {
    const reference = { mode, nodes: [rect('a'), rect('b')] };
    const local = new Map(arrangeGraph(reference).positions);
    const input = { mode, nodes: [rect('a', 100000, 100000), rect('b', 100000, 100000)] };
    const result = arrangeGraph(input);
    verify(input, result);
    const points = new Map(result.positions);
    for (const axis of ['x', 'y']) {
      close(points.get('b')[axis] - points.get('a')[axis], local.get('b')[axis] - local.get('a')[axis]);
      assert.equal(Math.max(...result.positions.map(([, point]) => point[axis])), 100000);
    }
  });

  test(`${mode}: spans exceeding both world bounds still reject atomically`, () => {
    const input = freeze({ mode, nodes: [rect('a', 0, 0, 300001, 300001), rect('b', 0, 0, 300001, 300001)] });
    const before = JSON.stringify(input);
    assert.throws(() => arrangeGraph(input), /200000/);
    assert.equal(JSON.stringify(input), before);
  });
}

for (const direction of ['LR', 'RL', 'TB', 'BT']) {
  test(`hierarchy: ${direction} honors edge direction and exact rendered dimensions`, () => {
    const nodes = [rect('root', 600, 300, 310, 120), rect('child', 800, 600, 75, 250), rect('leaf', 1000, 900, 220, 70)];
    const input = { nodes, edges: [edge('root', 'child'), edge('child', 'leaf')], direction, gap: 35 };
    const result = arrangeGraph(input);
    verify(input, result);
    const output = placed(input, result);
    for (let i = 1; i < output.length; i += 1) {
      const previous = output[i - 1];
      const next = output[i];
      if (direction === 'LR') assert.ok(next.x >= previous.x + previous.width + 35);
      if (direction === 'RL') assert.ok(previous.x >= next.x + next.width + 35);
      if (direction === 'TB') assert.ok(next.y >= previous.y + previous.height + 35);
      if (direction === 'BT') assert.ok(previous.y >= next.y + next.height + 35);
    }
  });
}

test('compact: variable column widths and row heights, zero gap', () => {
  const input = { mode: 'compact', gap: 0, nodes: [rect('a', 50, 80, 300, 100), rect('b', 50, 80, 70, 290), rect('c', 50, 80, 30, 40), rect('d', 50, 80, 40, 50)] };
  const result = arrangeGraph(input);
  verify(input, result);
  assert.deepEqual(result.positions, [['a', { x: 50, y: 80 }], ['b', { x: 350, y: 80 }], ['c', { x: 50, y: 370 }], ['d', { x: 350, y: 370 }]]);
});

test('radial: a star has one center and a circular first ring, not a grid', () => {
  const input = {
    mode: 'radial', nodes: [rect('root', 1700, 800, 75, 45), ...Array.from({ length: 8 }, (_, i) => rect(`leaf${i}`, 1700, 800, 50 + i * 3, 30 + i * 2))],
    edges: Array.from({ length: 8 }, (_, i) => edge('root', `leaf${i}`)),
  };
  const result = arrangeGraph(input);
  verify(input, result);
  const [root, ...leaves] = placed(input, result);
  const distances = leaves.map((node) => Math.hypot(node.x + node.width / 2 - root.x - root.width / 2, node.y + node.height / 2 - root.y - root.height / 2));
  distances.forEach((value) => close(value, distances[0]));
  assert.ok(leaves.some((node) => node.x < root.x) && leaves.some((node) => node.x > root.x));
  assert.ok(leaves.some((node) => node.y < root.y) && leaves.some((node) => node.y > root.y));
});

test('radial: dense rings retain their shape without collision repair or fixed obstacles', () => {
  for (let count = 2; count <= 48; count += 1) {
    const input = {
      mode: 'radial',
      nodes: Array.from({ length: count + 1 }, (_, i) => rect(String(i), 123.45, 67.89, 40, 40)),
      edges: Array.from({ length: count }, (_, i) => edge('0', String(i + 1))),
    };
    const result = arrangeGraph(input);
    verify(input, result);
    const [root, ...leaves] = placed(input, result);
    const distances = leaves.map((node) => Math.hypot(node.x - root.x, node.y - root.y));
    distances.forEach((distance) => close(distance, distances[0]));
  }
});

test('deterministic sweep: fractional rectangles, shared groups, cycles and pins never overlap', () => {
  let seed = 1883;
  const random = () => {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 2 ** 32;
  };
  for (let iteration = 0; iteration < 75; iteration += 1) {
    const count = 5 + Math.floor(random() * 30);
    const nodes = Array.from({ length: count }, (_, i) => rect(String(i), random() * 1500 - 500, random() * 1500 - 500, 1 + random() * 250, 1 + random() * 250, random() < 0.15));
    const groups = Array.from({ length: Math.floor(count / 5) }, (_, i) => group(String(i), String(i * 3), String(i * 3 + 1)));
    const edges = Array.from({ length: count }, () => edge(String(Math.floor(random() * count)), String(Math.floor(random() * count))));
    for (const mode of modes) {
      const input = { nodes, groups, edges, mode, gap: iteration % 2 ? 0 : 48 };
      verify(input, arrangeGraph(input));
    }
  }
});

test('collision repair: nearest right/down step, with bounded alternative when closest is outside range', () => {
  const input = { mode: 'compact', gap: 10, nodes: [rect('moving', 100, 100, 80, 40), rect('fixed', 100, 100, 50, 100, true)] };
  const result = arrangeGraph(input);
  verify(input, result);
  assert.deepEqual(new Map(result.positions).get('moving'), { x: 160, y: 100 });
  const boundary = { mode: 'compact', gap: 0, nodes: [rect('moving', 99995, 0, 10, 10), rect('fixed', 99990, -100, 20, 120, true)] };
  const shifted = arrangeGraph(boundary);
  verify(boundary, shifted);
  assert.deepEqual(new Map(shifted.positions).get('moving'), { x: 99995, y: 20 });
  const corner = { mode: 'compact', gap: 0, nodes: [rect('m', 100000, 100000), rect('p', 100000, 100000, 80, 40, true)] };
  const rescued = arrangeGraph(corner);
  verify(corner, rescued);
  assert.deepEqual(new Map(rescued.positions).get('m'), { x: 100000, y: 99960 });
});

for (const mode of modes) {
  test(`${mode}: complete fallback finds left/up vacancies at the positive corner`, () => {
    for (const [width, height, expected] of [
      [80, 40, { x: 100000, y: 99902 }],
      [40, 80, { x: 99902, y: 100000 }],
    ]) {
      const input = freeze({ mode, gap: 48, nodes: [
        rect('moving', 100000, 100000, width, height), rect('pin', 99990, 99990, 100, 100, true),
      ] });
      const before = JSON.stringify(input);
      const result = arrangeGraph(input);
      verify(input, result);
      const points = new Map(result.positions);
      assert.deepEqual(points.get('moving'), expected);
      assert.deepEqual(points.get('pin'), { x: 99990, y: 99990 });
      assert.ok(expected.x + width + 48 <= 99990 || expected.y + height + 48 <= 99990);
      assert.equal(JSON.stringify(input), before);
      assert.deepEqual(arrangeGraph(input), result);
    }
  });

  test(`${mode}: fallback preserves unselected obstacles and scope accounting`, () => {
    const input = freeze({ mode, gap: 48, scopeIds: ['moving'], nodes: [
      rect('moving', 100000, 100000, 80, 40), rect('outside', 99990, 99990, 100, 100),
    ] });
    const result = arrangeGraph(input);
    verify(input, result);
    assert.equal(result.blockedCount, 0);
    assert.equal(result.movedCount, 1);
    assert.deepEqual(new Map(result.positions).get('outside'), { x: 99990, y: 99990 });
  });

  test(`${mode}: rigid member bounds admit padding beyond negative limits and a single search line`, () => {
    for (const axis of ['x', 'y']) {
      for (const origin of [-100000, 100000]) {
        const nodes = axis === 'x'
          ? [rect('a', -100000, origin), rect('b', 100000, origin), rect('pin', 0, origin, 80, 40, true)]
          : [rect('a', origin, -100000), rect('b', origin, 100000), rect('pin', origin, 0, 80, 40, true)];
        const input = freeze({ mode, gap: 48, nodes, groups: [group('rigid', 'a', 'b')] });
        const result = arrangeGraph(input);
        verify(input, result);
        const points = new Map(result.positions);
        assert.equal(points.get('a')[axis], -100000);
        assert.equal(points.get('b')[axis], 100000);
        const output = buildLayoutBlocks(placed(input, result), input.groups).blocks;
        const rigid = output.find((block) => block.members.length === 2);
        const pin = output.find((block) => block.fixed);
        assert.equal(rigid[axis], -100026);
        assert.ok(rigid.x + rigid.width + 48 <= pin.x || pin.x + pin.width + 48 <= rigid.x
          || rigid.y + rigid.height + 48 <= pin.y || pin.y + pin.height + 48 <= rigid.y);
      }
    }
  });

  test(`${mode}: a fully covered origin domain still throws without mutating any input`, () => {
    for (const pins of [
      [rect('full', -100000, -100000, 200001, 200001, true)],
      [rect('left', -100000, -100000, 100001, 200001, true), rect('right', 0, -100000, 100001, 200001, true)],
    ]) {
      const input = freeze({ mode, gap: 0, nodes: [rect('moving', 0, 0, 40, 20), ...pins] });
      const before = JSON.stringify(input);
      assert.throws(() => arrangeGraph(input), /Cannot clear obstacles within/);
      assert.equal(JSON.stringify(input), before);
    }
  });

  test(`${mode}: far fractional origins do not introduce overlaps during final translation`, () => {
    for (const gap of [0, 48]) {
      const input = freeze({ mode, gap, nodes: [
        rect('a', -99999.7, -99999.7, 223.7, 40.1), rect('b', 99999.7, 99999.7, 31.3, 40.1),
      ], edges: [edge('a', 'b')] });
      const result = arrangeGraph(input);
      verify(input, result);
      const [a, b] = placed(input, result);
      assert.ok(a.x + a.width + gap <= b.x || b.x + b.width + gap <= a.x
        || a.y + a.height + gap <= b.y || b.y + b.height + gap <= a.y);
      if (mode === 'compact' && gap === 0) assert.equal(a.x + a.width, b.x);
    }
  });
}

test('compact: relative member offsets preserve mixed-size fractional rigid blocks across distant origins', () => {
  const input = freeze({ mode: 'compact', gap: 0, nodes: [
    rect('a', 99920.2, 99880.4, 31.3, 40.1), rect('b', 99960.7, 99931.1, 75.6, 29.3),
    rect('c', -99999.7, -99999.7, 223.7, 40.1),
  ], groups: [group('rigid', 'a', 'b')] });
  verify(input, arrangeGraph(input));
});

test('many obstacles: monotone repair clears a staircase without an arbitrary iteration cutoff', () => {
  const nodes = [rect('moving', 0, 0, 10, 10)];
  for (let i = 0; i < 140; i += 1) nodes.push(rect(`p${i}`, i * 10, 0, 10, 5000, true));
  const input = { mode: 'compact', gap: 0, nodes };
  const result = arrangeGraph(input);
  verify(input, result);
  assert.deepEqual(new Map(result.positions).get('moving'), { x: 1400, y: 0 });
});

test('group padding can extend beyond coordinate limits while member coordinates remain valid', () => {
  const input = { nodes: [rect('a', -100000, -100000)], groups: [group('g', 'a')] };
  const result = arrangeGraph(input);
  verify(input, result);
  assert.equal(result.movedCount, 0);
});

test('invalid node types, duplicate IDs, dimensions, flags and coordinates are rejected', () => {
  const cases = [null, {}, [null], [rect(undefined)], [rect(NaN)], [rect({})], [rect('a'), rect('a')]];
  for (const nodes of cases) assert.throws(() => buildLayoutBlocks(nodes));
  for (const name of ['x', 'y', 'width', 'height']) {
    for (const value of [NaN, Infinity, -Infinity, '1', undefined, null]) {
      assert.throws(() => arrangeGraph({ nodes: [{ ...rect('a'), [name]: value }] }));
    }
  }
  for (const name of ['width', 'height']) {
    for (const value of [0, -1]) assert.throws(() => buildLayoutBlocks([{ ...rect('a'), [name]: value }]));
  }
  for (const name of ['x', 'y']) {
    for (const value of [-100001, 100001]) assert.throws(() => buildLayoutBlocks([{ ...rect('a'), [name]: value }]));
  }
  for (const pinned of ['true', 1, null]) assert.throws(() => buildLayoutBlocks([{ ...rect('a'), pinned }]));
});

test('invalid group references, scope, edge endpoints and options fail even for no-op layouts', () => {
  const nodes = [rect('a')];
  for (const groups of [null, {}, [null], [{}], [group('g', 'missing')], [group('g'), group('g')], [{ id: 'g', nodeIds: {} }], [{ ...group('g', 'a'), collapsed: 1 }]]) {
    assert.throws(() => buildLayoutBlocks(nodes, groups));
  }
  for (const scopeIds of ['a', {}, ['missing'], [NaN]]) assert.throws(() => buildLayoutBlocks(nodes, [], scopeIds));
  for (const edges of [null, {}, [null], [{}], [edge('a', 'missing')], [edge([], 'a')]]) {
    assert.throws(() => arrangeGraph({ nodes, edges, scopeIds: [] }));
  }
  for (const mode of ['grid', null, 'constructor']) assert.throws(() => arrangeGraph({ nodes, mode }));
  for (const direction of ['x', null, 'lr', 'constructor']) assert.throws(() => arrangeGraph({ nodes, direction }));
  for (const gap of [NaN, Infinity, -1, '48', null]) assert.throws(() => arrangeGraph({ nodes, gap }));
  for (const input of [null, [], 1, undefined, {}]) assert.throws(() => arrangeGraph(input));
});

test('arithmetic overflow is rejected, never repaired with scale or fallback geometry', () => {
  const huge = Number.MAX_VALUE;
  for (const mode of modes) {
    assert.throws(() => arrangeGraph({ mode, nodes: [rect('a', 0, 0, huge), rect('b', 0, 0, huge)], gap: huge }));
  }
});

test('outline helper: local origins, input-order roots/siblings and per-tree size-aware columns', () => {
  const nodes = freeze([rect('z', 500, 300, 100, 40), rect('y', 900, 700, 400, 160), rect('x', 30, 70, 300, 32), rect('b', -10, -50, 200, 80), rect('a', 15, 90, 50, 16)]);
  const edges = freeze([childEdge('b', 'a'), childEdge('y', 'x'), childEdge('z', 'y')]);
  const expected = new Map([
    ['z', { x: 0, y: 0 }], ['y', { x: 280, y: 128 }], ['x', { x: 744, y: 336 }],
    ['b', { x: 0, y: 528 }], ['a', { x: 280, y: 656 }],
  ]);
  assert.deepEqual(outlineLayout(nodes, edges, freeze({ gap: 48, direction: 'LR' })), expected);
  assert.deepEqual(outlineLayout(nodes.map((node) => ({ ...node, x: -node.x, y: -node.y })), edges), expected);
  assert.deepEqual(outlineLayout(nodes, [...edges, edges[0]]), expected);
  assert.deepEqual(outlineLayout([], []), new Map());
  assert.deepEqual(outlineLayout([rect(0)], []), new Map([[0, { x: 0, y: 0 }]]));
});

test('outline helper: isolated roots and unsorted input still form a preorder forest', () => {
  const nodes = [rect('child'), rect('z-root'), rect('isolated'), rect('a-root'), rect('sibling')];
  const result = outlineLayout(nodes, [childEdge('z-root', 'sibling'), childEdge('z-root', 'child')]);
  assert.deepEqual([...result.keys()], nodes.map((node) => node.id));
  assert.ok(result.get('z-root').y < result.get('child').y);
  assert.ok(result.get('child').y < result.get('sibling').y);
  assert.ok(result.get('sibling').y < result.get('isolated').y);
  assert.ok(result.get('isolated').y < result.get('a-root').y);
  assert.equal(result.get('isolated').x, 0);
  assert.equal(result.get('a-root').x, 0);
});

function acceptedOutline() {
  // Same parent/depth sequence as graphs-integration.spec.ts, deliberately not ID-sorted.
  const parents = [null, 0, 1, 0, 3, 4, 4, 3, 3, 0, null, 10, 10];
  const nodes = parents.map((_, i) => rect(`uuid-${String(20 - i).padStart(2, '0')}`, 0, 0, 130 + i * 17 % 260, 80 + i * 13 % 140));
  const edges = parents.flatMap((parent, i) => parent === null ? [] : [childEdge(nodes[parent].id, nodes[i].id)]);
  return { nodes, edges, parents };
}

for (const direction of ['LR', 'RL', 'TB', 'BT']) {
  for (const gap of [0, 48, 170]) {
    test(`outline ${direction}, gap ${gap}: wizard -> radial -> compact -> hierarchy preserves the entire forest`, () => {
      const fixture = acceptedOutline();
      const local = outlineLayout(fixture.nodes, fixture.edges, { gap, direction });
      const outlineNodes = fixture.nodes.map((node) => ({ ...node, x: local.get(node.id).x + 2000, y: local.get(node.id).y + 1200 }));
      const general = [rect('general-a', -500, -100, 120, 50), rect('general-b', -700, 300, 420, 180), rect('general-c', -900, 600, 100, 120)];
      const input = {
        nodes: [...general, ...outlineNodes],
        edges: [...fixture.edges].reverse().concat([edge('general-a', 'general-b'), edge('general-b', 'general-c'), edge('general-c', 'general-a')]),
        gap, direction,
      };
      const original = JSON.stringify(input);
      let current = input;
      for (const mode of ['hierarchy', 'radial', 'compact', 'hierarchy']) {
        const result = arrangeGraph({ ...current, mode });
        verify(current, result);
        if (mode === 'hierarchy') {
          const points = new Map(result.positions);
          const anchor = points.get(outlineNodes[0].id);
          const initial = local.get(outlineNodes[0].id);
          for (const node of outlineNodes) {
            close(points.get(node.id).x - anchor.x, local.get(node.id).x - initial.x);
            close(points.get(node.id).y - anchor.y, local.get(node.id).y - initial.y);
          }
          const rowAxis = direction === 'LR' || direction === 'RL' ? 'y' : 'x';
          for (let i = 1; i < outlineNodes.length; i += 1) {
            assert.ok(points.get(outlineNodes[i].id)[rowAxis] > points.get(outlineNodes[i - 1].id)[rowAxis]);
          }
        }
        current = { ...input, nodes: placed(current, result) };
      }
      assert.equal(JSON.stringify(input), original);
    });
  }
}

test('outline helper: axis projection reflects actual rectangle edges, not just origins', () => {
  const nodes = [rect('root', 0, 0, 310, 100), rect('leaf', 0, 0, 80, 250)];
  const edges = [childEdge('root', 'leaf')];
  for (const [forward, reverse, axis, size] of [['LR', 'RL', 'x', 'width'], ['TB', 'BT', 'y', 'height']]) {
    const a = outlineLayout(nodes, edges, { direction: forward });
    const b = outlineLayout(nodes, edges, { direction: reverse });
    const extent = Math.max(...nodes.map((node) => a.get(node.id)[axis] + node[size]));
    for (const node of nodes) close(b.get(node.id)[axis], extent - a.get(node.id)[axis] - node[size]);
    assert.ok(b.get('root')[axis] >= b.get('leaf')[axis] + nodes[1][size] + 48);
  }
});

test('outline hierarchy: pins, actual groups and partial scope take the unchanged Dagre protection path', () => {
  for (const protection of ['pin', 'group', 'scope']) {
    const input = acceptedOutline();
    if (protection === 'pin') input.nodes[4].pinned = true;
    if (protection === 'group') input.groups = [group('rigid', input.nodes[1].id, input.nodes[2].id)];
    if (protection === 'scope') input.scopeIds = input.nodes.slice(0, 5).map((node) => node.id);
    const result = arrangeGraph(input);
    verify(input, result);
    assert.deepEqual(result, arrangeGraph({ ...input, edges: input.edges.map(({ source, target }) => edge(source, target)) }));
  }
});

test('outline hierarchy: cycles, multiple parents, self-loops and mixed-label components stay on Dagre', () => {
  const nodes = [rect('z'), rect('m'), rect('a')];
  const fixtures = [
    [childEdge('z', 'm'), childEdge('m', 'a'), childEdge('a', 'z')],
    [childEdge('z', 'a'), childEdge('m', 'a')],
    [childEdge('z', 'm'), childEdge('m', 'a'), childEdge('a', 'a')],
    [childEdge('z', 'm'), edge('m', 'a')],
  ];
  for (const edges of fixtures) {
    const input = { nodes, edges };
    const result = arrangeGraph(input);
    verify(input, result);
    assert.deepEqual(result, arrangeGraph({ nodes, edges: edges.map(({ source, target }) => edge(source, target)) }));
  }
});

test('outline hierarchy: disconnected invalid child components do not reorder valid forests', () => {
  const input = acceptedOutline();
  input.nodes.push(rect('cycle-a'), rect('cycle-b'));
  input.edges.push(childEdge('cycle-a', 'cycle-b'), childEdge('cycle-b', 'cycle-a'));
  const local = outlineLayout(input.nodes.slice(0, 13), input.edges.slice(0, -2));
  const result = arrangeGraph(input);
  verify(input, result);
  const points = new Map(result.positions);
  const anchor = points.get(input.nodes[0].id);
  for (const node of input.nodes.slice(0, 13)) {
    close(points.get(node.id).x - anchor.x, local.get(node.id).x);
    close(points.get(node.id).y - anchor.y, local.get(node.id).y);
  }
});

test('outline hierarchy: >100 rows, fractional dimensions, deterministic and immutable', () => {
  const nodes = Array.from({ length: 160 }, (_, i) => rect(`n${160 - i}`, -1500, -1800, 120.1 + i % 7 * 13.3, 70.25 + i % 11 * 5.75));
  const edges = nodes.slice(1).map((node, i) => childEdge(nodes[Math.floor(i / 3)].id, node.id));
  const input = freeze({ nodes, edges, gap: 37.5 });
  const before = JSON.stringify(input);
  const local = outlineLayout(nodes, edges, { gap: input.gap });
  const first = arrangeGraph(input);
  verify(input, first);
  assert.deepEqual(arrangeGraph(input), first);
  assert.equal(JSON.stringify(input), before);
  const points = new Map(first.positions);
  const anchor = points.get(nodes[0].id);
  for (const node of nodes) {
    close(points.get(node.id).x - anchor.x, local.get(node.id).x);
    close(points.get(node.id).y - anchor.y, local.get(node.id).y);
  }
});

test('outline helper: malformed forests, invalid options and nonfinite geometry throw', () => {
  const nodes = [rect('a'), rect('b'), rect('c')];
  for (const edges of [null, {}, [null], [{}], [edge('a', 'missing')], [edge('a', 'a')], [edge('a', 'b'), edge('b', 'a')], [edge('a', 'c'), edge('b', 'c')]]) {
    assert.throws(() => outlineLayout(nodes, edges));
  }
  for (const options of [null, [], { gap: NaN }, { gap: Infinity }, { gap: -1 }, { gap: '48' }, { direction: 'up' }]) {
    assert.throws(() => outlineLayout(nodes, [], options));
  }
  for (const invalid of [[rect('a', NaN)], [rect('a', 0, 0, 0)], [rect('a'), rect('a')]]) {
    assert.throws(() => outlineLayout(invalid));
  }
  assert.throws(() => outlineLayout(nodes, [edge('a', 'b')], { gap: Number.MAX_VALUE }));
});

test('hierarchy fit: 1500-node outline uses the full coordinate range with a single translation', () => {
  const nodes = Array.from({ length: 1500 }, (_, i) => rect(`n${1500 - i}`, 0, 0, 80, 40));
  const edges = nodes.slice(1).map((node, i) => childEdge(nodes[Math.floor(i / 2)].id, node.id));
  const input = freeze({ nodes, edges, mode: 'hierarchy' });
  const before = JSON.stringify(input);
  const local = outlineLayout(nodes, edges);
  const result = arrangeGraph(input);
  verify(input, result);
  const points = new Map(result.positions);
  const ys = result.positions.map(([, point]) => point.y);
  assert.equal(Math.max(...ys) - Math.min(...ys), 1499 * 128);
  assert.equal(Math.max(...ys), 100000);
  assert.equal(Math.min(...ys), 100000 - 1499 * 128);
  for (const node of nodes) {
    close(points.get(node.id).x, local.get(node.id).x);
    close(points.get(node.id).y, local.get(node.id).y + 100000 - 1499 * 128);
  }
  assert.equal(JSON.stringify(input), before);
  assert.throws(() => arrangeGraph({ ...input, gap: 170 }), /200000/);
  assert.equal(JSON.stringify(input), before);
});

test('hierarchy fit: the 1023-node integration fixture translates intact from its original grid', () => {
  const nodes = Array.from({ length: 1023 }, (_, i) => rect(`tree-node-${i}`, (i % 32) * 300, Math.floor(i / 32) * 140, 224, 108));
  const edges = nodes.slice(1).map((node, i) => ({ id: `tree-edge-${i}`, ...childEdge(nodes[Math.floor(i / 2)].id, node.id) }));
  const input = freeze({ nodes, edges, mode: 'hierarchy', gap: 48, direction: 'LR' });
  const before = JSON.stringify(input);
  const local = outlineLayout(nodes, edges, { gap: input.gap, direction: input.direction });
  const result = arrangeGraph(input);
  verify(input, result);
  const points = new Map(result.positions);
  const ys = result.positions.map(([, point]) => point.y);
  const expectedSpan = 1022 * (108 + 48);
  assert.ok(expectedSpan > 100000 && expectedSpan < 200000);
  assert.equal(Math.max(...ys) - Math.min(...ys), expectedSpan);
  assert.equal(Math.max(...ys), 100000);
  assert.equal(Math.min(...ys), 100000 - expectedSpan);
  for (const node of nodes) {
    close(points.get(node.id).x, local.get(node.id).x);
    close(points.get(node.id).y, local.get(node.id).y + 100000 - expectedSpan);
  }
  assert.deepEqual(arrangeGraph({ ...input, nodes: placed(input, result) }).positions, result.positions);
  assert.equal(JSON.stringify(input), before);
});

test('hierarchy fit: an exact 200000 origin span fits, larger spans fail without compression', () => {
  const nodes = ['a', 'b', 'c'].map((id) => rect(id, 0, 0, 100000, 10));
  const input = { nodes, edges: [edge('a', 'b'), edge('b', 'c')], gap: 0 };
  const result = arrangeGraph(input);
  verify(input, result);
  assert.deepEqual(result.positions.map(([, point]) => point.x), [-100000, 0, 100000]);
  assert.throws(() => arrangeGraph({ ...input, gap: 1 }), /200000/);
});

test('hierarchy fit: direction-aware proposals keep their relative geometry at the upper boundary', () => {
  for (const direction of ['LR', 'RL', 'TB', 'BT']) {
    const nodes = [rect('root', 0, 0, 310, 120), rect('child', 0, 0, 75, 250), rect('leaf', 0, 0, 220, 70)];
    const edges = [edge('root', 'child'), edge('child', 'leaf')];
    const local = new Map(arrangeGraph({ nodes, edges, direction }).positions);
    const input = { nodes: nodes.map((node) => ({ ...node, x: 99999, y: 99999 })), edges, direction };
    const result = arrangeGraph(input);
    verify(input, result);
    const points = new Map(result.positions);
    for (const node of nodes) {
      for (const axis of ['x', 'y']) {
        close(points.get(node.id)[axis] - points.get('root')[axis], local.get(node.id)[axis] - local.get('root')[axis]);
      }
    }
  }
});

test('fit counts rigid member origins, allows padding outside bounds and leaves fixed obstacles unchanged', () => {
  for (const origin of [-100000, 99900]) {
    const input = {
      mode: 'compact', gap: 48,
      nodes: [rect('a', origin, origin), rect('b', origin + 40, origin + 50), rect('c', origin + 90, origin + 90), rect('pin', 500, 500, 120, 80, true)],
      groups: [group('rigid', 'a', 'b')],
    };
    const result = arrangeGraph(input);
    verify(input, result);
    const points = new Map(result.positions);
    assert.equal(points.get('b').x - points.get('a').x, 40);
    assert.equal(points.get('b').y - points.get('a').y, 50);
    assert.deepEqual(points.get('pin'), { x: 500, y: 500 });
    if (origin < 0) assert.equal(Math.min(...result.positions.map(([, point]) => point.y)), -100000);
    else assert.equal(Math.max(...result.positions.map(([, point]) => point.x)), 100000);
  }
});

test('worker protocol: matching requestId, cloneable results, plain errors, recovery after failure', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'self');
  const messages = [];
  const worker = { postMessage: (message) => messages.push(structuredClone(message)) };
  Object.defineProperty(globalThis, 'self', { configurable: true, writable: true, value: worker });
  try {
    await import('../public/graph-workspace/layout-worker.mjs');
    worker.onmessage({ data: { requestId: 'bad', input: { nodes: [rect('a', NaN)] } } });
    assert.equal(messages[0].requestId, 'bad');
    assert.equal(typeof messages[0].error, 'string');
    assert.deepEqual(Object.keys(messages[0]).sort(), ['error', 'requestId']);
    const input = { nodes: [rect('a'), rect('b')], edges: [edge('a', 'b')] };
    worker.onmessage({ data: { requestId: 0, input } });
    assert.deepEqual(messages[1], { requestId: 0, result: arrangeGraph(input) });
    verify(input, messages[1].result);
    worker.onmessage({ data: null });
    assert.equal(typeof messages[2].error, 'string');
    assert.ok(!messages[2].error.includes('\n'));
  } finally {
    if (previous) Object.defineProperty(globalThis, 'self', previous);
    else delete globalThis.self;
  }
});
