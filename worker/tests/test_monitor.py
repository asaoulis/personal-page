"""Offline tests for the live monitor tick engine (no network / creds / model / torch).

Drives `monitor.tick()` with a FakeSource + monkeypatched download/build/infer seams + a
MemoryStore, so every branch of the per-event state machine is exercised deterministically.
"""
from datetime import datetime, timedelta, timezone

import pytest

from fnet_monitor import live_event, monitor
from fnet_monitor.config import Config
from fnet_monitor.inference import mock_posterior
from fnet_monitor.live_event import fnet_to_quakeevent
from fnet_monitor.sources import FakeSource, candidate_id
from fnet_monitor.state import DATA_WAITING, INFERRED, PENDING, PUBLISHED, State
from fnet_monitor.store import MemoryStore

BASE = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


class _Sol:
    """Minimal FnetMT stand-in — only the fields the live chain / serialisers read."""

    def __init__(self, when=None, mw=4.4):
        self.time = when or (BASE - timedelta(hours=2))
        self.lat, self.lon, self.depth_jma_km, self.mw = 41.58, 143.58, 51.55, mw
        self.region = "off Tokachi"
        self.np1 = (200.0, 30.0, 90.0)
        self.m6_use = [1, 1, 1, 0, 0, 0]


def _fake_factory():
    return object()  # seams ignore the backend, so a sentinel is enough


def _download_ok(sol, work_dir, **kw):
    from pathlib import Path
    raw = Path(work_dir) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "N.ABUF.SAC").write_bytes(b"\x00\x01")
    return raw


def _download_empty(sol, work_dir, **kw):
    return None  # nothing downloaded (archive lag)


def _build_ok(sol, work_dir, backend):
    from pathlib import Path
    h5 = Path(work_dir) / "event.h5"
    h5.write_bytes(b"h5")
    return str(h5)


def _infer_ok(sol, event_h5, backend, *, n=2000, qa=True, qa_full=False, catalogue_times=None):
    ev = fnet_to_quakeevent(sol)
    post = mock_posterior(ev, 20)
    return ev, post, [[1.0] * 6] * 20, None, ["N.ABUF"]


def _wire(monkeypatch, *, download=_download_ok, build=_build_ok, infer=_infer_ok):
    monkeypatch.setattr(live_event, "download_event_waveforms", download)
    monkeypatch.setattr(live_event, "build_event_h5", build)
    monkeypatch.setattr(live_event, "infer_live_event", infer)


def _tick(out_dir, sols, store, *, now, cfg=None, publish=False, delay_minutes=None, state=None):
    return monitor.tick(str(out_dir), FakeSource(sols), store, cfg=cfg or Config(), now=now,
                        state=state, backend_factory=_fake_factory, n_samples=20,
                        publish=publish, delay_minutes=delay_minutes)


# --------------------------------------------------------------------------- (a)
def test_new_event_registers_and_infers(tmp_path, monkeypatch):
    _wire(monkeypatch)
    sol = _Sol()
    store = MemoryStore()
    summary = _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30)
    eid = candidate_id(sol)
    state = State.load(str(tmp_path / "state.json"))
    # matured (2h old > 30 min delay) -> inferred -> published (delegated) this tick
    assert state.events[eid].status == PUBLISHED
    assert summary["counts"]["inferred"] == 1
    assert len(store.read_records()) == 1
    assert store.index is not None


# --------------------------------------------------------------------------- (b)
def test_too_young_event_is_held_then_matures(tmp_path, monkeypatch):
    _wire(monkeypatch)
    young = _Sol(when=BASE - timedelta(minutes=1))  # younger than delay
    store = MemoryStore()
    _tick(tmp_path, [young], store, now=BASE, delay_minutes=30)
    eid = candidate_id(young)
    st = State.load(str(tmp_path / "state.json")).events[eid]
    assert st.status == PENDING and st.attempts == 0
    assert st.next_retry_at is not None  # scheduled to mature at origin + delay
    assert len(store.read_records()) == 0  # not processed yet

    # advance past maturity -> processed
    later = BASE + timedelta(hours=1)
    _tick(tmp_path, [young], store, now=later, delay_minutes=30)
    st2 = State.load(str(tmp_path / "state.json")).events[eid]
    assert st2.status == PUBLISHED
    assert len(store.read_records()) == 1


# --------------------------------------------------------------------------- (c)
def test_data_waiting_then_retry_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky_download(sol, work_dir, **kw):
        calls["n"] += 1
        return _download_empty(sol, work_dir) if calls["n"] == 1 else _download_ok(sol, work_dir)

    _wire(monkeypatch, download=flaky_download)
    sol = _Sol()
    store = MemoryStore()
    _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30)
    eid = candidate_id(sol)
    st = State.load(str(tmp_path / "state.json")).events[eid]
    assert st.status == DATA_WAITING and st.attempts == 1
    assert st.next_retry_at is not None
    assert len(store.read_records()) == 0

    # jump past the backoff -> retry succeeds -> published
    from fnet_monitor.util import from_iso
    later = from_iso(st.next_retry_at) + timedelta(seconds=1)
    _tick(tmp_path, [sol], store, now=later, delay_minutes=30)
    st2 = State.load(str(tmp_path / "state.json")).events[eid]
    assert st2.status == PUBLISHED
    assert len(store.read_records()) == 1


# --------------------------------------------------------------------------- (d)
def test_infer_raises_schedules_retry_and_tick_survives(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model exploded")

    _wire(monkeypatch, infer=boom)
    sol = _Sol()
    store = MemoryStore()
    summary = _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30)  # must NOT raise
    eid = candidate_id(sol)
    st = State.load(str(tmp_path / "state.json")).events[eid]
    assert st.status == DATA_WAITING and st.attempts == 1
    assert "RuntimeError" in (st.last_error or "")
    assert summary["counts"]["data_waiting"] == 1
    assert len(store.read_records()) == 0


# --------------------------------------------------------------------------- (e)
def test_state_round_trips_to_disk_between_fresh_load_ticks(tmp_path, monkeypatch):
    _wire(monkeypatch)
    a = _Sol(when=BASE - timedelta(hours=3))
    b = _Sol(when=BASE - timedelta(hours=2))  # distinct origin -> distinct id
    store = MemoryStore()
    # tick 1 sees only `a`; state=None each tick -> fresh State.load from disk
    _tick(tmp_path, [a], store, now=BASE, delay_minutes=30)
    # tick 2 sees both; `a` already terminal (published) must NOT be reprocessed
    _tick(tmp_path, [a, b], store, now=BASE + timedelta(minutes=5), delay_minutes=30)
    state = State.load(str(tmp_path / "state.json"))
    assert state.events[candidate_id(a)].status == PUBLISHED
    assert state.events[candidate_id(b)].status == PUBLISHED
    assert len(store.read_records()) == 2


# --------------------------------------------------------------------------- (f)
def test_exit_when_drained_loop_semantics(monkeypatch):
    """The --loop --exit-when-drained loop exits once a tick reports no due_remaining."""
    monkeypatch.setattr(monitor.time, "sleep", lambda *_a, **_k: None)
    seq = [
        {"due_remaining": ["e1"], "status_hist": {}},  # still work -> keep looping
        {"due_remaining": [], "status_hist": {DATA_WAITING: 2}},  # drained -> exit
    ]
    calls = {"n": 0}

    def fake_run_once(*a, **k):
        s = seq[calls["n"]]
        calls["n"] += 1
        return s

    monkeypatch.setattr(monitor, "run_once", fake_run_once)
    rc = monitor.main(["--out", "/tmp/does-not-matter", "--loop", "--exit-when-drained"])
    assert rc == 0
    assert calls["n"] == 2  # looped once, exited on the drained tick


# --------------------------------------------------------------------------- (g)
class _SpyStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.publish_calls = 0

    def publish(self):
        self.publish_calls += 1


def test_publish_not_called_unless_flag(tmp_path, monkeypatch):
    _wire(monkeypatch)
    sol = _Sol()
    store = _SpyStore()
    _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30, publish=False)
    assert store.publish_calls == 0  # delegated to CI: never call publish()
    eid = candidate_id(sol)
    assert State.load(str(tmp_path / "state.json")).events[eid].status == PUBLISHED


def test_publish_called_with_flag(tmp_path, monkeypatch):
    _wire(monkeypatch)
    sol = _Sol()
    store = _SpyStore()
    _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30, publish=True)
    assert store.publish_calls == 1
    eid = candidate_id(sol)
    assert State.load(str(tmp_path / "state.json")).events[eid].status == PUBLISHED


# --------------------------------------------------------------------------- (h) out-of-domain
def test_deep_candidate_is_out_of_domain_never_downloads_or_indexes(tmp_path, monkeypatch):
    """A too-deep candidate is terminal `out_of_domain` at registration: no download, no retry,
    absent from the published index."""
    from fnet_monitor.state import OUT_OF_DOMAIN

    calls = {"download": 0}

    def spy_download(sol, work_dir, **kw):
        calls["download"] += 1
        return _download_ok(sol, work_dir, **kw)

    _wire(monkeypatch, download=spy_download)
    deep = _Sol()
    deep.depth_jma_km = 501.0  # deep-slab event, outside the shallow training domain
    store = MemoryStore()
    summary = _tick(tmp_path, [deep], store, now=BASE, delay_minutes=30)

    eid = candidate_id(deep)
    st = State.load(str(tmp_path / "state.json")).events[eid]
    assert st.status == OUT_OF_DOMAIN and st.terminal
    assert st.next_retry_at is None
    assert "outside model training domain" in (st.last_error or "")
    assert calls["download"] == 0                    # the download seam is never hit
    assert summary["counts"]["due"] == 0             # terminal -> never due
    assert len(store.read_records()) == 0
    idx_ids = [f["properties"]["id"] for f in (store.index or {}).get("features", [])]
    assert eid not in idx_ids                        # never appears in the published index


def test_deep_candidate_env_override(tmp_path, monkeypatch):
    """FNET_MAX_DEPTH_KM overrides the Config default at the consumption site."""
    from fnet_monitor.state import OUT_OF_DOMAIN

    _wire(monkeypatch)
    monkeypatch.setenv("FNET_MAX_DEPTH_KM", "40")  # below the _Sol depth (51.55 km)
    sol = _Sol()
    store = MemoryStore()
    _tick(tmp_path, [sol], store, now=BASE, delay_minutes=30)
    eid = candidate_id(sol)
    assert State.load(str(tmp_path / "state.json")).events[eid].status == OUT_OF_DOMAIN


def test_shallow_deep_mixed_tick(tmp_path, monkeypatch):
    """A deep event is skipped while a shallow one in the same tick still publishes."""
    from fnet_monitor.state import OUT_OF_DOMAIN

    _wire(monkeypatch)
    shallow = _Sol(when=BASE - timedelta(hours=3))
    deep = _Sol(when=BASE - timedelta(hours=2))
    deep.depth_jma_km = 400.0
    store = MemoryStore()
    _tick(tmp_path, [shallow, deep], store, now=BASE, delay_minutes=30)
    state = State.load(str(tmp_path / "state.json"))
    assert state.events[candidate_id(shallow)].status == PUBLISHED
    assert state.events[candidate_id(deep)].status == OUT_OF_DOMAIN
    assert len(store.read_records()) == 1
