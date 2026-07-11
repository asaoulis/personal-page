"""Phase 5.1 offline integration test: ONE event end-to-end through the REAL monitor.tick().

No network / creds / GPU / torch — the three heavy seams (download / build / infer) are the
ONLY fakes; everything else (state machine, record assembly, FileStore contract writes, index
build + validation) runs for real.  Asserts the written store satisfies the frontend contract
and state.json ends terminal.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fnet_monitor import contract, live_event, monitor
from fnet_monitor.config import Config
from fnet_monitor.inference import mock_posterior
from fnet_monitor.live_event import fnet_to_quakeevent
from fnet_monitor.sources import FakeSource, candidate_id
from fnet_monitor.state import PUBLISHED, State
from fnet_monitor.store import FileStore

NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


class _Sol:
    def __init__(self):
        self.time = NOW - timedelta(hours=3)  # matured past the delay window
        self.lat, self.lon, self.depth_jma_km, self.mw = 36.2, 141.1, 42.0, 5.1
        self.region = "off Ibaraki"
        self.np1 = (150.0, 45.0, 80.0)
        self.m6_use = [1.0, -0.5, -0.5, 0.2, 0.1, 0.0]


def _fake_download(sol, work_dir, **kw):
    """Write a tiny mseed-layout dir (station/day file), the shape the real fetch produces."""
    raw = Path(work_dir) / "raw" / "N.ABUF" / "2026.179"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "N.ABUF.U.SAC").write_bytes(b"\x00\x01\x02\x03")
    return Path(work_dir) / "raw"


def _fake_build(sol, work_dir, backend):
    h5 = Path(work_dir) / "catalogue" / "events" / "evt.h5"
    h5.parent.mkdir(parents=True, exist_ok=True)
    h5.write_bytes(b"\x89HDF\r\n\x1a\n")  # fixture h5 path; contents never opened (infer is faked)
    return str(h5)


def _fake_infer(sol, event_h5, backend, *, n=2000, qa=True, qa_full=False, catalogue_times=None):
    ev = fnet_to_quakeevent(sol)
    post = mock_posterior(ev, 40)  # schema-3-valid post dict (pure-python factory)
    return ev, post, [[1.0] * 6] * 40, None, ["N.ABUF"]


def test_one_event_through_real_tick(tmp_path, monkeypatch):
    monkeypatch.setattr(live_event, "download_event_waveforms", _fake_download)
    monkeypatch.setattr(live_event, "build_event_h5", _fake_build)
    monkeypatch.setattr(live_event, "infer_live_event", _fake_infer)

    sol = _Sol()
    store = FileStore(str(tmp_path))
    summary = monitor.tick(
        str(tmp_path), FakeSource([sol]), store, cfg=Config(), now=NOW,
        backend_factory=lambda: object(), n_samples=40, delay_minutes=30, publish=False)

    assert summary["counts"]["inferred"] == 1
    eid = candidate_id(sol)

    # store passes the frontend contract
    index = store.write_index(now=NOW)
    contract.validate_index(index)
    recs = store.read_records()
    assert len(recs) == 1 and recs[0]["id"] == eid
    contract.validate_event(recs[0])
    assert recs[0]["provenance"]["mock"] is False

    # on-disk layout exists
    assert (tmp_path / "events" / f"{eid}.json").exists()
    assert (tmp_path / "events.json").exists()

    # state terminal, and the _work dir was cleaned up on success
    state = State.load(str(tmp_path / "state.json"))
    assert state.events[eid].status == PUBLISHED
    assert not (tmp_path / "_work" / eid).exists()
