"""F-net (NIED) regional moment-tensor catalogue access.

THE Japanese-source reference for the live monitor. F-net runs Japan's routine regional MT
catalogue down to ~Mw 3.5, so it resolves almost every event in the demo region — far better
coverage than GCMT (~M5 global) or USGS-Mww (~M4.5). The MT *catalogue* is PUBLIC (the NIED
account is only needed for waveform download via HinetPy, which is a separate concern).

------------------------------------------------------------------------------------------------
HOW TO QUERY F-NET (documented for the live monitor — `query_fnet_mt_catalogue` below)
------------------------------------------------------------------------------------------------
The search form is `https://www.fnet.bosai.go.jp/event/search.php` (LANG=en). It POSTs to
`https://www.fnet.bosai.go.jp/event/mec_search.php`. Reproduce it programmatically as:

  1. Open a `requests.Session` and GET `search.php?LANG=en` first — the result page needs the
     session COOKIE (a bare request returns HTTP 500).
  2. POST the form fields to `mec_search.php` (GET 500s; it must be POST). Origin-time range:
        tm_flg   = 'ut' | 'jst'        (we use UT; the demo/USGS times are UTC)
        time_flg = 'and'               ('between'; other modes: eq/ge/le)
        end_flg  = 'date'              (explicit end date; the alternative is 'days' + days=N)
        year1/month1/day1/hour1/min1   start  (month/day/hour/min ZERO-PADDED, e.g. '01')
        year2/month2/day2/hour2/min2   end
        LANG     = 'en'
     Optional magnitude filter: mw_flg='and', mw1, mw2 (Mw); region/strike/dip/... similarly via
     their `*_flg` selects. For LIVE polling, use end_flg='days', days=N (last N days) — or just
     a start..now UT window.
  3. The response is **EUC-JP** HTML; the catalogue is a single `<pre>` block whose first line is
     the header `Origin_Time(UT) Latitude(deg) ... mxx mxy mxz myy myz mzz Unit(Nm) ...`. Decode
     EUC-JP, strip tags, parse the lines (`parse_fnet_mt_pre`). NOTE: obspy's `io.nied.fnetmt`
     reader does NOT work on this web output (it expects a count-bearing header), so we parse it
     directly.

Data columns (whitespace-split, 23 cols):
  0 Origin_Time `YYYY/MM/DD,HH:MM:SS.ss` (UT)   1 lat  2 lon  3 JMA_depth_km  4 Mj  5 region
  6 strike `np1;np2`  7 dip `np1;np2`  8 rake `np1;np2`  9 Mo(Nm)  10 MT_depth_km  11 Mw
  12 Var.Red.  13-18 mxx mxy mxz myy myz mzz  19 Unit(Nm)  20 n_stations  21 stations  22 URL

The MT components (cols 13-18) are in the **NED (north-east-down / Aki) convention** in units of
col 19 (typically 1e14 N·m). VERIFIED: interpreting them as NED reproduces the published nodal
planes exactly. We convert NED -> GCMT up-south-east (USE) purely:
    [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] = [mzz, mxx, myy, mxz, -myz, -mxy]
which matches `pyrocko.MomentTensor.m6_up_south_east()` and the seismo_sbi m6 convention with no
sign flips.

LIVE-MONITOR USAGE:
    sols = query_fnet_mt_catalogue(start_utc, end_utc)            # one call per poll window
    ref  = match_event(quake_event, sols)                        # nearest by time+distance
    if ref: m6_use = ref.m6_use                                  # feed kagan / lune / beachball
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

FNET_SEARCH_FORM = "https://www.fnet.bosai.go.jp/event/search.php?LANG=en"
FNET_MEC_SEARCH = "https://www.fnet.bosai.go.jp/event/mec_search.php"

SDR = Tuple[float, float, float]


@dataclass
class FnetMT:
    """One F-net moment-tensor solution."""

    time: datetime  # UT
    lat: float
    lon: float
    depth_jma_km: float
    mj: float
    region: str
    np1: SDR  # (strike, dip, rake)
    np2: SDR
    mo_nm: float
    mt_depth_km: float
    mw: float
    var_red: float
    m6_use: List[float]  # [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] (USE), scaled by Unit(Nm)
    n_stations: int
    url: str


def ned_to_use(mxx, mxy, mxz, myy, myz, mzz) -> List[float]:
    """F-net NED components -> GCMT up-south-east 6-vector (verified vs the published planes)."""
    return [mzz, mxx, myy, mxz, -myz, -mxy]


def _parse_time(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y/%m/%d,%H:%M:%S.%f", "%Y/%m/%d,%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unparseable F-net origin time: {s!r}")


def parse_fnet_mt_pre(text: str) -> List[FnetMT]:
    """Parse the F-net `<pre>` catalogue body (tags already stripped). PURE — no network/pyrocko.

    Tolerant of the header line and short/garbled lines (skips anything that doesn't have the
    expected 19+ numeric columns)."""
    out: List[FnetMT] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Origin_Time"):
            continue
        a = line.split()
        if len(a) < 19 or ";" not in a[6]:
            continue
        try:
            strike = tuple(float(x) for x in a[6].split(";"))
            dip = tuple(float(x) for x in a[7].split(";"))
            rake = tuple(float(x) for x in a[8].split(";"))
            comps = [float(x) for x in a[13:19]]
            unit = float(a[19]) if len(a) > 19 and _isfloat(a[19]) else 1.0
            m6 = [c * unit for c in ned_to_use(*comps)]
            out.append(
                FnetMT(
                    time=_parse_time(a[0]),
                    lat=float(a[1]),
                    lon=float(a[2]),
                    depth_jma_km=float(a[3]),
                    mj=float(a[4]),
                    region=a[5],
                    np1=(strike[0], dip[0], rake[0]),
                    np2=(strike[1], dip[1], rake[1]) if len(strike) > 1 else (strike[0], dip[0], rake[0]),
                    mo_nm=float(a[9]),
                    mt_depth_km=float(a[10]),
                    mw=float(a[11]),
                    var_red=float(a[12]),
                    m6_use=m6,
                    n_stations=int(float(a[20])) if len(a) > 20 and _isfloat(a[20]) else 0,
                    url=a[22] if len(a) > 22 else "",
                )
            )
        except (ValueError, IndexError):
            continue
    return out


def _isfloat(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def query_fnet_mt_catalogue(
    start: datetime,
    end: datetime,
    *,
    time_zone: str = "ut",
    min_mw: Optional[float] = None,
    max_mw: Optional[float] = None,
    session=None,
    timeout: int = 90,
) -> List[FnetMT]:
    """Query the public F-net MT catalogue for an origin-time window. Networked (lazy `requests`).

    See the module docstring for the full protocol. `start`/`end` are datetimes (interpreted in
    `time_zone`, 'ut' or 'jst'). Returns parsed `FnetMT` solutions (may be empty)."""
    import requests

    s = session or requests.Session()
    headers = {"User-Agent": "personal-page-fnet-monitor/1.0 (research)", "Referer": FNET_SEARCH_FORM}
    s.get(FNET_SEARCH_FORM, headers=headers, timeout=timeout)  # establish the session cookie

    data = {
        "LANG": "en",
        "tm_flg": time_zone,
        "time_flg": "and",  # 'between'
        "end_flg": "date",
        "year1": f"{start.year}", "month1": f"{start.month:02d}", "day1": f"{start.day:02d}",
        "hour1": f"{start.hour:02d}", "min1": f"{start.minute:02d}",
        "year2": f"{end.year}", "month2": f"{end.month:02d}", "day2": f"{end.day:02d}",
        "hour2": f"{end.hour:02d}", "min2": f"{end.minute:02d}",
    }
    if min_mw is not None or max_mw is not None:
        data["mw_flg"] = "and"
        data["mw1"] = "" if min_mw is None else f"{min_mw}"
        data["mw2"] = "" if max_mw is None else f"{max_mw}"

    r = s.post(FNET_MEC_SEARCH, data=data, headers=headers, timeout=timeout)
    r.raise_for_status()
    html = r.content.decode("euc-jp", "replace")
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.S | re.I)
    if not m:
        return []
    body = re.sub(r"<[^>]+>", "", m.group(1))
    return parse_fnet_mt_pre(body)


def _haversine_deg(lat1, lon1, lat2, lon2) -> float:
    """Great-circle separation in degrees (cheap, for event matching)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


def match_event(
    ev,
    solutions: List[FnetMT],
    *,
    tol_sec: float = 120.0,
    tol_deg: float = 1.0,
) -> Optional[FnetMT]:
    """Nearest F-net solution to a `QuakeEvent` by origin time + epicentre (or None).

    F-net and USGS ids differ, so we match on space-time: within `tol_sec` AND `tol_deg`, choose
    the smallest time offset (ties broken by distance)."""
    best = None
    best_key = None
    for s in solutions:
        dt = abs((s.time - ev.time).total_seconds())
        if dt > tol_sec:
            continue
        dist = _haversine_deg(ev.lat, ev.lon, s.lat, s.lon)
        if dist > tol_deg:
            continue
        key = (dt, dist)
        if best_key is None or key < best_key:
            best, best_key = s, key
    return best
