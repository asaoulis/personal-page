import { useEffect, useState } from 'react';
import Lune from './Lune';
import Beachball from './Beachball';
import { type EventFeature, type EventRecord, sourceColor } from './types';

interface Props {
  feature: EventFeature | null;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC'
  );
}

const DATA_BASE = `${import.meta.env.BASE_URL}demo/`;

export default function EventPanel({ feature }: Props) {
  const [record, setRecord] = useState<EventRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!feature) return;
    let alive = true;
    setRecord(null);
    setError(null);
    fetch(DATA_BASE + feature.properties.ensemble)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((rec: EventRecord) => alive && setRecord(rec))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [feature]);

  if (!feature) {
    return (
      <aside className="demo-panel" aria-live="polite">
        <p className="demo-panel__empty">Select an event on the map to see its inferred source.</p>
      </aside>
    );
  }

  const p = feature.properties;
  const [lon, lat] = feature.geometry.coordinates;
  const col = sourceColor(p.source_type);

  return (
    <aside className="demo-panel" aria-live="polite">
      <div className="demo-panel__head">
        <p className="demo-panel__region">{p.region}</p>
        <p className="demo-panel__time">{fmtTime(p.time)}</p>
        <div className="demo-chips">
          <span className="demo-chip">
            <strong>
              {p.magType} {p.mag.toFixed(1)}
            </strong>
          </span>
          <span className="demo-chip">{p.depth_km} km deep</span>
          <span className="demo-chip">{p.source_type}</span>
        </div>
      </div>

      <div className="demo-panel__body">
        <div className="demo-figs">
          <figure className="demo-fig demo-fig--lune">
            <div className="demo-fig__frame">
              {record ? (
                <Lune
                  gamma={record.posterior.gamma}
                  delta={record.posterior.delta}
                  mean={record.summary}
                  reference={record.reference}
                  accent={col}
                />
              ) : (
                <div className="demo-fig__loading">{error ? '—' : '…'}</div>
              )}
            </div>
            <figcaption>Posterior on the lune</figcaption>
          </figure>
          <figure className="demo-fig">
            <div className="demo-fig__frame">
              <Beachball strike={p.strike} dip={p.dip} rake={p.rake} color={col} size={132} />
            </div>
            <figcaption>Moment tensor</figcaption>
          </figure>
        </div>

        <div className="demo-kagan">
          Model vs catalogue: <strong>{p.kagan_deg.toFixed(1)}° Kagan angle</strong>{' '}
          <span style={{ color: 'var(--ink-faint)' }}>(source: {p.catalogue_source})</span>
        </div>

        <dl className="demo-meta">
          <dt>Origin time</dt>
          <dd>{fmtTime(p.time)}</dd>
          <dt>Location</dt>
          <dd>
            {lat.toFixed(2)}°, {lon.toFixed(2)}°
          </dd>
          <dt>Depth</dt>
          <dd>{p.depth_km} km</dd>
          <dt>Strike / dip / rake</dt>
          <dd>
            {p.strike} / {p.dip} / {p.rake}
          </dd>
          <dt>Posterior mean (γ, δ)</dt>
          <dd>
            {p.gamma.toFixed(1)}°, {p.delta.toFixed(1)}°
          </dd>
          <dt>Ensemble</dt>
          <dd>{record ? `${record.posterior.gamma.length} samples` : '…'}</dd>
        </dl>
      </div>
    </aside>
  );
}
