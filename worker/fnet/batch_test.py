#!/usr/bin/env python3
"""Find the largest per-call span (chunks-in-flight) that retrieves cleanly for
all 21 stations without hitting NIED's '150 latest requested data' cap.
Tests 360-min (6 chunks) then 180-min (3 chunks). Live log; creds internal."""
import os, sys, glob, tempfile, time
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_fnet as ff
from HinetPy import win32

u, p = ff.load_credentials()
client = ff._default_client_factory(u, p); del u, p
stations = ff.read_station_file("/home/alex/work/seismo-sbi/scripts/configs/japan/fnet_demo_stations.txt")
nied = [s.nied_name for s in stations]
client.select_stations("0103", nied)
print(f"selected {len(nied)} stations")

for span in (360, 180):
    jst = ff.utc_to_jst(datetime(2026, 1, 3, 0, 0))
    t0 = time.time()
    print(f"\n##### TEST span={span} min ({span//60} chunks) x {len(nied)} stations #####", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cnt, ct = client.get_continuous_waveform("0103", jst, span, max_span=60, outdir=tmp, threads=2)
        except Exception as e:
            print(f"  span={span} EXCEPTION {type(e).__name__}: {e}", flush=True); continue
        dt = time.time() - t0
        if not cnt:
            print(f"  span={span} returned None in {dt:.0f}s", flush=True); continue
        sd = os.path.join(tmp, "sac"); os.makedirs(sd)
        win32.extract_sac(ff._resolve(cnt, tmp), ff._resolve(ct, tmp), outdir=sd)
        n = len(glob.glob(sd + "/*.SAC"))
        print(f"  span={span} OK in {dt:.0f}s -> {n} SAC files (expect ~{len(nied)*3} B-set)", flush=True)
    # space the two tests so the first batch's queue clears
    time.sleep(20)
