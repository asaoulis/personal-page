"""The v2 data contract — compact JSON the frontend renders client-side.

  events.json            GeoJSON FeatureCollection index (one summary Feature/event,
                         with `properties.ensemble` pointing at the per-event file).
  events/<id>.json       full per-event record: the (gamma, delta) posterior ensemble,
                         strike/dip/rake (drives the canvas beachball), and the catalogue
                         reference solution. NO rendered images — the browser draws them.

`validate_index` / `validate_event` are the schema gate (used by tests + the worker
before writing). Keep them in lockstep with the frontend's TypeScript types.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import timedelta
from typing import List

from .catalogue import QuakeEvent
from .config import Config
from .util import from_iso, to_iso

SCHEMA_VERSION = 2


def build_event_record(ev: QuakeEvent, post: dict, generated_iso: str, mock: bool) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "id": ev.id,
        "time": to_iso(ev.time),
        "mag": round(ev.mag, 1),
        "magType": ev.magtype,
        "depth_km": round(ev.depth_km, 1),
        "lon": round(ev.lon, 4),
        "lat": round(ev.lat, 4),
        "region": ev.region,
        "source_type": post["source_type"],
        "strike": post["strike"],
        "dip": post["dip"],
        "rake": post["rake"],
        "posterior": post["posterior"],
        "summary": {"gamma": post["gamma_mean"], "delta": post["delta_mean"]},
        "reference": post["reference"],
        "provenance": {
            "generated": generated_iso,
            "mock": mock,
            "model": "mock-skeleton" if mock else "seismo_sbi-npe",
        },
    }


def index_feature(rec: dict) -> dict:
    """Compact summary Feature for the map + slider (no ensemble inline)."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [rec["lon"], rec["lat"]]},
        "properties": {
            "id": rec["id"],
            "time": rec["time"],
            "mag": rec["mag"],
            "magType": rec["magType"],
            "depth_km": rec["depth_km"],
            "region": rec["region"],
            "source_type": rec["source_type"],
            "gamma": rec["summary"]["gamma"],
            "delta": rec["summary"]["delta"],
            "strike": rec["strike"],
            "dip": rec["dip"],
            "rake": rec["rake"],
            "kagan_deg": rec["reference"]["kagan_deg"],
            "catalogue_source": rec["reference"]["source"],
            "ensemble": f"events/{rec['id']}.json",
        },
    }


def write_event(out_dir: str, rec: dict) -> str:
    d = os.path.join(out_dir, "events")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{rec['id']}.json")
    with open(path, "w") as f:
        json.dump(rec, f, separators=(",", ":"))
    return path


def rebuild_index(out_dir: str, cfg: Config, now, mock: bool) -> dict:
    """Read all per-event records, PRUNE those older than the window (deleting their
    files), and build the index FeatureCollection sorted newest-first."""
    cutoff_old = now - timedelta(days=cfg.window_days)
    recs: List[dict] = []
    for path in glob.glob(os.path.join(out_dir, "events", "*.json")):
        with open(path) as f:
            rec = json.load(f)
        if from_iso(rec["time"]) < cutoff_old:
            os.remove(path)  # rolling-window retention
            continue
        recs.append(rec)
    recs.sort(key=lambda r: r["time"], reverse=True)
    return {
        "type": "FeatureCollection",
        "schema": SCHEMA_VERSION,
        "generated": to_iso(now),
        "window_days": cfg.window_days,
        "region": cfg.region_name,
        "mock": mock,
        "features": [index_feature(r) for r in recs],
    }


def write_index(out_dir: str, index: dict) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "events.json")
    with open(path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    return path


# --------------------------------------------------------------------------- schema
def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"contract violation: {msg}")


def validate_event(rec: dict) -> None:
    for k in ("id", "time", "mag", "depth_km", "lon", "lat", "strike", "dip", "rake"):
        _require(k in rec, f"event missing '{k}'")
    p = rec.get("posterior", {})
    _require("gamma" in p and "delta" in p, "posterior missing gamma/delta")
    _require(len(p["gamma"]) == len(p["delta"]), "gamma/delta length mismatch")
    _require(len(p["gamma"]) > 0, "empty posterior")
    _require(all(-30.0 <= g <= 30.0 for g in p["gamma"]), "gamma out of [-30,30]")
    _require(all(-90.0 <= d <= 90.0 for d in p["delta"]), "delta out of [-90,90]")
    ref = rec.get("reference", {})
    _require("kagan_deg" in ref and "source" in ref, "reference missing kagan/source")


def validate_index(index: dict) -> None:
    _require(index.get("type") == "FeatureCollection", "index not a FeatureCollection")
    for key in ("generated", "window_days", "features"):
        _require(key in index, f"index missing '{key}'")
    for feat in index["features"]:
        props = feat.get("properties", {})
        for k in ("id", "time", "mag", "ensemble"):
            _require(k in props, f"index feature missing '{k}'")
        coords = feat.get("geometry", {}).get("coordinates", [])
        _require(len(coords) == 2, "feature geometry must be [lon, lat]")
