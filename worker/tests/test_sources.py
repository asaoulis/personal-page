from datetime import datetime, timezone

from fnet_monitor import contract
from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.config import Config
from fnet_monitor.fnet_mt import FnetMT
from fnet_monitor.inference import mock_posterior
from fnet_monitor.sources import (
    FakeSource,
    FnetMtSource,
    candidate_id,
    candidate_time,
    event_stem,
)
from fnet_monitor.store import MemoryStore

NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def _fnet(t, lat, lon, mw, region="R"):
    return FnetMT(
        time=t, lat=lat, lon=lon, depth_jma_km=12.0, mj=mw - 0.2, region=region,
        np1=(187.0, 25.0, 64.0), np2=(35.0, 68.0, 101.0), mo_nm=6e14, mt_depth_km=14.0,
        mw=mw, var_red=73.0, m6_use=[1e14, 2e14, 3e14, 4e14, 5e14, 6e14], n_stations=5, url="u",
    )


def _quake(fid, t, lat=36.0, lon=140.0, mag=4.5):
    return QuakeEvent(id=fid, time=t, lon=lon, lat=lat, depth_km=30.0, mag=mag,
                      magtype="mww", region="Japan")


# --------------------------------------------------------------------------- candidate id/time
def test_candidate_id_quakeevent_uses_its_id():
    q = _quake("usgs123", NOW)
    assert candidate_id(q) == "usgs123"
    assert candidate_time(q) == NOW


def test_candidate_id_fnet_uses_stem_convention():
    t = datetime(2026, 1, 1, 12, 46, 20, tzinfo=timezone.utc)
    s = _fnet(t, 39.5, 143.4, 3.8)
    assert event_stem(t) == "20260101T124620"
    # matches live_event.fnet_to_quakeevent's `fnet_<stem>`
    assert candidate_id(s) == "fnet_20260101T124620"
    assert candidate_time(s) == t


# --------------------------------------------------------------------------- FnetMtSource
def test_fnet_source_filters_bbox_and_min_mw():
    inside = _fnet(NOW, 36.0, 140.0, 4.5)
    too_small = _fnet(NOW, 36.0, 140.0, 3.0)
    outside = _fnet(NOW, 5.0, 100.0, 5.0)
    captured = {}

    def fake_fetcher(start, end, min_mw):
        captured["start"], captured["end"], captured["min_mw"] = start, end, min_mw
        return [inside, too_small, outside]

    src = FnetMtSource(Config(), fetcher=fake_fetcher)
    got = src.fetch(NOW)
    assert [candidate_id(g) for g in got] == [candidate_id(inside)]
    # seam received a lookback window ending at now, and the configured min_mw
    assert captured["end"] == NOW
    assert captured["min_mw"] == Config().min_magnitude
    assert captured["start"] < NOW


def test_fnet_source_custom_min_mw_and_lookback():
    ev = _fnet(NOW, 36.0, 140.0, 4.0)
    captured = {}

    def fake_fetcher(start, end, min_mw):
        captured["min_mw"] = min_mw
        captured["days"] = (end - start).days
        return [ev]

    src = FnetMtSource(Config(), fetcher=fake_fetcher, min_mw=4.5, lookback_days=7)
    got = src.fetch(NOW)
    assert got == []  # 4.0 < 4.5 client-side filter
    assert captured["min_mw"] == 4.5
    assert captured["days"] == 7


def test_fnet_source_handles_empty_fetch():
    src = FnetMtSource(Config(), fetcher=lambda s, e, m: None)
    assert src.fetch(NOW) == []


# --------------------------------------------------------------------------- FakeSource
def test_fake_source_returns_copy():
    evs = [_quake("a", NOW), _quake("b", NOW)]
    src = FakeSource(evs)
    got = src.fetch(NOW)
    assert [candidate_id(g) for g in got] == ["a", "b"]
    got.append("mutated")
    assert len(src.fetch(NOW)) == 2  # internal list untouched


# --------------------------------------------------------------------------- round-trip
def test_fakesource_to_memorystore_roundtrip_is_contract_valid():
    evs = [_quake("ev1", NOW), _quake("ev2", NOW)]
    src = FakeSource(evs)
    store = MemoryStore()
    for cand in src.fetch(NOW):
        rec = contract.build_event_record(cand, mock_posterior(cand, 40), "2026-06-28T00:00:00Z", True)
        store.upsert(rec)  # MemoryStore validates on upsert
    index = store.write_index(now=NOW, mock=True)
    contract.validate_index(index)
    assert len(index["features"]) == 2
    assert {candidate_id(e) for e in evs} == {f["properties"]["id"] for f in index["features"]}
