"""Offline tests for npe_backend pure logic + real_posterior wiring (no model/GPU/DB).

The heavy NpeBackend (pipeline+posterior+scaler) is validated by the task's live e2e run; here
we test the config->model_config mapping and the event-h5 / reference / serializer wiring with
injected seams, so these run in the pure-python worker CI.
"""
import numpy as np
import pytest

from fnet_monitor import inference
from fnet_monitor.npe_backend import (
    MIN_USABLE_STATIONS, NpeBackend, assemble_model_flow_config, expected_trace_length,
    filter_ragged_stations)


def test_assemble_model_flow_config_japan_shape():
    raw = {
        "ml_architecture": "tcn",
        "ml_encoder": {"enabled": True, "input_decimate": 3, "downsample": 2},
        "ml_conditioning": {"param_map": {"source_location": ["latitude", "longitude", "depth"]},
                            "d_cond": 256, "coord_mode": "geographic", "inject": ["token_add", "film"]},
        "ml_variable_stations": {"enabled": True, "keep_fraction": [0.5, 1.0],
                                "station_coords_mode": "relative"},
        "ml_amplitude_embedding": {"enabled": True, "mode": "array_relative"},
        "ml_positional_encoding": {"enabled": True, "mode": "fourier"},
        "ml_flow": {"num_transforms": 8, "num_blocks": 2},
    }
    arch, mc, fc, lr, wd, lrs = assemble_model_flow_config(raw)
    assert arch == "tcn" and mc["station_encoder"] == "tcn"
    assert mc["input_decimate"] == {"factor": 3}
    assert mc["encoder_config"] == {"downsample": 2}
    assert mc["conditioning"]["n_cond"] == 3
    assert mc["conditioning"]["inject"] == ["token_add", "film"]
    assert mc["variable_stations"] is True and mc["station_coords_mode"] == "relative"
    assert "amplitude_embedding" in mc and "positional_encoding" in mc
    assert fc == {"num_transforms": 8, "num_blocks": 2}
    assert lr == 1e-4 and wd == 1e-4 and lrs == "cosine"


def test_assemble_defaults_when_blocks_absent():
    arch, mc, fc, *_ = assemble_model_flow_config({"ml_architecture": "cnn"})
    assert arch == "cnn" and mc == {"station_encoder": "cnn"} and fc is None


class _Ev:
    def __init__(self, y, mo, d, h, mi, s, lat=38.0, lon=140.0, depth_km=20.0, mag=5.0, eid="us1"):
        from datetime import datetime, timezone
        self.time = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
        self.lat, self.lon, self.depth_km, self.mag, self.id = lat, lon, depth_km, mag, eid


def test_event_stem():
    assert inference.event_stem(_Ev(2026, 1, 14, 22, 13, 16)) == "20260114T221316"


def test_resolve_event_h5_exact_and_tolerant(tmp_path):
    (tmp_path / "20260114T221316.h5").write_text("x")
    ev = _Ev(2026, 1, 14, 22, 13, 16)
    assert inference.resolve_event_h5(ev, str(tmp_path)).endswith("20260114T221316.h5")
    # ±2 s tolerance: h5 stamped 1 s later than the origin
    ev2 = _Ev(2026, 1, 14, 22, 13, 15)
    assert inference.resolve_event_h5(ev2, str(tmp_path)).endswith("20260114T221316.h5")
    with pytest.raises(FileNotFoundError):
        inference.resolve_event_h5(_Ev(2026, 1, 14, 22, 20, 0), str(tmp_path))


def test_real_posterior_from_h5_wiring(monkeypatch):
    """real_posterior_from_h5 must: call backend.infer with [lat,lon,depth], fetch refs,
    and hand both to the serializer — without importing torch/seismo_sbi."""
    calls = {}

    class _FakeBackend:
        def infer(self, h5, source_vec, *, num_samples, components_map=None, station_names=None):
            calls["h5"] = h5
            calls["source_vec"] = list(source_vec)
            calls["n"] = num_samples
            return np.zeros((num_samples, 6)), ["ABU", "TSK"]

    monkeypatch.setattr(inference, "get_backend", lambda: _FakeBackend())
    monkeypatch.setattr(inference, "_references_for", lambda ev: [{"src": "F-net"}])
    monkeypatch.setattr("fnet_monitor.mt_serialize.post_from_cloud",
                        lambda cloud, refs, **kw: {"cloud_n": len(cloud), "refs": refs})

    ev = _Ev(2026, 1, 14, 22, 13, 16, lat=42.7, lon=145.5, depth_km=30.0)
    out = inference.real_posterior_from_h5(ev, "/tmp/ev.h5", 128)
    assert calls["h5"] == "/tmp/ev.h5"
    assert calls["source_vec"] == [42.7, 145.5, 30.0]
    assert calls["n"] == 128
    assert out == {"cloud_n": 128, "refs": [{"src": "F-net"}]}


# ------------------------------------------------------------------- ragged-trace guard
def test_expected_trace_length_from_config():
    assert expected_trace_length({"seismic_context": {"seismogram_duration": 800,
                                                      "sampling_rate": 1.0}}) == 801
    assert expected_trace_length({}) == 801  # falls back to the 800 s @ 1 Hz demo defaults


def test_filter_ragged_stations_pure():
    present = ["A", "B", "C"]
    lengths = {"A": [801, 801, 801], "B": [801, 663, 801], "C": [801, 801, 801]}
    usable, dropped = filter_ragged_stations(present, lengths, 801)
    assert usable == ["A", "C"] and dropped == ["B"]
    # a station with no traces at all is dropped, order preserved
    u2, d2 = filter_ragged_stations(["A", "B"], {"A": [], "B": [801]}, 801)
    assert u2 == ["B"] and d2 == ["A"]


class _RaggedFakeBackend:
    """Minimal stand-in exposing only what NpeBackend.present_stations reads."""

    def __init__(self, master_stations):
        self.master_stations = master_stations
        self.raw_cfg = {"seismic_context": {"seismogram_duration": 800, "sampling_rate": 1.0}}


def _write_event_h5(path, station_lengths):
    """Write a minimal SBI-shaped h5: outputs/<station>/{Z,1,2} traces of the given length."""
    import h5py

    with h5py.File(path, "w") as f:
        out = f.create_group("outputs")
        for sta, L in station_lengths.items():
            g = out.create_group(sta)
            for comp in ("Z", "1", "2"):
                g.create_dataset(comp, data=np.zeros(L, dtype=np.float32))


def test_present_stations_drops_ragged_and_proceeds(tmp_path, capsys):
    h5 = tmp_path / "ev.h5"
    # ABU has a ragged trace (663 != 801); the other three are well-formed.
    _write_event_h5(h5, {"ABU": 663, "TSK": 801, "KNP": 801, "TMR": 801})
    backend = _RaggedFakeBackend(["ABU", "TSK", "KNP", "TMR"])
    usable = NpeBackend.present_stations(backend, str(h5))
    assert usable == ["TSK", "KNP", "TMR"]           # ragged ABU dropped, master order kept
    assert "ragged-guard" in capsys.readouterr().out  # the drop is logged


def test_present_stations_raises_when_too_few_survive(tmp_path):
    h5 = tmp_path / "ev.h5"
    # only 2 well-formed stations survive (< MIN_USABLE_STATIONS) -> raise for the retry path
    _write_event_h5(h5, {"ABU": 663, "TSK": 801, "KNP": 801})
    backend = _RaggedFakeBackend(["ABU", "TSK", "KNP"])
    assert MIN_USABLE_STATIONS == 3
    with pytest.raises(ValueError, match="usable stations"):
        NpeBackend.present_stations(backend, str(h5))
