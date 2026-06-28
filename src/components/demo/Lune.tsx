import { useMemo } from 'react';

/**
 * Source-type lune rendered client-side (SVG) from a (gamma, delta) posterior
 * ensemble — Hammer equal-area projection, same as the research code. Far smaller
 * than a PNG and themeable / interactive.
 */
interface Props {
  gamma: number[];
  delta: number[];
  mean: { gamma: number; delta: number };
  reference: { gamma: number; delta: number };
  accent?: string;
}

function hammer(gammaDeg: number, deltaDeg: number): [number, number] {
  const lam = (gammaDeg * Math.PI) / 180;
  const phi = (deltaDeg * Math.PI) / 180;
  const d = Math.sqrt(1 + Math.cos(phi) * Math.cos(lam / 2));
  const x = (2 * Math.SQRT2 * Math.cos(phi) * Math.sin(lam / 2)) / d;
  const y = (Math.SQRT2 * Math.sin(phi)) / d;
  return [x, -y]; // SVG y points down
}

function polyline(pts: [number, number][]): string {
  return pts.map((p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`).join(' ');
}

const MERIDIANS = [-30, -15, 0, 15, 30];
const PARALLELS = [-90, -60, -30, 0, 30, 60, 90];
const REFS: {
  label: string;
  g: number;
  d: number;
  anchor: 'middle' | 'start' | 'end';
  dy: number;
}[] = [
  { label: 'DC', g: 0, d: 0, anchor: 'middle', dy: -0.06 },
  { label: '+ISO', g: 0, d: 90, anchor: 'middle', dy: -0.06 },
  { label: '−ISO', g: 0, d: -90, anchor: 'middle', dy: 0.16 },
  { label: '+CLVD', g: 30, d: 0, anchor: 'start', dy: 0.03 },
  { label: '−CLVD', g: -30, d: 0, anchor: 'end', dy: 0.03 },
];

export default function Lune({ gamma, delta, mean, reference, accent = '#2547ad' }: Props) {
  const geom = useMemo(() => {
    const grid = [
      ...MERIDIANS.map((g) =>
        polyline(Array.from({ length: 41 }, (_, i) => hammer(g, -90 + (i * 180) / 40))),
      ),
      ...PARALLELS.map((d) =>
        polyline(Array.from({ length: 31 }, (_, i) => hammer(-30 + (i * 60) / 30, d))),
      ),
    ];
    const leftEdge = Array.from({ length: 81 }, (_, i) => hammer(-30, -90 + (i * 180) / 80));
    const rightEdge = Array.from({ length: 81 }, (_, i) => hammer(30, 90 - (i * 180) / 80));
    const frame = `M ${polyline(leftEdge)} L ${polyline(rightEdge)} Z`;
    const pts = gamma.map((g, i) => hammer(g, delta[i]));
    return { grid, frame, pts };
  }, [gamma, delta]);

  const [mx, my] = hammer(mean.gamma, mean.delta);
  const [rx, ry] = hammer(reference.gamma, reference.delta);

  return (
    <svg
      viewBox="-1.0 -1.72 2.0 3.44"
      className="lune"
      role="img"
      aria-label="Posterior moment-tensor source type on the lune"
    >
      {geom.grid.map((pl, i) => (
        <polyline key={i} points={pl} fill="none" stroke="#d2d8e0" strokeWidth={0.008} />
      ))}
      <path
        d={geom.frame}
        fill="none"
        stroke="#171b23"
        strokeWidth={0.016}
        strokeLinejoin="round"
      />

      {/* posterior cloud */}
      {geom.pts.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r={0.022} fill={accent} fillOpacity={0.16} />
      ))}

      {/* reference source-type markers */}
      {REFS.map((r) => {
        const [x, y] = hammer(r.g, r.d);
        return (
          <g key={r.label}>
            <circle cx={x} cy={y} r={0.018} fill="#4d5564" />
            <text
              x={x}
              y={y + r.dy}
              fontSize={0.085}
              fill="#4d5564"
              textAnchor={r.anchor}
              dominantBaseline="middle"
            >
              {r.label}
            </text>
          </g>
        );
      })}

      {/* catalogue reference (star) */}
      <text
        x={rx}
        y={ry}
        fontSize={0.2}
        fill="#d4501e"
        textAnchor="middle"
        dominantBaseline="central"
      >
        ★
      </text>
      {/* posterior mean */}
      <circle cx={mx} cy={my} r={0.05} fill={accent} stroke="#ffffff" strokeWidth={0.018} />
    </svg>
  );
}
