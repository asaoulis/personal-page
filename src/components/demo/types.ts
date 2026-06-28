/** Data contract shared by the mock GeoJSON and the future live worker output. */

export interface EventProps {
  id: string;
  time: string; // ISO 8601
  mag: number;
  magType: string;
  depth_km: number;
  region: string;
  source_type: string;
  gamma: number; // lune longitude (deg)
  delta: number; // lune latitude (deg)
  kagan_deg: number;
  strike: number;
  dip: number;
  rake: number;
  catalogue_source: string;
  assets: { beachball: string; lune: string };
}

export interface EventFeature {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] }; // [lon, lat]
  properties: EventProps;
}

export interface EventCollection {
  type: 'FeatureCollection';
  generated: string;
  window_days: number;
  mock?: boolean;
  note?: string;
  features: EventFeature[];
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
