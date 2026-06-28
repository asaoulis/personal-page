from datetime import datetime, timezone

import pytest

from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.fnet_mt import (
    ned_to_use,
    parse_fnet_mt_pre,
    match_event,
)

# Two real lines from the F-net mec_search.php <pre> block (Jan 2026), tags stripped.
PRE = """Origin_Time(UT) Latitude(deg) Longitude(deg) JMA_Depth(km) JMA_Magnitude(Mj) Region_Name Strike Dip Rake Mo(Nm) MT_Depth(km) MT_Magnitude(Mw) Var._Red. mxx mxy mxz myy myz mzz Unit(Nm) Number_of_Stations Station URL
2026/01/01,12:46:20.41 39.5640 143.4412 12.92 3.6 FAR_E_OFF_SANRIKU 187;35 25;68 64;101 6.07e+14 14 3.8 73.54 -0.3850 1.5176 2.8189 -3.8383 -3.1931 4.2233 1e+14 3 OOW;KSK;GJM https://www.fnet.bosai.go.jp/event/tdmt.php?_id=20260101124500&LANG=en
2026/01/02,09:34:00.72 43.6182 147.4935 59.00 3.9 E_OFF_HOKKAIDO 203;77 22;77 38;107 9.17e+14 41 3.9 75.13 -2.4517 3.1361 7.8338 -1.5074 -1.0191 3.9591 1e+14 5 A;B;C;D;E https://www.fnet.bosai.go.jp/event/tdmt.php?_id=20260102093400&LANG=en
garbage line that should be skipped
"""


def test_ned_to_use_formula():
    # [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] = [mzz, mxx, myy, mxz, -myz, -mxy]
    assert ned_to_use(1, 2, 3, 4, 5, 6) == [6, 1, 4, 3, -5, -2]


def test_parse_fnet_mt_pre():
    sols = parse_fnet_mt_pre(PRE)
    assert len(sols) == 2
    s = sols[0]
    assert s.time == datetime(2026, 1, 1, 12, 46, 20, 410000, tzinfo=timezone.utc)
    assert abs(s.lat - 39.564) < 1e-4 and abs(s.lon - 143.4412) < 1e-4
    assert s.mw == 3.8 and s.mj == 3.6
    assert s.np1 == (187.0, 25.0, 64.0)
    assert s.region == "FAR_E_OFF_SANRIKU"
    assert len(s.m6_use) == 6
    # Unit scaling applied (1e14): Mrr = mzz*unit = 4.2233e14
    assert abs(s.m6_use[0] - 4.2233e14) < 1e9
    assert s.n_stations == 3 and "tdmt.php" in s.url


def test_parse_skips_header_and_junk():
    assert parse_fnet_mt_pre("Origin_Time foo\n\nrandom") == []


def _ev(t, lat, lon):
    return QuakeEvent(id="x", time=t, lon=lon, lat=lat, depth_km=10, mag=4.0, magtype="mb", region="R")


def test_match_event():
    sols = parse_fnet_mt_pre(PRE)
    # close in time + space -> matches the first solution
    near = _ev(datetime(2026, 1, 1, 12, 46, 40, tzinfo=timezone.utc), 39.6, 143.5)
    m = match_event(near, sols)
    assert m is not None and m.region == "FAR_E_OFF_SANRIKU"
    # far away in space -> no match
    far = _ev(datetime(2026, 1, 1, 12, 46, 40, tzinfo=timezone.utc), 10.0, 100.0)
    assert match_event(far, sols) is None
    # far in time -> no match
    late = _ev(datetime(2026, 1, 1, 14, 0, 0, tzinfo=timezone.utc), 39.6, 143.5)
    assert match_event(late, sols) is None


def test_convention_reproduces_nodal_planes():
    pytest.importorskip("pyrocko")
    import numpy as np
    from pyrocko import moment_tensor as pmt

    s = parse_fnet_mt_pre(PRE)[0]
    m6 = s.m6_use
    mt = pmt.MomentTensor(
        m_up_south_east=np.array(
            [[m6[0], m6[3], m6[4]], [m6[3], m6[1], m6[5]], [m6[4], m6[5], m6[2]]]
        )
    )
    planes = mt.both_strike_dip_rake()
    st, dp, rk = s.np1

    def close(p):
        return abs(((p[0] - st + 180) % 360) - 180) + abs(p[1] - dp) + abs(((p[2] - rk + 180) % 360) - 180)

    assert min(close(p) for p in planes) < 8.0
