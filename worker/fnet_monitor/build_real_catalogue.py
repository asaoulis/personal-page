"""Phase-B driver: run the trained NPE over the whole pre-built F-net catalogue.

For each catalogued event it:
  * samples the MT posterior (NpeBackend, loaded once),
  * writes the schema-3 per-event record + rebuilds the static index (the frontend contract),
  * emits an `EventSolution` dir (samples.npy + cached MT features) so the ENTIRE Santorini
    lomax_catalogue gallery (diagnostics / maps / posterior gallery) runs on it unchanged,
  * records the Kagan angle of the posterior median vs the F-net reference (a sanity metric).

Then (``--gallery``) it drives the lomax_catalogue CLIs as subprocesses on the solutions root.

Usage (seismo-sbi env):
  python -m fnet_monitor.build_real_catalogue --out <run_dir> [--limit N] [--num-samples 2000]
      [--gallery] [--config ...] [--ckpt ...] [--xml ...] [--catalogue-dir ...]
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = "/home/alex/work/seismo-sbi"
LOMAX = f"{REPO}/scripts/santorini_pathbreaker/lomax_catalogue"
DEFAULT_CONFIG = f"{REPO}/scripts/configs/japan/first_ml_npe_japan.yaml"
DEFAULT_CKPT = f"{REPO}/ml-checkpoints/japan_v1"
DEFAULT_XML = "/data/alex/fnet_japan/events_jan2026.xml"
DEFAULT_CAT = "/data/alex/fnet_japan/catalogue/events"
GENERATED = "2026-07-10T00:00:00Z"  # fixed stamp (no Date.now in this env)


def _load_event_solution_cls():
    """Import EventSolution from the (gitignored) lomax suite, adding it to sys.path."""
    if LOMAX not in sys.path:
        sys.path.insert(0, LOMAX)
    from solution import EventSolution
    return EventSolution


def run(args):
    from fnet_monitor import quakeml, references as R, contract
    from fnet_monitor.inference import event_stem, resolve_event_h5
    from fnet_monitor.mt_serialize import post_from_cloud
    from fnet_monitor.npe_backend import NpeBackend
    from fnet_monitor.config import Config
    from seismo_sbi.evaluation.moment_tensor import kagan

    out = Path(args.out)
    (out / "events").mkdir(parents=True, exist_ok=True)
    solutions_root = out / "solutions"
    solutions_root.mkdir(parents=True, exist_ok=True)
    EventSolution = _load_event_solution_cls()

    print(f"[backend] loading NPE  config={args.config}  ckpt={args.ckpt}")
    backend = NpeBackend(args.config, args.ckpt, num_samples=args.num_samples)
    events = quakeml.parse_quakeml(args.xml)
    cache = R.load_cache(args.reference_cache)
    cfg = Config()
    print(f"[catalogue] {len(events)} events; {len(cache)} cached references")

    # Full Fable-calibrated QA suite (preset "full" + persistent-bad blocklist + contamination
    # flags; contaminated windows are FLAGGED not mass-dropped).
    qa_thr = qa_blocklist = cat_times = None
    dur_s = 800.0
    if args.qa_full:
        from fnet_monitor.qa import data_qa_thresholds, load_channel_blocklist
        qa_thr = data_qa_thresholds("full")
        qa_blocklist = load_channel_blocklist()
        cat_times = [e.time for e in events]
        dur_s = float((backend.raw_cfg.get("seismic_context", {}) or {}).get(
            "seismogram_duration", 800))
        print(f"[qa] FULL suite: {len(qa_blocklist)} blocklisted channels; contamination flags on")

    records, kagan_rows, skipped, contaminated = [], [], [], []
    for i, ev in enumerate(events):
        stem = event_stem(ev)
        try:
            h5 = resolve_event_h5(ev, args.catalogue_dir)
        except FileNotFoundError:
            skipped.append(stem)
            continue
        try:
            source_vec = [float(ev.lat), float(ev.lon), float(ev.depth_km)]
            present0 = backend.present_stations(h5)
            qa_res = None
            if args.qa_full:
                from fnet_monitor.qa import qa_event
                qa_res = qa_event(backend, h5, source_vec, present0, thresholds=qa_thr,
                                  num_samples=args.num_samples, blocklist=qa_blocklist,
                                  origin_time=ev.time, catalogue_times=cat_times,
                                  window_duration_s=dur_s, contaminated_action="warn")
                samples6, used = qa_res.samples_qa, qa_res.kept_stations
            elif args.qa:
                from fnet_monitor.qa import qa_event_basic
                qa_res = qa_event_basic(backend, h5, source_vec, present0,
                                        num_samples=args.num_samples)
                samples6, used = qa_res.samples_qa, qa_res.kept_stations
            else:
                samples6, used = backend.infer(h5, source_vec, num_samples=args.num_samples)
            median = np.median(samples6, axis=0)

            raw = cache.get(ev.id, []) or [R.synthesize_reference(ev)]
            raw = sorted(raw, key=lambda r: R.source_rank(r.get("source", "")))
            refs_norm = [R.normalise_reference(r) for r in raw]
            post = post_from_cloud(samples6, refs_norm)
            rec = contract.build_event_record(ev, post, GENERATED, mock=False,
                                              model="seismo_sbi-npe")
            contract.validate_event(rec)
            contract.write_event(str(out), rec)
            records.append(rec)

            sol = EventSolution(
                event_id=stem, origin_time=ev.time.isoformat(),
                lat=float(ev.lat), lon=float(ev.lon), depth_km=float(ev.depth_km),
                ml=float(ev.mag), stations_all=present0, stations_used=used,
                qa_verdicts=(qa_res.dropped if qa_res else {}),
                components_used=(qa_res.components_map if qa_res else {}),
                point_estimate_mt6=[float(x) for x in median],
                first_guess_mt6=[float(x) for x in
                                 (np.median(qa_res.samples_noqa, axis=0) if qa_res else median)],
                conditioning_vec=source_vec, ckpt_dir=str(backend.ckpt_dir),
                notes=("qa_flags=" + str(dict(qa_res.event_flags))
                       if (qa_res and getattr(qa_res, "event_flags", None)) else ""),
                provenance="real")
            sol.samples = samples6
            if qa_res is not None:
                sol.samples_noqa = qa_res.samples_noqa
                if qa_res.event_flags.get("contaminated") or qa_res.event_flags.get(
                        "neighbour_in_window"):
                    contaminated.append((stem, float(ev.mag), dict(qa_res.event_flags)))
            sol.compute_features()
            sol.save(solutions_root)

            fnet = next((r for r in raw if r.get("source") == "F-net" and r.get("mt6")), None)
            if fnet is not None:
                kg = kagan(median.tolist(), fnet["mt6"])
                kagan_rows.append((stem, ev.id, float(ev.mag), fnet.get("mw"),
                                   post["mw"], round(float(kg), 1) if kg == kg else None))
            if (i + 1) % 10 == 0 or args.limit:
                print(f"  [{i+1}/{len(events)}] {stem} Mw={post['mw']} "
                      f"used={len(used)}/{len(present0)}")
        except Exception as e:  # noqa: BLE001 — one bad event must not kill the catalogue run
            print(f"  !! {stem} FAILED: {type(e).__name__}: {e}")
            skipped.append(stem)
            continue
        if args.limit and len(records) >= args.limit:
            break

    index = contract.build_static_index(records, GENERATED, cfg, mock=False)
    contract.validate_index(index)
    contract.write_index(str(out), index)
    print(f"[write] {len(records)} events -> {out}/events.json + events/  ({len(skipped)} skipped)")

    # Kagan-vs-F-net sanity
    if kagan_rows:
        kp = out / "kagan_vs_fnet.csv"
        with open(kp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["event_id", "usgs_id", "cat_mag", "fnet_mw", "npe_mw", "kagan_deg"])
            w.writerows(kagan_rows)
        kg = np.array([r[5] for r in kagan_rows if r[5] is not None], float)
        dmw = np.array([(r[4] - r[3]) for r in kagan_rows if r[3] is not None], float)
        print(f"[kagan] N={len(kg)}  median={np.median(kg):.1f}°  "
              f"<45°={np.mean(kg < 45)*100:.0f}%  <30°={np.mean(kg < 30)*100:.0f}%")
        print(f"[Mw bias] NPE-Fnet median={np.median(dmw):+.2f}  mean={np.mean(dmw):+.2f}")
        _kagan_plot(out, kg, dmw, kagan_rows)

    # contamination report (the QA "real win": flag, don't silently drop)
    if contaminated:
        with open(out / "contamination_report.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["event_id", "mag", "flags"])
            for stem, mag, flags in contaminated:
                w.writerow([stem, mag, str(flags)])
        print(f"[qa] {len(contaminated)} contamination-FLAGGED events (kept + warned): "
              + ", ".join(s for s, _m, _f in contaminated))

    if args.gallery:
        _run_gallery(out, solutions_root, args.config)
    return len(records)


def _kagan_plot(out, kg, dmw, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].hist(kg, bins=np.arange(0, 121, 10), color="#1f4e79", alpha=0.85)
    ax[0].axvline(np.median(kg), color="crimson", ls="--", label=f"median {np.median(kg):.0f}°")
    ax[0].set(xlabel="Kagan angle NPE-median vs F-net (deg)", ylabel="events",
              title="Mechanism agreement"); ax[0].legend()
    ax[1].hist(dmw, bins=20, color="#1f4e79", alpha=0.85)
    ax[1].axvline(np.median(dmw), color="crimson", ls="--", label=f"median {np.median(dmw):+.2f}")
    ax[1].set(xlabel="Mw(NPE) - Mw(F-net)", ylabel="events", title="Magnitude bias"); ax[1].legend()
    mags = np.array([r[2] for r in rows if r[5] is not None], float)
    ax[2].scatter(mags, kg, s=18, alpha=0.6, color="#1f4e79")
    ax[2].set(xlabel="catalogue mag", ylabel="Kagan (deg)", title="Agreement vs size")
    fig.tight_layout()
    fig.savefig(out / "kagan_vs_fnet.png", dpi=130)
    print(f"[plot] {out}/kagan_vs_fnet.png")


def _run_gallery(out, solutions_root, config):
    """Drive the lomax_catalogue gallery CLIs on the emitted EventSolution dirs (best-effort)."""
    gal = out / "gallery"
    gal.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=LOMAX + os.pathsep + os.environ.get("PYTHONPATH", ""))
    jobs = [
        ("diagnostics", ["run_diagnostics.py", "--solutions-root", str(solutions_root),
                         "--out", str(gal / "diagnostics")]),
        ("map", ["catalogue_map.py", "--solutions-root", str(solutions_root),
                 "--out", str(gal / "maps")]),
        ("posterior_gallery", ["posterior_gallery.py", "--solutions-root", str(solutions_root),
                               "--out", str(gal / "posteriors"), "--config", config]),
    ]
    for name, cmd in jobs:
        print(f"[gallery] {name}: {' '.join(cmd)}")
        try:
            r = subprocess.run([sys.executable] + cmd, cwd=LOMAX, env=env,
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                print(f"  !! {name} rc={r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
            else:
                print(f"  ok {name}")
        except Exception as e:  # noqa: BLE001
            print(f"  !! {name} raised {type(e).__name__}: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--ckpt", default=DEFAULT_CKPT)
    p.add_argument("--xml", default=DEFAULT_XML)
    p.add_argument("--catalogue-dir", default=DEFAULT_CAT)
    p.add_argument("--reference-cache",
                   default=os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                        "data", "reference_cache.json"))
    p.add_argument("--num-samples", type=int, default=2000)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--gallery", action="store_true")
    p.add_argument("--qa", action="store_true",
                   help="run the model-independent obs-only dead-channel QA before inference")
    p.add_argument("--qa-full", action="store_true",
                   help="run the FULL calibrated QA suite (data_qa_thresholds('full') + blocklist "
                        "+ contamination flags, warn-not-drop on contaminated windows)")
    run(p.parse_args())


if __name__ == "__main__":
    main()
