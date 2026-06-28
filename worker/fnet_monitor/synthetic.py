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
from .inference import classify_source_type

GAMMA_MIN, GAMMA_MAX = -30.0, 30.0
DELTA_MIN, DELTA_MAX = -90.0, 90.0


def _mw_spread_frac(mw: float) -> float:
    """Posterior width as a fraction of ‖M‖, larger for smaller magnitudes."""
    import numpy as np

    return float(np.clip(0.06 + 0.06 * (5.5 - min(mw, 5.5)), 0.06, 0.32))


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

    # Model best = primary reference nudged by a small seeded offset (realistic inversion gap).
    best = ref_m6 + r.normal(0, 0.04, size=6)
    best = best / (np.linalg.norm(best) or 1.0)

    sigma = _mw_spread_frac(mw)  # ref_m6 is unit-norm, so sigma is a direct fraction
    cloud = best + r.normal(0, sigma, size=(n_cloud, 6))
    g, d = mts6_to_gamma_delta(cloud)
    g = np.clip(g, GAMMA_MIN, GAMMA_MAX)
    d = np.clip(d, DELTA_MIN, DELTA_MAX)

    mt6_ens = best + r.normal(0, sigma, size=(n_mt6, 6))
    mt6_ens = mt6_ens / np.linalg.norm(mt6_ens, axis=1, keepdims=True)

    best_mt = pyrocko_mt(best.tolist())
    s, dip, rake = (float(x) for x in best_mt.both_strike_dip_rake()[0])
    gamma_mean, delta_mean = float(np.mean(g)), float(np.mean(d))
    source_type = classify_source_type(gamma_mean, delta_mean)

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
        "gamma_mean": round(gamma_mean, 2),
        "delta_mean": round(delta_mean, 2),
        "posterior": {
            "gamma": [round(float(x), 2) for x in g],
            "delta": [round(float(x), 2) for x in d],
            "mt6": [[round(float(x), 4) for x in m] for m in mt6_ens],
        },
        "references": out_refs,
    }
