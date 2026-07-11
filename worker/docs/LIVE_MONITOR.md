# Live F-net monitor — operator guide

This is the ops doc for the *live* pipeline (`fnet_monitor.monitor`): the state machine that
polls TWO sources — the public F-net regional-MT catalogue (authoritative, published
days–weeks late) and the USGS FDSN feed (near-live discovery within ~1 h) — downloads
waveforms for new events, runs the trained NPE, and publishes schema-3 records the frontend
reads. For the model/inference internals (QA gates, `NpeBackend`, MT conventions) see
**`INFERENCE_BACKEND.md`** — this doc does not duplicate that; it covers running, deploying,
and operating the monitor itself.

## 1. Architecture

```
                         ┌────────────────────────────────────────────────────┐
                         │                    one tick()                      │
                         │                                                    │
 EventSource.fetch(now) ─┼─▶ candidates, keyed by stable id                    │
  (MultiSource:          │    FnetMT solutions (authoritative, id fnet_<stem>) │
   FnetMtSource — public │    + USGS QuakeEvents (provisional, id us…)         │
   F-net MT query,       │                                                    │
   bbox+min_mw filter;   │  for each candidate: state.register(id)            │
   UsgsSource — FDSN,    │    - unknown  -> pending                           │
   usgs_min_magnitude)   │    - known    -> unchanged (idempotent)            │
                         │    - outside the TRAINING DOMAIN -> out_of_domain  │
                         │      (main-arc box 30.5–46°N / 128–146°E, minus    │
                         │       the Izu–Bonin strip lat<33 & lon>138,        │
                         │       depth ≤ 80 km — `config.in_training_domain`) │
                         │                                                    │
                         │  supersede pass: provisional (USGS) events whose    │
                         │  F-net solution has arrived go terminal            │
                         │  `superseded` (alias `superseded_by`) — F-net wins │
                         │  same-tick duplicates too (see §1.3)               │
                         │                                                    │
                         │  for each DUE, non-terminal event id:               │
                         │  ┌──────────────────────────────────────────────┐  │
                         │  │            per-event chain                  │  │
                         │  │ download_event_waveforms  (~23-min window,   │  │
                         │  │   pre=420s/post=960s around origin, ONE       │  │
                         │  │   fetch_window() request via NIED/HinetPy)    │  │
                         │  │        │ no waveforms -> data_waiting, retry  │  │
                         │  │        ▼                                     │  │
                         │  │ build_event_h5  (build_event_catalogue:       │  │
                         │  │   pre_event_window_s=60, covariance_window_s  │  │
                         │  │   =200, duration/sr from the training config) │  │
                         │  │        │ None (too few stations) -> retry     │  │
                         │  │        ▼                                     │  │
                         │  │ infer_live_event  (NpeBackend.infer + FULL    │  │
                         │  │   QA preset + channel blocklist +             │  │
                         │  │   contaminated_action="warn")                 │  │
                         │  │        │ exception -> retry (never kills tick)│  │
                         │  │        ▼                                     │  │
                         │  │ contract.build_event_record -> store.upsert   │  │
                         │  └──────────────────────────────────────────────┘  │
                         │                                                    │
                         │  store.write_index()  (rebuild events.json)        │
                         │  publish resolution (see §1.2)                     │
                         │  state.save()                                      │
                         └────────────────────────────────────────────────────┘
                                            │
                                            ▼
                              EventStore (FileStore / GitBranchStore)
                                events/<id>.json + events.json
                                            │
                                            ▼
                         publish channel: `data` branch (git) -------┐
                                            │                        │
                                            ▼                        ▼
                          vercel.json rewrite /live-data/*  ->  raw.githubusercontent.com
                                            │
                                            ▼
                              DemoViewer.tsx (frontend, §5)
```

### 1.1 Per-event state machine (`state.py`)

```
register -> pending
              |  (data present, inference run OK)
              v
data_waiting <-> inferred -> published        (terminal: ok)
     |
     `-- schedule_retry (exponential backoff) ... -> failed   (terminal: exhausted)
```

- **`pending`** — registered, not yet due (see the youth guard below) or not yet attempted.
- **`data_waiting`** — a download/build/infer attempt didn't succeed (no waveforms yet, too
  few stations, or an exception); a retry is scheduled.
- **`inferred`** — this tick's chain succeeded and `store.upsert()` ran; not yet confirmed
  published (see §1.2).
- **`published`** / **`failed`** — terminal. A published event is never re-inferred. A failed
  event has exhausted its retry budget (`max_attempts=20`, default) and is also never retried
  again — it needs a manual reset (§3.2).
- **`out_of_domain`** — terminal, set at registration: the candidate's epicentre/depth fall
  outside the NPE's training-prior domain (`config.in_training_domain`; env
  `FNET_MAX_DEPTH_KM` overrides the 80 km depth cut). Never downloaded, retried, or
  published; `last_error` records which check failed. Existing stores are migrated with
  `python -m fnet_monitor.reclassify --out <store>` (moves the now-OOD records to
  `<store>/_excluded/`, rebuilds the index, reports the surviving Kagan median).
- **`superseded`** — terminal, provisional (USGS) events only: the matching F-net solution
  arrived and re-ran the standard path, so this id's record was replaced (see §1.3);
  `superseded_by` links the F-net id. Neither id is ever re-inferred.

Every state entry also stamps `origin_time`/`lat`/`lon` at registration (used by the
supersede matching) and `provisional: true` for USGS-discovered candidates.

**Backoff**: exponential, `base_s=1800` (30 min) doubling up to `cap_s=43200` (12 h), with
±20% *deterministic* jitter seeded on `event_id:attempts` (so a resumed tick reproduces the
same schedule — no drift on restart, and tests are exact). Archive-lagged F-net events
legitimately retry for days, hence the generous 20-attempt cap.

**`delay_minutes` youth guard** (`Config.delay_minutes`, default 30): a *brand-new* candidate
(`status == pending`, `attempts == 0`) younger than `delay_minutes` is left `pending` with
`next_retry_at` set to `origin_time + delay_minutes` rather than attempted immediately — F-net
regional-MT solutions aren't in the archive the instant an event happens, so this avoids
burning a download attempt (and a retry-backoff cycle) on a guaranteed-empty fetch. Once an
event *has* had one real attempt (`attempts >= 1`), all further scheduling is the normal
exponential backoff above, not the youth guard.

### 1.2 Published vs inferred (who confirms publication)

Per due event: chain → `store.upsert(record)` → `state.advance(id, 'inferred')`. The record is
durable in the store but not yet confirmed published. At the END of the tick:

- **`--publish`** (local daemon) — call `store.publish()`; on success promote every
  this-tick `inferred` id to `published`.
- **default / CI** — `--publish` is NOT passed; the GitHub Actions workflow's own git-push
  step (a separate job step, *after* the python process exits) is what publishes, and it
  can't report status back into the process. So in this mode, upserting into `_data` *is*
  treated as publication: ids are promoted straight to `published` without calling
  `store.publish()` at all.

Either way an event ends terminal (`published`) exactly once, so it's never re-inferred; only
a failure schedules a retry.

### 1.3 Two-tier freshness: USGS discovery + F-net supersede-on-match

NIED publishes F-net MT solutions days–weeks after the earthquake; USGS origins arrive
within minutes. The monitor therefore polls both (`monitor.build_source` →
`MultiSource(FnetMtSource, UsgsSource)`; disable with `Config.usgs_enabled=False`):

- **USGS candidates are PROVISIONAL.** Discovery threshold `Config.usgs_min_magnitude`
  (default **4.0** — USGS magnitudes near the F-net 3.5 floor are mb-dominated). The same
  training-domain filter applies. The per-event chain is identical, except the conditioning
  vector comes from the USGS lat/lon/depth and no reference MT exists yet: the record is
  published with **`references: []`** ("F-net reference pending" badge in the frontend;
  index `primary_source: "pending"`).
- **Supersede-on-match.** When an F-net solution matching a provisional event appears
  (origin times within 120 s AND epicentres within 1° — the `fnet_mt.match_event`
  tolerances), the provisional id goes terminal `superseded` (alias `superseded_by`), the
  F-net event runs the STANDARD path (refined JMA location conditioning + F-net reference),
  and the provisional record is deleted once the F-net record is in the store — exactly one
  record survives, under the F-net id. Both sources returning the same event in one tick
  resolves the same way (F-net wins; the USGS id is never inferred).

### 1.4 Probabilistic source-type labels

Every record's `source_type` is the block `{p_outside_dc_box_10, label}`
(`fnet_monitor/source_type.py`): the posterior probability that the source lies OUTSIDE the
near-DC lune box |γ|<10° & |δ|<10° (the Santorini lomax-suite lune-box exclusion metric),
computed over the stored (γ, δ) posterior cloud. `label` claims a non-DC variant
(`"non-DC (+ISO|-ISO|+CLVD|-CLVD)"`, sub-classified by the dominant range-scaled lune
coordinate of the outside mass) **only when p ≥ 0.95**; otherwise it is `"DC-consistent"` —
the contract validator rejects any record that over-claims. Stores written before the block
existed are migrated with `python -m fnet_monitor.reclassify --out <store> --source-type`.

## 2. The two runtimes

### 2.1 GitHub Actions — one-shot tick (`.github/workflows/live-inference.yml`)

**Currently disabled by default** — `workflow_dispatch` only; the `schedule:` cron block is
commented out pending go-live authorization (uncomment it *and* disable
`update-events.yml`, the old mock-inference workflow, to go live).

Each run:
1. Checks out `main`, sets up Python 3.8 (pinned — matches the proven local `seismo-sbi`
   conda env; RHEL/Ubuntu-22.04 runner, not `-latest`, because 24.04 images drop 3.8).
2. Restores the four release assets (`japan10s_fiducial`, `japan_v1_ckpt`, `ci_config`,
   `win32tools`) from an `actions/cache` keyed on `fnet-assets-${ASSETS_TAG}` — downloaded
   from the `assets-v1` GitHub release only on a cache miss (not every tick).
3. Installs `torch==2.0.0` (CPU wheel) + `worker/requirements-inference.txt` +
   `seismo-sbi` pinned at `SEISMO_SBI_REV` (`--no-deps`, curated deps above — the library's
   own `requirements.txt` is stale/heavy).
4. Seeds `_data` (state.json + prior events) from the `data` branch, if it exists.
5. Runs `python -m fnet_monitor.monitor --once --out ../_data` (`working-directory: worker`),
   with `FNET_USERNAME`/`FNET_PASSWORD` from repo secrets, `FNET_CONFIG`/`FNET_CKPT` pointed
   at the runner asset paths, and `BACKFILL_START` from the `workflow_dispatch` input.
6. **If `inputs.publish` was true**: force-pushes `_data` as the orphan `data` branch (same
   recipe `GitBranchStore._push` implements for the local path). Otherwise the run only
   updates the cached local `_data` inside the ephemeral runner — nothing is published.

`permissions: contents: write` + `concurrency: group: live-inference, cancel-in-progress:
false` (never two ticks racing on the same state).

### 2.2 Local daemon (`--loop`)

```bash
cd worker    # conda env: seismo-sbi
# ordinary loop: a tick every --interval seconds (default 1200s = 20 min)
python -m fnet_monitor.monitor --loop --interval 1200 --out <dir> --publish

# BACKFILL (verbatim, June -> today): NOT a separate mode, just a widened lookback
# that exits once nothing is due right now (future-scheduled retries don't block):
python -m fnet_monitor.monitor --loop --interval 30 \
    --backfill-start 2026-06-01 --exit-when-drained --out <dir>
#   Events left in `data_waiting` after drain are EXPECTED leftovers (F-net archive
#   lag on very recent events) — the drain check reports them, doesn't wait on them.
```

`--publish` wraps the store in `GitBranchStore` and calls `store.publish()` at the end of
every tick that produced newly-inferred events. **`GitBranchStore` is guarded**: `publish()`
is a no-op unless the store was constructed with `enable_push=True` *and* both a `token`
(`GITHUB_TOKEN` env) and a `remote` (`GITHUB_REPOSITORY` env, `owner/repo`) are set — so
running `--publish` locally without those two env vars is safe (it just never pushes). Without
`--publish`, the local daemon uses a plain `FileStore` and only ever writes to `--out`.

## 3. Ops

### 3.1 Env overrides

All read at import/call time by `live_event.py` / `monitor.py`, local defaults as fallback:

| Var | Default (local) | Purpose |
|---|---|---|
| `FNET_CONFIG` | `{FNET_REPO}/scripts/configs/japan/first_ml_npe_japan.yaml` | training YAML the pipeline/scaler/backend are built from |
| `FNET_CKPT` | `{FNET_REPO}/ml-checkpoints/japan_v1` | checkpoint dir (`resolve_ckpt_dir`-compatible) |
| `FNET_NSAMPLES` | `2000` (code default; CLI `--min-mw` unaffected) | posterior samples per event |
| `FNET_STATIONS_FILE` | `{FNET_REPO}/scripts/configs/japan/fnet_demo_stations.txt` | the 21-station demo list `download_event_waveforms` reads |
| `FNET_REPO` | `/home/alex/work/seismo-sbi` | relocates the seismo-sbi checkout the three paths above are built from |
| `BACKFILL_START` | none | ISO date widening the poll window (CLI `--backfill-start` wins if both given) |
| `FNET_USERNAME` / `FNET_PASSWORD` | worker `.env` (locked, gitignored) | NIED creds, loaded internally by `fetch_fnet.load_credentials` — never logged |
| `GITHUB_TOKEN` / `GITHUB_REPOSITORY` | none | required (with `--publish`) for `GitBranchStore.push_enabled` |

In CI, `FNET_CONFIG`/`FNET_CKPT` point at the runner's extracted release-asset paths
(`/home/runner/fnet_assets/...`); locally they default straight at the seismo-sbi checkout.

### 3.2 `state.json` anatomy + resetting a stuck event

```json
{
  "last_time": null, "processed_ids": [], "archive_lag_minutes": null,
  "updated": "2026-07-11T10:00:00Z",
  "events": {
    "fnet_20260616T104633": {
      "status": "published", "attempts": 0, "next_retry_at": null,
      "first_seen": "2026-06-16T11:00:00Z", "last_error": null,
      "published_at": "2026-06-16T11:20:00Z",
      "origin_time": "2026-06-16T10:46:33Z", "lat": 36.29, "lon": 140.06,
      "provisional": false, "superseded_by": null
    }
  }
}
```

(`origin_time`/`lat`/`lon`/`provisional`/`superseded_by` were added for the USGS
supersede flow; legacy files without them load fine — the fields default empty.)

`events.<id>` is the only thing `tick()` ever inspects for that event past its first sighting
(`register` never resets an already-known event, so re-polling doesn't wipe retry state or a
terminal verdict). To reset a stuck event (e.g. one that hit `failed` after exhausting
retries, or you want to force a re-run against a fixed bug): edit `state.json`, either delete
that event's entry entirely (it will re-register as fresh `pending` next tick) or set
`"status": "data_waiting"`, `"attempts": 0`, `"next_retry_at": null`. Do **not** hand-edit
`"status": "published"` onto an event you actually want re-run — a published event's on-disk
`events/<id>.json` record is what the frontend reads, so you'd also need to remove/regenerate
that file, and re-running risks a duplicate publish race if a tick is also mid-flight.

### 3.3 Refreshing model assets

`worker/deploy/upload_assets.sh` packages the fiducial Instaseis DB (~950 MB), the *best*
(most negative val_loss) checkpoint + its `model_meta.json`, a CI-path-rewritten copy of the
training config + stations file, and the WIN32 tools, then uploads all four as assets on the
`assets-v1` GitHub release (`gh release upload ... --clobber`). Run it whenever the checkpoint
changes:

```bash
bash worker/deploy/upload_assets.sh
```

The CI workflow only re-downloads on an `actions/cache` miss keyed on `fnet-assets-${ASSETS_TAG}`
— bump `ASSETS_TAG` in `live-inference.yml` (currently `assets-v1`) to force every runner to
pick up a refreshed release immediately instead of waiting for the cache to naturally evict.

### 3.4 Rotating NIED credentials

See `worker/deploy/SETUP_GHA.md` §1: fill `worker/deploy/gha_secrets.env.template` from the
locked local `worker/.env`, then `gh secret set -f worker/deploy/gha_secrets.env.template`
(or the GitHub web UI) to update `FNET_USERNAME`/`FNET_PASSWORD`. No code change needed —
`fetch_fnet.load_credentials` reads dotenv-or-environment at call time. Delete the filled-in
template afterwards; never commit real values.

### 3.5 Frontend `/live-data/` rewrite + bundled fallback

`vercel.json` rewrites `/live-data/:path*` same-origin to
`https://raw.githubusercontent.com/asaoulis/personal-page/data/:path*` (the published `data`
branch), so the browser never talks cross-origin to GitHub directly. `DemoViewer.tsx` fetches
`${LIVE_BASE}events.json` first; on ANY failure (bad HTTP status, network error, malformed
JSON — e.g. the `data` branch doesn't exist yet, or a local `astro dev` has no rewrite) it
falls back to the bundled static snapshot under `public/demo/` (`BUNDLED_BASE`). This means
the demo always renders something, live or not, and local frontend dev needs no live backend.

### 3.6 Test tiers

- **Default offline suite** (`conda run -n seismo-sbi python -m pytest worker/tests
  worker/fnet -q`, run from the repo root) — every seam (download/build/infer, git push) is
  monkeypatched or an in-memory stub; no network, no creds, no GPU, no torch import required
  for most of it. This is what CI-equivalent local gating runs; **currently 145 tests**.
- **`-m live`** (`worker/tests/test_live_pipeline.py`) — opt-in, hits the real F-net query,
  real NIED download, real h5 build, real NPE inference with the real checkpoint. Excluded by
  default via `addopts = "-q -m \"not live\""` in `worker/pyproject.toml` (a `markers =
  [...]` entry registers `live` so it's not an "unknown marker" warning either way); `-m live`
  on the command line overrides the default (pytest's `-m` is last-wins):
  ```bash
  conda run -n seismo-sbi python -m pytest worker/tests/test_live_pipeline.py -m live -q
  ```
  Skips cleanly (`pytest.skip`, not a failure) if NIED creds, the training config, the
  checkpoint, the stations file, or the fiducial Instaseis DB are missing on the machine.

## 4. Known operational constraints

- **NIED archive lag on recent events**: a just-happened event may not be in the F-net
  archive yet — `data_waiting` (with a backoff retry) is the *expected*, not erroneous, state
  for such events; it self-resolves within a few retry cycles as the archive catches up.
- **Cron is best-effort**: a late, skipped, or failed scheduled run only delays publication —
  the state machine is fully resumable (`state.json` + the `data`-branch-backed store), so
  nothing is lost, only delayed.
- **Download timing**: the per-event `fetch_window` request (one ~23-min NIED window,
  `pre_s=420`/`post_s=960` around the origin — see `live_event.download_event_waveforms`'s
  docstring for the taper/filter-transient margin derivation) measured **~72 s
  wall time for the full chain (download → h5 build → NPE inference + full QA) on
  2026-07-11**, run against the archived 2026-06-16 SW_IBARAKI_PREF Mw 5.4 event via
  `test_live_pipeline.py`. Recent/flaky dates and large multi-event batches (the *bulk*
  `live_event.py --days N --max-events M` driver, not the monitor's per-event window fetch)
  can be materially slower — see `INFERENCE_BACKEND.md`'s "Operational constraints" section
  for the full-day-request caveats of that separate bulk path.

## 5. See also

- **`INFERENCE_BACKEND.md`** — the NPE model/inference internals: `NpeBackend`, the QA gate
  suite + calibration, MT conventions, the bulk catalogue driver.
- **`SETUP_GHA.md`** — one-time GitHub Actions secrets + release-asset setup.
- **`worker/fnet_monitor/monitor.py`** module docstring — the authoritative CLI reference
  (flags, env vars) kept in lockstep with the code.
