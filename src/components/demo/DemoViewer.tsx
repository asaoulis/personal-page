import { useEffect, useMemo, useState } from 'react';
import './demo.css';
import MapView from './MapView';
import EventPanel from './EventPanel';
import RangeSlider from './RangeSlider';
import { type EventIndex, markerSize } from './types';
import { type ColorMode, COLOR_MODES } from './coloring';

const DATA_URL = `${import.meta.env.BASE_URL}demo/events.json`;
const MAG_LEGEND = [4.0, 5.0, 6.0];

export default function DemoViewer() {
  const [coll, setColl] = useState<EventIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<[number, number] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [colorMode, setColorMode] = useState<ColorMode>('dc');

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
  const legend = COLOR_MODES.find((m) => m.id === colorMode)!;

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
          <MapView
            events={visible}
            selectedId={selectedId}
            onSelect={setSelectedId}
            colorMode={colorMode}
          />
        ) : (
          <div className="demo-skeleton">Loading map…</div>
        )}
        <div className="demo-banner">
          Demo preview — real F-net catalogue (Jan 2026), illustrative posteriors; live feed coming
          soon
        </div>

        <div className="demo-legend">
          <label className="demo-legend__control">
            <span>Colour by</span>
            <select
              value={colorMode}
              onChange={(e) => setColorMode(e.target.value as ColorMode)}
              aria-label="Colour markers by"
            >
              {COLOR_MODES.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <div className="demo-legend__rows">
            {legend.legend.map((l) => (
              <div className="demo-legend__row" key={l.label}>
                <span className="demo-legend__dot" style={{ background: l.color }} />
                {l.label}
              </div>
            ))}
          </div>
          <div className="demo-legend__sizes" aria-label="Marker size shows magnitude">
            {MAG_LEGEND.map((m) => (
              <div className="demo-legend__size" key={m}>
                <span
                  className="demo-legend__sizedot"
                  style={{ width: markerSize(m), height: markerSize(m) }}
                />
                <span className="demo-legend__sizelabel">M{m.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <EventPanel feature={selected} colorMode={colorMode} />

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
