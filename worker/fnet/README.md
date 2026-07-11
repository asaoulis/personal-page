# F-net download adapter (`fetch_fnet.py`)

Pulls F-net (NIED win network `0103` / FDSN `BO`) continuous broadband waveforms via
**HinetPy**, converts win32 → SAC (`win2sac_32`) → MiniSEED in the **exact** on-disk layout the
`seismo-sbi` catalogue pipeline expects, so `scripts/build_catalogue.py` runs **unchanged** on the
output:

```
{out}/{station}/{YYYY.DDD}/{net}.{sta}.{loc}.{cha}.{YYYY}.{DDD}.mseed
        e.g.  /data/alex/fnet_japan/raw/ABU/2026.001/BO.ABU..BHZ.2026.001.mseed
```

Channels are written as `BHZ` / `BHN` / `BHE` (band code configurable with `--band`), which
`seismo_sbi…sbi_export._rename_component` maps to `Z` / `2` / `1`.

## Prerequisites

- conda env `seismo-sbi` (HinetPy v0.10.0; `obspy`; `python-dotenv`).
- `catwin32` + `win2sac_32` on `PATH` (already at `~/.local/bin/`; otherwise build from
  `scripts/win32tools.tar.gz` in the science repo).
- **Credentials** in the worker dotenv (gitignored): `FNET_USERNAME` and `FNET_PASSWORD`
  (your NIED Hi-net/F-net account). They are loaded **internally** by `fetch_fnet.py` via
  `python-dotenv`; they are **never** logged, printed, or passed on a command line. You only need
  a NIED account — no token on the CLI.

## Response / units decision (risk #1 — **path (b)**, may need user confirmation)

`win2sac_32` **always** removes the scalar instrument sensitivity and multiplies by `1e9`, so its
SAC output is ground **velocity in nm/s** (not digital counts), and `win32.extract_sacpz` is
**Hi-net only** (no F-net pole-zeros). So the usual "raw counts + StationXML → DISP" route does not
apply to F-net. This adapter takes **path (b)**:

```
velocity[nm/s]  --(/1e9)-->  velocity[m/s]  --(integrate)-->  displacement[m]   (default --units displacement)
```

then writes displacement MiniSEED and you run `build_catalogue.py` with **no StationXML**
(`remove_response=False` → only taper/bandpass/resample). Result: displacement in **metres**,
matching the Instaseis synthetics.

**Why this is valid:** the default inversion band (0.02–0.05 Hz = 20–50 s) lies inside the
flat-to-velocity passband of F-net STS-1/STS-2 broadband sensors, so removing only the scalar
sensitivity recovers true ground velocity across the band.

**⚠ Confirm with the analysis owner before the full pull:** if your passband extends **below
~0.0083 Hz (120 s, the STS-2 corner)** — or ~360 s for STS-1 sites — the flat-response assumption
breaks and you must use **path (a)**: fetch full RESP from the F-net website `response.php` (or pull
StationXML from IRIS, see fallback below) and run `build_catalogue` **with** `--stationxml_dir` so
the _full_ response is deconvolved to DISP. For the planned 20–50 s band, path (b) is correct.

(`--units velocity` writes m/s without integrating; `--units raw` keeps win2sac nm/s untouched.)

## (a) Smoke — ONE station, ONE day (creds-gated)

```bash
cd /home/alex/work/personal-page
REPO=/home/alex/work/seismo-sbi

# 1-line stations file (FDSN 'CODE NET lat lon'); ABU is a long-running main-arc STS site.
printf 'ABU BO 34.8635 135.5706\n' > /tmp/fnet_one_station.txt

# Fetch a single UTC day into the standard layout (creds read from the worker dotenv).
conda run -n seismo-sbi python worker/fnet/fetch_fnet.py \
    --stations /tmp/fnet_one_station.txt \
    --start 2026-01-01T00:00:00 --end 2026-01-02T00:00:00 \
    --out /data/alex/fnet_japan/raw

# Expect: /data/alex/fnet_japan/raw/ABU/2026.001/BO.ABU..BH{Z,N,E}.2026.001.mseed
ls /data/alex/fnet_japan/raw/ABU/2026.001/

# Prove the seismo-sbi stack ingests it UNCHANGED: build a 1-event mini catalogue.
# (Make a one-event QuakeML whose origin falls inside the fetched UTC day, e.g.
#  obspy: cat = Catalog([Event(origins=[Origin(time=UTCDateTime('2026-01-01T03:00:00'),
#  latitude=..., longitude=..., depth=...)], magnitudes=[Magnitude(mag=4.5)])]);
#  cat.write('/tmp/one_event.xml','QUAKEML'))   -- no StationXML is passed (path b).
conda run -n seismo-sbi python $REPO/scripts/build_catalogue.py \
    --catalogue /tmp/one_event.xml \
    --data_dir /data/alex/fnet_japan/raw \
    --stations_file /tmp/fnet_one_station.txt \
    --output_dir /data/alex/fnet_japan/catalogue \
    --duration 200 --sampling_rate 1.0 \
    --no_noise --n_jobs 1

# Assert the locked h5 contract (keys Z/1/2, length compute_data_vector_length(dur,sr)+1):
conda run -n seismo-sbi python - <<'PY'
import h5py, glob
from seismo_sbi.instaseis_simulator.utils import compute_data_vector_length
f = sorted(glob.glob('/data/alex/fnet_japan/catalogue/events/*.h5'))[0]
with h5py.File(f, 'r') as h:
    sta = [k for k in h.keys() if k != 'misc'][0]
    comps = sorted(h[sta].keys())
    n = h[sta]['Z'].shape[0]
print('event h5:', f, '| station', sta, '| components', comps, '| npts', n,
      '| expected', compute_data_vector_length(200, 1.0) + 1)
assert comps == ['1', '2', 'Z']
PY
```

## (b) Full Jan-2026 month (creds-gated — multi-GB; only after smoke + user OK)

```bash
cd /home/alex/work/personal-page
# Default --stations is the task's artifacts/stations_candidate.txt (S5 draft); point at the
# final scripts/configs/japan/stations.txt once it exists. Inspect the plan first with --dry-run.
conda run -n seismo-sbi python worker/fnet/fetch_fnet.py --month 2026-01 --dry-run

conda run -n seismo-sbi python worker/fnet/fetch_fnet.py \
    --stations /home/alex/work/seismo-sbi/scripts/configs/japan/stations.txt \
    --month 2026-01 \
    --out /data/alex/fnet_japan/raw \
    --threads 3
```

One HinetPy request per **UTC calendar day**, requested in **JST** (anchored at 09:00 JST = 00:00
UTC) and shared across all stations; HinetPy auto-splits each day via `max_span` to honour the
server limits (record ≤ 60 min, channels × record ≤ 12000 min, only the latest 150 requests kept).
Throttle with `--threads` and override the split with `--max-span` if needed.

## (c) Build the event + noise catalogue over the month (`build_catalogue.py` unchanged)

```bash
REPO=/home/alex/work/seismo-sbi
conda run -n seismo-sbi python $REPO/scripts/build_catalogue.py \
    --catalogue /home/alex/work/seismo-sbi/.claude/runs/personal-page/fnet-data-sourcing/artifacts/japan_events_2026-01.xml \
    --data_dir /data/alex/fnet_japan/raw \
    --stations_file $REPO/scripts/configs/japan/stations.txt \
    --output_dir /data/alex/fnet_japan/catalogue \
    --duration 200 --sampling_rate 1.0 \
    --noise_start 2026-01-01 --noise_end 2026-02-01 \
    --n_jobs 8
# NOTE: no --stationxml_dir  → remove_response=False (path b). Writes
#   /data/alex/fnet_japan/catalogue/{events,noise}/*.h5
```

## IRIS fallback (path a / outage backup)

F-net is mirrored at IRIS as network **`BO`**. To get **raw counts + StationXML** (so you can take
path (a) — full response → DISP) or if the NIED service is unavailable, use the science repo's
downloader, which writes the _same_ `{station}/{YYYY.DDD}/` layout plus `stationxml/`:

```bash
REPO=/home/alex/work/seismo-sbi
conda run -n seismo-sbi python $REPO/scripts/custom_download.py \
    --stations_file $REPO/scripts/configs/japan/stations.txt \
    --providers IRIS \
    --starttime 2026-01-01T00:00:00 --endtime 2026-02-01T00:00:00 \
    --output_dir /data/alex/fnet_japan/raw_iris
# Then build_catalogue.py WITH --stationxml_dir /data/alex/fnet_japan/raw_iris/stationxml
# (remove_response=True → DISP). IRIS F-net availability/latency can lag NIED, so this is a backup.
```

## Tests

Offline (no network, no creds, no win2sac — the client + conversion are injected):

```bash
conda run -n seismo-sbi python -m pytest worker/fnet/test_fetch_fnet_offline.py -q
```

Covers JST↔UTC conversion, the `{station}/{YYYY.DDD}/` layout + filenames, the `U→BHZ`
(`N→BHN` / `E→BHE`) rename and its downstream `Z/2/1` mapping, NIED↔FDSN code mapping, unit
conversion, and that **no secret is ever logged**.
