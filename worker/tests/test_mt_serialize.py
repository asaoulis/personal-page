"""Offline tests for the shared MT -> schema-3 serializer (`mt_serialize.post_from_cloud`).

Gated on the seismo-sbi env (pyrocko + lune/kagan), like test_synthetic / test_references.
"""
import numpy as np
import pytest

pytest.importorskip("seismo_sbi")

from fnet_monitor import contract  # noqa: E402
from fnet_monitor.inference import sdr_to_m6_use  # noqa: E402
from fnet_monitor.mt_serialize import post_from_cloud, mw_from_m6  # noqa: E402


def _physical_dc_cloud(strike, dip, rake, mw, n=300, seed=0):
    """A tight physical-N·m cloud around a DC mechanism at a target Mw."""
    m0 = 10 ** (1.5 * mw + 9.1)
    base = np.asarray(sdr_to_m6_use(strike, dip, rake, scalar_moment=1.0), float)
    base = base / (np.linalg.norm(base) or 1.0) * (m0 * np.sqrt(2))  # ‖M‖_F = √2·M0
    r = np.random.default_rng(seed)
    return base + r.normal(0, 0.03 * np.linalg.norm(base), size=(n, 6))


def _norm_ref(strike, dip, rake, mw, source="F-net"):
    m6 = sdr_to_m6_use(strike, dip, rake)
    m6 = (np.asarray(m6) / (np.linalg.norm(m6) or 1.0)).tolist()
    from seismo_sbi.plotting.lune import mts6_to_gamma_delta
    g, d = mts6_to_gamma_delta(np.array([m6]))
    return {"source": source, "gamma": float(g[0]), "delta": float(d[0]),
            "strike": float(strike), "dip": float(dip), "rake": float(rake),
            "mt6": m6, "mw": mw}


def test_mw_from_m6_roundtrip():
    for mw in (3.5, 4.7, 5.8):
        m0 = 10 ** (1.5 * mw + 9.1)
        m6 = [m0 * np.sqrt(2), 0, 0, 0, 0, 0]  # ‖M‖_F = √2·M0
        assert abs(mw_from_m6(m6) - mw) < 0.05


def test_post_from_cloud_schema3_valid():
    cloud = _physical_dc_cloud(30, 70, 10, mw=5.2)
    refs = [_norm_ref(28, 68, 12, 5.3)]
    post = post_from_cloud(cloud, refs)
    # feed through the real schema gate
    from fnet_monitor.util import to_iso  # noqa
    rec = {
        "id": "x", "time": "2026-01-01T00:00:00Z", "mag": 5.2, "magType": "mw",
        "depth_km": 10.0, "lon": 140.0, "lat": 38.0, "region": "Japan",
        "source_type": post["source_type"], "strike": post["strike"], "dip": post["dip"],
        "rake": post["rake"], "mw": post["mw"], "p_outside_dc_box": post["p_outside_dc_box"],
        "posterior": post["posterior"], "summary": {"gamma": post["gamma_mean"],
                                                    "delta": post["delta_mean"]},
        "references": post["references"], "provenance": {"generated": "t", "mock": False,
                                                         "model": "npe"},
    }
    contract.validate_event(rec)
    # physical cloud -> derived Mw ~ target
    assert 5.0 <= post["mw"] <= 5.4
    # DC mechanism -> low non-DC exclusion prob and near-DC lune
    assert post["p_outside_dc_box"] < 0.3
    assert abs(post["gamma_mean"]) < 8 and abs(post["delta_mean"]) < 10
    # reference carries a finite Kagan angle to the (near-identical) model best
    assert post["references"][0]["kagan_deg"] < 20
    assert len(post["posterior"]["mt6"]) == min(80, len(cloud))


def test_post_mw_override_for_unit_cloud():
    """Unit-norm cloud (dummy path) must take the supplied mw, not derive ~ -6 from unit M0."""
    m6 = sdr_to_m6_use(10, 80, 0)
    m6 = (np.asarray(m6) / np.linalg.norm(m6)).tolist()
    cloud = np.asarray(m6) + np.random.default_rng(1).normal(0, 0.05, size=(120, 6))
    post = post_from_cloud(cloud, [_norm_ref(10, 80, 0, 4.5)], mw=4.5)
    assert post["mw"] == 4.5
