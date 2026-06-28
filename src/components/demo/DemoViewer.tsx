import { useEffect, useMemo, useState } from 'react';
import './demo.css';
import MapView from './MapView';
import EventPanel from './EventPanel';
import TimeSlider from './TimeSlider';
import { type EventCollection, sourceColor } from './types';

const DATA_URL = `${import.meta.env.BASE_URL}demo/events.json`;
const DAY = 86400_000;

const LEGEND = [
  { label: 'Double-couple', type: 'double-couple' },
  { label: 'Strike-slip', type: 'strike-slip' },
  { label: 'CLVD-leaning', type: 'clvd' },
  { label: 'Volcanic / −ISO', type: 'volcanic / -iso' },
];

export default function DemoViewer() {
  const [coll, setColl] = useState<EventCollection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cutoff, setCutoff] = useState<number>(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(DATA_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: EventCollection) => {
        if (!alive) return;
        setColl(data);
        setCutoff(Date.parse(data.generated));
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  const generatedMs = coll ? Date.parse(coll.generated) : 0;
  const minMs = coll ? generatedMs - coll.window_days * DAY : 0;
  const maxMs = generatedMs;

  const allSorted = useMemo(
    () =>
      coll
        ? [...coll.features].sort(
            (a, b) => Date.parse(b.properties.time) - Date.parse(a.properties.time),
          )
        : [],
    [coll],
  );
  const visible = useMemo(
    () => allSorted.filter((f) => Date.parse(f.properties.time) <= cutoff),
    [allSorted, cutoff],
  );

  // Keep the selection valid as the time window changes.
  useEffect(() => {
    if (!coll) return;
    const ids = new Set(visible.map((f) => f.properties.id));
    if (selectedId && ids.has(selectedId)) return;
    setSelectedId(visible.length ? visible[0].properties.id : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, coll]);

  const selected = visible.find((f) => f.properties.id === selectedId) ?? null;

  if (error) {
    return (
      <div className="demo-app">
        <div className="demo-stage">
          <div className="demo-skeleton">Could not load demo data ({error}).</div>
        </div>
      </div>
    );
  }

  return (
    <div className="demo-app">
      <div className="demo-stage">
        {coll ? (
          <MapView events={visible} selectedId={selectedId} onSelect={setSelectedId} />
        ) : (
          <div className="demo-skeleton">Loading map…</div>
        )}
        <div className="demo-banner">
          Demo preview — representative mock data; live F-net feed coming soon
        </div>
        <div className="demo-legend" aria-hidden="true">
          {LEGEND.map((l) => (
            <div className="demo-legend__row" key={l.type}>
              <span className="demo-legend__dot" style={{ background: sourceColor(l.type) }} />
              {l.label}
            </div>
          ))}
        </div>
      </div>

      <EventPanel event={selected} />

      <TimeSlider
        minMs={minMs}
        maxMs={maxMs}
        valueMs={cutoff || maxMs}
        visible={visible.length}
        total={allSorted.length}
        onChange={setCutoff}
        onReset={() => setCutoff(maxMs)}
      />
    </div>
  );
}
