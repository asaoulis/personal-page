# F-net NPE inference backend

The backend that turns a Japan earthquake into a moment-tensor posterior + the schema-3 record
the `/demo` frontend renders. It reuses the trained `seismo_sbi` NPE and drives it from two
sources: the **pre-built Jan-2026 catalogue** (bulk) and **live F-net events** (query → download
→ infer). Built under task `personal-page/testing-and-inference-prep`.

> **Model status.** The current checkpoint (`ml-checkpoints/japan_v1`, val_loss ≈ −24.85, epoch
> 37 of 100) is a *moderately early* DDP checkpoint. It constrains **magnitude** well but the
> **mechanism** (orientation + source type) is loosely resolved (median Kagan-to-F-net ≈ 78°,
> Mw bias ≈ −0.5). The whole pipeline is built + validated against it; recovery is expected to
> tighten materially with the final checkpoint. Nothing below is checkpoint-specific except the
> reported numbers.

## Modules (all under `worker/fnet_monitor/`)

| Module | Role |
|---|---|
| `npe_backend.py` | **`NpeBackend`** — loads pipeline+posterior+scaler ONCE; `.infer(h5, source_vec, station_names|components_map)` → physical MT samples; `.forward_synthetic(mt6, stations)` → clean fiducial-DB forward model (for QA). Reusable `build_inference_pipeline` (no-sims), `ensure_model_meta` (regenerates a mid-training checkpoint's sidecar), `assemble_model_flow_config` (mirrors `train_NPE.py`). |
| `mt_serialize.py` | **`post_from_cloud`** — MT posterior cloud + references → the schema-3 `post` dict. Shared by mock + real so output is identical. |
| `inference.py` | **`real_posterior`** (was a stub) — lazy `NpeBackend` singleton + `resolve_event_h5` + references + serializer. `real_posterior_from_h5` is the shared core. |
| `qa.py` | Data QA: `qa_event` (intelligent first-guess→QA→re-infer), `qa_event_basic` (obs-only dead guard), `obs_dead_components`, `read_noise_sigma` (`/misc`), threshold presets. |
| `qa_validation.py` | Model-free QA gate validation (forward-model the *reference* MT). |
| `build_real_catalogue.py` | Bulk driver over the Jan catalogue → schema-3 + `EventSolution` dirs + Kagan sanity + `--gallery`. |
| `live_event.py` | Live driver: F-net MT query → `fetch_fnet` download → `build_event_catalogue` → infer. |

Genuinely-reusable QA primitives live in **`seismo_sbi.data_quality`** (`src/`): the SNR metrics
+ gate (`SNRMetrics`, `snr_metrics`, `QAThresholds` SNR fields, `_snr_component_gate`,
`snr_station_drop`). Everything else is here in `worker/`.

## The inference path

```
event h5 (outputs/<STA>/{Z,1,2}, /misc) + source_vec [lat,lon,depth_km]
  -> load_event_subset -> pack_subset_observation (variable-station + conditioning)
  -> posterior.sample -> scaler.inverse_transform -> physical MT (N,6)
  -> post_from_cloud(samples, references) -> schema-3 record (contract.build_event_record)
```

The Japan model is **MT-only (6-D), variable-station, source-location-conditioned** — at inference
it needs the `[lat, lon, depth_km]` source vector (the `ml_conditioning.param_map` order). A
mid-training DDP checkpoint lacks its `model_meta.json` sidecar (written only at `fit()` end);
`ensure_model_meta` regenerates it from the config so the exact tcn+conditioning flow reloads.

## Data QA (calibrated 2026-07 — see the seismo-sbi task's `qa_calibration/FINDINGS.md`)

The "intelligent" QA (`qa_event`) runs inference once, forward-models the **median MT** through
the fiducial DB (location pinned), compares synthetic vs observed per (station, component),
drops bad channels (zero-filled; a station drops only when NO component survives — Z-primacy
collapse retired), and re-infers. **Governing principle:** drop only on *misfit conditional on
expected signal* — an expected-low-signal trace (nodal/distant/small event) is uninformative,
not bad, and is KEPT (the old G2 "below-noise" drop was retired).

- **SNR from the pre-event `/misc` noise floor.** RMS-based, so a pure-noise trace has `snr_obs ≈ 1`;
  the noise-debiased signal SNR is `snr_sig = √max(0, snr_obs²−1)`. obs↔syn are cross-correlation
  **aligned** before windowing (1-D models mis-time arrivals).
- **Gates** (each independently opt-in in `QAThresholds`, all default OFF; presets
  `data_qa_thresholds("minimal"|"full")`): DEAD (`snr_syn≥5 ∧ snr_sig<0.1·snr_syn`, plus the
  unrecognisable branch `<0.25·snr_syn ∧ xc<0.1`), SIGMA-OUTLIER (`σ > 50× network median`, with
  a waveform-match escape hatch), EXCESS (`obs energy > 25×(syn+noise)` — catches interlopers
  and glitches), and in "full" the CONDITIONAL fit gates (`snr_syn≥5 ∧ snr_sig≥2` then
  `xc<0.2` or amp outside `[0.1, 5]`).
- **Blocklist as data:** `data/qa_channel_blocklist.json` (F-net Jan-2026: KSN Z/E/N, YMZ Z,
  KIS E, SBR Z — the last is a *coherent* gain error, xc≈0.7 at 0.1× amplitude). Deployment-
  specific; re-derive with the calibration protocol.
- **Event-level contamination FLAGS (never silent drops):** metric flag
  (`event_contamination`: widespread failure of normally-good expected-signal traces — catches
  interlopers BELOW the catalogue threshold) + `neighbour_window_flag` (catalogue event inside
  the window; also covers pre-window coda that silently blinds the metric gates). On a flagged
  window `contaminated_action="warn"` (default) keeps the data minus channel-health drops —
  the A/B showed mass-dropping makes a contaminated posterior WORSE — and the warning is the
  product: display it.

**A/B (62 events, good checkpoint, after fixing the components_map N/E-swap wiring bug):**
QA is Kagan-neutral on clean events (median 14.2°→14.7°, |ΔMw| slightly better) and the
21-station NPE is intrinsically robust to isolated garbage channels (station-dropout training).
The per-trace QA is *hygiene* + few-station-scenario protection; the contamination flags are
the biggest scientific win. `qa_event_basic` (obs-only dead guard) remains the zero-dependency
fallback. A **`TraceQualityProvider`** seam lets a future posterior-predictive-check (PPC) QA
replace the point-estimate provider with no orchestration change.

## Running it

```bash
cd worker    # env: conda seismo-sbi
# Bulk over the pre-built Jan catalogue -> schema-3 + EventSolution + Santorini gallery
python -m fnet_monitor.build_real_catalogue --out <run> [--qa] [--gallery] [--num-samples 2000]
# Live: F-net MT query -> download -> infer the N biggest recent events
python -m fnet_monitor.live_event --out <run> --days 45 --min-mw 4.0 --max-events 10 [--no-qa]
python -m fnet_monitor.live_event --out <run> --dry-run     # query + plan, download nothing
```

`EventSolution` dirs feed the whole Santorini `lomax_catalogue` gallery unchanged
(`run_diagnostics.py` / `catalogue_map.py` / `posterior_gallery.py`).

## Operational constraints (live path)

- **F-net MT catalogue query** is public (no creds) and fast — the monitoring feed.
- **Waveform download** (`fnet/fetch_fnet.py`) needs NIED creds (`worker/.env`, locked) + the
  `win2sac_32`/`catwin32` tools. It requests **whole UTC days** (per HinetPy), so even a 12-min
  event pulls its full day (~10 min per station-day). Recent dates are also **flaky** (archive
  lag / throttling → intermittent `Error in data status`). A 10-event batch is therefore a
  multi-hour background run, not interactive — run `live_event.py` detached.
- **Amplitude/response:** F-net is processed path-b (win2sac removes the scalar sensitivity →
  ground velocity; integrated to displacement; no full deconvolution — valid in the 15–50 s
  flat-to-velocity band). Events and noise are processed identically; the Instaseis sims are in
  the same metres-of-displacement units. Verified: obs vs fiducial-reference-MT forward model
  gives RMS ≈ 0.6–0.8 (normal 1-D-vs-real misfit, not a gain bug).

## Tests

`conda run -n seismo-sbi python -m pytest worker/tests -q` (offline; injected seams). New:
`test_npe_backend`, `test_mt_serialize`, `test_qa`, `test_live_event`. The reusable SNR gate is
tested in `seismo_sbi` (`tests/unit/test_data_quality_snr.py`) with the golden regressions kept
byte-identical (SNR default-off).
