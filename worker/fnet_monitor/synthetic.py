"""Dummy posterior generator for the realistic static demo.

Stands in for the trained NPE (M-D2). Produces the SAME schema-3 `post` dict that
`contract.build_event_record` consumes, so the live `real_posterior` can swap in unchanged.

How the dummy posterior is built (faithful to the method, not just decorative):
  - The model "best" solution is the PRIMARY reference's MT nudged by a small seeded offset, so
    the model agrees with — but is not identical to — the catalogue (a few-degree Kagan angle, as
    a real inversion would give).
  - The posterior is a Gaussian cloud in MT (m6) space around that best solution — which is
    exactly what optimal score compression yields — with width scaled by Mw (small events ⇒
    broader posterior). ONE m6 ensemble drives BOTH the lune (γ,δ) cloud (via
    `mts6_to_gamma_delta`) and the client fuzzy beachball, so they are mutually consistent.
  - Every reference gets a Kagan angle to the model best.

Needs the `seismo-sbi` env (pyrocko + seismo_sbi lune/kagan).
"""

from __future__ import annotations

from typing import List

from .catalogue import QuakeEvent
from .source_type import source_type_block

GAMMA_MIN, GAMMA_MAX = -30.0, 30.0
DELTA_MIN, DELTA_MAX = -90.0, 90.0
DC_BOX_TAU = 10.0  # near-DC lune box half-width for the non-DC exclusion metric


def _mw_spread_frac(mw: float) -> float:
    """Posterior width as a fraction of ‖M‖, larger for smaller magnitudes — informative like an
    NPE posterior, not artificially tight."""
    import numpy as np

    return float(np.clip(0.045 + 0.05 * (5.5 - min(mw, 5.5)), 0.045, 0.22))


def _use_m6_to_matrix(m6):
    import numpy as np

    Mrr, Mtt, Mpp, Mrt, Mrp, Mtp = m6
    return np.array([[Mrr, Mrt, Mrp], [Mrt, Mtt, Mtp], [Mrp, Mtp, Mpp]])


def _matrix_to_use_m6(M):
    return [M[0, 0], M[1, 1], M[2, 2], M[0, 1], M[0, 2], M[1, 2]]


def _retype(ref_m6, lam_new):
    """Return a unit m6 (USE) with the SAME orientation (eigenvectors) as ``ref_m6`` but the given
    eigenvalues — i.e. the same fault geometry with a different source type (γ,δ). Keeps the Kagan
    angle to the reference small (shared principal axes) while moving the lune position. Represents
    the full-MT NPE resolving non-DC components the deviatoric-constrained F-net inversion sets to 0."""
    import numpy as np

    M = _use_m6_to_matrix(ref_m6)
    w, V = np.linalg.eigh(M)
    V = V[:, np.argsort(w)[::-1]]  # eigenvectors for descending eigenvalues
    lam = np.array(sorted(lam_new, reverse=True))
    Mnew = V @ np.diag(lam) @ V.T
    m = np.array(_matrix_to_use_m6(Mnew), float)
    n = np.linalg.norm(m)
    return m / n if n else m


def _model_truth(ref_m6, mw, rng):
    """Model 'best' MT. Mostly near the reference (small DC offset); for a seeded ~18% minority,
    a genuinely non-DC source type (moderate CLVD or ISO) so the demo's source-type / non-DC
    colour modes are populated (illustrative — the real NPE replaces this)."""
    import numpy as np

    roll = rng.random()
    if roll < 0.12:  # CLVD-leaning
        a = rng.uniform(1.4, 2.0)
        lam = [a, -(a - 1.0), -1.0]
        if rng.random() < 0.5:
            lam = [-x for x in lam]
        return _retype(ref_m6, lam)
    if roll < 0.18:  # isotropic-leaning (±ISO) — DC + a net trace
        iso = rng.choice([-1.0, 1.0]) * rng.uniform(0.45, 0.85)
        return _retype(ref_m6, [1.0 + iso, iso, -1.0 + iso])
    best = ref_m6 + rng.normal(0, 0.04, size=6)
    n = np.linalg.norm(best)
    return best / n if n else best


def synthetic_posterior(
    ev: QuakeEvent,
    refs: List[dict],
    *,
    n_cloud: int = 250,
    n_mt6: int = 80,
    seed: int = 0,
) -> dict:
    """Build a schema-3 `post` dict for an event from its normalised references (primary first)."""
    import numpy as np
    from seismo_sbi.evaluation.moment_tensor import kagan, pyrocko_mt
    from seismo_sbi.plotting.lune import mts6_to_gamma_delta

    if not refs:
        raise ValueError("synthetic_posterior needs at least one (normalised) reference")

    r = np.random.default_rng(seed)
    primary = refs[0]
    ref_m6 = np.asarray(primary["mt6"], float)
    ref_m6 = ref_m6 / (np.linalg.norm(ref_m6) or 1.0)
    mw = primary.get("mw") or float(ev.mag) or 4.0

    # Model best: near the reference, or (seeded minority) a genuinely non-DC source type.
    best = _model_truth(ref_m6, mw, r)

    sigma = _mw_spread_frac(mw)  # ref_m6 is unit-norm, so sigma is a direct fraction
    cloud = best + r.normal(0, sigma, size=(n_cloud, 6))
    g, d = mts6_to_gamma_delta(cloud)
    g = np.clip(g, GAMMA_MIN, GAMMA_MAX)
    d = np.clip(d, DELTA_MIN, DELTA_MAX)

    mt6_ens = best + r.normal(0, sigma, size=(n_mt6, 6))
    mt6_ens = mt6_ens / np.linalg.norm(mt6_ens, axis=1, keepdims=True)

    # Headline non-DC metric: posterior probability the source is OUTSIDE the near-DC lune box
    # |γ|<τ & |δ|<τ (τ=10°), matching the santorini uncertainty_metrics.prob_outside_dc_box.
    # `source_type` is the probabilistic block {p_outside_dc_box_10, label}.
    source_type = source_type_block(gamma=g, delta=d, tau_deg=DC_BOX_TAU)
    p_outside = source_type["p_outside_dc_box_10"]

    best_mt = pyrocko_mt(best.tolist())
    s, dip, rake = (float(x) for x in best_mt.both_strike_dip_rake()[0])
    gamma_mean, delta_mean = float(np.mean(g)), float(np.mean(d))

    out_refs = []
    for ref in refs:
        kg = kagan(best.tolist(), ref["mt6"])
        out_refs.append(
            {
                "source": ref["source"],
                "gamma": round(float(ref["gamma"]), 2),
                "delta": round(float(ref["delta"]), 2),
                "strike": round(float(ref["strike"]), 1),
                "dip": round(float(ref["dip"]), 1),
                "rake": round(float(ref["rake"]), 1),
                "mt6": [round(float(x), 4) for x in ref["mt6"]],
                "kagan_deg": round(float(kg), 1) if kg == kg else 0.0,  # nan-guard
                "mw": round(float(ref["mw"]), 1) if ref.get("mw") is not None else None,
            }
        )

    return {
        "strike": round(s, 1),
        "dip": round(dip, 1),
        "rake": round(rake, 1),
        "source_type": source_type,
        "mw": round(float(mw), 1),
        "p_outside_dc_box": round(p_outside, 3),
        "gamma_mean": round(gamma_mean, 2),
        "delta_mean": round(delta_mean, 2),
        "posterior": {
            "gamma": [round(float(x), 2) for x in g],
            "delta": [round(float(x), 2) for x in d],
            "mt6": [[round(float(x), 4) for x in m] for m in mt6_ens],
        },
        "references": out_refs,
    }
