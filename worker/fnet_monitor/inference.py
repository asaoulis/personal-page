"""Inference — produce a moment-tensor posterior ensemble for an event.

This skeleton ships ONLY a deterministic MOCK so the whole pipeline is end-to-end
testable without the trained model. Milestone M-D2 replaces `mock_posterior` with a
real call into `seismo_sbi` (fetch F-net waveforms -> NPE flow sampling), returning
the SAME dict shape so nothing downstream changes.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .catalogue import QuakeEvent

# Lune bounds (Tape & Tape source-type space), degrees.
GAMMA_MIN, GAMMA_MAX = -30.0, 30.0
DELTA_MIN, DELTA_MAX = -90.0, 90.0


def _seed(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16)


def classify_source_type(gamma: float, delta: float) -> str:
    if abs(delta) > 60:
        return "volcanic / -ISO" if delta < 0 else "explosive / +ISO"
    if abs(gamma) > 18 or abs(delta) > 20:
        return "CLVD-leaning"
    if abs(gamma) > 7 and abs(delta) < 8:
        return "strike-slip"
    return "double-couple"


def mock_posterior(ev: "QuakeEvent", n: int, rng: np.random.Generator | None = None) -> dict:
    """Deterministic, plausible posterior for an event.

    Uses the event's mechanism hints if present (the demo catalogue supplies them);
    otherwise derives a stable pseudo-mechanism from the event id so live USGS events
    still get a believable (but clearly MOCK) result.
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
    source_type = ev.source_type or classify_source_type(gc, dc)

    cov = [[14.0, 0.0], [0.0, 36.0]]
    samples = r.multivariate_normal([gc, dc], cov, n)
    gamma = np.clip(samples[:, 0], GAMMA_MIN, GAMMA_MAX)
    delta = np.clip(samples[:, 1], DELTA_MIN, DELTA_MAX)

    # A mock catalogue reference solution near the posterior mean.
    ref_gamma = float(np.clip(gc + r.normal(0, 2.5), GAMMA_MIN, GAMMA_MAX))
    ref_delta = float(np.clip(dc + r.normal(0, 4.0), DELTA_MIN, DELTA_MAX))
    kagan = round(float(abs(r.normal(10, 5)) + 2), 1)

    return {
        "strike": round(strike, 1),
        "dip": round(dip, 1),
        "rake": round(rake, 1),
        "source_type": source_type,
        "gamma_mean": round(float(gamma.mean()), 2),
        "delta_mean": round(float(delta.mean()), 2),
        "posterior": {
            "gamma": [round(float(x), 2) for x in gamma],
            "delta": [round(float(x), 2) for x in delta],
        },
        "reference": {
            "source": "F-net (mock)",
            "gamma": round(ref_gamma, 2),
            "delta": round(ref_delta, 2),
            "strike": round(strike + float(r.normal(0, 8)), 1),
            "dip": round(float(np.clip(dip + r.normal(0, 6), 0, 90)), 1),
            "rake": round(rake + float(r.normal(0, 10)), 1),
            "kagan_deg": kagan,
        },
    }


def real_posterior(ev: "QuakeEvent", n: int) -> dict:  # pragma: no cover - M-D2
    raise NotImplementedError(
        "Real NPE inference is milestone M-D2: fetch F-net waveforms (HinetPy, code 0103) "
        "and sample the trained seismo_sbi posterior. Must return the same dict shape as "
        "mock_posterior()."
    )
