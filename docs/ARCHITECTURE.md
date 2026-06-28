# Architecture & Project Proposal

> The overarching design for `personal-page` — a flashy-but-restrained personal site
> whose centrepiece is a **live earthquake-monitoring + ML-inference demo** for the
> Japan (F-net) region. This document is the durable plan: it captures goals, the target
> architecture, the data contracts, costs, security, and an incremental roadmap. It is
> meant to be edited as components land.

Status legend: ✅ done · 🚧 in progress · 🔭 planned

---

## 1. Vision & goals

Build a single, polished web presence for a computational-seismology / ML researcher that:

1. **Presents the standard material** — home, about, CV (with PDF), projects, contact — with a
   clean, modern, minimal-academic aesthetic. ✅ (stage-1)
2. **Showcases a live, interactive flagship demo**: a continuously-updating monitor that runs
   the author's neural-posterior-estimator (NPE) on new, resolvable (~M≥3.5) earthquakes in the
   Japan F-net region and visualises the inferred **moment-tensor posterior** against catalogue
   solutions — on an interactive map with diagnostic side panels (source-type **lune**,
   beachballs, uncertainty) and a **month-long time-slider**. 🔭 (the centrepiece; stage-1 ships
   only the interface preview with mock data)
3. **Scales to more projects** — cosmology SBI, diffusion-based climate downscaling — each an
   independently-shippable page. 🔭

### Success criteria

- A visitor immediately understands who the author is and what they do.
- The flagship demo loads fast, is genuinely interactive, and stays responsive when scrubbing a
  month of events — **without** a model server in the request path.
- Running it costs ~£0/month at this scale.
- Adding a project or a new event source is a small, well-documented change.

---

## 2. What stage-1 delivers (current)

- ✅ Astro + React-islands site (TypeScript), deployed static to **Vercel**.
- ✅ Clean minimal-academic design system (ink + deep-blue accent, Newsreader/Inter, self-hosted
  variable fonts), responsive, accessible, progressive-enhancement scroll-reveal.
- ✅ Pages: Home, About, CV (+ placeholder PDF), Projects (content-collection driven), Contact
  (scraper-safe email), and a `/demo` **interface preview**.
- ✅ `/demo`: a real **MapLibre GL** map over Japan with **mock GeoJSON** events, clickable
  markers, a working side panel (real lune + beachball images), and a functioning client-side
  **time-slider** — proving the whole interaction model end-to-end on representative data.
- ✅ This document + a data contract the live worker must satisfy.

Everything from here is the path to making the demo _live_.

---

## 3. Target architecture

The guiding principle is **decoupling inference from serving**. The model never runs in a user
request. A scheduled worker does all the heavy lifting offline and publishes small, static
artifacts; the frontend is a fast static site that reads them.

```
        ┌──────────────────────────────────────────────────────────────────────┐
        │                          SCHEDULED WORKER                              │
        │             (GitHub Actions cron, ~every 5–15 min)                     │
        │                                                                        │
  ┌───────────┐   poll    ┌──────────────┐  waveforms  ┌──────────────────────┐ │
  │ Catalogue │◀──────────│  new-event   │────────────▶│   seismo_sbi NPE      │ │
  │  sources  │   M≥3.5   │   detector   │             │  (CPU flow sampling)  │ │
  │ USGS/JMA/ │──────────▶│              │             │  + lune/beachball     │ │
  │  F-net    │           └──────────────┘             │     rendering         │ │
  └───────────┘                                        └───────────┬──────────┘ │
        │                                                          │ writes      │
        └──────────────────────────────────────────────────────────┼────────────┘
                                                                    ▼
                                         ┌───────────────────────────────────────┐
                                         │      STATIC RESULTS STORE             │
                                         │  git-committed: events.json (GeoJSON), │
                                         │  per-event JSON, lune.png, beachball.png│
                                         └───────────────────┬───────────────────┘
                                                             │ (build/CDN)
                                                             ▼
                                         ┌───────────────────────────────────────┐
                                         │    FRONTEND — Astro static @ Vercel    │
                                         │  /demo React island: MapLibre map +    │
                                         │  side panels + client-side time-slider │
                                         └───────────────────────────────────────┘
```

### 3.1 Why decoupled / precompute-first

- **Responsiveness.** The time-slider scrubs a _precomputed_ month window held in the browser —
  pure client-side filtering, no network round-trip per frame.
- **Cost.** No always-on GPU/CPU inference server. The worker runs only when triggered; the
  frontend is static files on a CDN. At M≥3.5 in one region the event volume is small (tens/month).
- **Robustness.** A user request can never trigger (or be blocked by) a model run, a waveform
  fetch, or an F-net outage. The site is always up even if the worker is mid-run or failing.
- **Simplicity.** The contract between worker and frontend is just files. Either side can be
  rebuilt/replaced independently.

### 3.2 Component choices (and rejected alternatives)

| Concern            | Choice                               | Why / rejected                                                                                                                                                                       |
| ------------------ | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Frontend framework | **Astro + React islands**            | Static-by-default, fast; React only for the heavy demo island.                                                                                                                       |
| Host (frontend)    | **Vercel** (free Hobby)              | Git-push deploys, free HTTPS + custom domain, room for serverless later.                                                                                                             |
| Map renderer       | **MapLibre GL JS**                   | OSS, WebGL vector tiles, **no token**. (Mapbox needs a token; deck.gl is overkill — can layer later.)                                                                                |
| Basemap tiles      | **OpenFreeMap** (`positron`)         | Free, no registration, no key, no limits → frontend stays secret-free. Fallbacks: self-hosted Protomaps `.pmtiles`, or MapTiler free tier.                                           |
| Inference worker   | **GitHub Actions cron**              | Free unlimited minutes on public repos; no always-on box. (HF Spaces free CPU sleeps when idle → unreliable poller; Vercel functions time out at 10–60 s → too short for inference.) |
| Results store      | **git-committed JSON/PNG** (default) | Simplest, free, versioned, CDN-served. Graduate to Cloudflare R2 / HF dataset only if volume grows.                                                                                  |
| Inference compute  | **CPU**                              | NPE flow sampling is cheap on CPU; the cost is waveform fetch + compression, not the flow.                                                                                           |

---

## 4. Data contract (worker → frontend)

The frontend reads a **single GeoJSON `FeatureCollection`** describing the current window. The
stage-1 mock at `public/demo/events.json` already uses this exact shape — the live worker must
emit the same schema so the frontend needs no changes to go live.

```jsonc
{
  "type": "FeatureCollection",
  "generated": "2026-06-28T00:00:00Z",   // worker run time (slider's "now")
  "window_days": 30,                       // rolling retention window
  "mock": false,                           // true only for the placeholder data
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [lon, lat] },
      "properties": {
        "id": "ev-2026-06-26-off-ibaraki",
        "time": "2026-06-26T21:36:00Z",
        "mag": 5.2, "magType": "Mw",
        "depth_km": 32,
        "region": "Off Ibaraki, Honshu",
        "source_type": "double-couple",
        "gamma": 1.5, "delta": -2.0,        // lune (source-type) coordinates, degrees
        "kagan_deg": 10.2,                   // model-vs-catalogue Kagan angle
        "strike": 198, "dip": 33, "rake": 86,
        "catalogue_source": "F-net",
        "assets": {
          "beachball": "/demo/<id>/beachball.png",
          "lune": "/demo/<id>/lune.png"
          // future: "posterior": "/demo/<id>/samples.json" for native-JS plots
        }
      }
    }
  ]
}
```

### 4.1 Time-slider data model

- The frontend loads the **whole window** (one `events.json`) once. The slider's value is a
  cutoff timestamp in `[generated − window_days, generated]`; **events with `time ≤ cutoff` are
  shown** (so scrubbing back "un-happens" recent events). Filtering is in-memory → instant.
- **Retention.** The worker keeps a rolling `window_days` window: each run appends new events and
  drops any older than the window (and prunes their `public/demo/<id>/` asset dirs). The store
  stays bounded and small.
- **Scale.** At M≥3.5 in one region this is tens of events and a few hundred KB of JSON + a
  handful of small PNGs — trivial for a CDN and the browser. If it ever grows, shard by
  week/month and lazy-load, or move assets to R2.

### 4.2 Store contents

Per run the static store holds: `events.json` (the frontend contract above); per-event
`<id>/lune.png` + `<id>/beachball.png` (and later `<id>/samples.json` for native-JS plots); and a
**worker-only `state.json`** (`last_processed_id`, `last_time`, backlog queue, measured
`archive_lag`) that the stateless cron reads to resume — **never fetched by the frontend** (see §6.5).

---

## 5. Reuse map — how the demo leans on `seismo_sbi`

The worker imports the author's research library (`seismo-sbi`) and serves what it already
produces. Verified entry points:

| Need                                  | `seismo_sbi` API                                                                                | Notes                                                                             |
| ------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Rebuild NPE from a checkpoint         | `evaluation/inference.py` → `build_eval_pipeline`, `build_ml_posterior(ckpt_dir, pipeline)`     | ~seconds/event on CPU once the model is loaded — cold-start dominates (see §6.4). |
| Ingest a fetched observation          | `evaluation/inference.py` → `load_real_observation`                                             | Undoes receiver time shifts, etc.                                                 |
| Posterior MT samples (physical units) | `evaluation/inference.py` → `recovered_mt_samples(inv) → (n,6)`                                 | Feeds lune + beachball.                                                           |
| Source-type lune plot                 | `plotting/lune.py` (`mts6_to_gamma_delta`, `plot_scatter_on_lune`, `plot_kde_contours_on_lune`) | Worker renders the **lune PNG** (catalogue MT vs model cloud).                    |
| Beachball + Kagan comparison          | `evaluation/moment_tensor.py` → `pyrocko_mt(m6)`, `kagan(a,b)`                                  | GCMT up-south-east convention (no Mrp/Mtp flip since the 2026-06-13 fix).         |
| Catalogue-wide visual style           | `scripts/santorini_pathbreaker/lomax_catalogue/catalogue_map.py`, `posterior_gallery.py`        | Reference for beachball-map + posterior panels (size∝Mw, colour=source-type γ).   |

**Plotting strategy.** Basemap/cartopy/pyrocko are heavy and Python-only. v1 demo visuals are
therefore **server-rendered PNGs** produced by the existing code (least effort, exactly matches
the published figures). A later enhancement is a **native-JS lune** (d3/canvas) reading a
`samples.json` for interactive hover/zoom — but PNG-first is the right starting point.

---

## 6. The inference worker — design & F-net data-access reality

The worker is the only stateful, credentialed component. Its design must reflect how F-net data
_actually_ works — request-based, archived, authenticated — not an idealised stream. (These notes
are grounded from prior F-net research; verify lag/quotas/ToS empirically once access is live.)

### 6.1 Trigger — detecting new events

A cron job is short-lived, so the worker does **not** hold a socket open; it **polls** on each run
for new region events since `state.json.last_time`:

- **USGS FDSN-event** GeoJSON (`earthquake.usgs.gov/fdsnws/event/1/query`) — global, keyless, easy
  → the default detector. (EMSC SeismicPortal's WebSocket
  `wss://www.seismicportal.eu/standing_order/websocket` is the better _push_ trigger for an
  always-on listener, but doesn't fit a cron poller — note the divergence.)
- Global feeds thin out below ~M4.5, so for the **M3.5–4.5 band** add a Japan-regional source —
  **JMA** or **NIED AQUA** (near-real-time auto-MT) — as the low-band trigger.
- De-duplicate across feeds by origin time + location into one canonical event id.

### 6.2 Fetch — F-net is request-based, not streaming

There is **no public SeedLink/FDSNWS firehose** for Hi-net/F-net. You post an authenticated
request, the server prepares data (~10–60 s), you poll, then download:

- Use **HinetPy**; the F-net broadband network code is **`0103`**.
- Convert WIN32 → SAC + pole-zero responses with `win32.extract_sac` / `win32.extract_sacpz`. This
  needs the NIED **`win32tools`** binaries (`catwin32`, `win2sac_32`) compiled and on `PATH` — a
  non-obvious CI step the worker workflow must build/cache, or conversion silently fails.
- **Request times are JST (UTC+9)** — a classic off-by-9-hours bug; convert carefully.
- Issue **one batched request per event** covering all needed stations (never per-station).

### 6.3 Archive lag → a deliberate delay window

F-net continuous data is requestable only once archived. **Measure the lag empirically** (don't
assume it). Process events on a **delay window** — only those older than
`max(archive_lag, required_waveform_window)`. Net effect: the demo shows events with a realistic
~30–60 min delay; state this in the UI copy.

### 6.4 Inference — fast per event; cold-start is the real cost

**Per-event NPE inference on a preloaded torch model takes ~seconds on CPU** — it is _not_ the
bottleneck. The dominant per-run cost is **cold-start**: importing the ML stack
(PyTorch + `seismo_sbi`), loading the model checkpoint, and opening the Green's-function database.
Design around that:

- **Load once, infer many.** Import libs and load the model + GF DB **once per run**, then loop
  over all new events — never pay cold-start per event.
- **Batch the backlog** (§6.5) so a single warm process clears multiple events.
- **Cache the environment + model weights** in the workflow (pip/conda cache, cached checkpoint) to
  cut per-run cold-start; bound the per-event job time.
- Because inference is seconds, even an event swarm is cheap _compute_ — the limiter is the
  serialised F-net fetch (§6.2), not the model.

### 6.5 Stateful, resumable worker (cron is best-effort)

GitHub Actions cron is **not punctual** (minutes–tens-of-minutes late, skipped under load) and is
**auto-disabled after ~60 days of repo inactivity**. F-net fetching is serialised and seismicity is
**bursty** (aftershock sequences = many events/day exactly when you're busiest). So:

- Persist **`state.json`** in the store (`last_processed_id`, `last_time`, a backlog **queue**,
  measured `archive_lag`). The stateless cron resumes from it each run.
- **Prioritise by magnitude**; during a swarm, accept that you **sample**, not capture, every event.
- If punctual timing ever matters, trigger via an external pinger (`workflow_dispatch`) rather than
  relying on `schedule`.

### 6.6 Validation overlay (catalogue ground truth)

Per event, pull a reference solution to plot beside the posterior / on the lune:

- **F-net routine MT** and **AQUA-MT / AQUA-CMT** for ~M3.5–5; **GCMT** for M5+.
- ObsPy reads the F-net MT catalogue natively (`obspy.io.nied.fnetmt` via `read_events()`).
- **Mw ≈ 3.5 is the floor** of reliable regional MT — treat 3.5–3.8 as best-effort and label it.
- AQUA doubles as a **low-band trigger candidate AND ground truth**; its initial magnitudes can be
  provisional (Tohoku was first put near M5) — honour updates.

### 6.7 Latency budget

Trigger (1–5 min) + archive availability + fetch/convert (1–3 min) + inversion (**seconds**) ≈
**~15–40 min end-to-end**. A **30-min refresh cadence is comfortable**; don't over-engineer for
sub-minute.

---

## 7. Cost model

| Item                                         | Service                               | Cost at this scale              |
| -------------------------------------------- | ------------------------------------- | ------------------------------- |
| Frontend hosting + CDN + HTTPS               | Vercel Hobby                          | **£0**                          |
| Custom domain (optional)                     | any registrar                         | ~£8–15 / yr                     |
| Basemap tiles                                | OpenFreeMap                           | **£0** (no key)                 |
| Inference worker (cron)                      | GitHub Actions (public repo)          | **£0** (free unlimited minutes) |
| Results store                                | git + CDN                             | **£0**                          |
| Trained NPE checkpoint / Green's-function DB | produced on existing research cluster | n/a (pre-existing)              |

**Total recurring: ~£0/month** (or ~£1/month amortised if a custom domain is bought). Graduate to
a small always-on box (Fly.io / Render / a ~£4–5/mo VPS) **only** if a longer-running or more
frequent worker is needed than Actions cron comfortably allows, or HF Spaces free CPU for an
on-demand inference API.

---

## 8. Security & secrets

- **The static frontend needs no secrets** to build or deploy.
- F-net/NIED credentials and any provider keys live **only** in the worker environment:
  **GitHub Actions repository secrets** (or a box's `.env`). Never in the frontend bundle, never
  committed.
- `.env` is gitignored; `.env.example` documents the variables (`FNET_USERNAME`, `FNET_PASSWORD`,
  optional `CATALOGUE_FDSN_URL`, optional `MAPTILER_KEY`).
- Keep the keyless OpenFreeMap path to avoid shipping any tile key to the client.

---

## 9. Risks & prerequisites

Going live presupposes work **not** in this stage:

- **Trained F-net NPE checkpoint** — a neural posterior estimator trained for the Japan F-net
  station geometry. (Produced with the existing `seismo-sbi` training pipeline.)
- **Japan-region Green's-function database** (e.g. Instaseis DB) for the forward
  simulation/compression the inference needs.
- **F-net account cadence** — registration must be renewed periodically; the worker must handle
  auth refresh and fail gracefully when access lapses.
- **Catalogue latency / feed choice** — which feed, how often to poll, de-duplication across
  feeds, and the magnitude threshold for "resolvable".
- **Data licensing / attribution** — display the required NIED/JMA/USGS attributions for
  catalogues, waveforms and basemap tiles.
- **Plotting deps are heavy** — fine inside a Python worker; means v1 visuals are images, not
  native JS (documented trade-off, §5).

Operational risks for the live worker (grounded; mitigations noted):

- **GitHub Actions cron is best-effort** — late/skipped under load, and **auto-disabled after
  ~60 days of repo inactivity**. → Document the looseness; use an external pinger
  (`workflow_dispatch`) if punctuality ever matters; a periodic commit keeps it from disabling.
- **Git binary bloat.** Committing per-event PNGs to the site repo grows history **permanently**
  (git keeps every binary forever). → Mitigate with an **orphan `data` branch** (force-pushed, no
  history), or move binaries to **Cloudflare R2 / HF dataset** (JSON-only in git), or rolling-window
  prune. Decide _before_ the worker lands — the default "git-committed" path needs one of these.
- **WIN32 tooling in CI.** The `win32tools` binaries (`catwin32`/`win2sac_32`) must be built/cached
  in the workflow or WIN32 → SAC conversion silently breaks (§6.2).
- **NIED login brittleness + ToS.** HinetPy drives an authenticated NIED flow that can break on
  login/2FA changes → keep a manual-run fallback; confirm NIED terms permit automated/CI access;
  watch for rate-limiting. **Publish only DERIVED products** (posteriors, lune/beachball plots,
  GeoJSON) with NIED/F-net acknowledgement — **never re-serve raw waveforms** (miniSEED/SAC) (§8).
  The demo footer must carry the F-net/NIED citation.
- **OpenFreeMap has no SLA** (donation-funded). Fine for a demo, but for a recruiter-facing page a
  tile outage looks bad → consider self-hosting a **Japan-only Protomaps `.pmtiles`** extract (a
  small single static file served from Vercel, zero tile server) for resilience.
- **Worker image weight / cold-start** — heavy ML stack (PyTorch + `seismo_sbi`). Kept off the
  request path by the precompute pattern; cache env + weights and load-once-per-run (§6.4).

---

## 10. Roadmap

Each milestone is independently shippable.

### Site (stage-1) — ✅ done

Repo + tooling, design system, content pages, `/demo` preview, this doc, Vercel deploy.

### Flagship demo — 🔭

1. **M-D1 Worker skeleton (no inference).** GitHub Actions cron + a Python entrypoint that polls
   USGS FDSN (+ JMA/AQUA for the M3.5–4.5 band) for new Japan events since `state.json.last_time`,
   applies the **delay window** (§6.3), and writes/updates `events.json` + `state.json` — wiring the
   whole contract end-to-end on real triggers but mock/empty inference output.
2. **M-D2 Inference.** F-net **fetch via HinetPy (code `0103`)** + build/cache **`win32tools`** for
   WIN32 → SAC; **load model + GF DB once per run**, run `seismo_sbi` inference (~seconds/event),
   render lune + beachball PNGs, commit results.
3. **M-D3 Catalogue comparison.** Pull reference MTs (F-net routine / AQUA / GCMT via
   `obspy.io.nied.fnetmt`); compute + display the Kagan angle and overlay catalogue vs model on the
   lune. Label Mw 3.5–3.8 as best-effort (regional-MT floor).
4. **M-D4 Retention + robustness.** Rolling-window pruning + **git-bloat mitigation** (orphan `data`
   branch or R2), stateful backlog/burst handling, auth-refresh + failure alerting, NIED/F-net +
   tile attributions, re-measured `archive_lag`.
5. **M-D5 (optional) Native-JS plots.** `samples.json` per event + a d3/canvas interactive lune.

### Other project pages — 🔭

- **Cosmology SBI** page: write-up + figures + (optional) a small interactive.
- **Diffusion climate-downscaling** page: write-up + before/after super-resolution viewer.
- A reusable "project detail" template (per-collection-entry route) so each project gets a full
  page, not just a card.

### Polish — 🔭

- Buy + wire a custom domain on Vercel.
- Real CV PDF + content; real bio, photo, publication links.
- Optional dark-mode toggle (tokens are already namespaced for it).
- OG image per page; analytics (privacy-friendly, e.g. Plausible) if wanted.

---

## 11. Tech stack summary

- **Astro** (static output) + **@astrojs/react** islands, **TypeScript** (strict).
- **MapLibre GL JS** + **OpenFreeMap** tiles for the map.
- Self-hosted **Fontsource** variable fonts (Inter, Newsreader).
- **Prettier** + **ESLint** (flat config, typescript-eslint + astro + react-hooks) + **astro check**.
- **Vercel** for hosting; **GitHub Actions** (future) for the inference worker.
- Content via **Astro content collections** (`src/content/`).
- **Future worker:** Python — **HinetPy** (F-net fetch, code `0103`) + `win32tools` (WIN32→SAC),
  **ObsPy** (`obspy.io.nied.fnetmt` reference MTs), **`seismo_sbi`** + PyTorch (NPE inference,
  ~seconds/event on CPU), on **GitHub Actions cron** with a stateful `state.json`.

```

```
