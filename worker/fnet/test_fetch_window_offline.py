"""Offline tests for the per-event windowed F-net download (``fetch_window``).

NO network, NO credentials, NO win2sac: the HinetPy ``Client`` and the win32->SAC
conversion are injected as fakes (same seams as ``test_fetch_fnet_offline.py``).
These lock the load-bearing contracts of the event-window path: exactly ONE
request with the correct JST anchor + span, the resumable {station}/{YYYY.DDD}/
mseed layout, the span sanity cap, and dry-run needing no credentials.
"""

import logging
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import fetch_fnet as ff  # noqa: E402

SECRET = "SUPERSECRET-pw-123"


class _CapturingClient:
    """Fake HinetPy Client that records every get_continuous_waveform call."""

    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.selected = None
        self.calls = []

    def select_stations(self, code, stations=None, **kw):
        assert code == ff.FNET_CODE
        self.selected = stations

    def get_continuous_waveform(self, code, starttime, span, max_span=None,
                                outdir=None, threads=3, **kw):
        # NOTE: no span==1440 assertion — the window path uses a small span.
        self.calls.append(
            dict(code=code, starttime=starttime, span=span, max_span=max_span)
        )
        cnt = os.path.join(outdir, "data.cnt")
        ctable = os.path.join(outdir, "table.ch")
        open(cnt, "w").close()
        open(ctable, "w").close()
        return "data.cnt", "table.ch"


def _make_fakes():
    holder = {}

    def factory(user, password):
        client = _CapturingClient(user, password)
        holder["client"] = client
        return client

    def extractor(cnt, ctable, sac_dir):
        from obspy import Trace, UTCDateTime

        jst = holder["client"].calls[-1]["starttime"]  # JST clock, naive
        for comp in ("U", "N", "E"):
            tr = Trace(np.arange(40, dtype=np.float64) + 1.0)
            tr.stats.sampling_rate = 20.0
            tr.stats.channel = comp
            tr.stats.starttime = UTCDateTime(jst)
            tr.write(os.path.join(sac_dir, f"N.ABUF.{comp}.SAC"), format="SAC")

    return factory, extractor, holder


def _write_env(tmp_path):
    env = tmp_path / "creds.env"
    env.write_text(f"FNET_USERNAME=fakeuser\nFNET_PASSWORD={SECRET}\n")
    return env


def _station():
    return ff.Station("ABU", "BO", 34.86, 135.57)


# Event origin used across the tests; pre_s=420 / post_s=960 -> 1380 s window.
_ORIGIN = datetime(2026, 1, 15, 12, 34, 30)
_START = _ORIGIN - timedelta(seconds=420)  # 12:27:30 UTC
_END = _ORIGIN + timedelta(seconds=960)    # 12:50:30 UTC


def test_fetch_window_single_request_start_and_span(tmp_path):
    """(a) Exactly ONE request, JST start floored to the minute, span = ceil+1."""
    factory, extractor, holder = _make_fakes()
    ff.fetch_window(
        [_station()], _START, _END, tmp_path / "raw",
        env_path=_write_env(tmp_path),
        client_factory=factory, extractor=extractor,
    )
    client = holder["client"]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["code"] == ff.FNET_CODE
    # 12:27:30 UTC -> +9h = 21:27:30 JST -> floored to the minute = 21:27:00.
    assert call["starttime"] == datetime(2026, 1, 15, 21, 27, 0)
    # span = ceil((1380 s)/60) + 1 = 23 + 1 = 24 min.
    assert call["span"] == 24
    # Server-side selection restricted to our NIED station names.
    assert client.selected == ["N.ABUF"]


def test_fetch_window_writes_layout(tmp_path):
    """(c) Written files land in the {station}/{YYYY.DDD}/ layout, true-UTC start."""
    import obspy

    factory, extractor, holder = _make_fakes()
    out_root = tmp_path / "raw"
    written = ff.fetch_window(
        [_station()], _START, _END, out_root,
        env_path=_write_env(tmp_path),
        client_factory=factory, extractor=extractor, units="displacement",
    )
    # JST 21:27 -> -9h -> 12:27 UTC on 2026-01-15 (julian day 015).
    expected = {
        out_root / "ABU/2026.015/BO.ABU..BHZ.2026.015.mseed",
        out_root / "ABU/2026.015/BO.ABU..BHN.2026.015.mseed",
        out_root / "ABU/2026.015/BO.ABU..BHE.2026.015.mseed",
    }
    assert {p.resolve() for p in written} == {p.resolve() for p in expected}
    for p in expected:
        assert p.exists()
    tr = obspy.read(str(out_root / "ABU/2026.015/BO.ABU..BHZ.2026.015.mseed"))[0]
    assert tr.stats.channel == "BHZ"
    assert tr.stats.network == "BO"
    assert tr.stats.starttime == obspy.UTCDateTime(2026, 1, 15, 12, 27, 0)


def test_fetch_window_dry_run_no_creds(tmp_path):
    """(b) dry_run loads no credentials and returns [] (writes nothing)."""
    written = ff.fetch_window(
        [_station()], _START, _END, tmp_path / "raw",
        env_path=tmp_path / "does-not-exist.env",  # would raise if creds loaded
        dry_run=True,
    )
    assert written == []
    assert not (tmp_path / "raw").exists()


def test_fetch_window_rejects_oversized_span(tmp_path):
    """Sanity cap: a > 120-min span means a caller bug — raise, don't hammer NIED."""
    origin = datetime(2026, 1, 15, 12, 0, 0)
    with pytest.raises(ValueError):
        ff.fetch_window(
            [_station()], origin, origin + timedelta(hours=3),  # 180 min > 120
            tmp_path / "raw", dry_run=True,  # cap is checked before dry_run/creds
        )


def test_fetch_window_never_logs_secret(tmp_path, capsys):
    """No credential ever reaches the logs on the window path."""
    factory, extractor, _ = _make_fakes()
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    ff.logger.addHandler(handler)
    ff.logger.setLevel(logging.DEBUG)
    try:
        ff.fetch_window(
            [_station()], _START, _END, tmp_path / "raw",
            env_path=_write_env(tmp_path),
            client_factory=factory, extractor=extractor,
        )
    finally:
        ff.logger.removeHandler(handler)

    blob = "\n".join(records)
    captured = capsys.readouterr()
    blob += captured.out + captured.err
    assert SECRET not in blob
    assert "fakeuser" not in blob


def test_fetch_window_normalises_tz_aware_input(tmp_path):
    """Regression: catalogue event times are tz-AWARE (UTC). HinetPy compares
    naive datetimes internally, so fetch_window must strip tzinfo (real probe
    2026-07-11 died with 'can't compare offset-naive and offset-aware')."""
    from datetime import timezone

    factory, extractor, holder = _make_fakes()
    aware_start = _START.replace(tzinfo=timezone.utc)
    aware_end = _END.replace(tzinfo=timezone.utc)
    ff.fetch_window(
        [_station()], aware_start, aware_end, tmp_path / "raw",
        env_path=_write_env(tmp_path),
        client_factory=factory, extractor=extractor,
    )
    call = holder["client"].calls[0]
    assert call["starttime"].tzinfo is None
    assert call["starttime"] == datetime(2026, 1, 15, 21, 27, 0)  # same as naive path
    assert call["span"] == 24
