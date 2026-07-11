#!/usr/bin/env python3
"""Diagnostic probe for the F-net continuous-data fetch failure.

Auth works but get_continuous_waveform returned None for a full day. This isolates
the cause: account/permission vs station vs data-availability vs request span/load.
Loads creds INTERNALLY; never prints them (errors are scrubbed). Writes only to
auto-cleaned temp dirs.
"""
import os
import sys
import glob
import tempfile
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_fnet as ff  # noqa: E402
from HinetPy import win32  # noqa: E402

u, p = ff.load_credentials()
_sec = [x for x in (u, p) if x]


def scrub(x):
    s = str(x)
    for v in _sec:
        s = s.replace(v, "***")
    return s


print("creds loaded:", bool(u) and bool(p))
client = ff._default_client_factory(u, p)
del u, p

print("=== doctor ===")
try:
    client.doctor()
except Exception as e:
    print("  doctor err:", scrub(e))

print("=== get_station_list('0103') ===")
try:
    stns = client.get_station_list("0103")
    codes = [getattr(s, "name", getattr(s, "code", "?")) for s in stns]
    print("  count:", len(stns), "| TSK present:", any("TSK" in str(c) for c in codes))
    print("  sample:", codes[:6])
except Exception as e:
    print("  station-list err:", scrub(e))

print("=== select N.TSKF ===")
try:
    client.select_stations("0103", ["N.TSKF"])
    print("  selected:", client.get_selected_stations("0103"))
except Exception as e:
    print("  select err:", scrub(e))

for (y, m, d) in [(2026, 1, 15), (2025, 11, 15), (2025, 6, 15)]:
    jst = ff.utc_to_jst(datetime(y, m, d, 3, 0))
    print(f"=== get_continuous_waveform 0103 {y}-{m:02d}-{d:02d} (JST {jst}) span=15 threads=1 ===")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cnt, ct = client.get_continuous_waveform("0103", jst, 15, outdir=tmp, threads=1)
            print("  returned: cnt=%r ctable=%r" % (cnt, ct))
            if cnt and ct:
                cnt = ff._resolve(cnt, tmp); ct = ff._resolve(ct, tmp)
                sd = os.path.join(tmp, "sac"); os.makedirs(sd, exist_ok=True)
                win32.extract_sac(cnt, ct, outdir=sd)
                sacs = glob.glob(os.path.join(sd, "*.SAC"))
                print("  SAC files:", len(sacs), [os.path.basename(x) for x in sacs[:6]])
        except Exception as e:
            print("  ERROR:", type(e).__name__, scrub(e))
            traceback.print_exc()
