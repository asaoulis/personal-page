# F-net inference worker (skeleton)

The scheduled, decoupled "precompute" worker behind the `/demo` page. It detects new
Japan-region earthquakes, runs inference, and writes the **v2 data contract** the frontend
renders client-side. This is the **M-D1 skeleton**: everything works end-to-end **except the
model** — inference is a deterministic MOCK. Real NPE inference is **M-D2**.

See **`../docs/ARCHITECTURE.md` §6** for the full design (triggers, F-net fetch via HinetPy,
archive-lag delay window, stateful resume, validation overlays, latency budget).

## What it does

```
poll catalogue (USGS FDSN)  ->  filter (region, M>=3.5, delay window, dedup)
  ->  infer per event (MOCK now / seismo_sbi NPE at M-D2)
  ->  write events/<id>.json (the (gamma,delta) posterior ensemble + reference)
  ->  rebuild events.json index (prune the rolling window)
  ->  save state.json (resume point + backlog)
```

## Output (the v2 contract)

```
<out>/events.json        GeoJSON index — one summary Feature per event (+ `ensemble` pointer)
<out>/events/<id>.json   full record: posterior {gamma[], delta[]}, strike/dip/rake, reference
<out>/state.json         worker-only resume state (NOT served to the frontend)
```

Plots are **not** rendered here — the frontend draws the lune (SVG) and beachball (canvas)
from this JSON, so the artifacts stay tiny (~5 KB/event).

## Run

```sh
pip install -r requirements.txt

# Regenerate the committed demo fixtures (curated catalogue, fixed timestamp):
python -m fnet_monitor.run --out ../public/demo --source demo --now 2026-06-28T00:00:00Z

# Live poll (still MOCK inference until M-D2):
python -m fnet_monitor.run --out <results-dir> --source usgs
```

In production the GitHub Actions workflow (`.github/workflows/update-events.yml`) runs this on a
~30-min cron and publishes the results to the orphan **`data`** branch (JSON-only → no git bloat).

## Tests

```sh
python -m pytest          # no network — the FDSN call is injected behind a fixture
```

## Layout

| File           | Role                                                            |
| -------------- | --------------------------------------------------------------- |
| `config.py`    | region bbox, thresholds, delay/retention windows                |
| `catalogue.py` | FDSN poll + parse + filter/dedup (`fetcher` injected for tests) |
| `inference.py` | **mock** posterior ensemble (real `seismo_sbi` NPE = M-D2)      |
| `contract.py`  | v2 schema + index/per-event writers + validators                |
| `state.py`     | `state.json` resume state                                       |
| `demo.py`      | curated catalogue for the offline `/demo` fixtures              |
| `run.py`       | orchestrator CLI                                                |

## Next (M-D2)

Replace `inference.real_posterior` with: fetch F-net waveforms (HinetPy, network code `0103`,
`win32tools` for WIN32→SAC), load the trained `seismo_sbi` NPE + Green's-function DB **once per
run**, sample the posterior (~seconds/event on CPU), and pull the reference MT
(`obspy.io.nied.fnetmt`). Same output shape — nothing else changes.
