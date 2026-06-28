import { type EventFeature } from './types';

interface Props {
  event: EventFeature | null;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return (
    d.toLocaleString('en-GB', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'UTC',
    }) + ' UTC'
  );
}

export default function EventPanel({ event }: Props) {
  if (!event) {
    return (
      <aside className="demo-panel" aria-live="polite">
        <p className="demo-panel__empty">Select an event on the map to see its inferred source.</p>
      </aside>
    );
  }

  const p = event.properties;
  const [lon, lat] = event.geometry.coordinates;

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
              <img src={p.assets.lune} alt={`Source-type lune posterior for ${p.region}`} />
            </div>
            <figcaption>Posterior on the lune</figcaption>
          </figure>
          <figure className="demo-fig">
            <div className="demo-fig__frame">
              <img src={p.assets.beachball} alt={`Beachball for ${p.region}`} />
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
          <dt>Lune (γ, δ)</dt>
          <dd>
            {p.gamma.toFixed(1)}°, {p.delta.toFixed(1)}°
          </dd>
        </dl>
      </div>
    </aside>
  );
}
