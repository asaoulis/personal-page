import { useEffect, useState } from 'react';
import Lune from './Lune';
import Beachball from './Beachball';
import { MarkerShape, referenceColor } from './markers';
import {
  type EventFeature,
  type EventRecord,
  type Reference,
  referenceMarker,
  sourceColor,
} from './types';

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

/** A tiny inline source glyph (matches the lune markers + the map). */
function RefGlyph({ source }: { source: string }) {
  return (
    <svg width="13" height="13" viewBox="-1 -1 2 2" aria-hidden="true" className="ref-glyph">
      <MarkerShape
        shape={referenceMarker(source)}
        cx={0}
        cy={0}
        r={0.85}
        color={referenceColor(source)}
      />
    </svg>
  );
}

function refLabel(source: string): string {
  const s = source.toLowerCase();
  if (s.includes('synth')) return 'Synthetic (no catalogue MT)';
  return source;
}

export default function EventPanel({ feature }: Props) {
  const [record, setRecord] = useState<EventRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

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
  const refs: Reference[] = record?.references ?? [];

  return (
    <aside className="demo-panel" aria-live="polite">
      <div className="demo-panel__head">
        <button
          className="demo-panel__collapse"
          type="button"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? '▸' : '▾'}
        </button>
        <p className="demo-panel__region">{p.region}</p>
        <p className="demo-panel__time">{fmtTime(p.time)}</p>
        <div className="demo-chips">
          <span className="demo-chip">
            <strong>
              {p.magType} {p.mag.toFixed(1)}
            </strong>
          </span>
          {p.mw != null && <span className="demo-chip">Mw {p.mw.toFixed(1)}</span>}
          <span className="demo-chip">{p.depth_km} km deep</span>
          <span className="demo-chip">{p.source_type}</span>
        </div>
      </div>

      {!collapsed && (
        <div className="demo-panel__body">
          <div className="demo-figs">
            <figure className="demo-fig demo-fig--lune">
              <div className="demo-fig__frame">
                {record ? (
                  <Lune
                    gamma={record.posterior.gamma}
                    delta={record.posterior.delta}
                    mean={record.summary}
                    references={refs}
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
                {record ? (
                  <Beachball samples={record.posterior.mt6} color={col} size={132} />
                ) : (
                  <div className="demo-fig__loading">{error ? '—' : '…'}</div>
                )}
              </div>
              <figcaption>Posterior mechanism</figcaption>
            </figure>
          </div>

          {refs.length > 0 && (
            <div className="demo-refs">
              <p className="demo-refs__title">
                Catalogue solutions vs model <span className="demo-refs__hint">(Kagan angle)</span>
              </p>
              <div className="demo-refs__row">
                {refs.map((ref, i) => (
                  <figure className="demo-ref" key={`${ref.source}-${i}`}>
                    <Beachball
                      strike={ref.strike}
                      dip={ref.dip}
                      rake={ref.rake}
                      color={referenceColor(ref.source)}
                      size={62}
                    />
                    <figcaption className="demo-ref__cap">
                      <span className="demo-ref__src">
                        <RefGlyph source={ref.source} /> {refLabel(ref.source)}
                      </span>
                      <span className="demo-ref__num">
                        {ref.mw != null ? `Mw ${ref.mw.toFixed(1)} · ` : ''}
                        {ref.kagan_deg.toFixed(0)}°
                      </span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          )}

          <dl className="demo-meta">
            <dt>Origin time</dt>
            <dd>{fmtTime(p.time)}</dd>
            <dt>Location</dt>
            <dd>
              {lat.toFixed(2)}°, {lon.toFixed(2)}°
            </dd>
            <dt>Depth</dt>
            <dd>{p.depth_km} km</dd>
            <dt>Model strike / dip / rake</dt>
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
      )}
    </aside>
  );
}
