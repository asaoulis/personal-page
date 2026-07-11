"""Offline tests for the F-net download adapter.

NO network, NO credentials, NO win2sac: the HinetPy ``Client`` and the win32->SAC
conversion are injected as fakes.  These tests lock the load-bearing contracts:
JST<->UTC conversion, the {station}/{YYYY.DDD}/ mseed layout + filenames, the
U->Z (N->BHN / E->BHE) rename, NIED<->FDSN mapping, and that NO secret is ever
logged.
"""

import logging
import os
import sys
from datetime import date, datetime

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import fetch_fnet as ff  # noqa: E402


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------

def test_jst_utc_roundtrip():
    t = datetime(2026, 1, 1, 0, 0, 0)
    assert ff.utc_to_jst(t) == datetime(2026, 1, 1, 9, 0, 0)
    assert ff.jst_to_utc(ff.utc_to_jst(t)) == t
    # UTC midnight must map to 09:00 JST clock (the per-UTC-day request anchor).
    assert ff.utc_to_jst(datetime(2026, 1, 31)) == datetime(2026, 1, 31, 9, 0)


def test_nied_fdsn_mapping():
    assert ff.fdsn_to_nied("ABU") == "N.ABUF"
    assert ff.nied_to_fdsn("N.ABUF") == "ABU"
    # idempotent
    assert ff.fdsn_to_nied("N.ABUF") == "N.ABUF"
    assert ff.nied_to_fdsn("ABU") == "ABU"
    for code in ("ABU", "NMR", "TSK"):
        assert ff.nied_to_fdsn(ff.fdsn_to_nied(code)) == code


def test_decimate_trace_antialias():
    from obspy import Trace
    import numpy as _np
    # 100 Hz, 60 s of band-limited noise -> decimate to 2 Hz (factor 50 = 5*5*2).
    tr = Trace(data=_np.random.RandomState(0).randn(6000).astype("float64"))
    tr.stats.sampling_rate = 100.0
    ff.decimate_trace(tr, 2.0)
    assert abs(tr.stats.sampling_rate - 2.0) < 1e-6
    assert tr.stats.npts == 120  # 60 s * 2 Hz
    # no-op when already at/below target
    tr2 = Trace(data=_np.zeros(100)); tr2.stats.sampling_rate = 1.0
    ff.decimate_trace(tr2, 2.0)
    assert tr2.stats.sampling_rate == 1.0
    # factorisation of the 100->2 ratio
    assert ff._factorize(50) == [5, 5, 2]


def test_component_to_channel_and_vertical_rename():
    assert ff.component_to_channel("U") == "BHZ"   # vertical -> Z (risk #2)
    assert ff.component_to_channel("N") == "BHN"
    assert ff.component_to_channel("E") == "BHE"
    assert ff.component_to_channel("BHU", band="HH") == "HHZ"
    # F-net real channels carry an A/B channel-set tag: {orient}{set}, e.g. "UB".
    assert ff.component_to_channel("UB") == "BHZ"
    assert ff.component_to_channel("NB") == "BHN"
    assert ff.component_to_channel("EB") == "BHE"
    with pytest.raises(ValueError):
        ff.component_to_channel("X")
    with pytest.raises(ValueError):
        ff.component_to_channel("")


def test_downstream_rename_component_accepts_our_channels():
    """The BH? codes we emit must satisfy seismo-sbi's _rename_component (Z/1/2)."""
    def rename(channel):  # mirror sbi_export._rename_component
        if "Z" in channel:
            return "Z"
        if "1" in channel or channel[-1] == "E":
            return "1"
        if "2" in channel or channel[-1] == "N":
            return "2"
        raise ValueError(channel)

    assert rename(ff.component_to_channel("U")) == "Z"
    assert rename(ff.component_to_channel("E")) == "1"
    assert rename(ff.component_to_channel("N")) == "2"


def test_mseed_storage_path_layout():
    p = ff.mseed_storage_path(
        "/root", "BO", "ABU", "", "BHZ", datetime(2026, 1, 1, 0, 0)
    )
    assert str(p) == "/root/ABU/2026.001/BO.ABU..BHZ.2026.001.mseed"
    # A later day in the year -> correct julian day.
    p2 = ff.mseed_storage_path("/root", "BO", "NMR", "", "BHN", datetime(2026, 2, 1))
    assert p2.name == "BO.NMR..BHN.2026.032.mseed"
    assert p2.parent.name == "2026.032"


def test_parse_sac_filename():
    assert ff.parse_sac_filename("N.ABUF.U.SAC") == ("N.ABUF", "U")
    assert ff.parse_sac_filename("/tmp/x/N.NMRF.E.SAC") == ("N.NMRF", "E")
    with pytest.raises(ValueError):
        ff.parse_sac_filename("garbage")


def test_day_range_and_month_bounds():
    assert ff.day_range(datetime(2026, 1, 1), datetime(2026, 1, 3, 23, 59)) == [
        date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    ]
    s, e = ff.month_bounds("2026-01")
    assert s == datetime(2026, 1, 1) and e == datetime(2026, 2, 1)
    s, e = ff.month_bounds("2025-12")
    assert s == datetime(2025, 12, 1) and e == datetime(2026, 1, 1)


def test_read_station_file(tmp_path):
    f = tmp_path / "stations.txt"
    f.write_text(
        "# header\nABU BO 34.86 135.57\nNMR BO 43.36 145.73  # inline comment\n\n"
    )
    stations = ff.read_station_file(f)
    assert [s.code for s in stations] == ["ABU", "NMR"]
    assert stations[0].network == "BO"
    assert stations[0].nied_name == "N.ABUF"
    assert stations[1].lat == pytest.approx(43.36)


def test_velocity_to_displacement_scaling():
    from obspy import Trace

    tr = Trace(np.ones(10, dtype=np.float64))
    tr.stats.sampling_rate = 1.0
    ff.velocity_to_displacement(tr)  # /1e9 then cumulative integral
    # constant 1 nm/s -> 1e-9 m/s integrated over time -> ramp ~ t*1e-9.
    assert tr.data[-1] == pytest.approx(9e-9, rel=1e-6)
    assert tr.data[0] == pytest.approx(0.0, abs=1e-18)


# ----------------------------------------------------------------------------
# convert_station_stream: time shift + rename + units, pure
# ----------------------------------------------------------------------------

def _sac_stream(jst_start, components=("U", "N", "E")):
    from obspy import Stream, Trace, UTCDateTime

    st = Stream()
    for c in components:
        tr = Trace(np.arange(20, dtype=np.float64) + 1.0)
        tr.stats.sampling_rate = 20.0
        tr.stats.channel = c                 # win2sac sets KCMPNM = U/N/E
        tr.stats.starttime = UTCDateTime(jst_start)  # JST clock, naive
        st += tr
    return st


def test_convert_station_stream_time_and_rename():
    # JST clock 09:00 of a UTC midnight request.
    st = _sac_stream(datetime(2026, 1, 1, 9, 0, 0))
    out = ff.convert_station_stream(st, "ABU", units="raw")
    chans = sorted(tr.stats.channel for tr in out)
    assert chans == ["BHE", "BHN", "BHZ"]   # U->BHZ
    for tr in out:
        assert tr.stats.network == "BO"
        assert tr.stats.station == "ABU"
        assert tr.stats.location == ""
        # 09:00 JST clock shifted back 9 h -> 00:00 UTC (the true window start).
        assert tr.stats.starttime.datetime == datetime(2026, 1, 1, 0, 0, 0)


def test_convert_station_stream_units():
    st = _sac_stream(datetime(2026, 1, 1, 9, 0, 0), components=("U",))
    raw = ff.convert_station_stream(st, "ABU", units="raw")[0]
    vel = ff.convert_station_stream(st, "ABU", units="velocity")[0]
    assert vel.data[0] == pytest.approx(raw.data[0] / 1e9)


# ----------------------------------------------------------------------------
# Full fetch() with injected fakes: layout + secret-safety
# ----------------------------------------------------------------------------

SECRET = "SUPERSECRET-pw-123"


class _FakeClient:
    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.selected = None
        self.last_start = None

    def select_stations(self, code, stations=None, **kw):
        assert code == ff.FNET_CODE
        self.selected = stations

    def get_continuous_waveform(self, code, starttime, span, max_span=None,
                                outdir=None, threads=3, **kw):
        assert code == ff.FNET_CODE
        assert span == 1440
        self.last_start = starttime
        # Write placeholder cnt + ctable the orchestrator will hand to extractor.
        cnt = os.path.join(outdir, "data.cnt")
        ctable = os.path.join(outdir, "table.ch")
        open(cnt, "w").close()
        open(ctable, "w").close()
        return "data.cnt", "table.ch"


def _make_fakes():
    holder = {}

    def factory(user, password):
        client = _FakeClient(user, password)
        holder["client"] = client
        return client

    def extractor(cnt, ctable, sac_dir):
        # Produce SAC exactly as win2sac would: {nied}.{comp}.SAC, JST-clock start.
        from obspy import Trace, UTCDateTime

        jst = holder["client"].last_start
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


def test_load_credentials(tmp_path):
    env = _write_env(tmp_path)
    user, pwd = ff.load_credentials(env)
    assert user == "fakeuser"
    assert pwd == SECRET
    with pytest.raises(RuntimeError):
        ff.load_credentials(tmp_path / "missing.env")


def test_fetch_writes_correct_layout(tmp_path):
    import obspy

    factory, extractor, holder = _make_fakes()
    out_root = tmp_path / "raw"
    written = ff.fetch(
        [ff.Station("ABU", "BO", 34.86, 135.57)],
        datetime(2026, 1, 1), datetime(2026, 1, 2),  # one UTC day
        out_root,
        env_path=_write_env(tmp_path),
        client_factory=factory, extractor=extractor,
        units="displacement",
    )
    # Server-side selection used NIED names.
    assert holder["client"].selected == ["N.ABUF"]
    # Requested JST anchor = 09:00 of the UTC day.
    assert holder["client"].last_start == datetime(2026, 1, 1, 9, 0, 0)

    expected = {
        out_root / "ABU/2026.001/BO.ABU..BHZ.2026.001.mseed",
        out_root / "ABU/2026.001/BO.ABU..BHN.2026.001.mseed",
        out_root / "ABU/2026.001/BO.ABU..BHE.2026.001.mseed",
    }
    assert {p.resolve() for p in written} == {p.resolve() for p in expected}
    for p in expected:
        assert p.exists()
    # The vertical file is true-UTC midnight of the requested day.
    tr = obspy.read(str(out_root / "ABU/2026.001/BO.ABU..BHZ.2026.001.mseed"))[0]
    assert tr.stats.starttime == obspy.UTCDateTime(2026, 1, 1, 0, 0, 0)
    assert tr.stats.channel == "BHZ"
    assert tr.stats.network == "BO"


def test_fetch_never_logs_secret(tmp_path, capsys):
    factory, extractor, holder = _make_fakes()

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    ff.logger.addHandler(handler)
    ff.logger.setLevel(logging.DEBUG)
    try:
        ff.fetch(
            [ff.Station("ABU", "BO", 34.86, 135.57)],
            datetime(2026, 1, 1), datetime(2026, 1, 2),
            tmp_path / "raw",
            env_path=_write_env(tmp_path),
            client_factory=factory, extractor=extractor,
        )
    finally:
        ff.logger.removeHandler(handler)

    captured = capsys.readouterr()
    blob = "\n".join(records) + captured.out + captured.err
    assert SECRET not in blob
    assert "fakeuser" not in blob


def test_dry_run_needs_no_creds(tmp_path, capsys):
    # Nonexistent env path: dry-run must not touch credentials.
    written = ff.fetch(
        [ff.Station("ABU", "BO", 34.86, 135.57)],
        datetime(2026, 1, 1), datetime(2026, 1, 3),
        tmp_path / "raw",
        env_path=tmp_path / "does-not-exist.env",
        dry_run=True,
    )
    assert written == []
    assert not (tmp_path / "raw").exists()
