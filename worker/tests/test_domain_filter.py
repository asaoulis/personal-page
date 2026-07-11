"""Offline tests for the training-domain filter (Phase 7) — config helper, monitor
registration, and the store reclassification round-trip.  No network/DB/GPU/creds.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fnet_monitor import contract, live_event, monitor, reclassify
from fnet_monitor.config import Config, in_training_domain
from fnet_monitor.inference import mock_posterior
from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.sources import FakeSource, candidate_id
from fnet_monitor.state import OUT_OF_DOMAIN, PUBLISHED, State
from fnet_monitor.store import FileStore, MemoryStore

BASE = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- helper
def test_mainland_shallow_event_is_in_domain():
    ok, reason = in_training_domain(36.0, 140.0, 30.0)
    assert ok and reason == ""


def test_izu_bonin_strip_is_excluded():
    # lat < 33 AND lon > 138: the island-arc strip the training prior dropped
    ok, reason = in_training_domain(31.5, 140.2, 10.0)
    assert not ok and "Izu" in reason and "training domain" in reason


def test_ryukyu_is_excluded():
    # lat < 30.5: south of the main-arc box entirely
    ok, reason = in_training_domain(27.9, 128.5, 20.0)
    assert not ok and "outside the training box" in reason


def test_east_of_kuril_lon_is_excluded():
    ok, reason = in_training_domain(43.9, 147.4, 30.0)  # lon > 146
    assert not ok and "outside the training box" in reason


def test_deep_event_is_excluded():
    ok, reason = in_training_domain(36.0, 140.0, 120.0)
    assert not ok and "depth 120km" in reason


def test_depth_cut_is_overridable():
    ok, _ = in_training_domain(36.0, 140.0, 120.0, max_depth_km=150.0)
    assert ok


def test_none_coordinates_fall_back_to_depth_only():
    assert in_training_domain(None, None, 30.0)[0]
    assert not in_training_domain(None, None, 300.0)[0]


def test_boundary_points_are_inclusive():
    assert in_training_domain(30.5, 128.0, 80.0)[0]
    assert in_training_domain(46.0, 146.0, 0.0)[0]
    # exactly on the Izu–Bonin edges is NOT excluded (strict <, > in the prior cut)
    assert in_training_domain(33.0, 140.0, 10.0)[0]
    assert in_training_domain(32.0, 138.0, 10.0)[0]


# --------------------------------------------------------------------------- monitor tick
class _Sol:
    """Minimal FnetMT stand-in (mirrors test_monitor)."""

    def __init__(self, when=None, lat=41.58, lon=143.58, depth=51.55, mw=4.4):
        self.time = when or (BASE - timedelta(hours=2))
        self.lat, self.lon, self.depth_jma_km, self.mw = lat, lon, depth, mw
        self.region = "off Tokachi"
        self.np1 = (200.0, 30.0, 90.0)
        self.m6_use = [1, 1, 1, 0, 0, 0]


def _wire_ok(monkeypatch):
    from fnet_monitor.live_event import fnet_to_quakeevent

    def _download_ok(sol, work_dir, **kw):
        raw = Path(work_dir) / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "N.ABUF.SAC").write_bytes(b"\x00\x01")
        return raw

    def _build_ok(sol, work_dir, backend):
        h5 = Path(work_dir) / "event.h5"
        h5.write_bytes(b"h5")
        return str(h5)

    def _infer_ok(sol, event_h5, backend, *, n=2000, qa=True, qa_full=False,
                  catalogue_times=None):
        ev = fnet_to_quakeevent(sol)
        return ev, mock_posterior(ev, 20), [[1.0] * 6] * 20, None, ["N.ABUF"]

    monkeypatch.setattr(live_event, "download_event_waveforms", _download_ok)
    monkeypatch.setattr(live_event, "build_event_h5", _build_ok)
    monkeypatch.setattr(live_event, "infer_live_event", _infer_ok)


def _tick(out_dir, sols, store, *, now=BASE):
    return monitor.tick(str(out_dir), FakeSource(sols), store, cfg=Config(), now=now,
                        backend_factory=lambda: object(), n_samples=20, delay_minutes=30)


def test_izu_bonin_candidate_is_out_of_domain_at_registration(tmp_path, monkeypatch):
    calls = {"download": 0}

    def spy_download(sol, work_dir, **kw):
        calls["download"] += 1

    _wire_ok(monkeypatch)
    monkeypatch.setattr(live_event, "download_event_waveforms", spy_download)
    izu = _Sol(lat=31.5, lon=140.2, depth=10.0)
    store = MemoryStore()
    _tick(tmp_path, [izu], store)
    st = State.load(str(tmp_path / "state.json")).events[candidate_id(izu)]
    assert st.status == OUT_OF_DOMAIN and st.terminal
    assert "Izu" in (st.last_error or "")
    assert calls["download"] == 0
    assert len(store.read_records()) == 0


def test_mixed_tick_keeps_mainland_drops_ryukyu(tmp_path, monkeypatch):
    _wire_ok(monkeypatch)
    mainland = _Sol(when=BASE - timedelta(hours=3))
    ryukyu = _Sol(when=BASE - timedelta(hours=2), lat=27.9, lon=128.5, depth=20.0)
    store = MemoryStore()
    _tick(tmp_path, [mainland, ryukyu], store)
    state = State.load(str(tmp_path / "state.json"))
    assert state.events[candidate_id(mainland)].status == PUBLISHED
    assert state.events[candidate_id(ryukyu)].status == OUT_OF_DOMAIN
    assert len(store.read_records()) == 1


# --------------------------------------------------------------------------- reclassify
def _record(eid, *, lat, lon, depth, when):
    ev = QuakeEvent(id=eid, time=when, lon=lon, lat=lat, depth_km=depth, mag=4.5,
                    magtype="Mw", region="test", strike=200, dip=40, rake=80)
    return contract.build_event_record(ev, mock_posterior(ev, 30), "t", mock=True)


def _seed_store(out_dir):
    """A store of 2 in-domain + 2 OOD published records, with matching state.json."""
    store = FileStore(str(out_dir))
    recs = [
        _record("in_a", lat=36.0, lon=140.0, depth=30.0, when=BASE - timedelta(days=3)),
        _record("in_b", lat=41.6, lon=143.6, depth=51.0, when=BASE - timedelta(days=2)),
        _record("ood_deep", lat=36.0, lon=140.0, depth=150.0, when=BASE - timedelta(days=4)),
        _record("ood_izu", lat=31.5, lon=140.2, depth=10.0, when=BASE - timedelta(days=1)),
    ]
    for r in recs:
        store.upsert(r)
    store.write_index(now=BASE)
    state = State()
    for r in recs:
        state.register(r["id"], BASE)
        state.advance(r["id"], PUBLISHED, BASE)
    state.save(str(Path(out_dir) / "state.json"))
    return store


def test_reclassify_round_trip(tmp_path):
    _seed_store(tmp_path)
    summary = reclassify.reclassify_domain(str(tmp_path), now=BASE)

    assert summary["n_excluded"] == 2 and summary["n_kept"] == 2
    assert {e["id"] for e in summary["excluded"]} == {"ood_deep", "ood_izu"}
    assert summary["kagan_median_deg"] is not None

    # OOD record files moved to _excluded/, survivors untouched
    assert not (tmp_path / "events" / "ood_deep.json").exists()
    assert (tmp_path / "_excluded" / "ood_deep.json").exists()
    assert (tmp_path / "events" / "in_a.json").exists()

    # index rebuilt over survivors only
    idx = json.loads((tmp_path / "events.json").read_text())
    ids = {f["properties"]["id"] for f in idx["features"]}
    assert ids == {"in_a", "in_b"}

    # state marked terminal out_of_domain (never re-inferred)
    state = State.load(str(tmp_path / "state.json"))
    assert state.events["ood_deep"].status == OUT_OF_DOMAIN
    assert state.events["ood_izu"].status == OUT_OF_DOMAIN
    assert state.events["in_a"].status == PUBLISHED

    # idempotent: a second run excludes nothing further
    summary2 = reclassify.reclassify_domain(str(tmp_path), now=BASE)
    assert summary2["n_excluded"] == 0 and summary2["n_kept"] == 2


def test_reclassify_dry_run_changes_nothing(tmp_path):
    _seed_store(tmp_path)
    summary = reclassify.reclassify_domain(str(tmp_path), dry_run=True, now=BASE)
    assert summary["n_excluded"] == 2
    assert (tmp_path / "events" / "ood_deep.json").exists()
    assert not (tmp_path / "_excluded").exists()
    state = State.load(str(tmp_path / "state.json"))
    assert state.events["ood_deep"].status == PUBLISHED


class TestOffshoreExclusions:
    """Pacific far-offshore exclusions (2026-07-11): beyond-trench events drift to
    spurious strong-ISO posteriors — filtered as out_of_domain."""

    def test_beyond_trench_east_dropped(self):
        # OFF_NEMURO / FAR_E_OFF_NORTH_HONSHU pathology band (lon > 144)
        ok, reason = in_training_domain(42.90, 145.47, 74.0)
        assert not ok and "offshore" in reason
        ok, reason = in_training_domain(39.00, 144.63, 15.0)
        assert not ok and "offshore" in reason

    def test_far_offshore_south_dropped(self):
        # FAR_E_OFF_CENTRAL_HONSHU / FAR_E_OFF_IZU (lat < 36, lon > 141.5)
        ok, reason = in_training_domain(34.78, 142.87, 28.0)
        assert not ok and "offshore" in reason
        ok, reason = in_training_domain(33.15, 142.48, 57.0)
        assert not ok  # (also inside Izu-Bonin strip; either reason is fine)

    def test_sanriku_band_and_coastal_kept(self):
        # mixed Sanriku band stays (contains excellent recoveries)
        assert in_training_domain(39.88, 143.17, 18.0)[0]
        assert in_training_domain(39.70, 143.42, 14.0)[0]
        # NE_OFF_IWATE near-coast band stays (Mw6.9 gold standard lives here)
        assert in_training_domain(40.21, 142.30, 44.0)[0]
        # Kujukuri coast (lat<36 but west of 141.5) stays
        assert in_training_domain(35.38, 140.32, 26.9)[0]
        # onshore Hidaka (Hokkaido, lon<144) stays
        assert in_training_domain(42.34, 143.01, 56.0)[0]
