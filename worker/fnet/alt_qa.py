#!/usr/bin/env python3
"""Quick availability QA for Japan-Sea-coast ALTERNATE stations (KZK, ADM) to
replace the dropped SBT. Same probe as availability_qa.py. Loads creds via the
adapter; never prints them. Raw -> temp; appends to station_qa_alt.csv.
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
OUT_CSV = os.path.join(ART, "station_qa_alt.csv")

ALTS = [("KZK", 37.30, 138.51), ("ADM", 37.90, 138.43)]
WIN_MIN = 30
SR = 100.0
EXPECTED_NPTS = int(WIN_MIN * 60 * SR)
DAYS = [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31]
HOURS = [2, 7, 12, 17, 21]
WINDOWS = [datetime(2026, 1, d, HOURS[i % len(HOURS)], 0) for i, d in enumerate(DAYS)]


def main():
    nied = [ff.fdsn_to_nied(c) for c, _, _ in ALTS]
    code_by_nied = {ff.fdsn_to_nied(c): c for c, _, _ in ALTS}
    u, p = ff.load_credentials()
    client = ff._default_client_factory(u, p)
    del u, p
    client.select_stations("0103", nied)

    present = collections.Counter()
    comp_sum = collections.defaultdict(float); comp_n = collections.defaultdict(int)
    flat = collections.Counter()
    rms_sum = collections.defaultdict(float); rms_n = collections.defaultdict(int)

    for w in WINDOWS:
        jst = ff.utc_to_jst(w)
        with tempfile.TemporaryDirectory(prefix="fnetalt_") as tmp:
            try:
                cnt, ct = client.get_continuous_waveform("0103", jst, WIN_MIN, max_span=60, outdir=tmp, threads=2)
            except Exception as e:
                print(f"  {w:%Y-%m-%d %H:%M} request error {type(e).__name__}"); continue
            if not cnt or not ct:
                print(f"  {w:%Y-%m-%d %H:%M} no data"); continue
            cnt = ff._resolve(cnt, tmp); ct = ff._resolve(ct, tmp)
            sd = os.path.join(tmp, "sac"); os.makedirs(sd, exist_ok=True)
            try:
                win32.extract_sac(cnt, ct, outdir=sd)
            except Exception as e:
                print(f"  {w:%Y-%m-%d %H:%M} extract error {type(e).__name__}"); continue
            groups = ff.group_sac_by_station(sd)
            got = [code_by_nied[n] for n in nied if groups.get(n)]
            for n in nied:
                st = groups.get(n)
                if not st:
                    continue
                present[n] += 1
                for tr in st:
                    comp_sum[n] += min(tr.stats.npts / EXPECTED_NPTS, 1.0); comp_n[n] += 1
                    d = tr.data.astype("float64")
                    if d.size and d.std() < 1e-9:
                        flat[n] += 1
                    if d.size:
                        rms_sum[n] += float(np.sqrt(np.mean(d ** 2))); rms_n[n] += 1
            print(f"  {w:%Y-%m-%d %H:%M} -> {got}")

    nwin = len(WINDOWS)
    rows = []
    for code, lat, lon in ALTS:
        n = ff.fdsn_to_nied(code)
        rows.append({
            "code": code, "nied": n, "lat": lat, "lon": lon, "windows": nwin,
            "present": present[n], "availability": round(present[n] / nwin, 3),
            "completeness": round(comp_sum[n] / comp_n[n], 3) if comp_n[n] else 0.0,
            "flat_comp": flat[n],
            "mean_rms": round(rms_sum[n] / rms_n[n], 1) if rms_n[n] else 0.0,
        })
    with open(OUT_CSV, "w", newline="") as f:
        wcsv = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wcsv.writeheader(); wcsv.writerows(rows)
    print("\n=== alternate QA ===")
    for r in rows:
        print(f"{r['code']:5} avail={r['availability']:.2f} compl={r['completeness']:.2f} "
              f"flat={r['flat_comp']} rms={r['mean_rms']:.1f}")
    print("wrote", OUT_CSV)


if __name__ == "__main__":
    main()
