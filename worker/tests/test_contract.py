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


def test_build_and_validate():
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 50), "2026-06-28T00:00:00Z", True)
    contract.validate_event(rec)
    assert len(rec["posterior"]["gamma"]) == 50
    assert len(rec["posterior"]["delta"]) == 50
    feat = contract.index_feature(rec)
    contract.validate_index(
        {"type": "FeatureCollection", "generated": "x", "window_days": 30, "features": [feat]}
    )
    assert feat["properties"]["ensemble"] == "events/demo-x.json"
    assert feat["geometry"]["coordinates"] == [140.0, 36.0]


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


def test_write_event_roundtrip(tmp_path):
    rec = contract.build_event_record(_ev(), mock_posterior(_ev(), 10), "t", True)
    p = contract.write_event(str(tmp_path), rec)
    with open(p) as f:
        assert json.load(f)["id"] == "demo-x"
