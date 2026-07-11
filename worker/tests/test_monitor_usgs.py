"""Offline tests for USGS near-live discovery (Phase 8) — provisional pending-reference
records, supersede-on-match, same-tick dedup, and the domain filter on USGS candidates.

All seams injected (FakeSource + monkeypatched download/build/infer + MemoryStore):
no network / creds / model / torch.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fnet_monitor import contract, live_event, monitor
from fnet_monitor.catalogue import QuakeEvent
from fnet_monitor.config import Config
from fnet_monitor.inference import mock_posterior
from fnet_monitor.sources import FakeSource, MultiSource, UsgsSource, candidate_id
from fnet_monitor.state import OUT_OF_DOMAIN, PUBLISHED, SUPERSEDED, State
from fnet_monitor.store import MemoryStore

BASE = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
ORIGIN = BASE - timedelta(hours=2)


class _Sol:
    """Minimal FnetMT stand-in (has m6_use => authoritative candidate)."""

    def __init__(self, when=ORIGIN, lat=41.58, lon=143.58, depth=51.55, mw=4.4):
        self.time = when
        self.lat, self.lon, self.depth_jma_km, self.mw = lat, lon, depth, mw
        self.region = "off Tokachi"
        self.np1 = (200.0, 30.0, 90.0)
        self.m6_use = [1, 1, 1, 0, 0, 0]


def _quake(when=ORIGIN, lat=41.58, lon=143.58, depth=51.55, mag=4.6, eid="us7000test"):
    """USGS QuakeEvent (no MT => provisional candidate)."""
    return QuakeEvent(id=eid, time=when, lon=lon, lat=lat, depth_km=depth, mag=mag,
                      magtype="mb", region="off Tokachi (USGS)")


def _download_ok(sol, work_dir, **kw):
    raw = Path(work_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "N.ABUF.SAC").write_bytes(b"\x00\x01")
    return raw


def _build_ok(sol, work_dir, backend):
    h5 = Path(work_dir) / "event.h5"
    h5.write_bytes(b"h5")
    return str(h5)


def _infer_passthrough(sol, event_h5, backend, *, n=2000, qa=True, qa_full=False,
                       catalogue_times=None):
    """Mirrors the real branch: an FnetMT-like sol gets a reference, a QuakeEvent gets []."""
    ev = live_event.sol_to_quakeevent(sol)
    post = mock_posterior(ev, 20)
    if getattr(sol, "m6_use", None) is None:
        post["references"] = []  # F-net reference pending
    return ev, post, [[1.0] * 6] * 20, None, ["N.ABUF"]


def _wire(monkeypatch, counters=None):
    def counting_download(sol, work_dir, **kw):
        if counters is not None:
            counters["download"] = counters.get("download", 0) + 1
        return _download_ok(sol, work_dir, **kw)

    monkeypatch.setattr(live_event, "download_event_waveforms", counting_download)
    monkeypatch.setattr(live_event, "build_event_h5", _build_ok)
    monkeypatch.setattr(live_event, "infer_live_event", _infer_passthrough)


def _tick(out_dir, cands, store, *, now=BASE):
    return monitor.tick(str(out_dir), FakeSource(cands), store, cfg=Config(), now=now,
                        backend_factory=lambda: object(), n_samples=20, delay_minutes=30)


# --------------------------------------------------------------------------- (1) USGS-only
def test_usgs_only_tick_publishes_pending_reference_record(tmp_path, monkeypatch):
    _wire(monkeypatch)
    u = _quake()
    store = MemoryStore()
    _tick(tmp_path, [u], store)

    state = State.load(str(tmp_path / "state.json"))
    st = state.events[u.id]
    assert st.status == PUBLISHED and st.provisional is True
    assert st.lat == u.lat and st.lon == u.lon and st.origin_time is not None

    recs = store.read_records()
    assert len(recs) == 1 and recs[0]["id"] == u.id
    contract.validate_event(recs[0])
    assert recs[0]["references"] == []  # F-net reference pending
    feat = next(f for f in store.index["features"] if f["properties"]["id"] == u.id)
    assert feat["properties"]["primary_source"] == "pending"
    assert feat["properties"]["n_references"] == 0


# --------------------------------------------------------------------------- (2) supersede
def test_fnet_arrival_supersedes_provisional_record(tmp_path, monkeypatch):
    _wire(monkeypatch)
    store = MemoryStore()
    u = _quake()
    _tick(tmp_path, [u], store, now=BASE)  # tick 1: provisional published
    assert store.read_records()[0]["references"] == []

    f = _Sol()  # tick 2: the matching F-net MT arrives (same origin/epicentre)
    _tick(tmp_path, [f], store, now=BASE + timedelta(days=3))

    state = State.load(str(tmp_path / "state.json"))
    fid = candidate_id(f)
    assert state.events[u.id].status == SUPERSEDED
    assert state.events[u.id].superseded_by == fid
    assert state.events[fid].status == PUBLISHED

    recs = store.read_records()
    assert len(recs) == 1 and recs[0]["id"] == fid  # exactly ONE record, no dup
    assert len(recs[0]["references"]) == 1          # reference attached
    assert recs[0]["references"][0]["source"] == "F-net (mock)"
    idx_ids = [ft["properties"]["id"] for ft in store.index["features"]]
    assert idx_ids == [fid]

    # a later re-poll of BOTH ids re-infers neither
    counters = {}
    _wire(monkeypatch, counters)
    _tick(tmp_path, [u, f], store, now=BASE + timedelta(days=4))
    assert counters.get("download", 0) == 0


# --------------------------------------------------------------------------- (3) same tick
def test_same_tick_dedup_fnet_wins(tmp_path, monkeypatch):
    counters = {}
    _wire(monkeypatch, counters)
    u, f = _quake(), _Sol()
    store = MemoryStore()
    _tick(tmp_path, [f, u], store)

    state = State.load(str(tmp_path / "state.json"))
    fid = candidate_id(f)
    assert state.events[u.id].status == SUPERSEDED
    assert state.events[u.id].superseded_by == fid
    assert state.events[fid].status == PUBLISHED
    recs = store.read_records()
    assert len(recs) == 1 and recs[0]["id"] == fid
    assert counters["download"] == 1  # only the F-net event ran the chain


# --------------------------------------------------------------------------- (4) domain
def test_domain_filter_applies_to_usgs_candidates(tmp_path, monkeypatch):
    counters = {}
    _wire(monkeypatch, counters)
    ryukyu = _quake(lat=27.9, lon=128.5, depth=20.0, eid="us7000ryu")
    store = MemoryStore()
    _tick(tmp_path, [ryukyu], store)
    st = State.load(str(tmp_path / "state.json")).events[ryukyu.id]
    assert st.status == OUT_OF_DOMAIN
    assert counters.get("download", 0) == 0
    assert store.read_records() == []


# --------------------------------------------------------------------------- (5) late USGS
def test_usgs_candidate_matching_already_published_fnet_is_never_inferred(tmp_path, monkeypatch):
    counters = {}
    _wire(monkeypatch, counters)
    store = MemoryStore()
    f = _Sol()
    _tick(tmp_path, [f], store, now=BASE)          # F-net processed first
    assert counters["download"] == 1

    u = _quake()                                    # the USGS origin shows up later
    _tick(tmp_path, [u], store, now=BASE + timedelta(hours=1))
    state = State.load(str(tmp_path / "state.json"))
    assert state.events[u.id].status == SUPERSEDED
    assert state.events[u.id].superseded_by == candidate_id(f)
    assert counters["download"] == 1               # no second inference
    assert len(store.read_records()) == 1


# --------------------------------------------------------------------------- wiring
def test_build_source_is_two_source_when_usgs_enabled():
    src = monitor.build_source(Config(), State(), BASE, None)
    assert isinstance(src, MultiSource)
    assert any(isinstance(s, UsgsSource) for s in src.sources)
    # the USGS leg uses the dedicated discovery threshold
    usgs = next(s for s in src.sources if isinstance(s, UsgsSource))
    assert usgs.cfg.min_magnitude == Config().usgs_min_magnitude == 4.0
    # and can be disabled
    from dataclasses import replace
    src_off = monitor.build_source(replace(Config(), usgs_enabled=False), State(), BASE, None)
    assert not isinstance(src_off, MultiSource)


def test_infer_live_event_quakeevent_branch_yields_pending_reference():
    """The real per-event chain, driven by a stub backend: a QuakeEvent conditions on the
    USGS origin and serialises with references=[] (no F-net MT exists yet)."""
    import numpy as np
    from fnet_monitor.inference import sdr_to_m6_use

    class _StubBackend:
        def present_stations(self, h5):
            return ["N.ABUF"]

        def infer(self, h5, source_vec, num_samples=100, **kw):
            assert source_vec == [41.58, 143.58, 51.55]  # USGS lat/lon/depth conditioning
            r = np.random.default_rng(0)
            base = np.asarray(sdr_to_m6_use(200.0, 40.0, 80.0), float) * 1e16
            return base + 1e14 * r.standard_normal((num_samples, 6)), ["N.ABUF"]

    u = _quake()
    ev, post, samples6, qa_res, present = live_event.infer_live_event(
        u, "unused.h5", _StubBackend(), n=50, qa=False)
    assert ev is u
    assert post["references"] == []
    rec = contract.build_event_record(ev, post, "t", mock=False, model="test")
    contract.validate_event(rec)
    assert contract.index_feature(rec)["properties"]["primary_source"] == "pending"
