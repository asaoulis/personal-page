#!/usr/bin/env python3
"""Confirm max_span=60 splits a >60-min request into 60-min sub-requests that
succeed (the Hi-net server caps Record_Length at 60 min). Loads creds via the
adapter; never prints them."""
import os, sys, glob, tempfile
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import fetch_fnet as ff
from HinetPy import win32

u, p = ff.load_credentials()
client = ff._default_client_factory(u, p); del u, p
client.select_stations("0103", ["N.TSKF"])
jst = ff.utc_to_jst(datetime(2026, 1, 1, 0, 0))  # JST 09:00
with tempfile.TemporaryDirectory() as tmp:
    cnt, ct = client.get_continuous_waveform("0103", jst, 180, max_span=60, outdir=tmp, threads=3)
    print("returned cnt=%r ctable=%r" % (cnt, ct))
    if cnt and ct:
        cnt = ff._resolve(cnt, tmp); ct = ff._resolve(ct, tmp)
        sd = os.path.join(tmp, "sac"); os.makedirs(sd, exist_ok=True)
        win32.extract_sac(cnt, ct, outdir=sd)
        import obspy
        for f in sorted(glob.glob(sd + "/*.SAC")):
            tr = obspy.read(f, format="SAC")[0]
            print("  %s sr=%s npts=%s (expect ~%d for 180min)" %
                  (os.path.basename(f), tr.stats.sampling_rate, tr.stats.npts, 180*60*100))
    else:
        print("FAILED: no data for the 180-min span even with 60-min chunks")
