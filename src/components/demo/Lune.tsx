import { useMemo } from 'react';
import { type Reference, referenceMarker } from './types';
import { MarkerShape, referenceColor } from './markers';

/**
 * Source-type lune rendered client-side (SVG) from a (gamma, delta) posterior ensemble —
 * Hammer equal-area projection, same as the research code. Each catalogue reference is scattered
 * at its own (γ, δ) with a distinct marker (star/square/triangle/diamond per source); the model
 * posterior mean is the ringed accent dot.
 */
interface Props {
  gamma: number[];
  delta: number[];
  mean: { gamma: number; delta: number };
  references: Reference[];
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
const ANCHORS: {
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

export default function Lune({ gamma, delta, mean, references, accent = '#2547ad' }: Props) {
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

      {/* source-type anchors */}
      {ANCHORS.map((r) => {
        const [x, y] = hammer(r.g, r.d);
        return (
          <g key={r.label}>
            <circle cx={x} cy={y} r={0.015} fill="#9aa1ad" />
            <text
              x={x}
              y={y + r.dy}
              fontSize={0.08}
              fill="#6a7280"
              textAnchor={r.anchor}
              dominantBaseline="middle"
            >
              {r.label}
            </text>
          </g>
        );
      })}

      {/* catalogue references — distinct marker per source */}
      {references.map((ref, i) => {
        const [x, y] = hammer(ref.gamma, ref.delta);
        return (
          <MarkerShape
            key={`${ref.source}-${i}`}
            shape={referenceMarker(ref.source)}
            cx={x}
            cy={y}
            r={0.07}
            color={referenceColor(ref.source)}
            stroke="#ffffff"
            strokeWidth={0.014}
          />
        );
      })}

      {/* posterior mean */}
      <circle cx={mx} cy={my} r={0.05} fill={accent} stroke="#ffffff" strokeWidth={0.018} />
    </svg>
  );
}
