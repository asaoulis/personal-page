import json
from datetime import datetime, timedelta, timezone

import pytest

from fnet_monitor import contract
from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.inference import mock_posterior

NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def _ev():
    return QuakeEvent(
        id="demo-x",
        time=NOW - timedelta(days=1),
        lon=140.0,
        lat=36.0,
        depth_km=30.0,
        mag=5.0,
        magtype="Mw",
        region="Region",
        strike=200,
        dip=40,
        rake=80,
        gamma=2.0,
        delta=-1.0,
        source_type="double-couple",
    )


def _index(feat):
    return {
        "type": "FeatureCollection",
        "generated": "2026-06-28T00:00:00Z",
        "window_days": 30,
        "window_start": "2026-05-29T00:00:00Z",
        "window_end": "2026-06-28T00:00:00Z",
        "features": [feat],
    }


def test_build_and_validate():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 50), "2026-06-28T00:00:00Z", True)
    contract.validate_event(rec)
    assert rec["schema"] == 3
    assert len(rec["posterior"]["gamma"]) == 50
    assert len(rec["posterior"]["delta"]) == 50
    # schema 3: mt6 ensemble + non-empty references list (primary first)
    assert len(rec["posterior"]["mt6"]) > 0
    assert all(len(m) == 6 for m in rec["posterior"]["mt6"])
    assert isinstance(rec["references"], list) and len(rec["references"]) >= 1
    assert len(rec["references"][0]["mt6"]) == 6

    feat = contract.index_feature(rec)
    contract.validate_index(_index(feat))
    assert feat["properties"]["ensemble"] == "events/demo-x.json"
    assert feat["geometry"]["coordinates"] == [140.0, 36.0]
    assert feat["properties"]["n_references"] == len(rec["references"])
    assert feat["properties"]["primary_source"] == rec["references"][0]["source"]


def test_build_static_index_spans_event_times():
    from fnet_monitor.config import Config

    e1, e2 = _ev(), _ev()
    e2.id = "demo-y"
    e2.time = NOW - timedelta(days=10)
    recs = [
        contract.build_event_record(e1, mock_posterior(e1, 10), "g", True),
        contract.build_event_record(e2, mock_posterior(e2, 10), "g", True),
    ]
    idx = contract.build_static_index(recs, "2026-06-28T00:00:00Z", Config(), mock=True)
    contract.validate_index(idx)
    assert idx["schema"] == 3
    assert len(idx["features"]) == 2
    # newest first; window bounds = actual event time span
    assert idx["features"][0]["properties"]["id"] == "demo-x"
    assert idx["window_start"] == contract.to_iso(e2.time)
    assert idx["window_end"] == contract.to_iso(e1.time)


def test_validate_event_catches_out_of_range():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    rec["posterior"]["gamma"][0] = 99.0  # out of [-30, 30]
    with pytest.raises(AssertionError):
        contract.validate_event(rec)


def test_validate_event_catches_length_mismatch():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    rec["posterior"]["delta"] = rec["posterior"]["delta"][:-1]
    with pytest.raises(AssertionError):
        contract.validate_event(rec)


def test_validate_event_references_list_required_but_may_be_empty():
    # missing / non-list references is a violation …
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    rec["references"] = None
    with pytest.raises(AssertionError):
        contract.validate_event(rec)
    # … but an EMPTY list is valid: a provisional USGS-discovered record publishes with the
    # F-net reference pending (attached later by supersede-on-match).
    rec2 = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    rec2["references"] = []
    contract.validate_event(rec2)
    feat = contract.index_feature(rec2)
    assert feat["properties"]["primary_source"] == "pending"
    assert feat["properties"]["n_references"] == 0


def test_validate_event_requires_mt6():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    del rec["posterior"]["mt6"]
    with pytest.raises(AssertionError):
        contract.validate_event(rec)


def test_validate_index_requires_window_bounds():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    idx = _index(contract.index_feature(rec))
    del idx["window_start"]
    with pytest.raises(AssertionError):
        contract.validate_index(idx)


def test_write_event_roundtrip(tmp_path):
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    p = contract.write_event(str(tmp_path), rec)
    with open(p) as f:
        assert json.load(f)["id"] == "demo-x"
