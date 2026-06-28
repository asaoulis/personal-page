interface Props {
  minMs: number;
  maxMs: number;
  startMs: number;
  endMs: number;
  visible: number;
  total: number;
  onChange: (startMs: number, endMs: number) => void;
  onReset: () => void;
}

function fmtDate(ms: number): string {
  return new Date(ms).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}
function fmtShort(ms: number): string {
  return new Date(ms).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    timeZone: 'UTC',
  });
}

const HOUR = 3600_000;

/**
 * Two-handle date-range selector. The map + count show events whose origin time falls inside
 * [start, end]. Implemented as two overlaid native range inputs (keyboard + touch accessible) with
 * a highlighted track between the handles.
 */
export default function RangeSlider({
  minMs,
  maxMs,
  startMs,
  endMs,
  visible,
  total,
  onChange,
  onReset,
}: Props) {
  const span = Math.max(1, maxMs - minMs);
  const startPct = ((startMs - minMs) / span) * 100;
  const endPct = ((endMs - minMs) / span) * 100;
  const full = startMs <= minMs && endMs >= maxMs;

  const setStart = (v: number) => onChange(Math.min(v, endMs - HOUR), endMs);
  const setEnd = (v: number) => onChange(startMs, Math.max(v, startMs + HOUR));

  return (
    <div className="demo-controls">
      <div className="demo-controls__head">
        <span className="demo-controls__now">
          {fmtDate(startMs)} — {fmtDate(endMs)}
        </span>
        <span className="demo-controls__count">
          {visible} / {total} events in range
        </span>
      </div>

      <div className="demo-rangewrap">
        <div className="demo-rangetrack" />
        <div
          className="demo-rangefill"
          style={{ left: `${startPct}%`, width: `${Math.max(0, endPct - startPct)}%` }}
        />
        <input
          className="demo-range demo-range--start"
          type="range"
          min={minMs}
          max={maxMs}
          step={HOUR}
          value={startMs}
          aria-label="Range start date"
          onChange={(e) => setStart(Number(e.target.value))}
        />
        <input
          className="demo-range demo-range--end"
          type="range"
          min={minMs}
          max={maxMs}
          step={HOUR}
          value={endMs}
          aria-label="Range end date"
          onChange={(e) => setEnd(Number(e.target.value))}
        />
      </div>

      <div className="demo-controls__ticks">
        <span>{fmtShort(minMs)}</span>
        <span>{fmtShort((minMs + maxMs) / 2)}</span>
        <span>{fmtShort(maxMs)}</span>
      </div>

      <div className="demo-controls__row">
        <button className="demo-btn" type="button" onClick={onReset} disabled={full}>
          Show full range
        </button>
        <span style={{ fontSize: 'var(--step--1)', color: 'var(--ink-faint)' }}>
          Drag either handle to select a window over the catalogue.
        </span>
      </div>
    </div>
  );
}
