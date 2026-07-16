import { useEffect, useRef } from 'react';
import { mtFromSdr, randomSdr, radiationLobes, renderBeachball, type Mat3 } from '../../lib/mech';
import { SCHEMES, rgba, type HeroPalette } from '../../styles/schemes';

/**
 * The split-hero backdrop: cosmology | seismology, meeting at a live seismogram.
 *
 * Left of the seam — a field of galaxy-shear ellipses. The cursor is a
 * dark-matter halo: galaxies shear tangentially around it (SIS reduced shear),
 * brighten with magnification, and a faint Einstein ring rides along. Until the
 * visitor moves the pointer, a slow virtual cursor wanders (also the touch
 * behaviour).
 *
 * Right of the seam — static focal-mechanism beachballs (they do not drift;
 * they ARE the events). Clicking ruptures a new solution at the click point;
 * existing solutions occasionally re-radiate on their own. Wavefronts carry the
 * mechanism's radiation pattern: the P ring (teal, radial push on the dot
 * lattice) is boldest along the compressional/dilatational lobes and vanishes
 * at the nodal planes; the S ring (white, transverse) is 45° out of phase, as
 * physics demands. The seam is the recording: a station glyph sits on it and
 * the drum trace kicks when each wavefront arrives.
 *
 * No controls — presets only. Pauses offscreen/hidden; static under
 * prefers-reduced-motion; galaxies-only below 720px.
 */

const TAU = Math.PI * 2;
const N_LOBE = 64;

// preset — tuned during prototype review (user: denser/brighter galaxies, no
// beachball motion, no sliders)
const CFG = {
  galaxyPer: 1250, // px² of left-panel area per galaxy
  sizeMin: 1.1,
  sizeMax: 4.8,
  alphaMin: 0.3,
  alphaMax: 0.88,
  thetaE: 88, // Einstein radius of the cursor halo, px
  ambient: 0.045, // ambient cosmic-shear amplitude
  vP: 330, // px/s
  vS: 185,
  maxBalls: 7,
  autoMin: 6500, // ms between ambient re-ruptures
  autoMax: 12500,
  seamFrac: 0.565,
};

type Gal = {
  x: number;
  y: number;
  e1: number;
  e2: number;
  s: number;
  a: number;
  tw: number;
  col: 'w' | 't' | 'm';
};
type Ev = { x: number; y: number; t0: number; mag: number; pl: Float32Array; sl: Float32Array };
type Ball = {
  x: number;
  y: number;
  size: number;
  M: Mat3;
  sprite: HTMLCanvasElement;
  born: number;
  dying: number;
};

export default function HeroBackdrop({ palette }: { palette?: HeroPalette } = {}) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // scheme inks (defaults reproduce the live constants exactly)
    const P = palette ?? SCHEMES.default;
    const COMP = P.comp;
    const DIL = P.dil;
    const INK = P.ink;
    // explicit non-null types so the hoisted function declarations below keep them
    const canvas: HTMLCanvasElement = el;
    // NOT parentElement: astro-island wraps the island with display:contents
    // (zero-size rect), which starves both observers
    const hero = (canvas.closest('.hero') ?? canvas.parentElement) as HTMLElement;
    const maybeCtx = canvas.getContext('2d');
    if (!maybeCtx) return;
    const ctx: CanvasRenderingContext2D = maybeCtx;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

    let W = 0;
    let H = 0;
    let dpr = 1;
    let seamX = 0;
    let mobile = false;
    let gal: Gal[] = [];
    let dots: { x: number; y: number }[] = [];
    const events: Ev[] = [];
    const balls: Ball[] = [];
    let stationY = 0;
    let textRect: { l: number; t: number; r: number; b: number } | null = null;
    let portrait = { x: 0, y: 0, r: 0 };

    // ---------- input ----------
    const mouse = { x: -1e4, y: -1e4, tx: -1e4, ty: -1e4, live: 0 };
    let lensPulse = 0;

    const toLocal = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const onMove = (e: PointerEvent) => {
      const p = toLocal(e);
      mouse.tx = p.x;
      mouse.ty = p.y;
      mouse.live = performance.now();
    };
    const onDown = (e: PointerEvent) => {
      const p = toLocal(e);
      if (!mobile && p.x > seamX) rupture(p.x, p.y, 0.4 + Math.random() * 0.45, true);
      else lensPulse = performance.now();
    };

    // ---------- scene ----------
    function rupture(x: number, y: number, mag: number, addBall: boolean) {
      const M = mtFromSdr(...randomSdr());
      if (addBall) {
        const size = 24 + mag * 26;
        balls.push({
          x,
          y,
          size,
          M,
          sprite: renderBeachball(size, M, COMP, DIL, INK, dpr),
          born: performance.now(),
          dying: 0,
        });
        const alive = balls.filter((b) => !b.dying);
        if (alive.length > CFG.maxBalls) alive[0].dying = performance.now();
        emit(x, y, mag, M);
      } else {
        emit(x, y, mag, M);
      }
    }
    function emit(x: number, y: number, mag: number, M: Mat3) {
      const { p, s } = radiationLobes(M, N_LOBE);
      events.push({ x, y, t0: performance.now(), mag, pl: p, sl: s });
    }
    /** an existing solution re-radiates with its own mechanism */
    function reRadiate() {
      const alive = balls.filter((b) => !b.dying);
      if (!alive.length) return;
      const b = alive[Math.floor(Math.random() * alive.length)];
      const { p, s } = radiationLobes(b.M, N_LOBE);
      events.push({
        x: b.x,
        y: b.y,
        t0: performance.now(),
        mag: 0.25 + (b.size - 24) / 100,
        pl: p,
        sl: s,
      });
    }

    function syncDom() {
      const cr = canvas.getBoundingClientRect();
      const ph = hero.querySelector('.hero__portrait img');
      if (ph) {
        const pr = ph.getBoundingClientRect();
        portrait = {
          x: pr.left + pr.width / 2 - cr.left,
          y: pr.top + pr.height / 2 - cr.top,
          r: pr.width / 2,
        };
      }
      const tx = hero.querySelector('.hero__text');
      if (tx) {
        const tr = tx.getBoundingClientRect();
        textRect = {
          l: tr.left - cr.left,
          t: tr.top - cr.top,
          r: tr.right - cr.left,
          b: tr.bottom - cr.top,
        };
      }
    }

    function build() {
      gal = [];
      let seed = 20260712;
      const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0), seed / 4294967296);
      const panelW = mobile ? W : seamX * 1.03;
      const n = Math.round((panelW * H) / CFG.galaxyPer);
      for (let i = 0; i < n; i++) {
        const cs = rnd();
        gal.push({
          x: rnd() * panelW,
          y: rnd() * H,
          e1: (rnd() + rnd() + rnd() - 1.5) * 0.3,
          e2: (rnd() + rnd() + rnd() - 1.5) * 0.3,
          s: CFG.sizeMin + rnd() * rnd() * (CFG.sizeMax - CFG.sizeMin),
          a: CFG.alphaMin + rnd() * (CFG.alphaMax - CFG.alphaMin),
          tw: rnd() * TAU,
          // main / accent / rare galaxy colours (see HeroPalette galaxy* roles)
          col: cs < 0.88 ? 'w' : cs < 0.95 ? 't' : 'm',
        });
      }
      dots = [];
      if (!mobile) {
        for (let y = 6; y < H + 28; y += 28)
          for (let x = seamX - 16; x < W + 28; x += 28)
            dots.push({ x: x + (Math.random() - 0.5) * 2, y: y + (Math.random() - 0.5) * 2 });
      }
    }

    function placeBalls() {
      balls.length = 0;
      if (mobile) return;
      syncDom();
      const { x: px, y: py, r: pr } = portrait;
      // a still constellation around the portrait — sized, not moving
      const spots = [
        { x: px - pr * 1.55, y: py - pr * 0.95, s: 34 },
        { x: px + pr * 1.45, y: py - pr * 0.55, s: 26 },
        { x: px + pr * 1.1, y: py + pr * 1.35, s: 42 },
        { x: px - pr * 1.2, y: py + pr * 1.15, s: 24 },
      ];
      const t = performance.now();
      for (const sp of spots) {
        const x = Math.min(Math.max(sp.x, seamX + 50), W - 40);
        const y = Math.min(Math.max(sp.y, 46), H - 46);
        const M = mtFromSdr(...randomSdr());
        balls.push({
          x,
          y,
          size: sp.s,
          M,
          sprite: renderBeachball(sp.s, M, COMP, DIL, INK, dpr),
          born: t,
          dying: 0,
        });
      }
    }

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = hero.getBoundingClientRect();
      W = r.width;
      H = r.height;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      mobile = W < 720;
      seamX = W * CFG.seamFrac;
      stationY = H * 0.36;
      syncDom();
      build();
      placeBalls();
      if (reduced) frame(performance.now(), 16);
    }

    // ---------- helpers ----------
    const lobeAt = (arr: Float32Array, dx: number, dy: number) => {
      // screen azimuth from North (up), clockwise — matches the sprite's rim
      const phi = Math.atan2(dx, -dy);
      let i = Math.round((phi / TAU) * N_LOBE);
      i = ((i % N_LOBE) + N_LOBE) % N_LOBE;
      return arr[i];
    };

    function textDim(x: number, y: number) {
      if (!textRect) return 1;
      const dx = Math.max(textRect.l - x, 0, x - textRect.r);
      const dy = Math.max(textRect.t - y, 0, y - textRect.b);
      const d = Math.hypot(dx, dy);
      return d > 70 ? 1 : 0.26 + 0.74 * (d / 70);
    }

    function seamValue(y: number, t: number) {
      let v =
        2.1 * Math.sin(y * 0.05 + t * 0.0011) +
        1.6 * Math.sin(y * 0.023 - t * 0.0007) +
        1.2 * Math.sin(y * 0.011 + t * 0.00042);
      // bursts recorded at the station, written upward like a drum record
      if (y <= stationY) {
        for (const ev of events) {
          const d = Math.hypot(ev.x - seamX, ev.y - stationY);
          for (const [vel, amp, fr] of [
            [CFG.vP, 9, 7.5],
            [CFG.vS, 26, 4.5],
          ] as const) {
            const arr = ev.t0 + (d / vel) * 1000;
            const tau = (t - arr) / 1000 - (stationY - y) / 90;
            if (tau > 0 && tau < 3)
              v +=
                amp *
                ev.mag *
                Math.exp(-2.1 * tau) *
                Math.sin(TAU * fr * tau) *
                Math.exp(-d / 1100);
          }
        }
      }
      return v;
    }

    // ---------- render ----------
    function frame(t: number, dt: number) {
      ctx.clearRect(0, 0, W, H);
      const diag = Math.hypot(W, H);
      for (let i = events.length - 1; i >= 0; i--)
        if ((CFG.vS * Math.max(0, t - events[i].t0)) / 1000 > diag + 300) events.splice(i, 1);

      // virtual cursor until the real one shows up (and on touch)
      if (t - mouse.live > 6000 || mouse.live === 0) {
        const u = t * 0.00009;
        const lim = mobile ? W : seamX;
        mouse.tx = lim * (0.5 + 0.36 * Math.sin(u * 2.1 + 1.3));
        mouse.ty = H * (0.45 + 0.28 * Math.sin(u * 3.3));
      }
      mouse.x += (mouse.tx - mouse.x) * Math.min(1, dt * 0.006);
      mouse.y += (mouse.ty - mouse.y) * Math.min(1, dt * 0.006);

      // ---- galaxies ----
      let thetaE = CFG.thetaE;
      if (lensPulse) {
        const f = (t - lensPulse) / 900;
        if (f < 1) thetaE *= 1 + 0.85 * Math.sin(Math.PI * f);
        else lensPulse = 0;
      }
      const am = CFG.ambient;
      const tt = t * 0.0001;
      const mOn = mouse.x > -1e3 && (mobile || mouse.x < seamX + 60);

      for (const p of gal) {
        const sx = p.x;
        const sy = p.y;
        let g1 = am * Math.sin(sx * 0.004 + tt * 2 + Math.cos(sy * 0.003 - tt));
        let g2 = am * Math.cos(sy * 0.0035 - tt * 1.6 + Math.sin(sx * 0.0025 + tt));
        let mag = 1;
        let coreFade = 1;

        if (mOn) {
          const dx = sx - mouse.x;
          const dy = sy - mouse.y;
          const r2 = dx * dx + dy * dy;
          const r = Math.sqrt(r2) + 1e-4;
          if (r < 1400) {
            const gl = Math.min(0.9, thetaE / (2 * r));
            g1 += (-gl * (dx * dx - dy * dy)) / r2;
            g2 += (-gl * 2 * dx * dy) / r2;
            mag = Math.min(2.4, Math.sqrt(1 / Math.max(0.14, Math.abs(1 - thetaE / r))));
            if (r < thetaE * 0.62) coreFade = Math.max(0.08, (r / (thetaE * 0.62)) ** 2);
          }
        }
        // passing wavefronts transiently lens the galaxy field
        for (const ev of events) {
          const dx = sx - ev.x;
          const dy = sy - ev.y;
          const r2 = dx * dx + dy * dy;
          const r = Math.sqrt(r2) + 1e-4;
          const rS = (CFG.vS * Math.max(0, t - ev.t0)) / 1000;
          const gw =
            0.5 *
            ev.mag *
            lobeAt(ev.sl, dx, dy) *
            Math.exp(-((r - rS) ** 2) / (2 * 34 * 34)) *
            Math.exp(-rS / 1500);
          if (gw > 0.004) {
            g1 += (-gw * (dx * dx - dy * dy)) / r2;
            g2 += (-gw * 2 * dx * dy) / r2;
            mag = Math.max(mag, 1 + gw);
          }
        }

        const n1 = p.e1 + g1;
        const n2 = p.e2 + g2;
        const d1 = 1 + g1 * p.e1 + g2 * p.e2;
        const d2 = g1 * p.e2 - g2 * p.e1;
        const dd = d1 * d1 + d2 * d2;
        let E1 = (n1 * d1 + n2 * d2) / dd;
        let E2 = (n2 * d1 - n1 * d2) / dd;
        let Em = Math.hypot(E1, E2);
        if (Em > 0.95) {
          E1 *= 0.95 / Em;
          E2 *= 0.95 / Em;
          Em = 0.95;
        }
        const q = (1 - Em) / (1 + Em);
        const pa = 0.5 * Math.atan2(E2, E1);
        const sq = Math.sqrt(q);
        const twk = reduced ? 1 : 0.86 + 0.14 * Math.sin(t * 0.0011 + p.tw);
        let al = p.a * twk * coreFade * Math.min(1.5, mag) * textDim(sx, sy);
        if (!mobile) al *= Math.min(1, Math.max(0, (seamX - sx) / 60 + 1)); // fade into the seam
        if (al < 0.01) continue;
        ctx.fillStyle =
          p.col === 'w'
            ? rgba(P.galaxyMain, al)
            : p.col === 't'
              ? rgba(P.galaxyAccent, al)
              : rgba(P.galaxyRare, al);
        ctx.beginPath();
        ctx.ellipse(sx, sy, (p.s * mag) / sq, p.s * mag * sq, pa, 0, TAU);
        ctx.fill();
      }

      if (mobile) return;

      // ---- dot lattice, displaced by radiation-patterned waves ----
      for (const p of dots) {
        let ux = 0;
        let uy = 0;
        let br = 0;
        for (const ev of events) {
          const dx = p.x - ev.x;
          const dy = p.y - ev.y;
          const d = Math.hypot(dx, dy);
          const age = Math.max(0, t - ev.t0) / 1000;
          const rP = CFG.vP * age;
          const rS = CFG.vS * age;
          if (Math.abs(d - rP) < 55 || Math.abs(d - rS) < 85) {
            const spread = 1 / Math.sqrt(1 + d / 120);
            const aP =
              6.5 * ev.mag * lobeAt(ev.pl, dx, dy) * Math.exp(-((d - rP) ** 2) / 512) * spread;
            const aS =
              15 * ev.mag * lobeAt(ev.sl, dx, dy) * Math.exp(-((d - rS) ** 2) / 1458) * spread;
            const ex = dx / (d + 1e-4);
            const ey = dy / (d + 1e-4);
            ux += ex * aP - ey * aS;
            uy += ey * aP + ex * aS;
            br += (aP + 1.4 * aS) / 16;
          }
        }
        const sx = p.x + ux;
        if (sx < seamX + seamValue(p.y, t) - 4) continue;
        const al = Math.min(0.8, 0.11 + br);
        ctx.fillStyle = br > 0.04 ? rgba(P.accent, al) : rgba(P.light, al);
        ctx.beginPath();
        ctx.arc(sx, p.y + uy, br > 0.04 ? 1.5 : 1.05, 0, TAU);
        ctx.fill();
      }

      // ---- wavefront rings, bold along the lobes, silent at the nodes ----
      const segs = 48;
      for (const ev of events) {
        const age = Math.max(0, t - ev.t0) / 1000;
        for (const [vel, base, col, lobes, lw] of [
          [CFG.vP, 0.5, P.accent.join(','), ev.pl, 1.2],
          [CFG.vS, 0.75, P.light.join(','), ev.sl, 1.8],
        ] as const) {
          const r = vel * age;
          const fade = ev.mag * base * Math.exp(-r / 640);
          if (fade < 0.012 || r < 2) continue;
          ctx.lineWidth = lw;
          for (let k = 0; k < segs; k++) {
            const a0 = (k / segs) * TAU;
            const a1 = ((k + 1) / segs) * TAU + 0.004;
            // arc angle -> screen dir -> lobe amplitude (arc angle 0 = +x = East)
            const mid = a0 + TAU / segs / 2;
            const amp = lobeAt(lobes, Math.cos(mid), Math.sin(mid));
            const al = fade * amp;
            if (al < 0.01) continue;
            ctx.strokeStyle = `rgba(${col},${al.toFixed(3)})`;
            ctx.beginPath();
            ctx.arc(ev.x, ev.y, r, a0, a1);
            ctx.stroke();
          }
        }
      }

      // ---- the seam: drum record + station ----
      ctx.strokeStyle = rgba(P.accent, 0.35);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      for (let y = 0; y <= H; y += 4) {
        const x = seamX + seamValue(y, t);
        if (y === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      // station glyph: the standard inverted triangle, pen at the trace
      const stx = seamX + seamValue(stationY, t);
      ctx.fillStyle = rgba(P.light, 0.92);
      ctx.strokeStyle = rgba(P.light, 0.92);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(stx - 6.5, stationY - 5.5);
      ctx.lineTo(stx + 6.5, stationY - 5.5);
      ctx.lineTo(stx, stationY + 5.5);
      ctx.closePath();
      ctx.fill();
      ctx.font = '10px "JetBrains Mono Variable", ui-monospace, monospace';
      ctx.fillStyle = rgba(P.station, 0.85);
      ctx.textAlign = 'left';
      ctx.fillText('HERO · Z', stx + 12, stationY - 8);

      // ---- beachballs: still lives (pop in, fade out — never drift) ----
      for (let i = balls.length - 1; i >= 0; i--) {
        const b = balls[i];
        const age = Math.max(0, t - b.born) / 1000;
        let sc = Math.min(1, age / 0.35);
        sc *= age < 0.7 ? 1 + 0.3 * Math.sin(Math.min(1, age / 0.7) * Math.PI) : 1;
        let al = 0.95;
        if (b.dying) {
          const f = (t - b.dying) / 1600;
          if (f >= 1) {
            balls.splice(i, 1);
            continue;
          }
          al *= 1 - f;
        }
        const s = b.size * sc;
        if (s < 1) continue;
        ctx.save();
        ctx.translate(b.x, b.y);
        ctx.globalAlpha = al;
        ctx.shadowColor = 'rgba(0,0,0,0.4)';
        ctx.shadowBlur = 10;
        ctx.shadowOffsetY = 2;
        ctx.drawImage(b.sprite, -s / 2, -s / 2, s, s);
        ctx.restore();
        ctx.globalAlpha = 1;
      }
    }

    // ---------- loop ----------
    let raf = 0;
    let last = 0;
    let visible = true;
    let nextAuto = performance.now() + 4000;
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(50, t - last || 16);
      last = t;
      if (!mobile && t > nextAuto) {
        reRadiate();
        nextAuto = t + CFG.autoMin + Math.random() * (CFG.autoMax - CFG.autoMin);
      }
      frame(t, dt);
    };
    const start = () => {
      if (!raf && !reduced && visible && !document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };
    const onVis = () => (document.hidden ? stop() : start());
    const io = new IntersectionObserver((es) => {
      visible = es[0].isIntersecting;
      if (visible) start();
      else stop();
    });
    io.observe(hero);
    document.addEventListener('visibilitychange', onVis);
    const ro = new ResizeObserver(resize);
    ro.observe(hero);
    canvas.addEventListener('pointermove', onMove, { passive: true });
    canvas.addEventListener('pointerdown', onDown);

    resize();
    // open alive: one wave already crossing from the largest solution
    if (!mobile && !reduced && balls.length) {
      const b = balls.reduce((a, c) => (c.size > a.size ? c : a));
      const { p, s } = radiationLobes(b.M, N_LOBE);
      events.push({ x: b.x, y: b.y, t0: performance.now() - 1300, mag: 0.45, pl: p, sl: s });
    }
    start();

    return () => {
      stop();
      io.disconnect();
      ro.disconnect();
      document.removeEventListener('visibilitychange', onVis);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerdown', onDown);
    };
  }, [palette]);

  return <canvas ref={ref} className="hero-backdrop" aria-hidden="true" />;
}
