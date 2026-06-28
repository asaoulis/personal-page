"""A curated, deterministic demo catalogue.

Used to (re)generate the frontend's mock data (`public/demo/`) without hitting a live
feed — a believable spread of events across Japan over the last ~month, each carrying a
mechanism hint so `inference.mock_posterior` produces a matching, varied result. The
live worker uses `catalogue.poll` instead; this is only for the offline preview.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from .catalogue import QuakeEvent, select_new
from .config import Config
from .state import State

# stub, days-ago, lat, lon, depth, mag, region, strike, dip, rake, gamma, delta, source_type
_DEMO = [
    ("off-ibaraki", 1.1, 36.30, 141.30, 32, 5.2, "Off Ibaraki, Honshu", 198, 33, 86, 1.5, -2.0, "double-couple"),
    ("hyuga-nada", 3.7, 32.10, 132.10, 28, 4.6, "Hyuga-nada, Kyushu", 212, 41, 74, -3.0, 4.5, "double-couple"),
    ("noto-peninsula", 6.2, 37.50, 137.30, 12, 5.8, "Noto Peninsula, Honshu", 55, 52, 110, 6.0, 10.5, "CLVD-leaning"),
    ("tokara", 9.4, 29.80, 129.40, 18, 4.1, "Tokara Islands", 170, 60, -20, -8.0, -6.0, "strike-slip"),
    ("iwate-coast", 13.0, 39.60, 142.20, 41, 5.0, "Off Iwate, Honshu", 185, 25, 95, 0.5, 1.0, "double-couple"),
    ("hida", 17.8, 36.20, 137.60, 8, 3.9, "Hida region, Honshu", 300, 80, -8, -5.5, -1.5, "strike-slip"),
    ("aizu", 22.5, 37.40, 139.90, 6, 4.3, "Aizu, Honshu", 145, 70, -160, 9.0, -14.0, "volcanic / -ISO"),
    ("kii-channel", 27.3, 33.80, 135.10, 36, 5.5, "Kii Channel", 225, 38, 92, -1.0, 2.5, "double-couple"),
]


def demo_events(now: datetime) -> List[QuakeEvent]:
    evs = []
    for stub, days, lat, lon, depth, mag, region, s, d, r, g, dl, src in _DEMO:
        t = now - timedelta(days=days)
        evs.append(
            QuakeEvent(
                id=f"demo-{stub}",
                time=t,
                lon=lon,
                lat=lat,
                depth_km=depth,
                mag=mag,
                magtype="Mw",
                region=region,
                strike=s,
                dip=d,
                rake=r,
                gamma=g,
                delta=dl,
                source_type=src,
            )
        )
    return evs


def provider(cfg: Config, state: State, now: datetime) -> List[QuakeEvent]:
    return select_new(demo_events(now), cfg, state, now)
