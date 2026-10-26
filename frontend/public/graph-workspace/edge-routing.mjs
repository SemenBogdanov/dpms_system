const COORDINATE_LIMIT = 1_000_000;
const MAX_OFFSET = 256;
const MAX_HANDLE = 64;
const EPSILON = 1e-9;

const bounded = (value, limit = COORDINATE_LIMIT) => Number.isFinite(value)
  ? Math.max(-limit, Math.min(limit, value)) : 0;
const position = (point) => ({ x: bounded(point?.x), y: bounded(point?.y) });
const distance = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
const same = (a, b) => a.x === b.x && a.y === b.y;
const mix = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
const move = (point, direction, length) => ({ x: point.x + direction.x * length, y: point.y + direction.y * length });

function unit(x, y, fallback = { x: 1, y: 0 }) {
  const scale = Math.max(Math.abs(x), Math.abs(y));
  if (!Number.isFinite(scale) || scale === 0) return fallback;
  const length = Math.hypot(x / scale, y / scale);
  return { x: x / scale / length, y: y / scale / length };
}

function onSegment(segment, t) {
  if (!segment.c1) return mix(segment.from, segment.to, t);
  const a = mix(segment.from, segment.c1, t);
  const b = mix(segment.c1, segment.c2, t);
  const c = mix(segment.c2, segment.to, t);
  return mix(mix(a, b, t), mix(b, c, t), t);
}

function pathMidpoint(segments) {
  const samples = [];
  let length = 0;
  for (const segment of segments) {
    const steps = segment.c1 ? 12 : 1;
    let previous = segment.from;
    for (let step = 1; step <= steps; step += 1) {
      const point = onSegment(segment, step / steps);
      const size = distance(previous, point);
      samples.push({ segment, fromT: (step - 1) / steps, toT: step / steps, start: length, size });
      length += size;
      previous = point;
    }
  }
  const halfway = length / 2;
  const sample = samples.find((item) => item.size > 0 && item.start + item.size >= halfway);
  if (!sample) return segments[0].from;
  return onSegment(sample.segment, sample.fromT + (sample.toT - sample.fromT) * (halfway - sample.start) / sample.size);
}

/**
 * Pure attachment routing. Normals point out of each node; no node bounds are used.
 * points is returned unchanged (including identity), never offset or mutated.
 * Signed reverseOffset uses a canonical, endpoint-order-independent perpendicular.
 * mid lies on the path at approximately half its arc length (sampled for cubics).
 * Render coordinates, offsets and cubic handles are bounded; input data is untouched.
 * The SVG marker's reference point must be its triangle tip to land exactly at end.
 */
export function routeEdge(start, end, routing = 'curve', points = [], reverseOffset = 0) {
  const source = position(start);
  const target = position(end);
  const chord = unit(target.x - source.x, target.y - source.y);
  const sourceNormal = unit(start?.nx, start?.ny, chord);
  const targetNormal = unit(end?.nx, end?.ny, { x: -chord.x, y: -chord.y });
  const stubLength = Math.max(12, Math.min(32, distance(source, target) * 0.12));
  const sourceStub = move(source, sourceNormal, stubLength);
  const targetStub = move(target, targetNormal, stubLength);

  // Reversing endpoints must not reverse the meaning of the caller's +/- lanes.
  const axis = distance(source, target) > EPSILON ? chord : sourceNormal;
  const sign = axis.x < 0 || (axis.x === 0 && axis.y < 0) ? -1 : 1;
  const canonical = { x: axis.x * sign, y: axis.y * sign };
  const perpendicular = { x: -canonical.y, y: canonical.x };
  const offset = bounded(reverseOffset, MAX_OFFSET);
  const configuredPoints = Array.isArray(points) ? points : [];
  let interior = configuredPoints.map((point) => move(position(point), perpendicular, offset));
  if (!interior.length) {
    if (distance(sourceStub, targetStub) < EPSILON) {
      const outside = move(sourceStub, perpendicular, offset || 32);
      interior = [move(outside, canonical, -24), move(outside, canonical, 24)];
    } else if (offset) {
      interior = [1 / 3, 2 / 3].map((t) => move(mix(sourceStub, targetStub, t), perpendicular, offset));
    } else if (routing === 'orthogonal') {
      interior = [mix(sourceStub, targetStub, 0.5)];
    }
  }

  const knots = [sourceStub, ...interior, targetStub].filter((point, index, all) => !index || !same(point, all[index - 1]));
  if (knots.length === 1) knots.push(move(sourceStub, perpendicular, 32), targetStub);
  const segments = [{ from: source, to: sourceStub }];
  const lineTo = (point) => {
    const previous = segments.at(-1).to;
    if (!same(previous, point)) segments.push({ from: previous, to: point });
  };

  if (routing === 'orthogonal') {
    for (let index = 1; index < knots.length; index += 1) {
      const previous = segments.at(-1).to;
      const next = knots[index];
      const horizontalFirst = index === knots.length - 1
        ? Math.abs(targetNormal.y) > Math.abs(targetNormal.x)
        : Math.abs(sourceNormal.x) >= Math.abs(sourceNormal.y);
      lineTo(horizontalFirst ? { x: next.x, y: previous.y } : { x: previous.x, y: next.y });
      lineTo(next);
    }
  } else if (routing === 'straight' || routing === 'polyline') {
    knots.slice(1).forEach(lineTo);
  } else {
    // Shared, bounded knot tangents give C1-continuous cubics through editable points.
    const tangents = knots.map((point, index) => {
      if (!index) return move({ x: 0, y: 0 }, sourceNormal, Math.min(MAX_HANDLE, distance(point, knots[1]) / 3));
      if (index === knots.length - 1) return move({ x: 0, y: 0 }, targetNormal, -Math.min(MAX_HANDLE, distance(knots[index - 1], point) / 3));
      const previous = knots[index - 1];
      const next = knots[index + 1];
      const direction = unit(next.x - previous.x, next.y - previous.y, unit(next.x - point.x, next.y - point.y));
      return move({ x: 0, y: 0 }, direction, Math.min(MAX_HANDLE, distance(previous, point) / 3, distance(point, next) / 3));
    });
    for (let index = 1; index < knots.length; index += 1) {
      segments.push({
        from: knots[index - 1],
        c1: move(knots[index - 1], tangents[index - 1], 1),
        c2: move(knots[index], tangents[index], -1),
        to: knots[index],
      });
    }
  }
  lineTo(target);

  const pair = (point) => `${point.x} ${point.y}`;
  const path = `M ${pair(source)} ${segments.map((segment) => segment.c1
    ? `C ${pair(segment.c1)} ${pair(segment.c2)} ${pair(segment.to)}`
    : `L ${pair(segment.to)}`).join(' ')}`;
  return { path, mid: pathMidpoint(segments), points: configuredPoints };
}
