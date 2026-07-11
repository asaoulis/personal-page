"""Opt-in LIVE integration test for the real F-net -> NPE pipeline.

Unlike every other test under `worker/tests` (which monkeypatch the download/build/infer
seams so the suite is offline-fast-deterministic), this test drives the REAL
`monitor.tick()` against a temp out-dir with NO seams faked: real F-net MT catalogue
query, real NIED waveform download (~2 min for the one event window), real mseed->h5
build, real NPE inference with the real trained checkpoint + the FULL QA suite.

It is gated behind the opt-in `live` pytest marker (registered in `worker/pyproject.toml`,
which also sets `addopts = "-q -m \"not live\""` so the default suite — `pytest
worker/tests worker/fnet`, run from the repo root — never executes it; passing `-m live`
on the command line overrides that default, pytest's `-m` being last-wins).

Target event: the archived 2026-06-16 10:46:33 UTC Mw 5.4 SW_IBARAKI_PREF F-net solution.
Chosen because it is (a) well past any NIED archive-lag window and (b) the ONLY
candidate the public F-net MT catalogue returns for min_mw=5.3 over 2026-06-16..17 (a
plain `FnetMtSource(cfg, lookback_days=1, min_mw=5.3)` fetched at `now=2026-06-17T00:00Z`
narrows to exactly this one event via its own bbox/magnitude filtering — no
reimplementation of the query needed).

Run:
    conda run -n seismo-sbi python -m pytest worker/tests/test_live_pipeline.py -m live -q

Skips cleanly (never errors) on a machine missing NIED creds, the training config, the
checkpoint, the stations file, or the fiducial Instaseis DB the QA forward model needs.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Registered in worker/pyproject.toml; applied at module scope so every test here is opt-in.
pytestmark = pytest.mark.live

TARGET_TIME = datetime(2026, 6, 16, 10, 46, 33, tzinfo=timezone.utc)
TARGET_EVENT_ID = "fnet_20260616T104633"
REFERENCE_MW = 5.4
MW_TOLERANCE = 0.5

# `now` for the tick: the query window is [now - lookback_days, now), so this pins the
# fetch to exactly 2026-06-16..2026-06-17 (see the module docstring). The event (10:46) is
# ~13 h before this `now`, comfortably past the default 30-min archive-lag delay window.
FIXED_NOW = datetime(2026, 6, 17, 0, 0, 0, tzinfo=timezone.utc)


def _missing_prerequisites():
    """Human-readable reasons this machine can't run the live test (empty == can run)."""
    reasons = []

    from fnet_monitor import live_event

    cfg_path = Path(live_event.DEFAULT_CONFIG)
    if not cfg_path.exists():
        reasons.append(f"training config missing: {cfg_path}")

    ckpt_dir = Path(live_event.DEFAULT_CKPT)
    if not ckpt_dir.exists():
        reasons.append(f"checkpoint dir missing: {ckpt_dir}")

    stations_file = Path(live_event.STATIONS_FILE)
    if not stations_file.exists():
        reasons.append(f"stations file missing: {stations_file}")

    if cfg_path.exists():
        try:
            import yaml

            raw = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"could not parse training config: {exc}")
        else:
            sc = raw.get("seismic_context", {}) or {}
            fiducial = sc.get("syngine_fiducial_address")
            if fiducial and not Path(fiducial).exists():
                reasons.append(f"fiducial Instaseis DB missing: {fiducial}")

    try:
        from fnet.fetch_fnet import load_credentials

        load_credentials()  # never logs/returns the values; only checked for presence
    except Exception as exc:  # noqa: BLE001 — any failure to load creds -> skip
        reasons.append(f"NIED credentials unavailable ({type(exc).__name__})")

    return reasons


def test_live_pipeline_one_event(tmp_path):
    reasons = _missing_prerequisites()
    if reasons:
        pytest.skip("live test prerequisites missing: " + "; ".join(reasons))

    from fnet_monitor import contract, monitor
    from fnet_monitor.config import Config
    from fnet_monitor.sources import FnetMtSource, candidate_id
    from fnet_monitor.state import PUBLISHED, State
    from fnet_monitor.store import FileStore

    cfg = Config()
    # FnetMtSource's OWN knobs narrow the query: lookback_days=1 + min_mw=5.3 fetched at
    # FIXED_NOW == exactly the 2026-06-16..17 window + only the Mw>=5.3 solution survives
    # the source's client-side magnitude/bbox filter (`FnetMtSource._keep`).
    source = FnetMtSource(cfg, lookback_days=1, min_mw=5.3)
    candidates = source.fetch(FIXED_NOW)
    assert len(candidates) == 1, (
        f"expected exactly 1 candidate for min_mw=5.3 on 2026-06-16..17, got "
        f"{[(c.time, c.mw) for c in candidates]}"
    )
    sol = candidates[0]
    assert abs((sol.time - TARGET_TIME).total_seconds()) < 5
    assert candidate_id(sol) == TARGET_EVENT_ID
    assert sol.mw == pytest.approx(REFERENCE_MW, abs=0.05)

    out_dir = tmp_path / "live_store"
    out_dir.mkdir()
    store = FileStore(str(out_dir))

    t0 = time.time()
    summary = monitor.tick(
        str(out_dir), source, store,
        cfg=cfg, now=FIXED_NOW,
        n_samples=2000, qa=True,   # qa=True -> tick() runs the FULL QA suite (qa_full=qa)
        publish=False,
    )
    wall_s = time.time() - t0
    print(f"\n[test_live_pipeline] real download+h5+inference wall time: {wall_s:.1f}s")

    assert summary["counts"]["inferred"] == 1, summary
    assert summary["counts"]["failed"] == 0, summary
    assert summary["counts"]["data_waiting"] == 0, summary

    # FileStore record satisfies the frontend contract.
    index = store.write_index(now=FIXED_NOW)
    contract.validate_index(index)

    recs = store.read_records()
    assert len(recs) == 1
    rec = recs[0]
    contract.validate_event(rec)
    assert rec["id"] == TARGET_EVENT_ID
    assert rec["provenance"]["mock"] is False

    assert rec["mw"] is not None
    mw_diff = abs(rec["mw"] - REFERENCE_MW)
    print(f"[test_live_pipeline] posterior mw={rec['mw']} vs F-net reference "
          f"mw={REFERENCE_MW} (|diff|={mw_diff:.2f})")
    assert mw_diff <= MW_TOLERANCE, (
        f"posterior mw {rec['mw']} outside +/-{MW_TOLERANCE} of the F-net reference "
        f"{REFERENCE_MW}"
    )

    # state ends terminal (published), never left mid-pipeline.
    state = State.load(str(out_dir / "state.json"))
    assert state.events[TARGET_EVENT_ID].status == PUBLISHED
