"""Inference — produce a moment-tensor posterior for an event.

This module ships ONLY a deterministic MOCK so the whole pipeline is end-to-end testable
without the trained model, and pure-python (numpy only) so it runs anywhere. The realistic
static demo data is produced by the `seismo_sbi`-backed generator (`synthetic.py` +
`build_demo_catalogue.py`); milestone M-D2 replaces `real_posterior` with the trained NPE.
All three return the SAME schema-3 `post` dict shape that `contract.build_event_record`
consumes, so nothing downstream changes.

`post` shape:
    strike, dip, rake        model best/mean SDR (drives the marker)
    source_type              coarse label
    gamma_mean, delta_mean   posterior-mean lune coords
    mw                       solution moment magnitude (or None)
    posterior {gamma[], delta[], mt6[][]}   (gamma, delta) cloud + downsampled mt6 ensemble
    references [ {source, gamma, delta, strike, dip, rake, mt6, kagan_deg, mw?}, ... ]  primary first
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING, List

import numpy as np

if TYPE_CHECKING:
    from .catalogue import QuakeEvent

# Lune bounds (Tape & Tape source-type space), degrees.
GAMMA_MIN, GAMMA_MAX = -30.0, 30.0
DELTA_MIN, DELTA_MAX = -90.0, 90.0

# Fuzzy-beachball ensemble size written per event (kept small — it only needs to render).
N_MT6 = 80


def _seed(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16)


def sdr_to_m6_use(strike: float, dip: float, rake: float, scalar_moment: float = 1.0) -> List[float]:
    """Strike/dip/rake (degrees) -> moment tensor [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] in the GCMT
    up-south-east convention (matches pyrocko `MomentTensor.m6_up_south_east()` and the
    seismo_sbi m6 convention exactly — verified to cos-align 1.0). Aki & Richards (1980) in
    NED, then NED->USE: [Mzz, Mxx, Myy, Mxz, -Myz, -Mxy] with (x,y,z) = (N,E,D)."""
    s, d, l = math.radians(strike), math.radians(dip), math.radians(rake)
    sd, cd = math.sin(d), math.cos(d)
    s2d, c2d = math.sin(2 * d), math.cos(2 * d)
    ss, cs = math.sin(s), math.cos(s)
    s2s, c2s = math.sin(2 * s), math.cos(2 * s)
    sl, cl = math.sin(l), math.cos(l)
    Mxx = -(sd * cl * s2s + s2d * sl * ss * ss)
    Mxy = sd * cl * c2s + 0.5 * s2d * sl * s2s
    Mxz = -(cd * cl * cs + c2d * sl * ss)
    Myy = sd * cl * s2s - s2d * sl * cs * cs
    Myz = -(cd * cl * ss - c2d * sl * cs)
    Mzz = s2d * sl
    m6 = [Mzz, Mxx, Myy, Mxz, -Myz, -Mxy]
    return [scalar_moment * x for x in m6]


def classify_source_type(gamma: float, delta: float) -> str:
    if abs(delta) > 60:
        return "volcanic / -ISO" if delta < 0 else "explosive / +ISO"
    if abs(gamma) > 18 or abs(delta) > 20:
        return "CLVD-leaning"
    if abs(gamma) > 7 and abs(delta) < 8:
        return "strike-slip"
    return "double-couple"


def _mt6_ensemble(strike: float, dip: float, rake: float, n: int, r: np.random.Generator) -> List[List[float]]:
    """A small SDR-perturbed mt6 ensemble (USE convention) for the fuzzy beachball."""
    out: List[List[float]] = []
    for _ in range(max(1, n)):
        s = strike + float(r.normal(0, 8))
        d = float(np.clip(dip + r.normal(0, 6), 1, 89))
        k = rake + float(r.normal(0, 10))
        out.append([round(x, 4) for x in sdr_to_m6_use(s, d, k)])
    return out


def mock_posterior(ev: "QuakeEvent", n: int, rng: np.random.Generator | None = None) -> dict:
    """Deterministic, plausible schema-3 posterior for an event.

    Uses the event's mechanism hints if present (the demo catalogue supplies them); otherwise
    derives a stable pseudo-mechanism from the event id so live USGS events still get a believable
    (but clearly MOCK) result. Pure-python — no seismo_sbi/pyrocko.
    """
    r = rng or np.random.default_rng(_seed(ev.id))

    if ev.strike is not None:
        strike, dip, rake = float(ev.strike), float(ev.dip), float(ev.rake)
    else:
        strike = float(r.uniform(0, 360))
        dip = float(r.uniform(20, 85))
        rake = float(r.choice([1, -1]) * r.uniform(20, 160))

    gc = ev.gamma if ev.gamma is not None else float(r.normal(0, 6))
    dc = ev.delta if ev.delta is not None else float(r.normal(0, 8))
    gc = float(np.clip(gc, GAMMA_MIN, GAMMA_MAX))
    dc = float(np.clip(dc, DELTA_MIN, DELTA_MAX))

    cov = [[14.0, 0.0], [0.0, 36.0]]
    samples = r.multivariate_normal([gc, dc], cov, n)
    gamma = np.clip(samples[:, 0], GAMMA_MIN, GAMMA_MAX)
    delta = np.clip(samples[:, 1], DELTA_MIN, DELTA_MAX)

    mt6 = _mt6_ensemble(strike, dip, rake, min(n, N_MT6), r)

    # probabilistic source-type block (lune-box exclusion metric, τ=10°) — pure numpy path.
    from .source_type import source_type_block
    source_type = source_type_block(gamma=gamma, delta=delta)
    p_outside = source_type["p_outside_dc_box_10"]

    # A mock catalogue reference solution near the posterior mean.
    ref_gamma = float(np.clip(gc + r.normal(0, 2.5), GAMMA_MIN, GAMMA_MAX))
    ref_delta = float(np.clip(dc + r.normal(0, 4.0), DELTA_MIN, DELTA_MAX))
    ref_strike = round(strike + float(r.normal(0, 8)), 1)
    ref_dip = round(float(np.clip(dip + r.normal(0, 6), 0, 90)), 1)
    ref_rake = round(rake + float(r.normal(0, 10)), 1)
    kagan = round(float(abs(r.normal(10, 5)) + 2), 1)
    mw = round(float(ev.mag), 1) if ev.mag is not None else None

    return {
        "strike": round(strike, 1),
        "dip": round(dip, 1),
        "rake": round(rake, 1),
        "source_type": source_type,
        "mw": mw,
        "p_outside_dc_box": round(p_outside, 3),
        "gamma_mean": round(float(gamma.mean()), 2),
        "delta_mean": round(float(delta.mean()), 2),
        "posterior": {
            "gamma": [round(float(x), 2) for x in gamma],
            "delta": [round(float(x), 2) for x in delta],
            "mt6": mt6,
        },
        "references": [
            {
                "source": "F-net (mock)",
                "gamma": round(ref_gamma, 2),
                "delta": round(ref_delta, 2),
                "strike": ref_strike,
                "dip": ref_dip,
                "rake": ref_rake,
                "mt6": [round(x, 4) for x in sdr_to_m6_use(ref_strike, ref_dip, ref_rake)],
                "kagan_deg": kagan,
                "mw": mw,
            }
        ],
    }


# --------------------------------------------------------------------------- real NPE
# Defaults point at the local seismo-sbi checkout + the Jan-2026 F-net catalogue; override via
# env so a server / CI can relocate them. The heavy backend is built lazily + cached so the
# pure-python worker (mock path) never imports torch/seismo_sbi.
import os as _os

NPE_CONFIG = _os.environ.get(
    "NPE_CONFIG", "/home/alex/work/seismo-sbi/scripts/configs/japan/first_ml_npe_japan.yaml")
NPE_CKPT_DIR = _os.environ.get(
    "NPE_CKPT_DIR", "/home/alex/work/seismo-sbi/ml-checkpoints/japan_v1")
NPE_CATALOGUE_DIR = _os.environ.get(
    "NPE_CATALOGUE_DIR", "/data/alex/fnet_japan/catalogue/events")
NPE_REFERENCE_CACHE = _os.environ.get(
    "NPE_REFERENCE_CACHE",
    _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "data", "reference_cache.json"))

_BACKEND = None


def get_backend():
    """Lazily build + cache the NpeBackend (loads the pipeline+posterior+scaler once)."""
    global _BACKEND
    if _BACKEND is None:
        from .npe_backend import NpeBackend
        _BACKEND = NpeBackend(NPE_CONFIG, NPE_CKPT_DIR)
    return _BACKEND


def event_stem(ev: "QuakeEvent") -> str:
    """Origin-time stem `YYYYMMDDTHHMMSS` — the catalogue h5 / EventSolution match key."""
    t = ev.time
    return f"{t.year:04d}{t.month:02d}{t.day:02d}T{t.hour:02d}{t.minute:02d}{t.second:02d}"


def resolve_event_h5(ev: "QuakeEvent", catalogue_dir: str = None) -> str:
    """Path to this event's SBI h5 in the pre-built catalogue (exact stem, else ±a few seconds).

    Returns the path or raises FileNotFoundError. The live download→preprocess path (Phase C)
    supplies its own h5 and calls `real_posterior_from_h5` directly.
    """
    import glob
    cdir = catalogue_dir or NPE_CATALOGUE_DIR
    stem = event_stem(ev)
    exact = _os.path.join(cdir, f"{stem}.h5")
    if _os.path.exists(exact):
        return exact
    # tolerate a ±2 s rounding difference between the QuakeML origin and the h5 stem
    day = stem[:9]
    for p in sorted(glob.glob(_os.path.join(cdir, f"{day}*.h5"))):
        hh = _os.path.basename(p)[9:15]
        try:
            dt = abs((int(hh[:2]) * 3600 + int(hh[2:4]) * 60 + int(hh[4:6]))
                     - (ev.time.hour * 3600 + ev.time.minute * 60 + ev.time.second))
        except ValueError:
            continue
        if dt <= 2:
            return p
    raise FileNotFoundError(f"no catalogue h5 for {stem} under {cdir}")


def _references_for(ev: "QuakeEvent") -> list:
    """Normalised references (primary first) for an event — real from the cache, else synthetic."""
    from . import references as R
    cache = R.load_cache(NPE_REFERENCE_CACHE)
    raw = cache.get(ev.id, [])
    if not raw:
        raw = [R.synthesize_reference(ev)]
    raw = sorted(raw, key=lambda r: R.source_rank(r.get("source", "")))
    return [R.normalise_reference(r) for r in raw]


def real_posterior_from_h5(ev: "QuakeEvent", event_h5: str, n: int, *,
                           components_map: dict = None, station_names=None) -> dict:
    """Run the trained NPE on a specific event h5 and return the schema-3 `post` dict.

    Shared by the catalogue driver and the live path. `source_vec` = `[lat, lon, depth_km]`
    (the model's `ml_conditioning.param_map` order).
    """
    from .mt_serialize import post_from_cloud
    backend = get_backend()
    source_vec = [float(ev.lat), float(ev.lon), float(ev.depth_km)]
    samples6, _used = backend.infer(event_h5, source_vec, num_samples=n,
                                    components_map=components_map, station_names=station_names)
    refs = _references_for(ev)
    return post_from_cloud(samples6, refs)


def real_posterior(ev: "QuakeEvent", n: int) -> dict:
    """Real NPE posterior for a catalogued event (resolves its h5 in the F-net catalogue)."""
    return real_posterior_from_h5(ev, resolve_event_h5(ev), n)
