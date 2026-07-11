/** v3 data contract — compact JSON the browser renders into plots client-side.
 * Shared shape between the worker output and this frontend. Keep in lockstep with
 * `worker/fnet_monitor/contract.py` (SCHEMA_VERSION = 3). */

/** Probabilistic source-type block (lune-box exclusion metric): the label claims non-DC
 * ONLY when >=95% of the posterior lies outside the +/-10 deg near-DC lune box, otherwise
 * "DC-consistent". Older bundled snapshots carry a plain string instead. */
export interface SourceTypeBlock {
  p_outside_dc_box_10: number; // posterior P(outside the +/-10 deg near-DC lune box)
  label: string; // "DC-consistent" | "non-DC (+ISO|-ISO|+CLVD|-CLVD)"
}
export type SourceType = string | SourceTypeBlock;

export function sourceTypeLabel(st: SourceType): string {
  return typeof st === 'string' ? st : st.label;
}

/** A summary feature in the `events.json` index (drives the map + slider). */
export interface EventSummaryProps {
  id: string;
  time: string; // ISO 8601
  mag: number;
  magType: string;
  depth_km: number;
  region: string;
  source_type: SourceType;
  gamma: number; // posterior-mean lune coords
  delta: number;
  strike: number;
  dip: number;
  rake: number;
  mw: number | null; // solution moment magnitude (from the primary reference / model), if known
  p_outside_dc_box: number | null; // posterior prob. outside the ±10° near-DC lune box (non-DC metric)
  primary_source: string; // catalogue source of the primary reference ("pending" when none yet)
  primary_kagan_deg: number | null; // Kagan angle model vs primary reference
  n_references: number;
  ensemble: string; // relative path to the per-event record, e.g. "events/<id>.json"
}

export interface EventFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] }; // [lon, lat]
  properties: EventSummaryProps;
}

export interface EventIndex {
  type: 'FeatureCollection';
  schema?: number;
  generated: string;
  window_days: number;
  window_start: string; // ISO — slider lower bound (oldest event / window start)
  window_end: string; // ISO — slider upper bound (newest event / window end)
  region?: string;
  mock?: boolean;
  features: EventFeature[];
}

/** One catalogue reference solution attached to an event. */
export interface Reference {
  source: string; // "GCMT" | "USGS" | "F-net" | "synthetic" | ...
  gamma: number;
  delta: number;
  strike: number;
  dip: number;
  rake: number;
  mt6: number[]; // [Mrr, Mtt, Mpp, Mrt, Mrp, Mtp] (USE / GCMT convention)
  kagan_deg: number; // Kagan angle vs the model best solution
  mw?: number | null;
}

/** The lazily-fetched per-event record carrying the posterior ensemble + all references. */
export interface EventRecord {
  schema?: number;
  id: string;
  time: string;
  mag: number;
  magType: string;
  depth_km: number;
  lon: number;
  lat: number;
  region: string;
  source_type: SourceType;
  strike: number;
  dip: number;
  rake: number;
  mw: number | null;
  p_outside_dc_box: number | null;
  posterior: {
    gamma: number[];
    delta: number[];
    mt6: number[][]; // downsampled MT ensemble (USE) — drives the fuzzy beachball
  };
  summary: { gamma: number; delta: number };
  /** Primary first. MAY BE EMPTY: a USGS-discovered event is published within ~1 h with the
   * F-net reference PENDING (the record is replaced when NIED publishes the F-net MT). */
  references: Reference[];
  provenance: { generated: string; mock: boolean; model: string };
}

/** Marker colour by (coarse) source type. */
export function sourceColor(sourceType: SourceType): string {
  const s = sourceTypeLabel(sourceType).toLowerCase();
  if (s.includes('strike')) return '#0f8a7e';
  if (s.includes('iso') || s.includes('volcan')) return '#b4452b';
  if (s.includes('clvd')) return '#d4801e';
  return '#2547ad'; // double-couple
}

export function markerSize(mag: number): number {
  return Math.round(11 + Math.max(0, mag - 3.5) * 5);
}

export type RefShape = 'star' | 'square' | 'triangle' | 'diamond' | 'circle';

/** Distinct lune/legend marker per reference catalogue (mirrors the science plotter). */
export function referenceMarker(source: string): RefShape {
  const s = source.toLowerCase();
  if (s.includes('gcmt')) return 'star';
  if (s.includes('usgs')) return 'square';
  if (s.includes('f-net') || s.includes('fnet')) return 'triangle';
  if (s.includes('synth')) return 'diamond';
  return 'circle';
}
