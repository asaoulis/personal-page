import { useEffect, useRef } from 'react';

/**
 * Focal-mechanism "beachball" rendered client-side by rastering the lower-hemisphere
 * focal sphere from strike/dip/rake — no precomputed image. Compressional quadrants
 * are filled with `color`, dilatational left light. Equal-area (Schmidt) projection.
 */
interface Props {
  strike: number;
  dip: number;
  rake: number;
  color?: string;
  size?: number; // CSS px
}

/** Aki & Richards (1980) moment tensor in NED from strike/dip/rake (Mo = 1). */
function mtFromSdr(strikeDeg: number, dipDeg: number, rakeDeg: number): number[][] {
  const s = (strikeDeg * Math.PI) / 180;
  const d = (dipDeg * Math.PI) / 180;
  const l = (rakeDeg * Math.PI) / 180;
  const sin = Math.sin;
  const cos = Math.cos;
  const Mxx = -(sin(d) * cos(l) * sin(2 * s) + sin(2 * d) * sin(l) * sin(s) ** 2);
  const Mxy = sin(d) * cos(l) * cos(2 * s) + 0.5 * sin(2 * d) * sin(l) * sin(2 * s);
  const Mxz = -(cos(d) * cos(l) * cos(s) + cos(2 * d) * sin(l) * sin(s));
  const Myy = sin(d) * cos(l) * sin(2 * s) - sin(2 * d) * sin(l) * cos(s) ** 2;
  const Myz = -(cos(d) * cos(l) * sin(s) - cos(2 * d) * sin(l) * cos(s));
  const Mzz = sin(2 * d) * sin(l);
  // [N, E, D]
  return [
    [Mxx, Mxy, Mxz],
    [Mxy, Myy, Myz],
    [Mxz, Myz, Mzz],
  ];
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export default function Beachball({ strike, dip, rake, color = '#2547ad', size = 150 }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const n = Math.round(size * dpr);
    canvas.width = n;
    canvas.height = n;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const M = mtFromSdr(strike, dip, rake);
    const [fr, fg, fb] = hexToRgb(color);
    const img = ctx.createImageData(n, n);
    const data = img.data;
    const R = n / 2;

    for (let py = 0; py < n; py++) {
      for (let px = 0; px < n; px++) {
        const nx = (px + 0.5 - R) / R; // east axis
        const ny = (py + 0.5 - R) / R; // south-on-screen (down)
        const rho = Math.hypot(nx, ny);
        const o = (py * n + px) * 4;
        if (rho > 1) {
          data[o + 3] = 0; // transparent outside the disk
          continue;
        }
        // equal-area inverse: takeoff angle i from the downward vertical
        const inc = 2 * Math.asin(Math.min(1, rho / Math.SQRT2));
        const az = Math.atan2(nx, -ny); // from north (screen up), clockwise
        const si = Math.sin(inc);
        const g = [si * Math.cos(az), si * Math.sin(az), Math.cos(inc)]; // ray dir, NED
        // P radiation ∝ gᵀ M g
        let v = 0;
        for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) v += g[a] * M[a][b] * g[b];
        const comp = v >= 0;
        const edge = rho > 0.97;
        if (edge) {
          data[o] = 23;
          data[o + 1] = 27;
          data[o + 2] = 35; // ink outline
        } else if (comp) {
          data[o] = fr;
          data[o + 1] = fg;
          data[o + 2] = fb;
        } else {
          data[o] = 247;
          data[o + 1] = 248;
          data[o + 2] = 250; // light
        }
        data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [strike, dip, rake, color, size]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size }}
      role="img"
      aria-label="Focal-mechanism beachball"
    />
  );
}
