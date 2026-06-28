"""Reference moment-tensor solutions per event (hybrid real + synthetic fallback).

Design mirrors `catalogue.py`: the network call is isolated behind an injectable `Fetcher`
callable, so the parsing/normalising/synthesising logic is pure and unit-testable offline.

Flow:
  - `fetch_references(events, fetcher)` (ONLINE, one-time) → raw refs per event id. The real
    fetcher hits the USGS event-detail endpoint, which aggregates moment-tensor products from
    several sources (US W-phase, GCMT, Duputel…). `parse_usgs_mt_products` is PURE.
  - `save_cache` / `load_cache` persist the raw refs to a committed JSON
    (`worker/data/reference_cache.json`). The deterministic generator reads ONLY the cache.
  - `synthesize_reference(ev)` → a seeded, geologically-plausible Japan-regime mechanism for
    events with no real solution (GCMT floor ~M5, USGS-Mww ~M4.5; many mb events have neither).
  - `normalise_reference(raw)` → {source, gamma, delta, strike, dip, rake, mt6, mw} via pyrocko
    + seismo_sbi lune conventions (needs the `seismo-sbi` env). Kagan-to-model is added later by
    `synthetic.synthetic_posterior` (it needs the model solution).

Raw ref shape (what the cache stores): {"source": str, "mt6": [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp],
"mw": float|None, "synthetic": bool}. mt6 is the GCMT up-south-east (USE) 6-vector.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Callable, Dict, List, Optional

from .catalogue import QuakeEvent

# fetcher: USGS event id -> event-detail GeoJSON dict
Fetcher = Callable[[str], dict]

# Primary-reference preference (lower = more trusted). F-net is the home regional catalogue for
# this Japan demo (best coverage + the authoritative local solution), so it leads; then the global
# GCMT, then USGS-Mww, then the synthetic fallback.
_SOURCE_RANK = {"F-net": 0, "GCMT": 1, "USGS": 2, "synthetic": 9}


def source_rank(source: str) -> int:
    return _SOURCE_RANK.get(source, 5)


# --------------------------------------------------------------------- USGS parsing (pure)
def _label_for(source: str) -> str:
    s = (source or "").lower()
    if "gcmt" in s or "gpr" in s:
        return "GCMT"
    return "USGS"


def parse_usgs_mt_products(detail: dict) -> List[dict]:
    """Extract moment-tensor raw refs from a USGS event-detail GeoJSON. Pure (no network).

    Reads `properties.products["moment-tensor"]` — each carries `tensor-mrr…tensor-mtp`
    (N·m, USE convention) + `derived-magnitude`. Dedupes to one ref per label (GCMT/USGS),
    keeping the first (USGS lists the preferred product first). focal-mechanism (NP-only,
    no tensor) products are skipped.
    """
    products = (detail.get("properties", {}) or {}).get("products", {}) or {}
    mts = products.get("moment-tensor", []) or []
    out: List[dict] = []
    seen: set = set()
    for mt in mts:
        p = mt.get("properties", {}) or {}
        try:
            m6 = [
                float(p["tensor-mrr"]),
                float(p["tensor-mtt"]),
                float(p["tensor-mpp"]),
                float(p["tensor-mrt"]),
                float(p["tensor-mrp"]),
                float(p["tensor-mtp"]),
            ]
        except (KeyError, ValueError, TypeError):
            continue  # no tensor on this product
        if not any(abs(x) > 0 for x in m6):
            continue
        label = _label_for(mt.get("source") or p.get("beachball-source") or "us")
        if label in seen:
            continue
        seen.add(label)
        mw = p.get("derived-magnitude")
        try:
            mw = float(mw) if mw is not None else None
        except (ValueError, TypeError):
            mw = None
        out.append({"source": label, "mt6": m6, "mw": mw, "synthetic": False})
    return out


# --------------------------------------------------------------------- online fetch
def usgs_detail_fetcher(event_id: str) -> dict:
    """Real USGS event-detail call. Imported lazily so offline tests need no `requests`."""
    import requests

    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    r = requests.get(url, params={"eventid": event_id, "format": "geojson"}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_references(events: List[QuakeEvent], fetcher: Fetcher = usgs_detail_fetcher) -> Dict[str, List[dict]]:
    """Per event, fetch + parse real moment-tensor refs. Returns {event_id: [raw_ref, ...]}
    (an empty list for events with no real solution). Network errors degrade to []."""
    cache: Dict[str, List[dict]] = {}
    for ev in events:
        try:
            detail = fetcher(ev.id)
            cache[ev.id] = parse_usgs_mt_products(detail)
        except Exception:  # noqa: BLE001 — best-effort; the generator synthesizes a fallback
            cache[ev.id] = []
    return cache


# --------------------------------------------------------------------- cache I/O (pure)
def save_cache(path: str, cache: Dict[str, List[dict]], meta: Optional[dict] = None) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"meta": meta or {}, "references": cache}
    with open(path, "w") as f:
        json.dump(payload, f, indent=1)


def load_cache(path: str) -> Dict[str, List[dict]]:
    """Load the committed raw-reference cache. Missing file → {} (generator then synthesizes
    every event, so it runs offline before any fetch)."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        payload = json.load(f)
    return payload.get("references", payload) if isinstance(payload, dict) else {}


# --------------------------------------------------------------------- synthesize (seeded)
def _seed(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16)


def _sdr_to_m6_use(strike, dip, rake):
    # Pure-python Aki&Richards -> USE; identical convention to inference.sdr_to_m6_use.
    from .inference import sdr_to_m6_use

    return sdr_to_m6_use(strike, dip, rake)


def synthesize_reference(ev: QuakeEvent) -> dict:
    """A geologically-plausible Japan-regime mechanism, seeded by event id (deterministic).

    Coarse regime by depth + position so synthetic refs still look real on the map/lune:
      - deep (>70 km) intraslab: steep, variable rake;
      - offshore Pacific side (lon ≳ 140, lat 34–42): subduction thrust (trench-parallel ~N20°E
        strike, shallow dip, reverse rake);
      - inland crustal: strike-slip or normal.
    """
    import numpy as np

    r = np.random.default_rng(_seed(ev.id))
    depth, lon, lat = ev.depth_km, ev.lon, ev.lat
    if depth > 70:  # intraslab
        strike = float(r.uniform(0, 360))
        dip = float(r.uniform(30, 75))
        rake = float(r.uniform(-180, 180))
    elif lon >= 140.0 and 34.0 <= lat <= 42.5:  # subduction thrust, Pacific side
        strike = float(r.normal(200, 18))
        dip = float(np.clip(r.normal(22, 6), 8, 45))
        rake = float(np.clip(r.normal(90, 18), 40, 140))
    elif r.random() < 0.5:  # inland strike-slip
        strike = float(r.uniform(0, 360))
        dip = float(np.clip(r.normal(78, 8), 55, 90))
        rake = float(r.choice([5.0, 175.0, -175.0]) + r.normal(0, 12))
    else:  # inland normal
        strike = float(r.uniform(0, 360))
        dip = float(np.clip(r.normal(50, 8), 35, 70))
        rake = float(np.clip(r.normal(-90, 18), -140, -40))
    mw = float(ev.mag) if ev.mag else 4.0
    return {"source": "synthetic", "mt6": _sdr_to_m6_use(strike, dip, rake), "mw": mw, "synthetic": True}


# --------------------------------------------------------------------- normalise (pyrocko)
def _unit(m6: List[float]) -> List[float]:
    import numpy as np

    a = np.asarray(m6, float)
    n = float(np.linalg.norm(a))
    return (a / n).tolist() if n > 0 else a.tolist()


def normalise_reference(raw: dict) -> dict:
    """Raw ref (with USE mt6) -> {source, gamma, delta, strike, dip, rake, mt6(unit), mw}.

    Uses pyrocko for SDR + a moment magnitude when none was supplied, and the seismo_sbi lune
    conventions for (gamma, delta). Needs the `seismo-sbi` env. Kagan-to-model is added later.
    """
    import numpy as np
    from seismo_sbi.evaluation.moment_tensor import pyrocko_mt
    from seismo_sbi.plotting.lune import mts6_to_gamma_delta

    m6 = [float(x) for x in raw["mt6"]]
    mt = pyrocko_mt(m6)
    sdr = mt.both_strike_dip_rake()[0]
    g, d = mts6_to_gamma_delta(np.array([m6]))
    mw = raw.get("mw")
    if mw is None:
        try:
            mw = float(mt.magnitude)
        except Exception:  # noqa: BLE001
            mw = None
    return {
        "source": raw["source"],
        "gamma": float(g[0]),
        "delta": float(d[0]),
        "strike": float(sdr[0]),
        "dip": float(sdr[1]),
        "rake": float(sdr[2]),
        "mt6": _unit(m6),
        "mw": float(mw) if mw is not None else None,
    }
