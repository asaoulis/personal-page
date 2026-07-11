#!/usr/bin/env python3
"""S4 availability QA: probe short windows across the target month for the 22
candidate F-net stations and rank them by availability / completeness / quality.

Strategy: 30-min windows on ~11 days spread across Jan 2026 (one shared HinetPy
request per window over all selected stations -> cheap). Per station we record:
  * availability = fraction of windows that returned data,
  * completeness = mean (npts / expected) per component,
  * dead/flat    = count of near-zero-variance components,
  * mean RMS     = rough signal level.
Loads creds INTERNALLY via the adapter; never prints them. Raw data -> temp dirs
(auto-cleaned). Writes station_qa.csv to the task artifacts dir.
"""
import os
import sys
import csv
import collections
import tempfile
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_fnet as ff  # noqa: E402
from HinetPy import win32  # noqa: E402

ART = "/home/alex/work/seismo-sbi/.claude/runs/personal-page/fnet-data-sourcing/artifacts"
STATIONS = os.path.join(ART, "stations_candidate.txt")
OUT_CSV = os.path.join(ART, "station_qa.csv")

WIN_MIN = 30
SR = 100.0
EXPECTED_NPTS = int(WIN_MIN * 60 * SR)

# ~11 windows spread across Jan 2026, rotating the hour so we sample day & night.
DAYS = [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31]
HOURS = [2, 7, 12, 17, 21]
WINDOWS = [datetime(2026, 1, d, HOURS[i % len(HOURS)], 0) for i, d in enumerate(DAYS)]


def main():
    stations = ff.read_station_file(STATIONS)
    nied_names = [s.nied_name for s in stations]
    print(f"QA over {len(stations)} stations x {len(WINDOWS)} windows (Jan 2026)")

    u, p = ff.load_credentials()
    client = ff._default_client_factory(u, p)
    del u, p
    try:
        client.select_stations("0103", nied_names)
    except Exception as e:
        print("select_stations warning:", type(e).__name__)

    present = collections.Counter()
    comp_sum = collections.defaultdict(float)
    comp_n = collections.defaultdict(int)
    flat = collections.Counter()
    rms_sum = collections.defaultdict(float)
    rms_n = collections.defaultdict(int)

    for w in WINDOWS:
        jst = ff.utc_to_jst(w)
        with tempfile.TemporaryDirectory(prefix="fnetqa_") as tmp:
            try:
                cnt, ct = client.get_continuous_waveform(
                    "0103", jst, WIN_MIN, max_span=60, outdir=tmp, threads=2)
            except Exception as e:
                print(f"  {w:%Y-%m-%d %H:%M} request error: {type(e).__name__}")
                continue
            if not cnt or not ct:
                print(f"  {w:%Y-%m-%d %H:%M} no data returned")
                continue
            cnt = ff._resolve(cnt, tmp); ct = ff._resolve(ct, tmp)
            sd = os.path.join(tmp, "sac"); os.makedirs(sd, exist_ok=True)
            try:
                win32.extract_sac(cnt, ct, outdir=sd)
            except Exception as e:
                print(f"  {w:%Y-%m-%d %H:%M} extract error: {type(e).__name__}")
                continue
            groups = ff.group_sac_by_station(sd)
            got = 0
            for nied in nied_names:
                st = groups.get(nied)
                if not st:
                    continue
                present[nied] += 1
                got += 1
                for tr in st:
                    comp_sum[nied] += min(tr.stats.npts / EXPECTED_NPTS, 1.0)
                    comp_n[nied] += 1
                    d = tr.data.astype("float64")
                    if d.size and d.std() < 1e-9:
                        flat[nied] += 1
                    if d.size:
                        rms_sum[nied] += float(np.sqrt(np.mean(d ** 2)))
                        rms_n[nied] += 1
            print(f"  {w:%Y-%m-%d %H:%M} -> {got}/{len(nied_names)} stations with data")

    nwin = len(WINDOWS)
    rows = []
    for s in stations:
        n = s.nied_name
        rows.append({
            "code": s.code, "nied": n, "lat": s.lat, "lon": s.lon,
            "windows": nwin, "present": present[n],
            "availability": round(present[n] / nwin, 3),
            "completeness": round(comp_sum[n] / comp_n[n], 3) if comp_n[n] else 0.0,
            "flat_comp": flat[n],
            "mean_rms": round(rms_sum[n] / rms_n[n], 1) if rms_n[n] else 0.0,
        })
    rows.sort(key=lambda r: (-r["availability"], -r["completeness"]))
    with open(OUT_CSV, "w", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wcsv.writeheader(); wcsv.writerows(rows)

    print("\n=== station QA (ranked) ===")
    print(f"{'code':5} {'avail':>6} {'compl':>6} {'flat':>4} {'mean_rms':>10}")
    for r in rows:
        print(f"{r['code']:5} {r['availability']:6.2f} {r['completeness']:6.2f} "
              f"{r['flat_comp']:4d} {r['mean_rms']:10.1f}")
    print(f"\nwrote {OUT_CSV}")


if __name__ == "__main__":
    main()
