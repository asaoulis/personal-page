"""Phase-C live path: F-net MT catalogue -> download -> preprocess -> infer, event by event.

Reuses every building block the offline catalogue used, so the live monitor and the batch
catalogue run the SAME code:
  * `fnet_mt.query_fnet_mt_catalogue`  — the public F-net regional-MT feed (no creds) -> events
  * `fnet.fetch_fnet.fetch`            — HinetPy F-net waveform download (needs NIED creds)
  * `data_handling.preprocessing.build_event_catalogue` — mseed -> SBI h5 (identical to Jan build)
  * `npe_backend` + `mt_serialize`     — inference -> schema-3 (+ optional obs-only QA)

For a live event the F-net MT solution IS the reference, so no synthetic fallback is used.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# Paths are env-overridable so the CI runner (assets under /home/runner/fnet_assets) works
# without touching the code; the local defaults are unchanged.  FNET_STATIONS_FILE points at
# the 21-station demo list; FNET_REPO relocates the seismo-sbi checkout; FNET_CONFIG / FNET_CKPT
# select the training YAML + checkpoint dir.
REPO = os.environ.get("FNET_REPO", "/home/alex/work/seismo-sbi")
STATIONS_FILE = os.environ.get(
    "FNET_STATIONS_FILE", f"{REPO}/scripts/configs/japan/fnet_demo_stations.txt")
DEFAULT_CONFIG = os.environ.get(
    "FNET_CONFIG", f"{REPO}/scripts/configs/japan/first_ml_npe_japan.yaml")
DEFAULT_CKPT = os.environ.get("FNET_CKPT", f"{REPO}/ml-checkpoints/japan_v1")


def event_stem(t) -> str:
    return f"{t.year:04d}{t.month:02d}{t.day:02d}T{t.hour:02d}{t.minute:02d}{t.second:02d}"


def fnet_to_quakeevent(sol):
    """FnetMT solution -> a QuakeEvent (for the schema-3 record)."""
    from .catalogue import QuakeEvent
    s, d, r = sol.np1
    return QuakeEvent(id=f"fnet_{event_stem(sol.time)}", time=sol.time, lon=float(sol.lon),
                      lat=float(sol.lat), depth_km=float(sol.depth_jma_km), mag=float(sol.mw),
                      magtype="Mw", region=sol.region, strike=s, dip=d, rake=r)


# The per-event chain accepts EITHER an `FnetMT` solution (authoritative: JMA location + MT
# reference) OR a bare `catalogue.QuakeEvent` (a provisional USGS-discovered candidate: USGS
# origin as the conditioning vector, F-net reference pending).  These tiny accessors read the
# fields whichever type `sol` is.
def sol_depth_km(sol) -> float:
    v = getattr(sol, "depth_jma_km", None)
    return float(v if v is not None else sol.depth_km)


def sol_mag(sol) -> float:
    v = getattr(sol, "mw", None)
    return float(v if v is not None else sol.mag)


def sol_to_quakeevent(sol):
    """Canonical QuakeEvent for the schema-3 record, whichever candidate type `sol` is."""
    from .catalogue import QuakeEvent
    return sol if isinstance(sol, QuakeEvent) else fnet_to_quakeevent(sol)


def download_event_waveforms(sol, work_dir, *, pre_s=420, post_s=960, threads=3, dry_run=False):
    """Download the 21 demo stations around the event. Returns the raw dir (mseed layout).

    Makes ONE small ``fetch_window`` request over [origin-pre_s, origin+post_s]
    instead of pulling full 1440-min days (~70x less data per event).

    Margin derivation (why pre_s=420, post_s=960; the old pre_s=120 was a latent
    bug masked by full-day fetches — a 20-min window would have left the pipeline
    with no clean pre-event data at all).  ``build_event_h5`` calls
    ``build_event_catalogue`` with ``pre_event_window_s=60``, ``covariance_window_s=200``
    and an 800 s / 1 Hz data vector, so it needs ARTEFACT-FREE data over
    ``[origin-260, origin+740]`` (200 s covariance window + 60 s pre-event shift
    before the origin; 740 s = 800-60 after it).

    The raw mseed passes through ``process_daily_files`` →
    ``deconvolve_and_filter`` (path-b: no response removal), which applies a 1%
    cosine taper (``taper(max_percentage=0.01)``) then a CAUSAL bandpass
    (``freqmin=0.02`` Hz / 50 s, ``freqmax=0.0667`` Hz, ``corners=4``,
    ``zerophase=False`` — forward-only, so its start-up transient sits at the
    LEADING edge only).  On the ~1380 s window the 1% taper eats ~14 s at each
    end; the 0.02 Hz causal transient needs ~2-3 low-corner periods (~100-150 s)
    to decay, all at the head.  So:
      * pre_s=420 covers origin-260 with 160 s of head margin (14 s taper +
        ~150 s filter start-up transient),
      * post_s=960 covers origin+740 with 220 s of tail margin (14 s taper +
        resample edge; the causal filter adds no tail transient).
    Total request = 1380 s = 23 min (≤ the 25-min / 120-min fetch_window cap).
    """
    from fnet.fetch_fnet import fetch_window, read_station_file
    stas = read_station_file(Path(STATIONS_FILE))
    raw = Path(work_dir) / "raw"
    t = sol.time
    fetch_window(stas, t - timedelta(seconds=pre_s), t + timedelta(seconds=post_s),
                 raw, units="displacement", threads=threads, dry_run=dry_run)
    return raw


def build_event_h5(sol, work_dir, backend):
    """mseed -> one SBI h5 (identical recipe to the offline Jan catalogue). Returns the h5 path."""
    from obspy import UTCDateTime
    from obspy.core.event import Event, Magnitude, Origin, ResourceIdentifier
    from seismo_sbi.data_handling.preprocessing.catalogue import (
        build_event_catalogue, read_stations_file)

    sc = backend.raw_cfg["seismic_context"]
    dur = float(sc.get("seismogram_duration", 800))
    sr = float(sc.get("sampling_rate", 1.0))
    # the config nests the filter at seismic_context.processing.filter (NOT sc['filter']);
    # reading the wrong key silently falls back to the 0.05 Hz default band.
    filt_cfg = (sc.get("processing", {}) or {}).get("filter") or sc.get("filter") or {}
    filt = {k: v for k, v in filt_cfg.items() if k != "type"}
    stem = event_stem(sol.time)
    o = Origin(time=UTCDateTime(sol.time), latitude=float(sol.lat), longitude=float(sol.lon),
               depth=sol_depth_km(sol) * 1000.0)
    ev = Event(resource_id=ResourceIdentifier(id=stem), origins=[o],
               magnitudes=[Magnitude(mag=sol_mag(sol))])
    ev.preferred_origin_id = o.resource_id
    out = Path(work_dir) / "catalogue"
    paths = build_event_catalogue(
        [ev], data_dir=Path(work_dir) / "raw", stationxml_dir=None,       # path-b: no response removal
        station_networks=read_stations_file(Path(STATIONS_FILE)), output_dir=out,
        duration_s=dur, sampling_rate=sr, filter_kwargs=filt, covariance_window_s=200.0,
        pre_event_window_s=60.0)   # sims place the origin at +60 s (SyntheticsPreprocessing) -> obs must too
    return paths[0] if paths else None


def infer_live_event(sol, event_h5, backend, *, n=2000, qa=True, qa_full=False,
                     catalogue_times=None):
    """Infer + serialise ONE live event.

    `sol` is either an `FnetMT` solution (its MT is attached as the reference) or a
    provisional USGS `QuakeEvent` (no MT exists yet: the record is published with
    `references=[]`, i.e. the F-net reference PENDING — the supersede-on-match flow
    replaces the record when NIED publishes).

    QA level:
      * ``qa_full=True``  — the FULL calibrated suite, mirroring ``build_real_catalogue --qa-full``:
        ``data_qa_thresholds('full')`` + the persistent-bad channel blocklist +
        ``contaminated_action='warn'`` (contaminated windows are FLAGGED, not mass-dropped).
        ``catalogue_times`` (origin times of the other candidates this tick) arms the
        neighbour-in-window flag.  This is what the live monitor uses.
      * ``qa=True`` (and not ``qa_full``) — the lightweight obs-only dead-channel gate.
      * ``qa=False`` — no QA, raw posterior.
    """
    from . import references as R
    from .mt_serialize import post_from_cloud

    ev = sol_to_quakeevent(sol)
    source_vec = [float(sol.lat), float(sol.lon), sol_depth_km(sol)]
    present = backend.present_stations(event_h5)
    qa_res = None
    if qa_full:
        from .qa import data_qa_thresholds, load_channel_blocklist, qa_event
        thr = data_qa_thresholds("full")
        blocklist = load_channel_blocklist()
        dur_s = float((backend.raw_cfg.get("seismic_context", {}) or {}).get(
            "seismogram_duration", 800))
        qa_res = qa_event(backend, event_h5, source_vec, present, thresholds=thr,
                          num_samples=n, blocklist=blocklist, origin_time=sol.time,
                          catalogue_times=catalogue_times, window_duration_s=dur_s,
                          contaminated_action="warn")
        samples6 = qa_res.samples_qa
    elif qa:
        from .qa import qa_event_basic
        qa_res = qa_event_basic(backend, event_h5, source_vec, present, num_samples=n)
        samples6 = qa_res.samples_qa
    else:
        samples6, _ = backend.infer(event_h5, source_vec, num_samples=n)
    # the F-net catalogue solution is the reference; a provisional USGS candidate has no MT
    # yet, so its record carries an EMPTY references list (reference pending).
    m6 = getattr(sol, "m6_use", None)
    if m6 is not None:
        refs = [R.normalise_reference({"source": "F-net", "mt6": list(m6),
                                       "mw": float(sol.mw), "synthetic": False})]
    else:
        refs = []
    post = post_from_cloud(samples6, refs)
    return ev, post, np.asarray(samples6), qa_res, present


def run_live(sols, backend, out_dir, *, n=2000, qa=True, dry_run=False):
    """Full live pipeline over a list of FnetMT solutions -> schema-3 store + EventSolution dirs."""
    from . import contract
    from .config import Config
    import sys
    sys.path.insert(0, f"{REPO}/scripts/santorini_pathbreaker/lomax_catalogue")
    from solution import EventSolution  # noqa: E402

    out_dir = Path(out_dir)
    (out_dir / "events").mkdir(parents=True, exist_ok=True)
    solutions_root = out_dir / "solutions"
    records = []
    for i, sol in enumerate(sols):
        stem = event_stem(sol.time)
        wdir = out_dir / "work" / stem
        try:
            print(f"[{i+1}/{len(sols)}] {stem} Mw{sol.mw} — downloading…", flush=True)
            download_event_waveforms(sol, wdir, dry_run=dry_run)
            if dry_run:
                continue
            h5 = build_event_h5(sol, wdir, backend)
            if h5 is None:
                print(f"  !! {stem}: no h5 built (insufficient stations)"); continue
            ev, post, samples6, qa_res, present = infer_live_event(sol, h5, backend, n=n, qa=qa)
            rec = contract.build_event_record(ev, post, datetime.now(timezone.utc).isoformat(),
                                              mock=False, model="seismo_sbi-npe-live")
            contract.validate_event(rec)
            contract.write_event(str(out_dir), rec)
            records.append(rec)
            median = np.median(samples6, axis=0)
            sol_obj = EventSolution(
                event_id=stem, origin_time=sol.time.isoformat(), lat=float(sol.lat),
                lon=float(sol.lon), depth_km=float(sol.depth_jma_km), ml=float(sol.mw),
                stations_all=present, stations_used=(qa_res.kept_stations if qa_res else present),
                qa_verdicts=(qa_res.dropped if qa_res else {}),
                point_estimate_mt6=[float(x) for x in median],
                conditioning_vec=[float(sol.lat), float(sol.lon), float(sol.depth_jma_km)],
                ckpt_dir=str(backend.ckpt_dir), provenance="real-live")
            sol_obj.samples = samples6
            sol_obj.compute_features()
            sol_obj.save(solutions_root)
            print(f"  ok {stem}: Mw={post['mw']} kagan(F-net)="
                  f"{post['references'][0]['kagan_deg']}° used={len(present)}", flush=True)
        except Exception as e:  # noqa: BLE001 — one bad event must not kill the run
            import traceback
            traceback.print_exc()
            print(f"  !! {stem} FAILED: {type(e).__name__}: {e}", flush=True)
    if records:
        idx = contract.build_static_index(records, datetime.now(timezone.utc).isoformat(),
                                          Config(), mock=False)
        contract.write_index(str(out_dir), idx)
    print(f"[done] {len(records)} live events -> {out_dir}", flush=True)
    return len(records)


def main():
    p = argparse.ArgumentParser(description="Live F-net event inference (query->download->infer).")
    p.add_argument("--out", required=True)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--ckpt", default=DEFAULT_CKPT)
    p.add_argument("--days", type=int, default=45, help="look-back window from --end")
    p.add_argument("--end", default=None, help="ISO end date (default: now)")
    p.add_argument("--min-mw", type=float, default=4.0)
    p.add_argument("--max-events", type=int, default=10)
    p.add_argument("--num-samples", type=int, default=2000)
    p.add_argument("--no-qa", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="query + plan downloads, fetch nothing")
    args = p.parse_args()

    from .fnet_mt import query_fnet_mt_catalogue
    from .npe_backend import NpeBackend

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end \
        else datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    print(f"Querying F-net MT {start.date()}..{end.date()} (Mw>={args.min_mw})…", flush=True)
    sols = query_fnet_mt_catalogue(start, end, min_mw=args.min_mw)
    sols = sorted(sols, key=lambda s: -s.mw)[:args.max_events]
    print(f"  {len(sols)} events selected (top by Mw)", flush=True)
    backend = NpeBackend(args.config, args.ckpt, num_samples=args.num_samples)
    run_live(sols, backend, args.out, n=args.num_samples, qa=not args.no_qa, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
