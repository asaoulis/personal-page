"""Event sources — the pluggable seam that yields *candidate* events for the live monitor.

An `EventSource.fetch(now)` returns a list of candidate objects for the poll window ending at
`now`.  The monitor then registers each candidate by its stable id, and drives it through the
per-event state machine (see `state.py`), so the source itself is stateless and side-effect free.

CANDIDATE TYPE — we yield `fnet_mt.FnetMT` solution objects from the primary `FnetMtSource`,
because the downstream live per-event path (`live_event.run_live` / `infer_live_event`) consumes
`FnetMT` directly: it needs the F-net solution's `m6_use`/`np1`/`mw` as the reference AND its
`time`/`lat`/`lon`/`depth_jma_km` to download+build the h5.  `UsgsSource` yields `catalogue.
QuakeEvent` (USGS carries no MT).  `FakeSource` passes through whatever it was given, so tests can
use either type.  Use `candidate_id()` / `candidate_time()` to read the stable id + origin time off
a candidate regardless of which type it is — the id reuses the existing event-stem convention
(`fnet_<YYYYMMDDTHHMMSS>` for an F-net solution, matching `live_event.fnet_to_quakeevent`).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

try:  # PEP 544; py<3.8 has no typing.Protocol but the env is 3.9+
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore

from . import catalogue
from .config import Config
from .state import State


def event_stem(t: datetime) -> str:
    """Origin-time stem `YYYYMMDDTHHMMSS` — the shared catalogue/EventSolution key convention."""
    return f"{t.year:04d}{t.month:02d}{t.day:02d}T{t.hour:02d}{t.minute:02d}{t.second:02d}"


def candidate_id(cand) -> str:
    """Stable unique id for a candidate, whichever type it is.

    A `QuakeEvent` already carries `.id`; an `FnetMT` solution has none, so we synthesise the
    `fnet_<stem>` id used everywhere else (matches `live_event.fnet_to_quakeevent`)."""
    cid = getattr(cand, "id", None)
    if cid:
        return str(cid)
    return f"fnet_{event_stem(cand.time)}"


def candidate_time(cand) -> datetime:
    """Origin time of a candidate (both `QuakeEvent` and `FnetMT` expose `.time`)."""
    return cand.time


def candidate_depth(cand) -> Optional[float]:
    """Source depth (km) of a candidate, whichever type it is, or None if unknown.

    An `FnetMT` solution carries `depth_jma_km`; a `QuakeEvent` carries `depth_km`.  Used by the
    monitor's out-of-domain filter (deep-slab events are outside the NPE's training domain)."""
    for attr in ("depth_jma_km", "depth_km"):
        v = getattr(cand, attr, None)
        if v is not None:
            return float(v)
    return None


def candidate_latlon(cand) -> Tuple[Optional[float], Optional[float]]:
    """Epicentre (lat, lon) of a candidate, whichever type it is (both `FnetMT` and
    `QuakeEvent` expose `.lat`/`.lon`).  Used by the monitor's training-domain filter."""
    lat = getattr(cand, "lat", None)
    lon = getattr(cand, "lon", None)
    return (float(lat) if lat is not None else None,
            float(lon) if lon is not None else None)


def is_provisional_candidate(cand) -> bool:
    """True for a detector-only candidate (USGS `QuakeEvent` — no MT solution attached):
    its record is published with the F-net reference PENDING, and it is superseded when the
    matching F-net solution appears.  An `FnetMT` solution (has `m6_use`) is authoritative."""
    return getattr(cand, "m6_use", None) is None


# --------------------------------------------------------------------------- protocol
class EventSource(Protocol):
    def fetch(self, now: datetime) -> list:  # pragma: no cover - structural
        ...


# --------------------------------------------------------------------------- F-net
# Fetcher seam: (start, end, min_mw) -> list[FnetMT].  The default hits the live catalogue; tests
# inject a fake that returns a fixed list with no network.
FnetFetcher = Callable[[datetime, datetime, Optional[float]], List["object"]]


def _default_fnet_fetcher(start: datetime, end: datetime, min_mw: Optional[float]) -> list:
    from .fnet_mt import query_fnet_mt_catalogue

    return query_fnet_mt_catalogue(start, end, min_mw=min_mw)


def _in_bbox_ll(lat: float, lon: float, bbox: dict) -> bool:
    return (
        bbox["minlat"] <= lat <= bbox["maxlat"]
        and bbox["minlon"] <= lon <= bbox["maxlon"]
    )


class FnetMtSource:
    """Primary source: the public F-net regional-MT catalogue over a lookback window.

    Filters candidates to the configured Japan bbox and `min_mw` (client-side too, so the
    behaviour is identical whether or not the server honoured the query filter)."""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        *,
        fetcher: Optional[FnetFetcher] = None,
        lookback_days: Optional[int] = None,
        min_mw: Optional[float] = None,
    ) -> None:
        self.cfg = cfg or Config()
        self._fetcher = fetcher or _default_fnet_fetcher
        self.lookback_days = lookback_days if lookback_days is not None else self.cfg.window_days
        self.min_mw = min_mw if min_mw is not None else self.cfg.min_magnitude

    def fetch(self, now: datetime) -> list:
        start = now - timedelta(days=self.lookback_days)
        sols = self._fetcher(start, now, self.min_mw) or []
        return [s for s in sols if self._keep(s)]

    def _keep(self, s) -> bool:
        return float(s.mw) >= self.min_mw and _in_bbox_ll(float(s.lat), float(s.lon), self.cfg.bbox)


# --------------------------------------------------------------------------- USGS
class UsgsSource:
    """Near-live discovery source wrapping `catalogue.poll` (USGS FDSN GeoJSON -> QuakeEvent).

    USGS carries no MT, so this is a detector-only feed: its candidates are PROVISIONAL
    (inferred from the USGS origin, published reference-pending, superseded when the F-net MT
    appears).  The state machine (not `poll`'s own dedup) owns de-duplication, so it polls
    against a throwaway State unless one is injected.  `min_magnitude` defaults to the
    dedicated `cfg.usgs_min_magnitude` discovery threshold (USGS mags are mb-dominated near
    the F-net floor); `lookback_days` overrides the poll window."""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        *,
        fetcher: Optional[catalogue.Fetcher] = None,
        state: Optional[State] = None,
        min_magnitude: Optional[float] = None,
        lookback_days: Optional[int] = None,
    ) -> None:
        from dataclasses import replace

        cfg = cfg or Config()
        overrides = {
            "min_magnitude": cfg.usgs_min_magnitude if min_magnitude is None else min_magnitude,
        }
        if lookback_days is not None:
            overrides["window_days"] = int(lookback_days)
        self.cfg = replace(cfg, **overrides)
        self._fetcher = fetcher or catalogue.usgs_fetcher
        self._state = state or State()

    def fetch(self, now: datetime) -> list:
        return catalogue.poll(self.cfg, self._state, now, self._fetcher)


# --------------------------------------------------------------------------- multi
class MultiSource:
    """Concatenate several sources into one poll (order preserved: list the primary —
    F-net — first, so same-tick duplicates resolve in its favour downstream)."""

    def __init__(self, *sources) -> None:
        self.sources = [s for s in sources if s is not None]

    def fetch(self, now: datetime) -> list:
        out: list = []
        for src in self.sources:
            out.extend(src.fetch(now))
        return out


# --------------------------------------------------------------------------- fake
class FakeSource:
    """Fixed-list source for tests + integration (returns a copy each `fetch`)."""

    def __init__(self, events: list) -> None:
        self._events = list(events)

    def fetch(self, now: datetime) -> list:
        return list(self._events)
