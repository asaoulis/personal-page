import { useEffect, useMemo, useState } from 'react';
import './demo.css';
import MapView from './MapView';
import EventPanel from './EventPanel';
import RangeSlider from './RangeSlider';
import { type EventIndex, sourceColor } from './types';

const DATA_URL = `${import.meta.env.BASE_URL}demo/events.json`;

const LEGEND = [
  { label: 'Double-couple', type: 'double-couple' },
  { label: 'Strike-slip', type: 'strike-slip' },
  { label: 'CLVD-leaning', type: 'clvd' },
  { label: 'Volcanic / −ISO', type: 'volcanic / -iso' },
];

export default function DemoViewer() {
  const [coll, setColl] = useState<EventIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch(DATA_URL)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: EventIndex) => {
        if (!alive) return;
        setColl(data);
        setRange([Date.parse(data.window_start), Date.parse(data.window_end)]);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  const minMs = coll ? Date.parse(coll.window_start) : 0;
  const maxMs = coll ? Date.parse(coll.window_end) : 0;
  const [startMs, endMs] = range ?? [minMs, maxMs];

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
    () =>
      allSorted.filter((f) => {
        const t = Date.parse(f.properties.time);
        return t >= startMs && t <= endMs;
      }),
    [allSorted, startMs, endMs],
  );

  // Keep the selection valid as the window changes.
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
          Demo preview — real F-net catalogue (Jan 2026), illustrative posteriors; live feed coming
          soon
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

      <EventPanel feature={selected} />

      {coll && (
        <RangeSlider
          minMs={minMs}
          maxMs={maxMs}
          startMs={startMs}
          endMs={endMs}
          visible={visible.length}
          total={allSorted.length}
          onChange={(s, e) => setRange([s, e])}
          onReset={() => setRange([minMs, maxMs])}
        />
      )}
    </div>
  );
}
