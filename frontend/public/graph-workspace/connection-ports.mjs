export const PORT_IDS = ['n', 'e', 's', 'w'].flatMap((side) =>
  Array.from({ length: 5 }, (_, index) => `${side}:${index}`));

export function portPosition(id, box) {
  const [side, index] = id.split(':');
  const fraction = (Number(index) + 0.5) / 5;
  const { x, y, width, height } = box;
  if (side === 'n') return { x: x + width * fraction, y, nx: 0, ny: -1 };
  if (side === 's') return { x: x + width * fraction, y: y + height, nx: 0, ny: 1 };
  if (side === 'w') return { x, y: y + height * fraction, nx: -1, ny: 0 };
  return { x: x + width, y: y + height * fraction, nx: 1, ny: 0 };
}
