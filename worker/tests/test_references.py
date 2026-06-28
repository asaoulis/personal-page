from datetime import datetime, timezone

import pytest

from fnet_monitor import references
from fnet_monitor.catalogue import QuakeEvent

NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


def _ev(eid, mag=5.0, depth=30.0, lon=142.0, lat=38.0):
    return QuakeEvent(
        id=eid, time=NOW, lon=lon, lat=lat, depth_km=depth, mag=mag, magtype="mb", region="R"
    )


DETAIL = {
    "properties": {
        "products": {
            "moment-tensor": [
                {
                    "source": "us",
                    "properties": {
                        "tensor-mrr": "1e16",
                        "tensor-mtt": "-2e16",
                        "tensor-mpp": "1e16",
                        "tensor-mrt": "3e15",
                        "tensor-mrp": "-1e15",
                        "tensor-mtp": "2e15",
                        "derived-magnitude": "5.1",
                    },
                },
                {
                    "source": "gcmt",
                    "properties": {
                        "tensor-mrr": "1.1e16",
                        "tensor-mtt": "-2.1e16",
                        "tensor-mpp": "1.0e16",
                        "tensor-mrt": "3e15",
                        "tensor-mrp": "-1e15",
                        "tensor-mtp": "2e15",
                        "derived-magnitude": "5.2",
                    },
                },
                {"source": "us", "properties": {"nodal-plane-1-strike": "200"}},  # NP-only -> skip
            ]
        }
    }
}


# ---- pure (no env) ----
def test_parse_usgs_mt_products():
    refs = references.parse_usgs_mt_products(DETAIL)
    assert {r["source"] for r in refs} == {"USGS", "GCMT"}
    usgs = next(r for r in refs if r["source"] == "USGS")
    assert usgs["mt6"][0] == 1e16 and usgs["mw"] == 5.1 and usgs["synthetic"] is False


def test_parse_empty_or_missing():
    assert references.parse_usgs_mt_products({}) == []
    assert references.parse_usgs_mt_products({"properties": {"products": {}}}) == []


def test_fetch_references_injected_fetcher():
    def fake(eid):
        if eid == "us1":
            return DETAIL
        if eid == "boom":
            raise RuntimeError("network down")
        return {"properties": {"products": {}}}

    cache = references.fetch_references([_ev("us1"), _ev("us2"), _ev("boom")], fake)
    assert len(cache["us1"]) == 2
    assert cache["us2"] == [] and cache["boom"] == []  # graceful degrade


def test_cache_roundtrip(tmp_path):
    p = str(tmp_path / "c.json")
    raw = {"us1": [{"source": "USGS", "mt6": [1, 0, -1, 0, 0, 0], "mw": 5.0, "synthetic": False}]}
    references.save_cache(p, raw, meta={"n_events": 1})
    assert references.load_cache(p)["us1"][0]["source"] == "USGS"
    assert references.load_cache(str(tmp_path / "missing.json")) == {}


def test_source_rank_orders_gcmt_first():
    assert references.source_rank("GCMT") < references.source_rank("USGS")
    assert references.source_rank("USGS") < references.source_rank("synthetic")


# ---- pyrocko / seismo_sbi gated ----
def test_synthesize_is_deterministic_and_regime_aware():
    pytest.importorskip("numpy")
    ev = _ev("us9", depth=30, lon=142, lat=38)
    raw = references.synthesize_reference(ev)
    assert raw["source"] == "synthetic" and len(raw["mt6"]) == 6 and raw["synthetic"] is True
    assert references.synthesize_reference(ev)["mt6"] == raw["mt6"]  # seeded


def test_normalise_reference():
    pytest.importorskip("pyrocko")
    pytest.importorskip("seismo_sbi")
    raw = references.synthesize_reference(_ev("usX", depth=20, lon=141, lat=37))
    norm = references.normalise_reference(raw)
    for k in ("source", "gamma", "delta", "strike", "dip", "rake", "mt6", "mw"):
        assert k in norm
    assert -30.0 <= norm["gamma"] <= 30.0 and -90.0 <= norm["delta"] <= 90.0
    assert len(norm["mt6"]) == 6
    assert abs(sum(x * x for x in norm["mt6"]) - 1.0) < 1e-6  # unit-norm
