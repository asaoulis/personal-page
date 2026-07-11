#!/usr/bin/env python3
"""Validate the real-data SAC->mseed conversion on a 15-min F-net window.

Checks the actual KCMPNM / sample rate / start time and whether
fetch_fnet.convert_station_stream survives real F-net channel naming
(.EB/.NB/.UB vs the single-letter the offline tests mocked).
Loads creds internally; never prints them.
"""
import os
import sys
import glob
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_fnet as ff  # noqa: E402
from HinetPy import win32  # noqa: E402
import obspy  # noqa: E402

u, p = ff.load_credentials()
_sec = [x for x in (u, p) if x]


def scrub(x):
    s = str(x)
    for v in _sec:
        s = s.replace(v, "***")
    return s


client = ff._default_client_factory(u, p)
del u, p
client.select_stations("0103", ["N.TSKF"])
jst = ff.utc_to_jst(datetime(2026, 1, 15, 3, 0))

with tempfile.TemporaryDirectory() as tmp:
    cnt, ct = client.get_continuous_waveform("0103", jst, 15, outdir=tmp, threads=1)
    cnt = ff._resolve(cnt, tmp); ct = ff._resolve(ct, tmp)
    sd = os.path.join(tmp, "sac"); os.makedirs(sd, exist_ok=True)
    win32.extract_sac(cnt, ct, outdir=sd)
    files = sorted(glob.glob(sd + "/*.SAC"))
    print("SAC files:", [os.path.basename(x) for x in files])
    for f in files:
        tr = obspy.read(f, format="SAC")[0]
        print("  %s: channel(KCMPNM)=%r station=%r sr=%s npts=%s start=%s"
              % (os.path.basename(f), tr.stats.channel, tr.stats.station,
                 tr.stats.sampling_rate, tr.stats.npts, tr.stats.starttime))
    print("--- fetch_fnet conversion ---")
    groups = ff.group_sac_by_station(sd)
    print("groups:", list(groups))
    for nied, stream in groups.items():
        try:
            conv = ff.convert_station_stream(stream, ff.nied_to_fdsn(nied), units="displacement")
            print("  OK %s -> channels=%s npts=%s start(UTC)=%s"
                  % (nied, [t.stats.channel for t in conv],
                     [t.stats.npts for t in conv],
                     conv[0].stats.starttime if conv else "-"))
        except Exception as e:
            print("  CONVERT ERROR for %s: %s %s" % (nied, type(e).__name__, scrub(e)))
