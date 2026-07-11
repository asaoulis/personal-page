"""Probabilistic source-type classification — the lune-box exclusion metric.

Mirrors the Santorini lomax-suite headline metric (`uncertainty_metrics.prob_outside_dc_box`):
the posterior probability that the source lies OUTSIDE the near-DC lune box
``|gamma| < tau  &  |delta| < tau`` (tau = 10 degrees), computed over the (gamma, delta)
lune coordinates of the MT posterior cloud.  This is a *credible* statement, not a point
estimate: an event is labelled "non-DC" ONLY when ``p_outside >= 0.95`` — below that
threshold the honest label is "DC-consistent", never a hard non-DC claim.

The outside mass is sub-classified by its dominant lune coordinate (|delta|/90 vs
|gamma|/30, i.e. scaled by their respective ranges — the same rule as the frontend's
``sourceTypeClass``): delta-dominated -> ISO (signed +/-), else CLVD (signed +/-).

Core functions take (gamma, delta) arrays directly and are PURE numpy — the mock/demo
worker path stays free of seismo_sbi.  ``*_from samples6`` entry points convert an ``(N, 6)``
``[Mrr,Mtt,Mpp,Mrt,Mrp,Mtp]`` cloud via ``seismo_sbi.plotting.lune.mts6_to_gamma_delta``
(lazy import; scale-invariant, so physical and unit-norm clouds both work).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

DC_BOX_TAU_DEG = 10.0     # near-DC lune box half-width (the headline "first box")
NON_DC_THRESHOLD = 0.95   # credible mass required before an event is CALLED non-DC


def _gamma_delta(samples6):
    """(gamma, delta) arrays (deg) from an (N, 6) MT cloud (lazy seismo_sbi import)."""
    from seismo_sbi.plotting.lune import mts6_to_gamma_delta

    s = np.asarray(samples6, float).reshape(-1, 6)
    return mts6_to_gamma_delta(s)


def _resolve(samples6, gamma, delta):
    if gamma is None or delta is None:
        if samples6 is None:
            raise ValueError("need either samples6 or (gamma, delta)")
        gamma, delta = _gamma_delta(samples6)
    return np.asarray(gamma, float).ravel(), np.asarray(delta, float).ravel()


def prob_outside_dc_box(samples6=None, *, gamma=None, delta=None,
                        tau_deg: float = DC_BOX_TAU_DEG) -> float:
    """Posterior probability the source is outside the near-DC lune box
    ``|gamma| < tau & |delta| < tau`` — fraction of samples with
    ``|gamma| >= tau or |delta| >= tau``."""
    g, d = _resolve(samples6, gamma, delta)
    if g.size == 0:
        return float("nan")
    return float(np.mean((np.abs(g) >= tau_deg) | (np.abs(d) >= tau_deg)))


def classify_outside_mass(gamma, delta, tau_deg: float = DC_BOX_TAU_DEG) -> Optional[str]:
    """Sub-classify the outside-the-box posterior mass: ``"+ISO"/"-ISO"/"+CLVD"/"-CLVD"``.

    Over the samples outside the box, ISO vs CLVD by the dominant range-scaled coordinate
    (median ``|delta|/90`` vs median ``|gamma|/30``); the sign is the median sign of the
    dominant coordinate.  Returns None when no sample is outside."""
    g, d = _resolve(None, gamma, delta)
    outside = (np.abs(g) >= tau_deg) | (np.abs(d) >= tau_deg)
    if not np.any(outside):
        return None
    go, do = g[outside], d[outside]
    if np.median(np.abs(do)) / 90.0 >= np.median(np.abs(go)) / 30.0:
        return ("+" if np.median(do) >= 0 else "-") + "ISO"
    return ("+" if np.median(go) >= 0 else "-") + "CLVD"


def source_type_block(samples6=None, *, gamma=None, delta=None,
                      tau_deg: float = DC_BOX_TAU_DEG,
                      threshold: float = NON_DC_THRESHOLD) -> dict:
    """The record's ``source_type`` block: ``{p_outside_dc_box_10, label}``.

    ``label`` is a non-DC variant (``"non-DC (+ISO)"`` etc.) ONLY when the outside
    probability reaches ``threshold`` (default 0.95); otherwise ``"DC-consistent"``."""
    g, d = _resolve(samples6, gamma, delta)
    p = prob_outside_dc_box(gamma=g, delta=d, tau_deg=tau_deg)
    if np.isfinite(p) and p >= threshold:
        sub = classify_outside_mass(g, d, tau_deg=tau_deg)
        label = f"non-DC ({sub})" if sub else "non-DC"
    else:
        label = "DC-consistent"
    return {"p_outside_dc_box_10": round(float(p), 3), "label": label}
