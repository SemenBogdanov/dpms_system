import assert from 'node:assert/strict';
import test from 'node:test';
import { routeEdge } from '../public/graph-workspace/edge-routing.mjs';

const normals = {
  n: { nx: 0, ny: -1 },
  e: { nx: 1, ny: 0 },
  s: { nx: 0, ny: 1 },
  w: { nx: -1, ny: 0 },
};
const modes = ['curve', 'orthogonal', 'straight'];
const points = Object.freeze([Object.freeze({ x: 70, y: 190 }), Object.freeze({ x: 210, y: -70 })]);
const near = (actual, expected, message = '') => assert.ok(Math.abs(actual - expected) < 1e-7, `${message}: ${actual} != ${expected}`);
const vector = (from, to) => ({ x: to.x - from.x, y: to.y - from.y });

function direction(actual, expected) {
  const length = Math.hypot(actual.x, actual.y);
  const expectedLength = Math.hypot(expected.x, expected.y);
  assert.ok(length > 0, 'A terminal tangent must not be zero');
  near(actual.x / length, expected.x / expectedLength, 'Tangent x');
  near(actual.y / length, expected.y / expectedLength, 'Tangent y');
}

function parsePath(path) {
  const tokens = path.trim().split(/\s+/);
  const segments = [];
  let previous;
  let start;
  for (let index = 0; index < tokens.length;) {
    const command = tokens[index++];
    assert.ok(['M', 'L', 'C'].includes(command), `Unexpected path command: ${command}`);
    const values = tokens.slice(index, index + (command === 'C' ? 6 : 2)).map(Number);
    assert.equal(values.length, command === 'C' ? 6 : 2);
    assert.ok(values.every((value) => Number.isFinite(value) && Math.abs(value) < 1_001_000), 'Bounded, finite SVG coordinates');
    index += values.length;
    const to = { x: values.at(-2), y: values.at(-1) };
    if (command === 'M') {
      assert.equal(start, undefined, 'Only one SVG subpath');
      start = to;
    } else {
      assert.ok(previous);
      segments.push({
        from: previous, to,
        ...(command === 'C' ? { c1: { x: values[0], y: values[1] }, c2: { x: values[2], y: values[3] } } : {}),
      });
    }
    previous = to;
  }
  assert.ok(segments.length >= 2);
  return { start, segments };
}

function checkGeometry(result, start, end, mode, configuredPoints, diagonal = false) {
  const { start: actualStart, segments } = parsePath(result.path);
  assert.deepEqual(actualStart, { x: start.x, y: start.y });
  assert.deepEqual(segments.at(-1).to, { x: end.x, y: end.y });
  assert.strictEqual(result.points, configuredPoints, 'Editing handles must keep the original array and coordinates');
  assert.ok(Number.isFinite(result.mid.x) && Number.isFinite(result.mid.y));
  assert.ok(Math.abs(result.mid.x) < 1_001_000 && Math.abs(result.mid.y) < 1_001_000);
  const first = segments[0];
  const last = segments.at(-1);
  assert.equal(first.c1, undefined, 'Source has an explicit outward stub');
  assert.equal(last.c1, undefined, 'Target has an explicit outside stub');
  direction(vector(first.from, first.to), { x: start.nx, y: start.ny });
  direction(vector(last.from, last.to), { x: -end.nx, y: -end.ny });
  if (mode === 'orthogonal') {
    const axial = diagonal ? segments.slice(1, -1) : segments;
    for (const segment of axial) {
      assert.equal(segment.c1, undefined);
      assert.ok(segment.from.x === segment.to.x || segment.from.y === segment.to.y, 'Orthogonal segment is axis aligned');
    }
  }
  if (mode === 'curve') {
    const curves = segments.filter((segment) => segment.c1);
    assert.ok(curves.length > 0, 'Editable points must not turn a curve into a polyline');
    direction(vector(curves[0].from, curves[0].c1), { x: start.nx, y: start.ny });
    direction(vector(curves.at(-1).c2, curves.at(-1).to), { x: -end.nx, y: -end.ny });
    for (let index = 1; index < curves.length; index += 1) {
      const incoming = vector(curves[index - 1].c2, curves[index - 1].to);
      const outgoing = vector(curves[index].from, curves[index].c1);
      near(incoming.x, outgoing.x, 'C1 continuity x');
      near(incoming.y, outgoing.y, 'C1 continuity y');
    }
    for (const segment of curves) {
      assert.ok(Math.hypot(...Object.values(vector(segment.from, segment.c1))) <= 64 + 1e-7);
      assert.ok(Math.hypot(...Object.values(vector(segment.to, segment.c2))) <= 64 + 1e-7);
    }
  }
  return segments;
}

for (const mode of modes) {
  for (const [side, normal] of Object.entries(normals)) {
    for (const configuredPoints of [Object.freeze([]), Object.freeze([points[0]]), points]) {
      test(`${mode}: target ${side}, ${configuredPoints.length} configured points, every source side and offset`, () => {
        const end = Object.freeze({ x: 300, y: 90, ...normal });
        for (const sourceNormal of Object.values(normals)) {
          const start = Object.freeze({ x: -40, y: 20, ...sourceNormal });
          const base = routeEdge(start, end, mode, configuredPoints);
          const baseSegments = checkGeometry(base, start, end, mode, configuredPoints);
          for (const offset of [-18, 18]) {
            const shifted = routeEdge(start, end, mode, configuredPoints, offset);
            const shiftedSegments = checkGeometry(shifted, start, end, mode, configuredPoints);
            assert.deepEqual(shiftedSegments[0], baseSegments[0], 'Offset must not move the source stub');
            assert.deepEqual(shiftedSegments.at(-1), baseSegments.at(-1), 'Offset must not move the target stub');
            assert.notEqual(shifted.path, base.path, 'Offset must change the interior');
          }
          for (const point of configuredPoints) {
            assert.ok(baseSegments.some((segment) => segment.to.x === point.x && segment.to.y === point.y), 'Unshifted route passes through each editable point');
          }
          assert.deepEqual(routeEdge(start, end, mode, configuredPoints), base, 'Routing is deterministic');
        }
      });
    }
  }

  test(`${mode}: coincident, aligned, short, repeated and collinear geometry remains finite`, () => {
    for (const endPosition of [{ x: 0, y: 0 }, { x: 0, y: 240 }, { x: 240, y: 0 }, { x: 1e-8, y: 0 }, { x: 24, y: 0 }]) {
      for (const sourceNormal of Object.values(normals)) {
        for (const targetNormal of Object.values(normals)) {
          const start = { x: 0, y: 0, ...sourceNormal };
          const end = { ...endPosition, ...targetNormal };
          for (const configuredPoints of [[], [{ x: 0, y: 0 }, { x: 0, y: 0 }], [{ x: 12, y: 0 }, { x: 12, y: 0 }], [{ x: 60, y: 0 }, { x: 120, y: 0 }]]) {
            for (const offset of [0, -18, 18]) {
              checkGeometry(routeEdge(start, end, mode, configuredPoints, offset), start, end, mode, configuredPoints);
            }
          }
        }
      }
    }
  });

  test(`${mode}: opposite signed reverse edges use opposite lanes`, () => {
    const start = { x: 0, y: 0, ...normals.e };
    const end = { x: 300, y: 0, ...normals.w };
    for (const configuredPoints of [[], [{ x: 100, y: 0 }, { x: 200, y: 0 }]]) {
      const reversedPoints = [...configuredPoints].reverse();
      const forward = routeEdge(start, end, mode, configuredPoints, 18);
      const reverse = routeEdge(end, start, mode, reversedPoints, -18);
      checkGeometry(forward, start, end, mode, configuredPoints);
      checkGeometry(reverse, end, start, mode, reversedPoints);
      assert.ok(forward.mid.y > 0);
      assert.ok(reverse.mid.y < 0);
      near(forward.mid.x, reverse.mid.x);
      near(forward.mid.y, -reverse.mid.y);
    }
  });

  test(`${mode}: circle normals keep radial terminals`, () => {
    for (const angle of [Math.PI / 4, Math.PI * 3 / 4, Math.PI * 5 / 4, Math.PI * 7 / 4]) {
      const start = { x: -100, y: 10, nx: Math.cos(angle), ny: Math.sin(angle) };
      const end = { x: 150, y: 180, nx: Math.sin(angle), ny: -Math.cos(angle) };
      for (const configuredPoints of [[], points]) {
        checkGeometry(routeEdge(start, end, mode, configuredPoints, 18), start, end, mode, configuredPoints, true);
      }
    }
  });

  test(`${mode}: extreme and malformed inputs cannot produce NaN or runaway SVG coordinates`, () => {
    for (const magnitude of [100_000, Number.MAX_VALUE, Infinity, NaN]) {
      const result = routeEdge(
        { x: magnitude, y: -magnitude, nx: magnitude, ny: magnitude },
        { x: -magnitude, y: magnitude, nx: 0, ny: 0 },
        mode, [{ x: magnitude, y: -magnitude }, null, { x: NaN, y: Infinity }], magnitude,
      );
      parsePath(result.path);
      assert.ok(Number.isFinite(result.mid.x) && Number.isFinite(result.mid.y));
    }
    parsePath(routeEdge(null, undefined, mode, null, NaN).path);
  });
}

test('default curve and polyline alias keep the public API', () => {
  const start = { x: 0, y: 0, ...normals.e };
  const end = { x: 300, y: 0, ...normals.w };
  assert.deepEqual(routeEdge(start, end), routeEdge(start, end, 'curve', [], 0));
  assert.deepEqual(routeEdge(start, end, 'polyline', points), routeEdge(start, end, 'straight', points));
  assert.deepEqual(Object.keys(routeEdge(start, end)), ['path', 'mid', 'points']);
});

test('mid is centered on an aligned route, not an editable control handle', () => {
  for (const mode of modes) {
    const start = { x: 0, y: 0, ...normals.e };
    const end = { x: 300, y: 0, ...normals.w };
    const result = routeEdge(start, end, mode, [{ x: 45, y: 0 }, { x: 70, y: 0 }]);
    if (mode === 'curve') assert.ok(Math.abs(result.mid.x - 150) < 0.25, 'Sampled arc midpoint is within a quarter pixel');
    else near(result.mid.x, 150);
    near(result.mid.y, 0);
  }
});
