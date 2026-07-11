"""Intelligent data QA for F-net NPE inference: first-guess → SNR/amplitude QA → re-infer.

Orchestration lives here (application-specific); the REUSABLE, unit-tested primitives are in
`seismo_sbi.data_quality` (metrics + SNR gates + policy). The loop, per Fable's design:

  1. infer on ALL present stations (no QA)  -> first-guess median MT
  2. forward-model that median through the fiducial 1-D DB (clean, nuisances off)
  3. per (station,component): classical fit metrics + pre-event-noise SNR metrics
  4. component + station verdicts (SNR gates run FIRST); build a components map
  5. keep-floor: if too few stations survive, RANK-FILL by observed signal SNR (never
     revert-all — that re-injects the pure-noise traces the gate just removed)
  6. re-infer on the cleaned components map (zero-filled dropped channels)

The trace-quality step is behind a `TraceQualityProvider` seam: the default point-forward
provider is one fiducial forward model of the median MT; a future PPC provider forwards many
posterior draws and returns predictive metrics, with NO change to the orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

# Trace component (Z/E/N, receiver order) -> h5 /misc key (Z/1/2, the E->1 N->2 rename).
_MISC_KEY = {"Z": "Z", "E": "1", "N": "2", "1": "1", "2": "2"}


def data_qa_thresholds(level: str = "minimal", **overrides):
    """CALIBRATED QA presets (2026-07, 62-event pe60 catalogue vs F-net reference-MT
    forward models; evidence in the seismo-sbi task's ``qa_calibration/FINDINGS.md``).

    Every gate encodes *misfit conditional on expected signal* — an expected-low-signal
    trace (nodal / distant / small event) is always KEPT. Levels:

    * ``"minimal"`` — the ESSENTIAL gates only (each catches a distinct, eyeball-confirmed
      failure mode that no other gate sees):
        DEAD (signal predicted >=5 sigma, observed <10% of it, or <25% with xcorr<0.1),
        SIGMA-OUTLIER (pre-event sigma >50x network median: broken channel, e.g. YMZ Z),
        EXCESS (obs energy >25x the signal+noise budget: glitches / interloper events).
      Classical fit gates are neutralised.
    * ``"full"`` — minimal + the CONDITIONAL FIT gates: where signal is clearly expected
      (snr_syn>=5) AND observed (snr_sig>=2), drop if best-lag xcorr<0.2 or the amplitude
      ratio leaves [0.1, 5] (catches coherent gain errors like SBR Z at ~0.1x). ~1% extra
      drops on the clean population.
    """
    from seismo_sbi.data_quality import QAThresholds
    kw = dict(enable_snr_gates=True, snr_dead_ratio=0.1, snr_dead_min_syn=5.0,
              snr_dead_unrecog_ratio=0.25, xcorr_dead=0.1,
              sigma_rel_max=50.0,
              enable_snr_excess=True, snr_excess_factor=5.0,
              # classical station-level gates neutralised (per-component QA only)
              xcorr_drop=0.0, amp_hi=1e12, amp_lo=0.0, enable_ppc_drops=False)
    if level == "full":
        kw.update(conditional_fit_gates=True, snr_fit_min_syn=5.0, snr_fit_sig_min=2.0,
                  xcorr_drop=0.2, amp_lo=0.1, amp_hi=5.0)
    elif level != "minimal":
        raise ValueError(f"unknown QA preset level: {level!r}")
    kw.update(overrides)
    return QAThresholds(**kw)


def early_ckpt_thresholds(**overrides):
    """DEPRECATED — use :func:`data_qa_thresholds`. Kept for compatibility; note the old
    G2 'below-noise' drop was retired in seismo_sbi.data_quality (expected-low-signal
    traces are kept), so this preset now applies the dead gate only."""
    from seismo_sbi.data_quality import QAThresholds
    kw = dict(enable_snr_gates=True, snr_syn_min=2.0, snr_dead_ratio=0.1, snr_dead_min_syn=5.0,
              enable_snr_excess=False, xcorr_drop=0.0, amp_hi=1e12, amp_lo=0.0,
              enable_ppc_drops=False)
    kw.update(overrides)
    return QAThresholds(**kw)


def mature_ckpt_thresholds(**overrides):
    """DEPRECATED — use :func:`data_qa_thresholds("full")`."""
    from seismo_sbi.data_quality import QAThresholds
    kw = dict(enable_snr_gates=True, amp_hi=3.0, enable_snr_excess=True)
    kw.update(overrides)
    return QAThresholds(**kw)


def load_channel_blocklist(path=None):
    """Persistent-bad-channel blocklist -> ``{(station, component), ...}``.

    DATA, not code: ``data/qa_channel_blocklist.json`` next to the package, derived from
    the 2026-07 62-event calibration and DEPLOYMENT-SPECIFIC (F-net, Jan-2026 channel
    states) — re-derive it per network/period with the calibration protocol. Channels here
    are dropped up-front (verdict ``"drop-blocklist"``) before any gate runs. Missing /
    unreadable file -> empty set.
    """
    import json
    from pathlib import Path
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "data" / "qa_channel_blocklist.json"
    try:
        doc = json.loads(p.read_text())
        return {(str(e[0]), str(e[1])) for e in doc.get("channels", [])}
    except (OSError, ValueError):
        return set()


def neighbour_window_flag(origin_time, duration_s, catalogue_times, pre_s=120.0):
    """Catalogue-neighbour contamination check (a FLAG, never a silent drop).

    Another catalogue event with origin inside ``[origin - pre_s, origin + duration_s]``
    puts its wavetrain (or, before the origin, its coda) into this event's window — the
    two confirmed cases in the Jan-2026 calibration had neighbours 98 s and 152 s away,
    and pre-window coda also corrupts the noise-sigma estimates (making the metric-based
    gates silently blind), which is why this check is essential even with the metric flag.
    ``catalogue_times``: iterable of datetimes of OTHER events. Returns
    ``{"neighbour_in_window": bool, "nearest_neighbour_s": float}``.
    """
    best = float("inf")
    for t in catalogue_times:
        dt = (t - origin_time).total_seconds()
        if abs(dt) < 1e-6:
            continue
        if abs(dt) < abs(best):
            best = dt
    return {"neighbour_in_window": bool(best != float("inf") and -pre_s <= best <= duration_s),
            "nearest_neighbour_s": best}


def read_noise_sigma(event_h5, stations, components) -> Dict[Tuple[str, str], float]:
    """Pre-event noise std sigma per (station, component) from the h5 `/misc` group.

    `/misc/<sta>/<Z|1|2>` is the pre-event autocorrelation; lag-0 = pre-event mean(x^2) = sigma^2
    (see `sbi_export.py`). Returns sigma = sqrt(that). Missing/degenerate entries are omitted
    (the SNR gate then treats them as dead channels).
    """
    import h5py
    out: Dict[Tuple[str, str], float] = {}
    with h5py.File(event_h5, "r") as f:
        misc = f.get("misc")
        if misc is None:
            return out
        for sta in stations:
            g = misc.get(sta)
            if g is None:
                continue
            for comp in components:
                ds = g.get(_MISC_KEY.get(comp, comp))
                if ds is None:
                    continue
                arr = np.asarray(ds)
                var = float(arr.flat[0]) if arr.size else float("nan")  # lag-0
                if np.isfinite(var) and var > 0:
                    out[(sta, comp)] = float(np.sqrt(var))
    return out


def obs_dead_components(obs, present, components, *, rel_floor=0.02, abs_floor=1e-12):
    """Model-INDEPENDENT dead-channel detection from the observation alone.

    A channel is dead if its event-window RMS is < ``abs_floor`` (flatline / dead sensor) OR
    < ``rel_floor`` * the per-component MEDIAN RMS across present stations (a gross amplitude
    outlier reading ~0 while its peers see the event). Needs no synthetic, so unlike the
    SNR/fit gates it is robust to model quality — the reliable "obviously broken" basic QA.
    Returns ``{(station, component): 'drop-dead'}``.
    """
    obs = np.asarray(obs)                       # (Np, C, T)
    Np, C, _ = obs.shape
    rms = np.sqrt(np.mean(obs ** 2, axis=2))    # (Np, C)
    dead = {}
    for c in range(C):
        col = rms[:, c]
        pos = col[col > 0]
        med = float(np.median(pos)) if pos.size else 0.0
        for si in range(Np):
            if col[si] < abs_floor or (med > 0 and col[si] < rel_floor * med):
                dead[(present[si], components[c])] = "drop-dead"
    return dead


@dataclass
class TraceQuality:
    """Per-event trace-quality bundle handed to the policy. `snr` is optional (PPC providers
    may instead fill `predictive`)."""
    metrics: list                       # List[TraceMetrics]
    snr: Optional[list] = None          # List[SNRMetrics]
    traces: list = field(default_factory=list)
    obs2d: Optional[np.ndarray] = None
    syn2d: Optional[np.ndarray] = None


def point_forward_provider(backend, event_h5, source_vec, present, first_guess_mt6, *,
                           max_lag=60) -> TraceQuality:
    """Default provider: ONE fiducial forward model of the median MT + classical & SNR metrics."""
    from seismo_sbi.data_quality import (
        TraceDescriptor, compute_trace_metrics, snr_metrics)

    obs, coords = backend.data_loader.load_event_subset(str(event_h5), present, stacked=True)
    # PIN the source location (bug fix): an unpinned forward model samples a random prior
    # location -> wrong moveout -> meaningless obs-vs-syn comparison.
    syn = backend.forward_synthetic(first_guess_mt6, present, source_vec=source_vec)  # (Np, C, T)
    comps = list(backend.components)
    Np, C, T = obs.shape
    traces = [TraceDescriptor(sta, comps[c], float(coords[si, 0]), float(coords[si, 1]))
              for si, sta in enumerate(present) for c in range(C)]
    obs2d, syn2d = obs.reshape(Np * C, T), syn.reshape(Np * C, T)
    lat = float(source_vec[0]); lon = float(source_vec[1])
    metrics = compute_trace_metrics(obs2d, syn2d, traces, lat, lon, max_lag)
    sigma_map = read_noise_sigma(event_h5, present, comps)
    snr = snr_metrics(obs2d, syn2d, traces, sigma_map)
    return TraceQuality(metrics=metrics, snr=snr, traces=traces, obs2d=obs2d, syn2d=syn2d)


@dataclass
class QAResult:
    samples_noqa: np.ndarray
    samples_qa: np.ndarray
    components_map: Dict[str, List[str]]     # station -> kept components (post-QA)
    kept_stations: List[str]
    dropped: Dict[str, str]                  # station -> most-severe drop verdict
    changed: bool
    scorecard: str
    component_drops: Dict[Tuple[str, str], str] = field(default_factory=dict)
    event_flags: Dict[str, float] = field(default_factory=dict)


def qa_event(backend, event_h5, source_vec, present: List[str], *,
             thresholds, samples_noqa: Optional[np.ndarray] = None,
             num_samples: int = 2000, min_stations: int = 5, min_fraction: float = 0.25,
             provider: Callable = point_forward_provider,
             blocklist=(), origin_time=None, catalogue_times=None,
             window_duration_s: float = 800.0,
             contaminated_action: str = "warn") -> QAResult:
    """Run the first-guess → QA → re-infer loop for one event. Returns a :class:`QAResult`.

    Per-COMPONENT policy (2026-07 calibration): dropped channels are zero-filled
    individually and a station is dropped only when NO component survives — Z-primacy
    station collapse was retired (YMZ's horizontals stayed healthy for weeks of broken Z).

    ``blocklist``: ``{(station, component), ...}`` dropped up-front (see
    :func:`load_channel_blocklist`). ``origin_time`` + ``catalogue_times`` (datetimes of
    other catalogue events) arm the neighbour-contamination FLAG; the metric-based
    :func:`seismo_sbi.data_quality.event_contamination` flag is always computed. Flags are
    reported in ``event_flags`` — they never silently drop the event.

    ``contaminated_action`` (A/B-calibrated, 2026-07): on a metric-flagged contaminated
    window the fit/excess gates fire on MOST normally-good traces, and mass-dropping them
    made the posterior WORSE than keeping the data (Kagan 4->30 and 16->37 on the two worst
    interlopers — the noise-robust NPE averages an interloper better than a gutted network
    resolves anything). ``"warn"`` (default) therefore keeps every channel except the
    channel-HEALTH drops (blocklist / sigma-outlier / dead / obs-dead) and relies on the
    warning; ``"drop"`` applies all gates as usual. EITHER way the posterior of a flagged
    event is untrustworthy — the flag itself is the product; display it.
    """
    from seismo_sbi.data_quality import (
        component_verdicts, sigma_outlier_verdicts, event_contamination, ComponentVerdict)

    comps = list(backend.components)
    if samples_noqa is None:
        samples_noqa, _ = backend.infer(event_h5, source_vec, station_names=present,
                                        num_samples=num_samples)
    first_guess = np.median(np.asarray(samples_noqa), axis=0)

    tq = provider(backend, event_h5, source_vec, present, first_guess)
    cv = component_verdicts(tq.metrics, thresholds, snr_metrics=tq.snr)
    # model-free sigma-outlier channel health (needs the cross-station context, so it is
    # applied here rather than inside the per-trace gate)
    for (sta, comp), verdict in sigma_outlier_verdicts(
            tq.snr or [], thresholds, metrics=tq.metrics).items():
        old = cv.get(sta, {}).get(comp)
        if old is not None and old.is_kept:
            cv[sta][comp] = ComponentVerdict(sta, comp, verdict,
                                             old.max_xcorr, old.amp_ratio_obs_syn)
    # persistent-bad-channel blocklist (deployment data, not a gate)
    for (sta, comp) in blocklist:
        old = cv.get(sta, {}).get(comp)
        if old is not None:
            cv[sta][comp] = ComponentVerdict(sta, comp, "drop-blocklist",
                                             old.max_xcorr, old.amp_ratio_obs_syn)

    # model-INDEPENDENT dead-channel guard (basic QA, robust to a bad first guess): drop
    # channels reading ~0 vs their peers. Runs regardless of the synthetic-comparison gates.
    if tq.obs2d is not None:
        obs3d = np.asarray(tq.obs2d).reshape(len(present), len(comps), -1)
        for (sta, comp) in obs_dead_components(obs3d, present, comps):
            old = cv.get(sta, {}).get(comp)
            if old is not None and old.is_kept:
                cv[sta][comp] = ComponentVerdict(sta, comp, "drop-dead",
                                                 old.max_xcorr, old.amp_ratio_obs_syn)

    # per-component collapse: keep surviving channels; a station drops only when none survive
    component_drops = {(s, c): v.verdict for s, d in cv.items()
                       for c, v in d.items() if v.is_dropped}
    comp_map: Dict[str, List[str]] = {}
    dropped: Dict[str, str] = {}
    for sta in present:
        kept_c = [c for c in comps if cv.get(sta, {}).get(c) is not None
                  and cv[sta][c].is_kept]
        if kept_c:
            comp_map[sta] = kept_c
        else:
            vs = [cv[sta][c].verdict for c in comps if c in cv.get(sta, {})]
            dropped[sta] = vs[0] if vs else "drop"

    # event-level contamination diagnostics (FLAGS, never silent drops)
    event_flags = event_contamination(tq.metrics, tq.snr or [], cv, exclude=tuple(blocklist))
    if event_flags.get("contaminated") and contaminated_action == "warn":
        # A/B-calibrated: mass-dropping a contaminated window's traces makes the posterior
        # WORSE (Kagan 4->30, 16->53 on the interloper windows), and even the sigma-BASED
        # health gates are untrustworthy there (a neighbour's coda corrupts the pre-event
        # sigma non-uniformly). Keep everything except the sigma-INDEPENDENT drops
        # (blocklist + obs-only dead channels); the warning is the output.
        keep_drops = {k: v for k, v in component_drops.items() if v == "drop-blocklist"}
        if tq.obs2d is not None:
            obs3d = np.asarray(tq.obs2d).reshape(len(present), len(comps), -1)
            for (sta, comp) in obs_dead_components(obs3d, present, comps):
                keep_drops.setdefault((sta, comp), "drop-dead")
        component_drops = keep_drops
        comp_map, dropped = {}, {}
        for sta in present:
            kept_c = [c for c in comps if (sta, c) not in component_drops]
            if kept_c:
                comp_map[sta] = kept_c
            else:
                dropped[sta] = component_drops.get((sta, comps[0]), "drop")
    if origin_time is not None and catalogue_times is not None:
        nb = neighbour_window_flag(origin_time, window_duration_s, catalogue_times)
        event_flags["neighbour_in_window"] = float(nb["neighbour_in_window"])
        event_flags["nearest_neighbour_s"] = nb["nearest_neighbour_s"]

    # keep-floor: RANK-FILL by observed debiased signal SNR (not revert-all).
    floor = max(min_stations, int(np.ceil(min_fraction * len(present))))
    if len(comp_map) < floor:
        snr_by_sta = {}
        for s in (tq.snr or []):
            snr_by_sta.setdefault(s.station, []).append(s.snr_sig)
        rank = sorted(present, key=lambda st: -max(snr_by_sta.get(st, [0.0])))
        block = set(blocklist)
        for st in rank:
            if len(comp_map) >= floor:
                break
            if st not in comp_map:
                restore = [c for c in comps if (st, c) not in block]   # never un-blocklist
                if restore:
                    comp_map[st] = restore
                    dropped.pop(st, None)

    kept = sorted(comp_map.keys())
    changed = not (set(kept) == set(present)
                   and all(len(comp_map[s]) == len(comps) for s in kept))
    if changed and len(kept) > 0:
        samples_qa, _ = backend.infer(event_h5, source_vec, components_map=comp_map,
                                      num_samples=num_samples)
    else:
        samples_qa = samples_noqa

    scorecard = _scorecard(present, comp_map, dropped, tq, thresholds)
    if event_flags.get("contaminated"):
        scorecard += ("\n# WARNING: event-level contamination flag "
                      f"(frac_expected_dropped={event_flags['frac_expected_dropped']:.2f}, "
                      f"median_xcorr={event_flags['median_xcorr_expected']:.2f})")
    if event_flags.get("neighbour_in_window"):
        scorecard += ("\n# WARNING: catalogue neighbour inside the window "
                      f"({event_flags['nearest_neighbour_s']:+.0f} s)")
    return QAResult(np.asarray(samples_noqa), np.asarray(samples_qa), comp_map, kept,
                    dropped, changed, scorecard,
                    component_drops=component_drops, event_flags=event_flags)


def qa_event_basic(backend, event_h5, source_vec, present: List[str], *,
                   samples_noqa: Optional[np.ndarray] = None, num_samples: int = 2000) -> QAResult:
    """Model-INDEPENDENT QA: drop only obs-only dead/flatlined channels, then re-infer.

    No forward model, no threshold tuning — the safe early-checkpoint default. Robustly removes
    genuinely broken stations (e.g. a flatlined sensor) without the synthetic-comparison gates'
    dependence on a well-calibrated model. The full intelligent QA (:func:`qa_event`) becomes the
    default once the checkpoint is good.
    """
    comps = list(backend.components)
    if samples_noqa is None:
        samples_noqa, _ = backend.infer(event_h5, source_vec, station_names=present,
                                        num_samples=num_samples)
    obs, _coords = backend.data_loader.load_event_subset(str(event_h5), present, stacked=True)
    dead = obs_dead_components(obs, present, comps)
    comp_map = {s: list(comps) for s in present}
    dropped: Dict[str, str] = {}
    for (sta, comp) in dead:
        comp_map[sta] = [c for c in comp_map[sta] if c != comp]
        if comp == "Z" or not comp_map[sta]:
            comp_map[sta] = []
            dropped[sta] = "drop-dead"
    comp_map = {s: c for s, c in comp_map.items() if c}
    kept = sorted(comp_map)
    changed = not (set(kept) == set(present)
                   and all(len(comp_map[s]) == len(comps) for s in kept))
    if changed and kept:
        samples_qa, _ = backend.infer(event_h5, source_vec, components_map=comp_map,
                                      num_samples=num_samples)
    else:
        samples_qa = samples_noqa
    sc = (f"# basic obs-only QA: present={len(present)} kept={len(kept)} "
          f"dropped={list(dropped)}")
    return QAResult(np.asarray(samples_noqa), np.asarray(samples_qa), comp_map, kept,
                    dropped, changed, sc)


def _scorecard(present, comp_map, dropped, tq, thresholds) -> str:
    lines = [f"# QA scorecard  (enable_snr_gates={thresholds.enable_snr_gates}, "
             f"amp_hi={thresholds.amp_hi})",
             f"# present={len(present)} kept={len(comp_map)} "
             f"dropped={len(present) - len(comp_map)}"]
    snr_by = {(s.station, s.component): s for s in (tq.snr or [])}
    for sta in present:
        ch = comp_map.get(sta, [])
        tag = "KEEP" if ch else f"DROP({dropped.get(sta, '?')})"
        z = snr_by.get((sta, "Z"))
        snr_s = f" snr_syn={z.snr_syn:.1f} snr_sig={z.snr_sig:.1f}" if z else ""
        lines.append(f"  {sta:5s} {tag:22s} comps={ch}{snr_s}")
    return "\n".join(lines)
