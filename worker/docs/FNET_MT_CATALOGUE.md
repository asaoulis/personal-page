# Querying the F-net (NIED) moment-tensor catalogue — for the live monitor

This is the **Japanese reference source** for the live earthquake-source demo. F-net runs Japan's
routine regional MT catalogue down to **~Mw 3.5**, so it resolves almost every event in the demo
region — far better coverage than GCMT (~M5, global) or USGS-Mww (~M4.5). Measured coverage on the
Jan-2026 demo catalogue: **68/78 events (87%)** had an F-net solution; the next-best single source
(USGS W-phase) had 18.

> The MT **catalogue is public** — no login. The NIED account is only for **waveform** download
> (HinetPy), which is a separate concern (`worker/fnet/fetch_fnet.py`).

The reusable, documented implementation is **`worker/fnet_monitor/fnet_mt.py`**:

```python
from fnet_monitor.fnet_mt import query_fnet_mt_catalogue, match_event
sols = query_fnet_mt_catalogue(start_utc, end_utc)   # one call per poll window
ref  = match_event(quake_event, sols)                # nearest by origin time + epicentre
if ref:
    m6_use = ref.m6_use   # [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp], GCMT up-south-east, scaled by Unit(Nm)
    mw, np1, var_red = ref.mw, ref.np1, ref.var_red
```

## The query protocol (what `query_fnet_mt_catalogue` does)

The search UI is `https://www.fnet.bosai.go.jp/event/search.php` (LANG=en); it POSTs to
`https://www.fnet.bosai.go.jp/event/mec_search.php`. Reproduce it as:

1. **Session cookie first.** Open a `requests.Session` and `GET search.php?LANG=en` — the result
   page needs the session cookie; a cold request returns **HTTP 500**.
2. **POST (not GET)** the form fields to `mec_search.php` (GET also 500s). Origin-time window:

   | field                                  | value         | meaning                                                              |
   | -------------------------------------- | ------------- | -------------------------------------------------------------------- |
   | `tm_flg`                               | `ut` \| `jst` | timezone of the range (we use UT; USGS/QuakeML times are UTC)        |
   | `time_flg`                             | `and`         | "between" (also `eq`/`ge`/`le`)                                      |
   | `end_flg`                              | `date`        | explicit end date (alternative: `days` + `days=N` for "last N days") |
   | `year1`,`month1`,`day1`,`hour1`,`min1` | start         | **month/day/hour/min zero-padded** (`01`)                            |
   | `year2`,`month2`,`day2`,`hour2`,`min2` | end           |                                                                      |
   | `LANG`                                 | `en`          |                                                                      |

   Optional magnitude filter: `mw_flg=and`, `mw1`, `mw2`. Region/strike/dip/… via their `*_flg`
   selects. **For live polling**: `end_flg=days`, `days=N`, or a `start..now` UT window each poll.

3. **Parse the response.** It is **EUC-JP** HTML; the catalogue is a single `<pre>` block whose
   first line is the header `Origin_Time(UT) … mxx mxy mxz myy myz mzz Unit(Nm) …`. Decode EUC-JP,
   strip tags, parse the lines (`parse_fnet_mt_pre`, pure/offline-testable).
   **obspy's `io.nied.fnetmt` does NOT work on this web output** (it expects a count-bearing
   header), so we parse it directly.

### Columns (whitespace-split, 23 cols)

```
0 Origin_Time `YYYY/MM/DD,HH:MM:SS.ss` (UT)  1 lat  2 lon  3 JMA_depth_km  4 Mj  5 region
6 strike `np1;np2`  7 dip `np1;np2`  8 rake `np1;np2`  9 Mo(Nm)  10 MT_depth_km  11 Mw
12 Var.Red.  13-18 mxx mxy mxz myy myz mzz  19 Unit(Nm)  20 n_stations  21 stations  22 URL
```

### MT convention (VERIFIED)

Components (cols 13–18) are **NED (north-east-down / Aki)** in units of col 19 (usually 1e14 N·m).
Interpreting them as NED reproduces the published nodal planes exactly. Convert NED → GCMT
up-south-east (USE) **purely**:

```
[Mrr, Mtt, Mpp, Mrt, Mrp, Mtp] = [mzz, mxx, myy, mxz, -myz, -mxy]
```

which matches `pyrocko.MomentTensor.m6_up_south_east()` and the `seismo_sbi` m6 convention with no
sign flips — so it feeds `evaluation.moment_tensor.kagan` / `plotting.lune.mts6_to_gamma_delta`
directly. Cross-check on the demo data: F-net-vs-USGS Kagan angles are small for well-constrained
events (Mw 5.8 → 5.5°) and large/variable for tiny ones (Mw 4.0 → 60°+) — the magnitude-dependent
agreement you expect, confirming the convention.

## Event matching

F-net and USGS event ids differ, so we match on **space-time** (`match_event`): within `tol_sec`
(default 120 s) AND `tol_deg` (default 1.0°), choosing the smallest time offset. F-net hypocentres
are JMA-sourced and can differ from USGS by a few seconds / tenths of a degree.

## Live-monitor integration

The live worker reuses this unchanged: each poll, call `query_fnet_mt_catalogue(now-Δ, now)` once,
then `match_event` per new catalogue event, attaching the F-net solution as the primary reference
(`references[]`, see `contract.py` / `references.py`). For the static demo, this is driven by
`fnet_monitor/fetch_references.py` → committed `worker/data/reference_cache.json`.
