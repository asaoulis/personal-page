/** v2 data contract — compact JSON the browser renders into plots client-side.
 * Shared shape between the worker output and this frontend. */

/** A summary feature in the `events.json` index (drives the map + slider). */
export interface EventSummaryProps {
  id: string;
  time: string; // ISO 8601
  mag: number;
  magType: string;
  depth_km: number;
  region: string;
  source_type: string;
  gamma: number; // posterior-mean lune coords
  delta: number;
  strike: number;
  dip: number;
  rake: number;
  kagan_deg: number;
  catalogue_source: string;
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
  region?: string;
  mock?: boolean;
  features: EventFeature[];
}

/** The lazily-fetched per-event record carrying the posterior ensemble. */
export interface EventRecord {
  id: string;
  time: string;
  mag: number;
  magType: string;
  depth_km: number;
  lon: number;
  lat: number;
  region: string;
  source_type: string;
  strike: number;
  dip: number;
  rake: number;
  posterior: { gamma: number[]; delta: number[] };
  summary: { gamma: number; delta: number };
  reference: {
    source: string;
    gamma: number;
    delta: number;
    strike: number;
    dip: number;
    rake: number;
    kagan_deg: number;
  };
  provenance: { generated: string; mock: boolean; model: string };
}

/** Marker colour by (coarse) source type. */
export function sourceColor(sourceType: string): string {
  const s = sourceType.toLowerCase();
  if (s.includes('strike')) return '#0f8a7e';
  if (s.includes('iso') || s.includes('volcan')) return '#b4452b';
  if (s.includes('clvd')) return '#d4801e';
  return '#2547ad'; // double-couple
}

export function markerSize(mag: number): number {
  return Math.round(13 + Math.max(0, mag - 3.5) * 6);
}
