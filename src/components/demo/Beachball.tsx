import { useEffect, useRef } from 'react';

/**
 * Focal-mechanism "beachball" rendered client-side by rastering the lower-hemisphere focal
 * sphere — no precomputed image. Two modes:
 *   - single mechanism: pass strike/dip/rake → crisp compressional/dilatational quadrants.
 *   - FUZZY posterior: pass `samples` (an mt6 ensemble, USE convention) → each pixel is shaded by
 *     the FRACTION of posterior members that are compressional there (a probability field), so the
 *     nodal planes are smeared by the orientation uncertainty. This is the browser-side equivalent
 *     of pyrocko's `plot_fuzzy_beachball_mpl_pixmap` (the seismo_sbi `plot_fuzzy_beachball_samples`
 *     look), drawn live from the committed samples — no heavy PNG.
 * Equal-area (Schmidt) projection.
 */
interface Props {
  strike?: number;
  dip?: number;
  rake?: number;
  samples?: number[][]; // mt6 = [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] (USE), drives the fuzzy field
  color?: string;
  size?: number; // CSS px
}

type Mat3 = number[][];

/** Aki & Richards (1980) moment tensor in NED from strike/dip/rake (Mo = 1). */
function mtFromSdr(strikeDeg: number, dipDeg: number, rakeDeg: number): Mat3 {
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
  return [
    [Mxx, Mxy, Mxz],
    [Mxy, Myy, Myz],
    [Mxz, Myz, Mzz],
  ];
}

/** USE m6 [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] → NED 3×3 (x=N, y=E, z=D). */
function useToNed(m6: number[]): Mat3 {
  const [Mrr, Mtt, Mpp, Mrt, Mrp, Mtp] = m6;
  return [
    [Mtt, -Mtp, Mrt],
    [-Mtp, Mpp, -Mrp],
    [Mrt, -Mrp, Mrr],
  ];
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export default function Beachball({
  strike,
  dip,
  rake,
  samples,
  color = '#2547ad',
  size = 150,
}: Props) {
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

    const fuzzy = !!(samples && samples.length);
    const mats: Mat3[] = fuzzy
      ? samples!.map(useToNed)
      : [mtFromSdr(strike ?? 0, dip ?? 0, rake ?? 0)];
    const N = mats.length;
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
        const gx = si * Math.cos(az);
        const gy = si * Math.sin(az);
        const gz = Math.cos(inc); // ray dir, NED

        // fraction of members compressional (gᵀ M g ≥ 0)
        let comp = 0;
        for (let k = 0; k < N; k++) {
          const M = mats[k];
          const v =
            gx * (M[0][0] * gx + M[0][1] * gy + M[0][2] * gz) +
            gy * (M[1][0] * gx + M[1][1] * gy + M[1][2] * gz) +
            gz * (M[2][0] * gx + M[2][1] * gy + M[2][2] * gz);
          if (v >= 0) comp++;
        }
        const p = comp / N; // 1 = always compressional (accent), 0 = always dilatational (light)

        if (rho > 0.985) {
          data[o] = 23;
          data[o + 1] = 27;
          data[o + 2] = 35; // ink outline
        } else {
          // blend light → accent by compressional probability
          data[o] = Math.round(247 + (fr - 247) * p);
          data[o + 1] = Math.round(248 + (fg - 248) * p);
          data[o + 2] = Math.round(250 + (fb - 250) * p);
        }
        data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [strike, dip, rake, samples, color, size]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size }}
      role="img"
      aria-label={samples ? 'Posterior fuzzy beachball' : 'Focal-mechanism beachball'}
    />
  );
}
