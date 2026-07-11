"""Offline tests for the model-independent QA helpers (no NPE/DB needed)."""
import numpy as np
import pytest

from fnet_monitor.qa import obs_dead_components, read_noise_sigma, early_ckpt_thresholds


def test_obs_dead_components_flags_flatline_and_outlier():
    rng = np.random.default_rng(0)
    present = ["AAA", "BBB", "CCC", "DDD"]
    comps = ["Z", "E", "N"]
    obs = rng.normal(0, 1.0, size=(4, 3, 200))     # 4 healthy stations
    obs[1] *= 1e-6                                  # BBB ~ flatlined (dead sensor)
    obs[2, 0] *= 0.005                              # CCC-Z a gross amplitude outlier (<2% of peers)
    dead = obs_dead_components(obs, present, comps)
    assert ("BBB", "Z") in dead and ("BBB", "E") in dead and ("BBB", "N") in dead
    assert ("CCC", "Z") in dead
    assert ("CCC", "E") not in dead               # CCC horizontals are healthy
    assert not any(s == "AAA" for (s, _c) in dead)
    assert not any(s == "DDD" for (s, _c) in dead)


def test_obs_dead_abs_floor():
    present, comps = ["X"], ["Z"]
    obs = np.full((1, 1, 100), 1e-15)             # below abs_floor
    assert ("X", "Z") in obs_dead_components(obs, present, comps)


def test_read_noise_sigma_from_misc(tmp_path):
    h5py = pytest.importorskip("h5py")
    p = tmp_path / "ev.h5"
    with h5py.File(p, "w") as f:
        misc = f.create_group("misc")
        # /misc/<sta>/<Z|1|2> lag-0 = pre-event variance; sigma = sqrt(var)
        g = misc.create_group("ABU")
        g.create_dataset("Z", data=np.array([4.0, 1.0, 0.5]))   # var=4 -> sigma=2
        g.create_dataset("1", data=np.array([9.0, 2.0]))        # var=9 -> sigma=3 (comp E->1)
        g.create_dataset("2", data=np.array([0.0]))             # degenerate -> omitted
    sig = read_noise_sigma(str(p), ["ABU", "MISSING"], ["Z", "E", "N"])
    assert abs(sig[("ABU", "Z")] - 2.0) < 1e-9
    assert abs(sig[("ABU", "E")] - 3.0) < 1e-9   # E maps to /misc key '1'
    assert ("ABU", "N") not in sig               # degenerate variance dropped
    assert not any(s == "MISSING" for (s, _c) in sig)


def test_threshold_presets():
    early = early_ckpt_thresholds()
    assert early.enable_snr_gates and early.xcorr_drop == 0.0 and not early.enable_ppc_drops
    assert early.amp_hi > 1e6                     # amplitude gate effectively disabled


def test_data_qa_thresholds_presets():
    from fnet_monitor.qa import data_qa_thresholds
    minimal = data_qa_thresholds()
    # essential gates armed: dead(+unrecognisable), sigma-outlier, excess
    assert minimal.enable_snr_gates and minimal.snr_dead_unrecog_ratio == 0.25
    assert minimal.sigma_rel_max == 50.0
    assert minimal.enable_snr_excess and minimal.snr_excess_factor == 5.0
    # classical fit gates neutralised in minimal
    assert not minimal.conditional_fit_gates and minimal.xcorr_drop == 0.0
    full = data_qa_thresholds("full")
    assert full.conditional_fit_gates and full.xcorr_drop == 0.2
    assert full.amp_lo == 0.1 and full.amp_hi == 5.0
    # overrides pass through
    assert data_qa_thresholds("full", xcorr_drop=0.15).xcorr_drop == 0.15
    import pytest
    with pytest.raises(ValueError):
        data_qa_thresholds("bogus")


def test_channel_blocklist_loads_and_is_data(tmp_path):
    from fnet_monitor.qa import load_channel_blocklist
    # the shipped deployment blocklist (F-net Jan-2026 calibration)
    bl = load_channel_blocklist()
    assert ("YMZ", "Z") in bl and ("KSN", "Z") in bl and ("SBR", "Z") in bl
    assert ("GJM", "Z") not in bl                 # healthy reference station
    # custom path + missing file -> empty set (never crashes the live path)
    p = tmp_path / "bl.json"
    p.write_text('{"channels": [["AAA", "N"]]}')
    assert load_channel_blocklist(p) == {("AAA", "N")}
    assert load_channel_blocklist(tmp_path / "missing.json") == set()


def test_neighbour_window_flag():
    from datetime import datetime, timedelta
    from fnet_monitor.qa import neighbour_window_flag
    t0 = datetime(2026, 1, 12, 0, 48, 37)
    others = [t0 + timedelta(seconds=98), t0 - timedelta(days=2)]
    r = neighbour_window_flag(t0, 800.0, others)
    assert r["neighbour_in_window"] and abs(r["nearest_neighbour_s"] - 98) < 1
    # pre-window coda case: neighbour 100 s BEFORE the origin also flags
    r2 = neighbour_window_flag(t0, 800.0, [t0 - timedelta(seconds=100)])
    assert r2["neighbour_in_window"]
    # far neighbours don't flag; empty catalogue doesn't crash
    assert not neighbour_window_flag(t0, 800.0, [t0 + timedelta(hours=5)])["neighbour_in_window"]
    assert not neighbour_window_flag(t0, 800.0, [])["neighbour_in_window"]
