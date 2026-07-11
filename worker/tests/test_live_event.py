"""Offline tests for the live-path pure logic (no network / creds / model)."""
from datetime import datetime, timedelta, timezone

from fnet_monitor.live_event import (
    download_event_waveforms, event_stem, fnet_to_quakeevent)


class _Sol:
    """Minimal FnetMT stand-in (only the fields the pure helpers read)."""
    def __init__(self):
        self.time = datetime(2026, 5, 27, 7, 38, 55, tzinfo=timezone.utc)
        self.lat, self.lon, self.depth_jma_km, self.mw = 41.58, 143.58, 51.55, 4.4
        self.region = "off Tokachi"
        self.np1 = (200.0, 30.0, 90.0)
        self.m6_use = [1, 1, 1, 0, 0, 0]


def test_event_stem():
    assert event_stem(datetime(2026, 5, 27, 7, 38, 55, tzinfo=timezone.utc)) == "20260527T073855"


def test_fnet_to_quakeevent():
    ev = fnet_to_quakeevent(_Sol())
    assert ev.id == "fnet_20260527T073855"
    assert ev.lat == 41.58 and ev.lon == 143.58 and ev.depth_km == 51.55
    assert ev.mag == 4.4 and ev.magtype == "Mw"
    assert ev.strike == 200.0 and ev.dip == 30.0 and ev.rake == 90.0


def test_download_event_waveforms_passes_derived_window(monkeypatch, tmp_path):
    """download_event_waveforms must hand fetch_window the derived [-pre_s, +post_s]
    window (pre_s=420 / post_s=960 -> 1380 s) — the derivation keeps
    [origin-260, origin+740] clean of taper/filter transients downstream."""
    import fnet.fetch_fnet as ff

    captured = {}

    def fake_fetch_window(stas, start_utc, end_utc, out_root, **kw):
        captured.update(start=start_utc, end=end_utc, out_root=out_root, kw=kw)
        return []

    # Avoid touching the real stations file / network.
    monkeypatch.setattr(ff, "fetch_window", fake_fetch_window)
    monkeypatch.setattr(ff, "read_station_file", lambda p: ["N.ABUF"])

    sol = _Sol()
    raw = download_event_waveforms(sol, tmp_path / "work")

    assert raw == tmp_path / "work" / "raw"
    assert captured["start"] == sol.time - timedelta(seconds=420)
    assert captured["end"] == sol.time + timedelta(seconds=960)
    # Single-request span is the derived 1380 s (= 23 min; fetch_window adds +1 min).
    assert (captured["end"] - captured["start"]).total_seconds() == 1380
    assert captured["kw"]["units"] == "displacement"
    assert captured["kw"]["dry_run"] is False
