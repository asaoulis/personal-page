"""Shared moment-tensor -> schema-3 `post` serializer.

`post_from_cloud` turns a moment-tensor posterior cloud `(N,6)` + a list of normalised
references into the SAME schema-3 `post` dict that `contract.build_event_record` consumes.
Both the dummy `synthetic.synthetic_posterior` (unit-norm cloud, mw supplied) and the real
`npe_backend`/`inference.real_posterior` (physical-N·m cloud, mw derived) call this, so the
mock and the real model produce byte-identical output shapes.

Needs the `seismo-sbi` env (pyrocko + seismo_sbi lune/kagan). Convention: mt6 is
`[Mrr,Mtt,Mpp,Mrt,Mrp,Mtp]` (GCMT up-south-east). Lune `(γ,δ)` is eigenvalue-based, so it is
scale-invariant — it works on both the physical and the unit-norm clouds.
"""

from __future__ import annotations

from typing import List, Optional

GAMMA_MIN, GAMMA_MAX = -30.0, 30.0
DELTA_MIN, DELTA_MAX = -90.0, 90.0
DC_BOX_TAU = 10.0  # near-DC lune box half-width for the non-DC exclusion metric (τ=10°)


def mw_from_m6(m6) -> float:
    """Mw from a physical [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp] N·m tensor. M0 = ‖M‖_F/√2."""
    import numpy as np

    m = np.asarray(m6, float)
    frob2 = m[0] ** 2 + m[1] ** 2 + m[2] ** 2 + 2 * (m[3] ** 2 + m[4] ** 2 + m[5] ** 2)
    m0 = float(np.sqrt(frob2 / 2.0))
    return (2.0 / 3.0) * (np.log10(max(m0, 1e-30)) - 9.1)


def post_from_cloud(
    cloud6,
    refs: List[dict],
    *,
    mw: Optional[float] = None,
    best6=None,
    n_mt6: int = 80,
    seed: int = 0,
) -> dict:
    """Assemble a schema-3 `post` dict from an MT posterior cloud + normalised references.

    Parameters
    ----------
    cloud6 : array ``(N, 6)`` — posterior MT samples (physical N·m for the real NPE; unit-norm
        for the dummy). `mts6_to_gamma_delta` is scale-invariant so either works.
    refs : list of NORMALISED references (each ``{source, gamma, delta, strike, dip, rake,
        mt6, mw}`` as produced by ``references.normalise_reference``), PRIMARY FIRST. `kagan_deg`
        to the model best is added here.
    mw : if given (dummy path — unit cloud), used verbatim; if None (real path — physical cloud),
        derived from the best MT's scalar moment.
    best6 : model point estimate ``(6,)``; defaults to the per-component median of the cloud.
    n_mt6 : size of the downsampled unit-norm mt6 ensemble that drives the client fuzzy beachball.
    """
    import numpy as np
    from seismo_sbi.evaluation.moment_tensor import kagan, pyrocko_mt
    from seismo_sbi.plotting.lune import mts6_to_gamma_delta
    from .source_type import source_type_block

    cloud6 = np.asarray(cloud6, float).reshape(-1, 6)
    if cloud6.shape[0] == 0:
        raise ValueError("post_from_cloud needs a non-empty (N,6) cloud")
    best6 = np.asarray(best6, float) if best6 is not None else np.median(cloud6, axis=0)

    g, d = mts6_to_gamma_delta(cloud6)
    g = np.clip(np.asarray(g, float), GAMMA_MIN, GAMMA_MAX)
    d = np.clip(np.asarray(d, float), DELTA_MIN, DELTA_MAX)

    r = np.random.default_rng(seed)
    k = min(n_mt6, cloud6.shape[0])
    idx = r.choice(cloud6.shape[0], size=k, replace=False)
    ens = cloud6[idx]
    norms = np.linalg.norm(ens, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mt6_ens = ens / norms  # unit-norm: the client beachball only needs orientation

    # probabilistic source-type block (lune-box exclusion metric at tau=10 deg); the legacy
    # top-level `p_outside_dc_box` float is kept in lockstep (the map colouring reads it).
    source_type = source_type_block(gamma=g, delta=d, tau_deg=DC_BOX_TAU)
    p_outside = source_type["p_outside_dc_box_10"]
    best_mt = pyrocko_mt(best6.tolist())
    s, dip, rake = (float(x) for x in best_mt.both_strike_dip_rake()[0])
    gamma_mean, delta_mean = float(np.mean(g)), float(np.mean(d))
    if mw is None:
        mw = mw_from_m6(best6)

    out_refs = []
    for ref in refs:
        kg = kagan(best6.tolist(), ref["mt6"])
        out_refs.append({
            "source": ref["source"],
            "gamma": round(float(ref["gamma"]), 2),
            "delta": round(float(ref["delta"]), 2),
            "strike": round(float(ref["strike"]), 1),
            "dip": round(float(ref["dip"]), 1),
            "rake": round(float(ref["rake"]), 1),
            "mt6": [round(float(x), 4) for x in ref["mt6"]],
            "kagan_deg": round(float(kg), 1) if kg == kg else 0.0,  # nan-guard
            "mw": round(float(ref["mw"]), 1) if ref.get("mw") is not None else None,
        })

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
