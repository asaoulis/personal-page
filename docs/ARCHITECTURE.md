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

---

## 5. Reuse map — how the demo leans on `seismo_sbi`

The worker imports the author's research library (`seismo-sbi`) and serves what it already
produces. Verified entry points:

| Need                                  | `seismo_sbi` API                                                                                | Notes                                                                           |
| ------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Rebuild NPE from a checkpoint         | `evaluation/inference.py` → `build_eval_pipeline`, `build_ml_posterior(ckpt_dir, pipeline)`     | Flow sampling is the cheap part (CPU).                                          |
| Ingest a fetched observation          | `evaluation/inference.py` → `load_real_observation`                                             | Undoes receiver time shifts, etc.                                               |
| Posterior MT samples (physical units) | `evaluation/inference.py` → `recovered_mt_samples(inv) → (n,6)`                                 | Feeds lune + beachball.                                                         |
| Source-type lune plot                 | `plotting/lune.py` (`mts6_to_gamma_delta`, `plot_scatter_on_lune`, `plot_kde_contours_on_lune`) | Worker renders the **lune PNG** (catalogue MT vs model cloud).                  |
| Beachball + Kagan comparison          | `evaluation/moment_tensor.py` → `pyrocko_mt(m6)`, `kagan(a,b)`                                  | GCMT up-south-east convention (no Mrp/Mtp flip since the 2026-06-13 fix).       |
| Catalogue-wide visual style           | `scripts/santorini_pathbreaker/lomax_catalogue/catalogue_map.py`, `posterior_gallery.py`        | Reference for beachball-map + posterior panels (size∝Mw, colour=source-type γ). |

**Plotting strategy.** Basemap/cartopy/pyrocko are heavy and Python-only. v1 demo visuals are
therefore **server-rendered PNGs** produced by the existing code (least effort, exactly matches
the published figures). A later enhancement is a **native-JS lune** (d3/canvas) reading a
`samples.json` for interactive hover/zoom — but PNG-first is the right starting point.

---

## 6. Catalogue & waveform sources

The worker needs (a) a **catalogue feed** to detect new events and (b) **waveforms** to run
inference. Options, in rough order of latency/coverage trade-off:

- **USGS FDSN** (`earthquake.usgs.gov`, `service.iris.edu`) — global, easy, low-latency event
  feed; good for the _detector_.
- **JMA** — authoritative for Japan; richer regional catalogue.
- **NIED F-net** — the target network for waveforms and the reference MT catalogue; requires a
  **registered account, re-registered periodically** (a known operational chore — see Risks).

A pragmatic split: detect events via USGS/JMA (fast, keyless), fetch F-net waveforms + reference
MTs for the actual inference and the catalogue-vs-model comparison.

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

---

## 10. Roadmap

Each milestone is independently shippable.

### Site (stage-1) — ✅ done

Repo + tooling, design system, content pages, `/demo` preview, this doc, Vercel deploy.

### Flagship demo — 🔭

1. **M-D1 Worker skeleton.** GitHub Actions cron + a Python entrypoint that polls USGS/JMA for
   new Japan M≥3.5 events and writes/updates `events.json` (no inference yet — wire the contract).
2. **M-D2 Inference.** Plug in the trained F-net NPE checkpoint + Green's-function DB; for each new
   event fetch waveforms, run `seismo_sbi` inference, render lune + beachball PNGs, commit results.
3. **M-D3 Catalogue comparison.** Fetch F-net reference MTs; compute + display the Kagan angle and
   overlay catalogue vs model on the lune.
4. **M-D4 Retention + robustness.** Rolling window pruning, auth-refresh handling, alerting on
   worker failure, attributions.
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

```

```
