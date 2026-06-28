import type { RefShape } from './types';

/** Per-source styling for reference markers (mirrors the science plotter's distinct glyphs). */
export function referenceColor(source: string): string {
  const s = source.toLowerCase();
  if (s.includes('f-net') || s.includes('fnet')) return '#d4501e';
  if (s.includes('gcmt')) return '#6a3d9a';
  if (s.includes('usgs')) return '#1f78b4';
  if (s.includes('synth')) return '#8a8f99';
  return '#4d5564';
}

function starPoints(cx: number, cy: number, r: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 === 0 ? r : r * 0.42;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    pts.push(`${(cx + rr * Math.cos(a)).toFixed(4)},${(cy + rr * Math.sin(a)).toFixed(4)}`);
  }
  return pts.join(' ');
}

interface Props {
  shape: RefShape;
  cx: number;
  cy: number;
  r: number;
  color: string;
  stroke?: string;
  strokeWidth?: number;
}

/** An SVG reference marker of the given shape, centred at (cx, cy) with radius r. */
export function MarkerShape({
  shape,
  cx,
  cy,
  r,
  color,
  stroke = '#ffffff',
  strokeWidth = 0,
}: Props) {
  const common = { fill: color, stroke, strokeWidth };
  switch (shape) {
    case 'square':
      return <rect x={cx - r} y={cy - r} width={2 * r} height={2 * r} {...common} />;
    case 'triangle':
      return (
        <polygon
          points={`${cx},${cy - r} ${cx + r},${cy + r * 0.85} ${cx - r},${cy + r * 0.85}`}
          {...common}
        />
      );
    case 'diamond':
      return (
        <polygon
          points={`${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`}
          {...common}
        />
      );
    case 'star':
      return <polygon points={starPoints(cx, cy, r)} {...common} />;
    default:
      return <circle cx={cx} cy={cy} r={r} {...common} />;
  }
}
