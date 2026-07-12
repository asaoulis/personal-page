import { useEffect, useRef } from 'react';
import { mtFromSdr, randomSdr, renderBeachball } from '../../lib/mech';

/**
 * "Imprint" — block-print pattern papers in the spirit of Cambridge Imprint,
 * built from the site's own primitives (beachballs, shear ellipses, waveform
 * rows). Studying the real papers set the rules: ONE hand-cut motif, at most
 * two inks on a saturated mid-tone ground, loose rows with rhythm variation,
 * flat colour — no gradients, no shadows.
 *
 * variant="plate": a bookplate for the research section's empty right column.
 *   It re-inks to match the strand under the cursor (rows carry data-domain):
 *   seismology → beachball calico · cosmology → shear meadow · signals →
 *   wavetrain. Click to re-print a new arrangement.
 * variant="band": a quiet full-width divider strip (shear meadow on cream).
 */

type Domain = 'seismology' | 'cosmology' | 'signals';

const TAU = Math.PI * 2;

const CAPTION: Record<Domain, string> = {
  seismology: 'blockprint no.1 — source solutions',
  cosmology: 'blockprint no.2 — cosmic shear',
  signals: 'blockprint no.3 — recorded signals',
};

function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---- the three papers (each: one motif, two inks, mid-tone ground) ------- */

function drawCalico(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  seed: number,
  dpr: number,
) {
  const rnd = mulberry32(seed);
  ctx.fillStyle = '#9fa03c'; // olive ground
  ctx.fillRect(0, 0, w, h);
  const CREAM: [number, number, number] = [242, 236, 217];
  const INK: [number, number, number] = [38, 43, 69];
  const sp = 52;
  let row = 0;
  for (let y = sp * 0.55; y < h + 14; y += sp * 0.82, row++) {
    for (let x = (row % 2 ? sp / 2 : 0) + sp * 0.38; x < w + 14; x += sp) {
      const jx = (rnd() - 0.5) * 8;
      const jy = (rnd() - 0.5) * 8;
      if (rnd() < 0.8) {
        const s = 24 + rnd() * 9;
        const spr = renderBeachball(s, mtFromSdr(...randomSdr(rnd)), INK, CREAM, INK, dpr);
        ctx.save();
        ctx.translate(x + jx, y + jy);
        ctx.rotate((rnd() - 0.5) * 0.6);
        ctx.drawImage(spr, -s / 2, -s / 2, s, s);
        ctx.restore();
      } else {
        ctx.save();
        ctx.translate(x + jx, y + jy);
        ctx.rotate(TAU / 8);
        ctx.fillStyle = 'rgb(38,43,69)';
        const d = 3.4 + rnd() * 2.4;
        ctx.fillRect(-d / 2, -d / 2, d, d);
        ctx.restore();
      }
    }
  }
}

function drawMeadow(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  seed: number,
  ground = '#27607a',
  ink = 'rgba(242,236,217,0.94)',
  scale = 1,
) {
  const rnd = mulberry32(seed);
  ctx.fillStyle = ground;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = ink;
  // loose columns of hand-cut shear "beans", some rows of small dots (the
  // rhythm trick from the real papers)
  const colW = 26 * scale;
  const rowH = 21 * scale;
  for (let x = colW * 0.5; x < w + colW; x += colW) {
    const smallCol = rnd() < 0.22;
    for (let y = rowH * 0.5; y < h + rowH; y += rowH) {
      const jx = (rnd() - 0.5) * 5 * scale;
      const jy = (rnd() - 0.5) * 4 * scale;
      const ang = 0.8 * Math.sin(x * 0.02 + y * 0.013) + (rnd() - 0.5) * 0.5;
      ctx.save();
      ctx.translate(x + jx, y + jy);
      ctx.rotate(ang);
      if (smallCol) {
        ctx.beginPath();
        ctx.ellipse(0, 0, 2.3 * scale, 1.7 * scale, 0, 0, TAU);
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.ellipse(0, 0, (6.4 + rnd() * 2.2) * scale, (3 + rnd() * 1.2) * scale, 0, 0, TAU);
        ctx.fill();
      }
      ctx.restore();
    }
  }
}

function drawWavetrain(ctx: CanvasRenderingContext2D, w: number, h: number, seed: number) {
  const rnd = mulberry32(seed);
  ctx.fillStyle = '#a84a37'; // madder ground
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = 'rgba(242,236,217,0.92)';
  ctx.lineWidth = 1.5;
  for (let y = 18; y < h; y += 26) {
    const bursts: { x: number; a: number; f: number }[] = [];
    let bx = rnd() * 180;
    while (bx < w + 60) {
      bursts.push({ x: bx, a: 5 + rnd() * 11, f: 0.32 + rnd() * 0.25 });
      bx += 130 + rnd() * 260;
    }
    const ph = rnd() * TAU;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 2.5) {
      let v = 1.1 * Math.sin(x * 0.05 + ph);
      for (const b of bursts) {
        const d = x - b.x;
        v += b.a * Math.exp((-d * d) / 340) * Math.sin(d * b.f);
      }
      if (x === 0) ctx.moveTo(x, y + v);
      else ctx.lineTo(x, y + v);
    }
    ctx.stroke();
  }
}

function paint(cv: HTMLCanvasElement, domain: Domain, seed: number) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const r = cv.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return;
  cv.width = Math.round(r.width * dpr);
  cv.height = Math.round(r.height * dpr);
  const ctx = cv.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (domain === 'seismology') drawCalico(ctx, r.width, r.height, seed, dpr);
  else if (domain === 'cosmology') drawMeadow(ctx, r.width, r.height, seed);
  else drawWavetrain(ctx, r.width, r.height, seed);
}

/* ---- component ----------------------------------------------------------- */

export default function Imprint({ variant = 'plate' }: { variant?: 'plate' | 'band' }) {
  const cvRef = useRef<HTMLCanvasElement | null>(null);
  const capRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const cv = cvRef.current;
    if (!cv) return;

    if (variant === 'band') {
      // quiet divider: shear meadow, olive on the page's warm cream
      const seed = 41;
      const draw = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const r = cv.getBoundingClientRect();
        if (!r.width) return;
        cv.width = Math.round(r.width * dpr);
        cv.height = Math.round(r.height * dpr);
        const ctx = cv.getContext('2d');
        if (!ctx) return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        drawMeadow(ctx, r.width, r.height, seed, '#f4f0e4', 'rgba(159,160,60,0.5)', 0.8);
      };
      draw();
      const ro = new ResizeObserver(draw);
      ro.observe(cv);
      return () => ro.disconnect();
    }

    // plate: re-inks per hovered research strand, click to re-print
    let domain: Domain = 'seismology';
    let seed = 7;
    let fading = 0;
    let prev: HTMLCanvasElement | null = null;

    const redraw = () => {
      paint(cv, domain, seed);
      if (capRef.current) capRef.current.textContent = CAPTION[domain];
    };
    const switchTo = (d: Domain) => {
      if (d === domain) return;
      // snapshot for a short crossfade
      prev = document.createElement('canvas');
      prev.width = cv.width;
      prev.height = cv.height;
      prev.getContext('2d')!.drawImage(cv, 0, 0);
      domain = d;
      redraw();
      const snap = prev;
      const ctx = cv.getContext('2d')!;
      const t0 = performance.now();
      cancelAnimationFrame(fading);
      const fade = (t: number) => {
        const f = (t - t0) / 260;
        if (f < 1 && snap === prev) {
          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.globalAlpha = 1 - f;
          ctx.drawImage(snap, 0, 0);
          ctx.restore();
          fading = requestAnimationFrame(fade);
        } else if (snap === prev) {
          redraw();
        }
      };
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches)
        fading = requestAnimationFrame(fade);
    };

    redraw();
    const rows = Array.from(document.querySelectorAll<HTMLElement>('.work__item[data-domain]'));
    const handlers = rows.map((row) => {
      const h = () => switchTo(row.dataset.domain as Domain);
      row.addEventListener('pointerenter', h);
      return { row, h };
    });
    const onClick = () => {
      seed = ((seed * 9301 + 49297) % 233280) | 1;
      redraw();
    };
    cv.addEventListener('click', onClick);
    const ro = new ResizeObserver(redraw);
    ro.observe(cv);
    return () => {
      handlers.forEach(({ row, h }) => row.removeEventListener('pointerenter', h));
      cv.removeEventListener('click', onClick);
      cancelAnimationFrame(fading);
      ro.disconnect();
    };
  }, [variant]);

  if (variant === 'band') return <canvas ref={cvRef} className="imprint-band" aria-hidden="true" />;
  return (
    <figure className="imprint-plate" aria-hidden="true">
      <canvas ref={cvRef} title="re-print"></canvas>
      <figcaption
        ref={(el) => {
          capRef.current = el;
        }}
      >
        {CAPTION.seismology}
      </figcaption>
    </figure>
  );
}
