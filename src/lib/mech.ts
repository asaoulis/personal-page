/**
 * Focal-mechanism math shared by the hero backdrop and the imprint patterns.
 * Same conventions as components/demo/Beachball.tsx: Aki & Richards (1980)
 * moment tensor in NED (x=N, y=E, z=D) from strike/dip/rake, equal-area
 * (Schmidt) lower-hemisphere projection for rendering.
 */

export type Mat3 = number[][];
export type RGB = [number, number, number];

export function mtFromSdr(strikeDeg: number, dipDeg: number, rakeDeg: number): Mat3 {
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

/** Random double-couple orientation. */
export function randomSdr(rnd: () => number = Math.random): [number, number, number] {
  return [rnd() * 360, rnd() * 90, rnd() * 360 - 180];
}

/**
 * Horizontal-plane radiation patterns for screen azimuth phi, where the screen
 * maps to a map view (up = North, right = East): ray g = (cos phi_N, sin phi_E, 0).
 * Returns P (radial, g'Mg) and S (transverse, t'Mg with t = phi-hat) amplitudes —
 * signed; callers usually take |.| and normalise. phi = atan2(dx, -dy) for a
 * screen-space direction (dx, dy).
 */
export function radiationAt(M: Mat3, phi: number): { p: number; s: number } {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  const p = c * c * M[0][0] + 2 * c * s * M[0][1] + s * s * M[1][1];
  const sv = -s * c * M[0][0] + (c * c - s * s) * M[0][1] + s * c * M[1][1];
  return { p, s: sv };
}

/**
 * Sampled |P| and |S| radiation lobes over azimuth, each normalised to max 1
 * with a small floor so nodal directions stay faintly visible.
 */
export function radiationLobes(
  M: Mat3,
  n = 64,
  floor = 0.08,
): { p: Float32Array; s: Float32Array } {
  const p = new Float32Array(n);
  const s = new Float32Array(n);
  let pm = 1e-9;
  let sm = 1e-9;
  for (let i = 0; i < n; i++) {
    const r = radiationAt(M, (i / n) * 2 * Math.PI);
    p[i] = Math.abs(r.p);
    s[i] = Math.abs(r.s);
    pm = Math.max(pm, p[i]);
    sm = Math.max(sm, s[i]);
  }
  for (let i = 0; i < n; i++) {
    p[i] = floor + (1 - floor) * (p[i] / pm);
    s[i] = floor + (1 - floor) * (s[i] / sm);
  }
  return { p, s };
}

/**
 * Rasterise one beachball to an offscreen canvas (prerender once, blit later).
 * comp/dil/ink are the compressional fill, dilatational fill and rim colours.
 */
export function renderBeachball(
  sizeCss: number,
  M: Mat3,
  comp: RGB,
  dil: RGB,
  ink: RGB,
  dpr: number,
): HTMLCanvasElement {
  const n = Math.max(10, Math.round(sizeCss * dpr));
  const off = document.createElement('canvas');
  off.width = n;
  off.height = n;
  const octx = off.getContext('2d')!;
  const img = octx.createImageData(n, n);
  const data = img.data;
  const R = n / 2;
  for (let py = 0; py < n; py++) {
    for (let px = 0; px < n; px++) {
      const nx = (px + 0.5 - R) / R;
      const ny = (py + 0.5 - R) / R;
      const rho = Math.hypot(nx, ny);
      const o = (py * n + px) * 4;
      if (rho > 1) {
        data[o + 3] = 0;
        continue;
      }
      const inc = 2 * Math.asin(Math.min(1, rho / Math.SQRT2));
      const az = Math.atan2(nx, -ny);
      const si = Math.sin(inc);
      const gx = si * Math.cos(az);
      const gy = si * Math.sin(az);
      const gz = Math.cos(inc);
      const v =
        gx * (M[0][0] * gx + M[0][1] * gy + M[0][2] * gz) +
        gy * (M[1][0] * gx + M[1][1] * gy + M[1][2] * gz) +
        gz * (M[2][0] * gx + M[2][1] * gy + M[2][2] * gz);
      let c = v >= 0 ? comp : dil;
      if (rho > 1 - 4.4 / n) c = ink;
      data[o] = c[0];
      data[o + 1] = c[1];
      data[o + 2] = c[2];
      data[o + 3] = rho > 1 - 1.5 / n ? Math.round((255 * (1 - rho) * n) / 1.5) : 255;
    }
  }
  octx.putImageData(img, 0, 0);
  return off;
}
