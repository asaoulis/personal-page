import type { EventSummaryProps } from './types';

/** The selectable marker colour-by modes. */
export type ColorMode = 'dc' | 'fault' | 'sourcetype';

const PALETTE = {
  dc: '#2547ad', // double-couple (blue)
  nonDC: '#b4452b', // resolvably non-DC (oxblood)
  normal: '#2547ad',
  thrust: '#b4452b',
  strike: '#0f8a7e',
  iso: '#b4452b',
  clvd: '#d4801e',
};

/** Posterior probability threshold for calling an event resolvably non-DC. */
export const NON_DC_THRESHOLD = 0.95;

export interface ColorModeDef {
  id: ColorMode;
  label: string;
  legend: { label: string; color: string }[];
}

export const COLOR_MODES: ColorModeDef[] = [
  {
    id: 'dc',
    label: 'DC vs non-DC',
    legend: [
      { label: 'Double-couple', color: PALETTE.dc },
      { label: `Non-DC (≥95% outside ±10° box)`, color: PALETTE.nonDC },
    ],
  },
  {
    id: 'fault',
    label: 'Faulting style',
    legend: [
      { label: 'Thrust / reverse', color: PALETTE.thrust },
      { label: 'Normal', color: PALETTE.normal },
      { label: 'Strike-slip', color: PALETTE.strike },
    ],
  },
  {
    id: 'sourcetype',
    label: 'DC / ISO / CLVD',
    legend: [
      { label: 'Double-couple', color: PALETTE.dc },
      { label: 'Isotropic', color: PALETTE.iso },
      { label: 'CLVD', color: PALETTE.clvd },
    ],
  },
];

/** Faulting style from rake (Aki convention): reverse ~+90°, normal ~−90°, else strike-slip. */
export function faultStyle(rake: number): 'thrust' | 'normal' | 'strike' {
  const r = ((rake % 360) + 360) % 360;
  if (r > 45 && r < 135) return 'thrust';
  if (r > 225 && r < 315) return 'normal';
  return 'strike';
}

/** Coarse source type from lune (γ, δ): near origin = DC, else whichever of isotropic (δ) or
 * CLVD (γ) dominates (scaled by their respective ranges). */
export function sourceTypeClass(gamma: number, delta: number): 'dc' | 'iso' | 'clvd' {
  if (Math.abs(gamma) <= 10 && Math.abs(delta) <= 10) return 'dc';
  return Math.abs(delta) / 90 >= Math.abs(gamma) / 30 ? 'iso' : 'clvd';
}

/** Marker colour for an event under the chosen mode. */
export function markerColor(p: EventSummaryProps, mode: ColorMode): string {
  if (mode === 'fault') {
    const f = faultStyle(p.rake);
    return f === 'thrust' ? PALETTE.thrust : f === 'normal' ? PALETTE.normal : PALETTE.strike;
  }
  if (mode === 'sourcetype') {
    const s = sourceTypeClass(p.gamma, p.delta);
    return s === 'iso' ? PALETTE.iso : s === 'clvd' ? PALETTE.clvd : PALETTE.dc;
  }
  return (p.p_outside_dc_box ?? 0) >= NON_DC_THRESHOLD ? PALETTE.nonDC : PALETTE.dc;
}
