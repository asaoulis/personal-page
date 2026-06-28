from datetime import datetime, timezone

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pyrocko")
pytest.importorskip("seismo_sbi")

import numpy as np  # noqa: E402

from fnet_monitor import references, synthetic  # noqa: E402
from fnet_monitor.catalogue import QuakeEvent  # noqa: E402
from fnet_monitor.inference import sdr_to_m6_use  # noqa: E402

NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _ev(eid, mag=5.0):
    return QuakeEvent(id=eid, time=NOW, lon=142.0, lat=38.0, depth_km=30.0, mag=mag, magtype="mb", region="R")


def _ref(mw=None, sdr=(200.0, 40.0, 80.0)):
    m6 = np.array(sdr_to_m6_use(*sdr))
    m6 = m6 / np.linalg.norm(m6)
    return {
        "source": "USGS",
        "gamma": 0.0,
        "delta": 0.0,
        "strike": sdr[0],
        "dip": sdr[1],
        "rake": sdr[2],
        "mt6": m6.tolist(),
        "mw": mw,
    }


def test_shapes_and_ranges():
    post = synthetic.synthetic_posterior(_ev("a"), [_ref()], n_cloud=120, n_mt6=40, seed=1)
    assert len(post["posterior"]["gamma"]) == 120 == len(post["posterior"]["delta"])
    assert len(post["posterior"]["mt6"]) == 40 and all(len(m) == 6 for m in post["posterior"]["mt6"])
    assert all(-30.0 <= g <= 30.0 for g in post["posterior"]["gamma"])
    assert all(-90.0 <= d <= 90.0 for d in post["posterior"]["delta"])
    assert post["references"][0]["kagan_deg"] >= 0.0
    assert post["mw"] is not None
    # mt6 ensemble members are unit-norm
    assert abs(sum(x * x for x in post["posterior"]["mt6"][0]) - 1.0) < 1e-3


def test_mw_scaled_spread():
    """Bigger Mw ⇒ tighter posterior (same ref + seed, mw taken from the event)."""
    big = synthetic.synthetic_posterior(_ev("z", mag=5.5), [_ref(mw=None)], seed=5)
    small = synthetic.synthetic_posterior(_ev("z", mag=3.9), [_ref(mw=None)], seed=5)
    spread_big = np.std(big["posterior"]["gamma"]) + np.std(big["posterior"]["delta"])
    spread_small = np.std(small["posterior"]["gamma"]) + np.std(small["posterior"]["delta"])
    assert spread_big < spread_small


def test_kagan_present_for_each_reference():
    refs = [_ref(sdr=(200, 40, 80)), _ref(sdr=(30, 80, 0))]
    refs[1]["source"] = "GCMT"
    post = synthetic.synthetic_posterior(_ev("m"), refs, seed=3)
    assert len(post["references"]) == 2
    assert all("kagan_deg" in r for r in post["references"])


def test_requires_a_reference():
    with pytest.raises(ValueError):
        synthetic.synthetic_posterior(_ev("e"), [], seed=0)
