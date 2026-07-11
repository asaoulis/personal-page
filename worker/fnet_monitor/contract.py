"""The v3 data contract — compact JSON the frontend renders client-side.

  events.json            GeoJSON FeatureCollection index (one summary Feature/event,
                         with `properties.ensemble` pointing at the per-event file).
                         Carries explicit `window_start`/`window_end` (the slider bounds
                         come from the DATA, not wall-clock `now`).
  events/<id>.json       full per-event record: the (gamma, delta) posterior cloud AND a
                         downsampled `posterior.mt6` ensemble (drives the client-rendered
                         FUZZY beachball), plus `references[]` — every catalogue solution
                         that resolved the event (GCMT / USGS / F-net / synthetic), each
                         with its own (gamma, delta), strike/dip/rake, mt6 and Kagan angle
                         to the model. NO rendered images — the browser draws everything.

`validate_index` / `validate_event` are the schema gate (used by tests + the worker before
writing). Keep them in lockstep with the frontend's TypeScript types (`types.ts`).

Schema history: v2 = single `reference` + (gamma, delta) cloud. v3 = `references[]` (multi-
reference, primary first) + `posterior.mt6` ensemble + index `window_start`/`window_end` +
`primary_source`/`primary_kagan_deg`/`n_references`. v3 extension (2026-07): `source_type`
became the probabilistic block `{p_outside_dc_box_10, label}` (lune-box exclusion metric;
"non-DC (...)" only at p >= 0.95, else "DC-consistent"). This module stays PURE (json/stdlib only)
so the legacy pure-python worker + its tests run anywhere; the science-heavy generator lives in
separate modules under the `seismo-sbi` conda env.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import timedelta
from typing import List, Optional

from .catalogue import QuakeEvent
from .config import Config
from .util import from_iso, to_iso

SCHEMA_VERSION = 3


def build_event_record(
    ev: QuakeEvent,
    post: dict,
    generated_iso: str,
    mock: bool,
    model: Optional[str] = None,
) -> dict:
    """Assemble a schema-3 per-event record from an event + an inference `post` dict.

    `post` must provide: strike/dip/rake (model best/mean SDR — drives the marker), source_type,
    gamma_mean/delta_mean, optional `mw`, `posterior` ({gamma, delta, mt6}) and `references`
    (non-empty list, primary first; each {source, gamma, delta, strike, dip, rake, mt6, kagan_deg,
    optional mw}).
    """
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
        "mw": post.get("mw"),
        "p_outside_dc_box": post.get("p_outside_dc_box"),
        "posterior": post["posterior"],
        "summary": {"gamma": post["gamma_mean"], "delta": post["delta_mean"]},
        "references": post["references"],
        "provenance": {
            "generated": generated_iso,
            "mock": mock,
            "model": model or ("mock-skeleton" if mock else "seismo_sbi-npe"),
        },
    }


def index_feature(rec: dict) -> dict:
    """Compact summary Feature for the map + slider (no ensemble inline)."""
    refs = rec.get("references") or []
    primary = refs[0] if refs else {}
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
            "mw": rec.get("mw"),
            "p_outside_dc_box": rec.get("p_outside_dc_box"),
            # no references yet => a provisional record awaiting the F-net publication
            "primary_source": primary.get("source", "pending"),
            "primary_kagan_deg": primary.get("kagan_deg"),
            "n_references": len(refs),
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


def _index_envelope(generated_iso, window_start, window_end, cfg, mock, feats):
    return {
        "type": "FeatureCollection",
        "schema": SCHEMA_VERSION,
        "generated": generated_iso,
        "window_days": cfg.window_days,
        "window_start": window_start,
        "window_end": window_end,
        "region": cfg.region_name,
        "mock": mock,
        "features": feats,
    }


def rebuild_index(out_dir: str, cfg: Config, now, mock: bool) -> dict:
    """LIVE path: read all per-event records, PRUNE those older than the window (deleting their
    files), and build the index FeatureCollection sorted newest-first. The slider window is the
    rolling `[now - window_days, now]`."""
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
    return _index_envelope(
        to_iso(now), to_iso(cutoff_old), to_iso(now), cfg, mock, [index_feature(r) for r in recs]
    )


def build_static_index(records: List[dict], generated_iso: str, cfg: Config, mock: bool = True) -> dict:
    """STATIC path (the realistic demo generator): build the index over an explicit set of records
    with NO now-based pruning. `window_start`/`window_end` span the actual event times so the
    frontend slider scrubs the real catalogue date range (e.g. Jan 2026), independent of `now`."""
    recs = sorted(records, key=lambda r: r["time"], reverse=True)
    times = [r["time"] for r in recs]
    window_start = min(times) if times else generated_iso
    window_end = max(times) if times else generated_iso
    return _index_envelope(
        generated_iso, window_start, window_end, cfg, mock, [index_feature(r) for r in recs]
    )


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


def _validate_reference(ref: dict) -> None:
    for k in ("source", "gamma", "delta", "strike", "dip", "rake", "mt6", "kagan_deg"):
        _require(k in ref, f"reference missing '{k}'")
    _require(len(ref["mt6"]) == 6, "reference mt6 must be a 6-vector")
    _require(-30.0 <= ref["gamma"] <= 30.0, "reference gamma out of [-30,30]")
    _require(-90.0 <= ref["delta"] <= 90.0, "reference delta out of [-90,90]")


def _validate_source_type(st) -> None:
    """`source_type` is the probabilistic block {p_outside_dc_box_10, label}: the label may
    claim non-DC ONLY at >= 0.95 posterior mass outside the +/-10 deg near-DC lune box."""
    _require(isinstance(st, dict), "source_type must be a {p_outside_dc_box_10, label} block")
    _require("label" in st and isinstance(st["label"], str) and st["label"],
             "source_type missing 'label'")
    p = st.get("p_outside_dc_box_10")
    _require(isinstance(p, (int, float)) and 0.0 <= float(p) <= 1.0,
             "source_type p_outside_dc_box_10 must be a probability in [0,1]")
    if st["label"].lower().startswith("non-dc"):
        _require(float(p) >= 0.95, "non-DC label below the 0.95 credibility threshold")


def validate_event(rec: dict) -> None:
    for k in ("id", "time", "mag", "depth_km", "lon", "lat", "strike", "dip", "rake"):
        _require(k in rec, f"event missing '{k}'")
    _require("source_type" in rec, "event missing 'source_type'")
    _validate_source_type(rec["source_type"])
    p = rec.get("posterior", {})
    _require("gamma" in p and "delta" in p, "posterior missing gamma/delta")
    _require(len(p["gamma"]) == len(p["delta"]), "gamma/delta length mismatch")
    _require(len(p["gamma"]) > 0, "empty posterior")
    _require(all(-30.0 <= g <= 30.0 for g in p["gamma"]), "gamma out of [-30,30]")
    _require(all(-90.0 <= d <= 90.0 for d in p["delta"]), "delta out of [-90,90]")
    _require("mt6" in p, "posterior missing mt6 ensemble")
    _require(len(p["mt6"]) > 0, "empty mt6 ensemble")
    _require(all(len(m) == 6 for m in p["mt6"]), "mt6 entries must be 6-vectors")
    refs = rec.get("references")
    # An EMPTY list is valid: a provisional USGS-discovered event is published with the
    # F-net reference PENDING (attached later by the supersede-on-match flow).
    _require(isinstance(refs, list), "references must be a list (may be empty: pending)")
    for ref in refs:
        _validate_reference(ref)


def validate_index(index: dict) -> None:
    _require(index.get("type") == "FeatureCollection", "index not a FeatureCollection")
    for key in ("generated", "window_days", "features", "window_start", "window_end"):
        _require(key in index, f"index missing '{key}'")
    for feat in index["features"]:
        props = feat.get("properties", {})
        for k in ("id", "time", "mag", "ensemble", "primary_source", "n_references"):
            _require(k in props, f"index feature missing '{k}'")
        coords = feat.get("geometry", {}).get("coordinates", [])
        _require(len(coords) == 2, "feature geometry must be [lon, lat]")
