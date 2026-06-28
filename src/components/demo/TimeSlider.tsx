interface Props {
  minMs: number;
  maxMs: number;
  valueMs: number;
  visible: number;
  total: number;
  onChange: (ms: number) => void;
  onReset: () => void;
}

function fmtDate(ms: number): string {
  return new Date(ms).toLocaleString('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
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

export default function TimeSlider({
  minMs,
  maxMs,
  valueMs,
  visible,
  total,
  onChange,
  onReset,
}: Props) {
  const atNow = valueMs >= maxMs;
  return (
    <div className="demo-controls">
      <div className="demo-controls__head">
        <span className="demo-controls__now">{fmtDate(valueMs)} UTC</span>
        <span className="demo-controls__count">
          {visible} / {total} events shown
        </span>
      </div>

      <input
        className="demo-range"
        type="range"
        min={minMs}
        max={maxMs}
        step={HOUR}
        value={valueMs}
        aria-label="Scrub through time"
        onChange={(e) => onChange(Number(e.target.value))}
      />

      <div className="demo-controls__ticks">
        <span>{fmtShort(minMs)}</span>
        <span>{fmtShort((minMs + maxMs) / 2)}</span>
        <span>now</span>
      </div>

      <div className="demo-controls__row">
        <button className="demo-btn" type="button" onClick={onReset} disabled={atNow}>
          Jump to now
        </button>
        <span style={{ fontSize: 'var(--step--1)', color: 'var(--ink-faint)' }}>
          Scrub back up to {Math.round((maxMs - minMs) / (24 * HOUR))} days. Events appear as time
          advances.
        </span>
      </div>
    </div>
  );
}
