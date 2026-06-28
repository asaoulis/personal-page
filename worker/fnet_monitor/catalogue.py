"""Catalogue polling — detect new region events from a FDSN-event GeoJSON feed.

The network call is isolated behind a `fetcher` callable so the rest is pure and
unit-testable without internet. `usgs_fetcher` is the real one; tests inject a fake
that returns fixture JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from .config import Config
from .state import State
from .util import from_epoch_ms, to_iso

Fetcher = Callable[[str, dict], dict]


@dataclass
class QuakeEvent:
    id: str
    time: datetime  # UTC
    lon: float
    lat: float
    depth_km: float
    mag: float
    magtype: str
    region: str
    # Optional mechanism hints (used by the demo catalogue; absent for live USGS).
    strike: Optional[float] = None
    dip: Optional[float] = None
    rake: Optional[float] = None
    gamma: Optional[float] = None
    delta: Optional[float] = None
    source_type: Optional[str] = None


def usgs_fetcher(url: str, params: dict) -> dict:
    """Real FDSN call. Imported lazily so tests need no `requests`."""
    import requests

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_usgs(geojson: dict) -> List[QuakeEvent]:
    """Parse a USGS FDSN-event GeoJSON FeatureCollection into QuakeEvents."""
    out: List[QuakeEvent] = []
    for f in geojson.get("features", []):
        p = f.get("properties", {}) or {}
        g = f.get("geometry", {}) or {}
        coords = g.get("coordinates") or [None, None, None]
        if p.get("mag") is None or coords[0] is None or coords[1] is None:
            continue
        out.append(
            QuakeEvent(
                id=str(f.get("id")),
                time=from_epoch_ms(p["time"]),
                lon=float(coords[0]),
                lat=float(coords[1]),
                depth_km=float(coords[2]) if coords[2] is not None else 0.0,
                mag=float(p["mag"]),
                magtype=str(p.get("magType") or "M"),
                region=str(p.get("place") or "Japan region"),
            )
        )
    return out


def _in_bbox(ev: QuakeEvent, bbox: dict) -> bool:
    return (
        bbox["minlat"] <= ev.lat <= bbox["maxlat"]
        and bbox["minlon"] <= ev.lon <= bbox["maxlon"]
    )


def select_new(
    events: List[QuakeEvent],
    cfg: Config,
    state: State,
    now: datetime,
) -> List[QuakeEvent]:
    """Filter parsed events to the genuinely-new, processable ones.

    Keeps events that are: in-region, >= min magnitude, OLDER than the delay window
    (archive lag), within the retention window, and not already processed. Returns
    them sorted ascending by origin time.
    """
    cutoff_recent = now - timedelta(minutes=cfg.delay_minutes)
    cutoff_old = now - timedelta(days=cfg.window_days)
    seen = set(state.processed_ids)
    keep = [
        ev
        for ev in events
        if ev.mag >= cfg.min_magnitude
        and _in_bbox(ev, cfg.bbox)
        and ev.time <= cutoff_recent
        and ev.time >= cutoff_old
        and ev.id not in seen
    ]
    return sorted(keep, key=lambda e: e.time)


def poll(
    cfg: Config,
    state: State,
    now: datetime,
    fetcher: Fetcher = usgs_fetcher,
) -> List[QuakeEvent]:
    """Query the feed for the active window and return new processable events."""
    start = now - timedelta(days=cfg.window_days)
    params = {
        "format": "geojson",
        "starttime": to_iso(start),
        "endtime": to_iso(now),
        "minmagnitude": cfg.min_magnitude,
        "minlatitude": cfg.bbox["minlat"],
        "maxlatitude": cfg.bbox["maxlat"],
        "minlongitude": cfg.bbox["minlon"],
        "maxlongitude": cfg.bbox["maxlon"],
        "orderby": "time-asc",
    }
    geojson = fetcher(cfg.fdsn_url, params)
    return select_new(parse_usgs(geojson), cfg, state, now)
