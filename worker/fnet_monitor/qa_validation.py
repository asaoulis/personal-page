"""Model-FREE validation of the SNR QA gates (Fable's protocol).

The end-to-end QA is limited by the NPE's median-MT quality (an early checkpoint's wrong
mechanism makes the synthetic-comparison gates mis-fire). To validate the GATES THEMSELVES,
decouple them from the model: forward-model the published **F-net reference MT** (correct
mechanism + amplitude) through the fiducial DB, then check the gates flag genuinely-bad traces
(dead / noise-dominated) WITHOUT false-dropping well-recorded ones.

Outputs (per `out_dir`):
  * `gate_validation.csv`   — per (event, station, component): snr_syn, snr_sig, amp_ratio, verdict
  * `station_drop_rate.csv` — per station: fraction of events each gate drops it (KSN should top)
  * `gate_validation.png`   — drop-rate bars + snr_syn-vs-snr_sig scatter coloured by verdict
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np


def _fnet_ref_phys(reference_cache: dict, usgs_id: str):
    for r in reference_cache.get(usgs_id, []):
        if r.get("source") == "F-net" and r.get("mt6"):
            return np.asarray(r["mt6"], float)
    for r in reference_cache.get(usgs_id, []):
        if r.get("mt6"):
            return np.asarray(r["mt6"], float)
    return None


def validate_gates_model_free(backend, events, reference_cache, out_dir, *,
                              thresholds=None, resolve_h5=None):
    """`events`: iterable of QuakeEvent. `resolve_h5(ev)->path` (raises if absent).

    Uses `thresholds` (default: SNR-only early-ckpt preset) purely to LABEL traces; the forward
    model is the F-net reference MT, so the labels reflect data quality, not model quality.
    """
    from seismo_sbi.data_quality import (
        TraceDescriptor, compute_trace_metrics, snr_metrics, decide_component)
    from .qa import read_noise_sigma, early_ckpt_thresholds
    from .inference import event_stem

    thresholds = thresholds or early_ckpt_thresholds()
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    comps = list(backend.components)

    rows = []          # (event, sta, comp, snr_syn, snr_sig, amp_ratio, verdict)
    n_events = 0
    # flush per-event so a long run's partial results survive an interruption
    csv_f = open(out_dir / "gate_validation.csv", "w", newline="")
    cw = csv.writer(csv_f)
    cw.writerow(["event", "station", "component", "snr_syn", "snr_sig", "amp_ratio", "verdict"])
    for ev in events:
        if resolve_h5 is None:
            continue
        try:
            h5 = resolve_h5(ev)
        except FileNotFoundError:
            continue
        ref = _fnet_ref_phys(reference_cache, ev.id)
        if ref is None:
            continue
        present = backend.present_stations(h5)
        if len(present) < 3:
            continue
        obs, coords = backend.data_loader.load_event_subset(str(h5), present, stacked=True)
        try:
            syn = backend.forward_synthetic(ref, present,          # reference MT (good synthetic)
                                            source_vec=[float(ev.lat), float(ev.lon),
                                                        float(ev.depth_km)])
        except Exception as e:  # noqa: BLE001
            print(f"  !! {event_stem(ev)} forward failed: {e}")
            continue
        Np, C, T = obs.shape
        traces = [TraceDescriptor(sta, comps[c], float(coords[si, 0]), float(coords[si, 1]))
                  for si, sta in enumerate(present) for c in range(C)]
        obs2d, syn2d = obs.reshape(Np * C, T), syn.reshape(Np * C, T)
        mets = compute_trace_metrics(obs2d, syn2d, traces, float(ev.lat), float(ev.lon), 60)
        sigma_map = read_noise_sigma(h5, present, comps)
        snrs = snr_metrics(obs2d, syn2d, traces, sigma_map)
        snr_by = {(s.station, s.component): s for s in snrs}
        for m in mets:
            s = snr_by.get((m.station, m.component))
            v = decide_component(m, thresholds, snr=s).verdict
            row = (event_stem(ev), m.station, m.component,
                   s.snr_syn if s else np.nan, s.snr_sig if s else np.nan,
                   m.amp_ratio_obs_syn, v)
            rows.append(row)
            cw.writerow(row)
        csv_f.flush()
        n_events += 1
        print(f"  [{n_events}] {event_stem(ev)} M{ev.mag} present={len(present)}", flush=True)
    csv_f.close()

    # per-station drop rate (station-level: dropped if its Z dropped or >=2/3 comps dropped)
    by_ev_sta = defaultdict(dict)
    for ev, sta, comp, *_rest, v in rows:
        by_ev_sta[(ev, sta)][comp] = v
    sta_present = defaultdict(int)
    sta_drop = defaultdict(int)
    from .qa import _MISC_KEY  # noqa
    for (ev, sta), cv in by_ev_sta.items():
        sta_present[sta] += 1
        drops = [c for c, v in cv.items() if v.startswith("drop")]
        if "Z" in [c for c, v in cv.items() if v.startswith("drop")] or len(drops) >= 2:
            sta_drop[sta] += 1
    drate = {s: sta_drop[s] / sta_present[s] for s in sta_present}
    with open(out_dir / "station_drop_rate.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station", "n_events", "n_dropped", "drop_rate"])
        for s in sorted(drate, key=lambda x: -drate[x]):
            w.writerow([s, sta_present[s], sta_drop[s], round(drate[s], 3)])

    _plot(out_dir, rows, drate, sta_present, n_events)
    return {"n_events": n_events, "n_traces": len(rows), "drop_rate": drate}


def _plot(out_dir, rows, drate, sta_present, n_events):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from seismo_sbi.data_quality import VERDICT_COLORS

    fig, ax = plt.subplots(1, 2, figsize=(15, 5.2))
    stas = sorted(drate, key=lambda x: -drate[x])
    ax[0].bar(stas, [drate[s] * 100 for s in stas], color="#1f4e79")
    ax[0].set(ylabel="% of events station-dropped", title=f"Model-free gate drop rate "
              f"({n_events} events, reference-MT synthetic)")
    ax[0].tick_params(axis="x", rotation=90)
    ax[0].axhline(50, color="grey", ls=":", lw=0.8)

    # scatter snr_syn vs snr_sig coloured by verdict (log-log)
    for v in ("keep", "drop-snr-dead", "drop-snr-noisy", "drop-snr-excess",
              "drop-corr", "drop-amp"):
        pts = [(r[3], r[4]) for r in rows if r[6] == v and r[3] > 0]
        if pts:
            xs, ys = zip(*pts)
            ax[1].scatter(xs, np.clip(ys, 1e-2, None), s=10, alpha=0.5,
                          color=VERDICT_COLORS.get(v, "grey"), label=v)
    ax[1].plot([1e0, 1e4], [1e0, 1e4], "k--", lw=0.6, alpha=0.5)  # snr_sig = snr_syn
    ax[1].set(xscale="log", yscale="log", xlabel="snr_syn (predicted, reference MT)",
              ylabel="snr_sig (observed, debiased)", title="Gate decision space")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "gate_validation.png", dpi=130)
    plt.close(fig)
