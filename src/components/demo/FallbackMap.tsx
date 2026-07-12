import { type EventFeature, markerSize } from './types';
import { type ColorMode, markerColor } from './coloring';

/**
 * Lightweight SVG fallback for the interactive map, used when the browser lacks WebGL2
 * (MapLibre GL v5 requires it — e.g. headless / GPU-less / WebGL-disabled environments).
 * Plots the same events on a simple equirectangular geographic frame (graticule + labels), fully
 * interactive (click to select), so the demo's core — the event scatter + selection — always works.
 */
interface Props {
  events: EventFeature[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  colorMode: ColorMode;
}

// Frame the Japanese main arc.
const LON0 = 127,
  LON1 = 147,
  LAT0 = 29,
  LAT1 = 46;
const COSLAT = Math.cos(((LAT0 + LAT1) / 2) * (Math.PI / 180));
const S = 40;
const W = (LON1 - LON0) * COSLAT * S;
const H = (LAT1 - LAT0) * S;

function project(lon: number, lat: number): [number, number] {
  return [(lon - LON0) * COSLAT * S, (LAT1 - lat) * S];
}

const LON_LINES = [130, 135, 140, 145];
const LAT_LINES = [30, 35, 40, 45];

export default function FallbackMap({ events, selectedId, onSelect, colorMode }: Props) {
  return (
    <div className="demo-fallbackmap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Map of recent events (schematic)"
      >
        <rect x={0} y={0} width={W} height={H} fill="#eef2f6" />
        {/* graticule */}
        {LON_LINES.map((lon) => {
          const [x] = project(lon, LAT0);
          return (
            <g key={`lon${lon}`}>
              <line x1={x} y1={0} x2={x} y2={H} stroke="#d2d8e0" strokeWidth={1} />
              <text x={x + 3} y={H - 5} fontSize={11} fill="#9aa1ad">
                {lon}°E
              </text>
            </g>
          );
        })}
        {LAT_LINES.map((lat) => {
          const [, y] = project(LON0, lat);
          return (
            <g key={`lat${lat}`}>
              <line x1={0} y1={y} x2={W} y2={y} stroke="#d2d8e0" strokeWidth={1} />
              <text x={4} y={y - 4} fontSize={11} fill="#9aa1ad">
                {lat}°N
              </text>
            </g>
          );
        })}
        <rect x={0} y={0} width={W} height={H} fill="none" stroke="#c2c9d2" strokeWidth={1.5} />

        {/* events */}
        {events.map((f) => {
          const [x, y] = project(f.geometry.coordinates[0], f.geometry.coordinates[1]);
          const r = markerSize(f.properties.mag) / 2;
          const sel = f.properties.id === selectedId;
          const col = markerColor(f.properties, colorMode);
          return (
            <g key={f.properties.id} transform={`translate(${x},${y})`}>
              <circle
                r={r}
                fill={col}
                stroke="#fff"
                strokeWidth={sel ? 3 : 1.5}
                style={{ cursor: 'pointer' }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(f.properties.id);
                }}
              >
                <title>
                  M{f.properties.mag} · {f.properties.region}
                </title>
              </circle>
              {sel && <circle r={r + 4} fill="none" stroke={col} strokeWidth={2} />}
            </g>
          );
        })}
      </svg>
      <div className="demo-fallbackmap__note">Schematic map (interactive basemap needs WebGL2)</div>
    </div>
  );
}
