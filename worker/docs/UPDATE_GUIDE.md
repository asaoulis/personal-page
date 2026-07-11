# Live F-net NPE demo — pipeline map + update guide

Audience: future maintainers (human or agent) changing the live earthquake demo. This is the
"where do I poke it" document; the deep architecture reference is `LIVE_MONITOR.md` (state
machine, tick semantics) and `INFERENCE_BACKEND.md` (NPE internals). Paths are relative to the
personal-page repo root unless noted. The shared science library is the SEPARATE repo
`seismo-sbi` (installed in CI at a pinned rev — see §5).

## 1. The two ingestion streams and the publish chain

```
 STREAM A: F-net MT catalogue (authoritative, days–weeks late)
 ────────────────────────────────────────────────────────────
  NIED F-net MT search (public HTTP)
        │  fnet_mt.query_fnet_mt_catalogue()
        ▼
  FnetMtSource ──┐
                 │                        STREAM B: USGS origins (near-live, ~minutes)
                 │                        ──────────────────────────────────────────
                 │                          USGS FDSN GeoJSON (keyless)
                 │                              │  catalogue.usgs_fetcher / poll()
                 │                              ▼
                 ├────────── MultiSource ◄── UsgsSource   (F-net wins same-tick ties;
                 ▼                                         usgs_min_magnitude = 4.0)
        monitor.tick()  ── one state-machine step per due event ──
                 │
                 ├─ register: in_training_domain(lat, lon, depth)?  ──no──► out_of_domain (terminal)
                 ├─ download ~23 min windowed waveforms (fnet/fetch_fnet.py, NIED creds)
                 ├─ build SBI h5 (seismo_sbi build_event_catalogue, pre_event_window 60 s)
                 ├─ QA (full preset + channel blocklist)  ──►  NpeBackend.infer (torch, CPU)
                 ├─ source_type labels (p_outside_dc_box, ≥0.95 rule)
                 ├─ contract.build_event_record (schema-3)  ──►  store.upsert
                 │     • STREAM B records: references: []  → frontend "F-net reference pending"
                 │     • supersede: later F-net solution matching a provisional USGS event
                 │       (±120 s / 1°) re-infers via STREAM A and replaces it (one record)
                 ▼
        FileStore / GitBranchStore  (events.json GeoJSON index + events/<id>.json + state.json)
                 │   publish: force-push to the ORPHAN `data` BRANCH
                 │   (.gitignore excludes _work/ raw waveforms — NIED licence — and _excluded/)
                 ▼
  GitHub `data` branch ──► Vercel rewrite /live-data/* (vercel.json; data-branch deploys OFF)
                 ▼
  Frontend: DemoViewer.tsx fetches /live-data/events.json (live-first, bundled fallback),
  slider right handle pinned to *today*, left default −2 months.
```

Where each stage RUNS:
- **Production**: GitHub Actions `.github/workflows/live-inference.yml`, one `monitor.tick()`
  per run (30-min cron once enabled; `workflow_dispatch` for manual runs — scheduled runs
  always publish, manual runs only with `publish=true`). Heavy assets (fiducial Instaseis DB,
  checkpoint, CI-rewritten config, win32tools) come from the GitHub release `assets-v1` and are
  cached by `actions/cache`.
- **Locally** (backfills, debugging): `python -m fnet_monitor.monitor --loop|--once --out <dir>`
  (worker/ cwd, conda env `seismo-sbi`); `--publish` wraps the store in `GitBranchStore`.

## 2. Key functionality → file map (what to change, where)

| Concern | File(s) | Notes |
|---|---|---|
| Domain filter (lat/lon/depth) | `worker/fnet_monitor/config.py` — `TRAINING_DOMAIN`, `IZU_BONIN_EXCLUSION`, `OFFSHORE_EXCLUSIONS`, `TRAINING_MAX_DEPTH_KM`, `in_training_domain()` | Must mirror the NPE **training prior** (seismo-sbi task `source-catalogue-dataset`). Retrain with a wider prior before loosening. Tests: `worker/tests/test_domain_filter.py`. |
| Discovery thresholds / cadence | `config.py` — `min_magnitude` (F-net 3.5), `usgs_min_magnitude` (4.0), `usgs_enabled`, `window_days`, `delay_minutes` | Env override for depth: `FNET_MAX_DEPTH_KM`. |
| Event sources | `worker/fnet_monitor/sources.py` (`FnetMtSource`, `UsgsSource`, `MultiSource`, `FakeSource`) | Add a new stream by implementing `fetch(now)` + id/time/latlon accessors, then wiring into `monitor.build_source`. |
| State machine / lifecycle | `worker/fnet_monitor/state.py` (`EventStatus`; terminal: `published`, `out_of_domain`, `superseded`, `failed`) | Supersede matching in `monitor.tick` uses `fnet_mt.match_event` (±120 s / 1°). |
| Per-event pipeline | `worker/fnet_monitor/live_event.py` (download → h5 → infer; env overrides `FNET_CONFIG` / `FNET_CKPT` / `FNET_STATIONS_FILE` / `FNET_NSAMPLES` — **defaults are workstation paths; CI must set them**) | |
| NPE backend | `worker/fnet_monitor/npe_backend.py` + seismo-sbi `sbi/compression/ML/` (`robust_posterior_sample`, packing) | Model is MT-only 6-D, variable-station, location-conditioned. |
| QA gates + blocklist | `worker/fnet_monitor/qa.py`; **data**: `worker/data/qa_channel_blocklist.json` (KSN ZEN, YMZ Z, KIS E, SBR Z, ABU Z) | Blocklist changes need evidence (see the json's `meta.evidence` convention). FUJ is an open watch candidate (rings, gates don't fire). |
| Source-type labels | `worker/fnet_monitor/source_type.py` (`prob_outside_dc_box`, ±10° box, non-DC only at p≥0.95) | `contract.validate_event` REJECTS labels that under-shoot the threshold. |
| Record schema (v3) | `worker/fnet_monitor/contract.py` ⟷ `src/components/demo/types.ts` — **keep in lockstep** | Frontend must tolerate: empty `references` (pending), legacy string `source_type` in the bundled snapshot. |
| Reference solutions | `worker/fnet_monitor/references.py` + `fetch_references.py` (USGS detail endpoint aggregates GCMT/W-phase) | Wired for the January demo cache only. **TODO: live enrichment** (approved follow-up): attach GCMT/USGS refs at record build + periodic re-check; real refs only, never the synthetic fallback. |
| Store / publish | `worker/fnet_monitor/store.py`; `PUBLISH_EXCLUDES` guards the public branch (**never** ship `_work/` raw waveforms — NIED licence) | Keep the workflow's publish-step `.gitignore` in lockstep. |
| Store migrations | `python -m fnet_monitor.reclassify --out <store> [--dry-run] [--source-type]` | Re-applies the domain filter + recomputes labels over an existing store; moves excluded records to `_excluded/`; rebuilds the index. Run it (then republish) after any domain/label change. |
| Frontend viewer | `src/components/demo/DemoViewer.tsx` (fetch + slider defaults), `EventPanel.tsx` (pending badge, labels), `demo.astro` (copy) | Slider: rail max = today; default left = −61 d. |
| Vercel wiring | `vercel.json` — `/live-data/*` rewrite to the data branch; `git.deploymentEnabled.data: false` (do NOT remove — every data push otherwise triggers a doomed deploy) | |
| CI workflow | `.github/workflows/live-inference.yml` | Gotchas in §5. `update-events.yml` is the RETIRED mock (no cron — never re-enable, it force-pushes mock data over the real store). |

## 3. Operational data locations

- **Local store (source of truth for backfills)**: `/data/alex/fnet_live/store/`
  (`events.json`, `events/`, `state.json`; `_work/` = failure debug, `_excluded/` = filtered).
- **Local preview**: `public/live-data/` (gitignored copy served by `npm run dev`; refresh with
  rsync from the store after migrations).
- **Assets release**: `assets-v1` on the personal-page GitHub repo — refresh via
  `worker/deploy/upload_assets.sh` (e.g. after retraining: new ckpt tarball; bump the cache key
  or tag if contents change shape).
- **NIED credentials**: LOCKED `worker/.env` (never read/echo it; code loads it internally) +
  GitHub repo secrets `FNET_USERNAME`/`FNET_PASSWORD`.
- Fiducial Instaseis DB (local QA/forward): `/data/alex/axisem_dbs/japan10s/fiducial/`.

## 4. Test tiers (run before pushing worker/frontend changes)

```bash
# offline suite (~150 tests, all seams injected — no network/DB/GPU/creds):
conda run -n seismo-sbi python -m pytest worker/tests worker/fnet -q
# opt-in LIVE tier (real NIED download + NPE, one known event):
conda run -n seismo-sbi python -m pytest worker/tests -m live -q
# frontend:
npm run build
```
seismo-sbi library changes: its own fast gate (`tests/unit tests/integration`) + push, then
bump `SEISMO_SBI_REV` in `live-inference.yml` to the new SHA.

## 5. Known gotchas (each cost a debugging round — do not rediscover)

1. **instaseis in CI** must install with `setuptools==59.8.0` + `SETUPTOOLS_USE_DISTUTILS=stdlib`
   + `--no-build-isolation` (modern setuptools compiles its Fortran modules unordered). Locally
   it is a conda-forge binary; the pip build only exists in CI.
2. **Env-var defaults are workstation paths** (`live_event.py`). Any new runtime input needs an
   `FNET_*` override AND a line in the workflow env (the missing `FNET_STATIONS_FILE` silently
   sent every CI event to `data_waiting`).
3. **NIED publication lag**: F-net MT solutions arrive days–weeks late — an "empty" F-net feed
   in July for July events is normal, not a bug. USGS stream covers freshness; F-net archive
   waveform lag also legitimately keeps very recent events in `data_waiting` for hours.
4. **Publish excludes**: raw waveforms under `_work/` are NIED-licensed — the store/workflow
   `.gitignore` guard must survive any refactor (`test_store.py` pins it).
5. **Schema lockstep**: any `contract.py` record change needs `types.ts` + `EventPanel` +
   `validate_event` updated together; the bundled `public/demo` snapshot keeps the LEGACY shape.
6. **Depth/region are model constraints, not preferences** — events outside the training domain
   produce confident-looking garbage (spurious +ISO). Filter first; retrain to expand.
7. **Mw reads ~0.2–0.3 low** vs F-net (1-D amplitude offset) and low-Mw ISO claims are
   unverifiable against the deviatoric F-net reference — presentation must stay probabilistic
   (the ≥0.95 rule) and honest (demo copy).

## 6. Update recipes (fast paths for common asks)

- **New checkpoint**: train in seismo-sbi → `upload_assets.sh` (new ckpt tar) → dispatch a
  no-publish smoke → watch one inferred event → done (no code change).
- **Change the region/depth domain**: edit `config.py` constants + tests → `reclassify --dry-run`
  on the store → real run → rsync preview → republish (`GitBranchStore.publish`) → push.
- **Add/remove a blocklisted channel**: edit `worker/data/qa_channel_blocklist.json` with
  evidence; existing records are NOT retro-edited (re-run events only if it matters).
- **Copy/text changes**: `src/pages/demo.astro` + `EventPanel.tsx`; `npm run build`; push (Vercel
  auto-deploys `main`).
- **Live reference enrichment (queued follow-up)**: implement in `references.py` at record build
  + a tick-level re-check; backfill via a `reclassify`-style pass; republish.
