"""NpeBackend — load the trained seismo_sbi Japan F-net NPE once, infer MT posteriors per event.

This is the real inference engine behind `inference.real_posterior` and the catalogue driver.
It reuses the `seismo_sbi.evaluation` machinery but avoids the two live-inference pitfalls
proven out in the task's Phase-A smoke:

  1. **No-sims light pipeline.** `evaluation.build_eval_pipeline` regenerates the FULL training
     `random_events` set when no sims are on disk — catastrophic on a serving box. We build a
     light pipeline (parse -> SingleEventPipeline -> load_seismo_parameters -> set trace_length
     from a real event h5) that never simulates.
  2. **Sidecar regeneration.** A DDP checkpoint only gets its `model_meta.json` at `trainer.fit()`
     END, so a mid-training checkpoint lacks it and `build_ml_posterior` would rebuild the WRONG
     (default seismogram_transformer) architecture. We regenerate the sidecar from the config
     (mirrors `train_NPE.py`) so the exact tcn+conditioning+variable-station flow reloads.

The Japan model is variable-station + source-location-conditioned (MT-only, 6-D): at inference
it needs the `[lat, lon, depth_km]` source vector per event (the `ml_conditioning.param_map`
order) alongside the station subset.  Amplitude/response caveats are handled upstream in the
data pipeline; here we only ingest the SBI h5 the catalogue builder wrote.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Config-driven model width (matches train_NPE.py `model_dim = 256`).
MODEL_DIM = 256

# Minimum stations that must survive the ragged-trace guard for a variable-station inference to
# be attempted; below this we raise so the monitor's normal retry path handles the event.
MIN_USABLE_STATIONS = 3


def expected_trace_length(raw_cfg: dict) -> int:
    """The per-component data-vector length the SBI h5 builder writes, from the config.

    Mirrors `data_handling.preprocessing`: `compute_data_vector_length(duration, sr) + 1`
    (inclusive slice), e.g. 800 s @ 1 Hz -> 801 samples.  This is the length every station's
    trace MUST have; a station whose traces differ is a ragged-trace F-net data defect."""
    from seismo_sbi.instaseis_simulator.utils import compute_data_vector_length

    sc = (raw_cfg or {}).get("seismic_context", {}) or {}
    dur = float(sc.get("seismogram_duration", 800))
    sr = float(sc.get("sampling_rate", 1.0))
    return compute_data_vector_length(dur, sr) + 1


def filter_ragged_stations(present, lengths_by_station, expected):
    """Split `present` into (usable, dropped) by per-station trace length.

    A station is USABLE iff it has at least one component trace and EVERY component trace is
    exactly `expected` samples long; otherwise it is dropped (a ragged-trace data defect that
    would otherwise break the variable-station context packing).  Order-preserving."""
    usable, dropped = [], []
    for s in present:
        comp_lens = list(lengths_by_station.get(s, []) or [])
        if comp_lens and all(int(L) == int(expected) for L in comp_lens):
            usable.append(s)
        else:
            dropped.append(s)
    return usable, dropped


# --------------------------------------------------------------------------------------
# config -> model_config / flow_config assembly. Mirrors scripts/train_NPE.py:156-368 so
# the reconstructed flow matches the trained one EXACTLY. (Source of truth = train_NPE.py;
# kept in sync deliberately — the reconstruction is validated by every checkpoint that loads
# with no shape mismatch.)
# --------------------------------------------------------------------------------------
def assemble_model_flow_config(raw_cfg: dict, model_dim: int = MODEL_DIM,
                               arch_override: Optional[str] = None):
    architecture = arch_override or raw_cfg.get("ml_architecture") or "cnn"
    model_config: dict = {"station_encoder": architecture}

    enc = raw_cfg.get("ml_encoder")
    if enc:
        enc = {k: v for k, v in enc.items() if k != "enabled"}
        dec = enc.pop("input_decimate", None)
        if dec:
            model_config["input_decimate"] = (
                dict(dec) if isinstance(dec, dict) else {"factor": int(dec)})
        if enc:
            model_config["encoder_config"] = enc

    cond = raw_cfg.get("ml_conditioning")
    if cond:
        cpm = cond["param_map"]
        model_config["conditioning"] = {
            "n_cond": cond.get("n_cond", sum(len(v) for v in cpm.values())),
            "d_cond": cond.get("d_cond", model_dim),
            "coord_mode": cond.get("coord_mode", "geographic"),
            "inject": cond.get("inject", []),
            "n_fourier": cond.get("n_fourier", 0),
        }

    var = raw_cfg.get("ml_variable_stations")
    if var and var.get("enabled", False):
        model_config["variable_stations"] = True
        model_config["station_coords_mode"] = var.get("station_coords_mode", "absolute")

    amp = raw_cfg.get("ml_amplitude_embedding")
    if amp and amp.get("enabled", False):
        model_config["amplitude_embedding"] = {k: v for k, v in amp.items() if k != "enabled"}

    pe = raw_cfg.get("ml_positional_encoding")
    if pe and pe.get("enabled", False):
        model_config["positional_encoding"] = {k: v for k, v in pe.items() if k != "enabled"}

    pool = raw_cfg.get("ml_pooling")
    if pool and pool.get("enabled", False):
        model_config["pma_pooling"] = {k: v for k, v in pool.items() if k != "enabled"}

    flow_config = None
    fc = raw_cfg.get("ml_flow")
    if fc:
        flow_config = {k: v for k, v in fc.items() if k != "enabled"}

    perf = raw_cfg.get("ml_perf") or {}
    if perf:
        model_config["perf"] = {k: v for k, v in perf.items() if k != "enabled"}

    opt = raw_cfg.get("ml_optimizer") or {}
    lr = float(opt.get("lr", 1e-4))
    weight_decay = float(opt.get("weight_decay", 1e-4))
    lr_second_stage = opt.get("lr_schedule", "cosine")
    return architecture, model_config, flow_config, lr, weight_decay, lr_second_stage


def build_inference_pipeline(config_path):
    """A no-sims pipeline sufficient for variable-station ML inference on a real event.

    Mirrors the first steps of `evaluation.build_eval_pipeline` but SKIPS sim generation,
    compressors and test noises (none are needed to sample the ML posterior on a real event) —
    so it never triggers a local dataset regeneration. Returns (config, pipeline, raw_cfg).
    """
    import yaml
    from seismo_sbi.sbi.configuration import SBI_Configuration
    from seismo_sbi.sbi.pipeline import SingleEventPipeline

    config = SBI_Configuration()
    config.parse_config_file(str(config_path))
    pipe = SingleEventPipeline(config.pipeline_parameters, str(config_path))
    pipe.compression_methods = config.compression_methods
    pipe.load_seismo_parameters(config.sim_parameters, config.model_parameters,
                                config.dataset_parameters)
    pipe._default_receiver_time_shifts = dict(
        pipe.simulation_parameters.receivers.receiver_time_shifts_map)
    # trace_length WITHOUT sims: compute_data_vector_properties reads the first
    # jobs.real_events h5 when test_jobs_paths is empty.
    if config.real_event_jobs:
        pipe.compute_data_vector_properties([], config.real_event_jobs)
    raw_cfg = yaml.safe_load(open(config_path)) or {}
    return config, pipe, raw_cfg


def ensure_model_meta(ckpt_dir, pipe, raw_cfg) -> Path:
    """Regenerate `model_meta.json` in `ckpt_dir` if absent (mid-training DDP checkpoint).

    Reconstructs the exact CompressionTrainer the config specifies and dumps the same 10-field
    sidecar `train.py` writes at fit-end, so `build_ml_posterior` reloads the correct flow.
    Idempotent — a no-op when the sidecar already exists.
    """
    ckpt_dir = Path(ckpt_dir)
    meta_path = ckpt_dir / "model_meta.json"
    if meta_path.exists():
        return meta_path
    from seismo_sbi.sbi.compression.ML.train import CompressionTrainer

    components = pipe.data_manager.data_loader.components
    station_locations = pipe.simulation_parameters.receivers.get_station_locations_array()
    _, model_config, flow_config, lr, wd, lrs = assemble_model_flow_config(raw_cfg)
    t = CompressionTrainer(components, station_locations, channels=MODEL_DIM, latent_dim=MODEL_DIM,
                           trace_length=pipe.trace_length, model_config=model_config,
                           flow_config=flow_config, lr=lr, weight_decay=wd, lr_second_stage=lrs)
    meta = {
        "architecture": t.architecture,
        "model_config": t._model_config,
        "flow_config": t._flow_config,
        "trace_length": t.trace_length,
        "num_seismic_components": t.num_seismic_components,
        "num_dims": t.num_dims,
        "latent_dim": t.latent_dim,
        "feature_length": t._feature_length,
        "station_locations_shape": t._station_locations_shape,
        "station_locations": np.asarray(t._station_locations).tolist(),
    }
    meta_path.write_text(json.dumps(meta, indent=2, default=str))
    return meta_path


class NpeBackend:
    """Trained Japan F-net NPE, loaded ONCE. `infer()` -> physical MT posterior samples.

    Parameters
    ----------
    config_path : the training YAML (fnet japan config).
    ckpt_dir : a directory resolvable by `resolve_ckpt_dir` (holds/【will get】 model_meta.json +
        checkpoints/best_model-*.ckpt).
    device : torch device string; defaults to cuda if available.
    num_samples : default posterior samples per inference call.
    """

    def __init__(self, config_path, ckpt_dir, *, device: Optional[str] = None,
                 num_samples: int = 2000):
        for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            os.environ.setdefault(v, "1")
        import torch
        from seismo_sbi.evaluation.inference import resolve_ckpt_dir, build_ml_posterior
        from seismo_sbi.sbi.scalers import build_flexible_scaler

        self.config_path = str(config_path)
        self.num_samples = num_samples
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.config, self.pipe, self.raw_cfg = build_inference_pipeline(config_path)
        self.ckpt_dir = resolve_ckpt_dir(ckpt_dir)
        ensure_model_meta(self.ckpt_dir, self.pipe, self.raw_cfg)
        self.posterior = build_ml_posterior(self.ckpt_dir, self.pipe, dim=MODEL_DIM)
        self.scaler = build_flexible_scaler(self.pipe.parameters, self.config.raw_config)

        self.data_loader = self.pipe.data_manager.data_loader
        # Per-ROW component order of every (N, C, T) array this backend produces or loads.
        # This is the RECEIVER master component order (station_components_path json, e.g.
        # Z,E,N) — the order convert_sim_data_to_array reads channels in — NOT the
        # dataloader's `components` string (config seismic_context.components, e.g. 'ZNE').
        # [Fixed 2026-07: using the config string mislabelled every horizontal row (E<->N)
        # and cross-paired each horizontal with its sibling's noise sigma in the QA gates.]
        receivers = list(self.pipe.simulation_parameters.receivers.iterate())
        self.components = list(receivers[0].components) if receivers \
            else list(self.data_loader.components)
        self.master_stations = [r.station_name for r in receivers]

    # -- helpers ---------------------------------------------------------------
    def present_stations(self, event_h5) -> List[str]:
        """Master stations with an `outputs` group in this event h5 AND well-formed traces.

        Applies the ragged-trace guard: a station whose component traces are not all exactly
        `expected_trace_length(raw_cfg)` samples (a known F-net data defect that breaks the
        variable-station context packing) is DROPPED (logged), and the rest proceed.  If fewer
        than `MIN_USABLE_STATIONS` survive, raises so the monitor's retry path handles the event.
        """
        import h5py
        expected = expected_trace_length(self.raw_cfg)
        lengths: Dict[str, List[int]] = {}
        with h5py.File(event_h5, "r") as f:
            outputs = f["outputs"]
            present = [s for s in self.master_stations if s in outputs]
            for s in present:
                grp = outputs[s]
                # read every component dataset's length (disk keys are Z/1/2; membership only).
                lengths[s] = [int(grp[c].shape[0]) for c in grp.keys()]
        usable, dropped = filter_ragged_stations(present, lengths, expected)
        for s in dropped:
            print(f"[ragged-guard] {Path(event_h5).name}: dropping station {s} — trace lengths "
                  f"{lengths.get(s)} != expected {expected}.", flush=True)
        if len(usable) < MIN_USABLE_STATIONS:
            raise ValueError(
                f"only {len(usable)} usable stations after dropping {len(dropped)} ragged "
                f"(present={len(present)}, expected trace length {expected}); "
                f"need >= {MIN_USABLE_STATIONS}.")
        return usable

    # -- inference -------------------------------------------------------------
    def infer(self, event_h5, source_vec, *, station_names: Optional[Sequence[str]] = None,
              components_map: Optional[Dict[str, List[str]]] = None,
              num_samples: Optional[int] = None) -> Tuple[np.ndarray, List[str]]:
        """Sample the MT posterior for one event.

        Returns ``(samples (n,6) physical N·m, used_stations)``.

        * ``station_names`` (default = all present): full-component station subset.
        * ``components_map`` (QA path): ``{station: [kept components] | []}`` — dropped components
          are zero-filled (mirrors training's component dropout); overrides ``station_names``.
        * ``source_vec``: ``[lat, lon, depth_km]`` (ml_conditioning.param_map order).
        """
        import torch
        from seismo_sbi.sbi.compression.ML.source_conditioning import pack_subset_observation
        from seismo_sbi.sbi.compression.ML.station_dropout import robust_posterior_sample

        n = num_samples or self.num_samples
        if components_map is not None:
            obs, coords, used = self.data_loader.load_event_subset_with_components(
                str(event_h5), components_map, stacked=True)
        else:
            used = list(station_names) if station_names is not None \
                else self.present_stations(event_h5)
            obs, coords = self.data_loader.load_event_subset(str(event_h5), used, stacked=True)

        sv = None if source_vec is None else np.asarray(source_vec, float)
        ctx = pack_subset_observation(obs, coords, source_vec=sv).to(self.device)  # (1, W)
        samples = robust_posterior_sample(self.posterior, ctx, n)
        phys = self.scaler.inverse_transform(np.asarray(samples.cpu().numpy()))  # (n, 6)
        return np.asarray(phys, float).reshape(-1, 6), used

    def forward_synthetic(self, mt6, station_names: Sequence[str], source_vec=None,
                          stf_scale: float = 1.0) -> np.ndarray:
        """Clean fiducial forward model of one MT (nuisances OFF) restricted to `station_names`.

        ``source_vec = [lat, lon, depth_km]`` PINS the source location (and ``stf_scale`` the STF
        duration), overriding the random prior draws. This is REQUIRED for a meaningful
        synthetic-vs-obs comparison: without it the simulator samples ``source_location`` from the
        catalogue-KDE prior (hundreds of km off, different every call) so the moveout is wrong.
        ``source_vec=None`` keeps the legacy random-draw behaviour.

        Returns ``(N, C, T)``. Requires the local fiducial Instaseis DB.
        """
        receivers = self.pipe.simulation_parameters.receivers
        saved = receivers.receivers
        sim = self.pipe.simulator_wrapper.simulator
        saved_effects = sim.post_processing_chain.effects
        try:
            keep = set(station_names)
            receivers.receivers = [r for r in saved if r.station_name in keep]
            sim.post_processing_chain.effects = []
            # input_output_simulation merges **kwargs LAST, so these override the sampled nuisances.
            kw = {"use_fiducial": True}
            if source_vec is not None:
                sv = np.asarray(source_vec, float)
                kw["source_location"] = np.array([sv[0], sv[1], sv[2], 0.0])
                kw["stf_duration"] = np.array([float(stf_scale)])
            flat = np.asarray(self.pipe.simulator_wrapper.simulation_callable(
                np.asarray(mt6, float), **kw)).flatten()
            n = len(receivers.receivers)
        finally:
            receivers.receivers = saved
            sim.post_processing_chain.effects = saved_effects
        return flat.reshape(n, len(self.components), -1)
