# Data scoping — F-net stations, data & reference catalogues (M-D2 prep)

> Scoping pass for the live-demo data pipeline (the inputs the real NPE inference, M-D2, will
> need). **This is a plan for a NEW agent/task to execute — no downloader is built yet.** It
> records what's reusable from the `seismo-sbi` repo, the empirical F-net access reality, and an
> autonomous plan to build the target station list, fetch a month of data, and attach multiple
> reference solutions. Grounded 2026-06-28.

---

## 0. Framing (read first)

**The station set must be the stations NIED routinely uses for F-net moment-tensor / earthquake
monitoring — the operationally-trusted, most-reliable ones — NOT merely whatever is convenient to
download.** Concretely:

- **F-net (NIED's "Full Range Seismograph Network") _is_ the network behind the routine Japanese
  regional MT catalogue.** So "best stations" ⇒ a well-distributed, high-uptime subset of the
  **F-net broadband stations themselves**. Selecting from F-net = selecting from the trusted set.
- **Primary path: F-net via HinetPy.** The user **has an F-net/NIED account** and can install
  **HinetPy + `win32tools`**. The agent should target F-net directly.
- **IRIS FDSN is a convenience fallback / cross-check only** (see §2.3) — it does **not** serve
  F-net and its Japan coverage is a different, sparser station set. Do not let "available on IRIS"
  drive the selection.
- The chosen geometry is the **training geometry**: it determines the Green's-function databases
  and the NPE training (§4). Fix the station list **before** building GF DBs / training.
- Per event, attach **every available reference MT** (F-net MT + GCMT + USGS …) for the multi-
  solution lune/beachball view (§3, §5).

---

## 1. What the `seismo-sbi` repo gives us (reusable)

The repo's **preprocessing, QA, HDF5 export, and reference-overlay plotting are fully reusable**;
only the **download layer** needs a Japan/F-net adapter.

| Component                       | File(s)                                                                                               | Reuse for F-net                                                                                                                          |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Waveform download               | `scripts/custom_download.py` (obspy FDSN `MassDownloader`, `--providers` configurable)                | **Only for the IRIS fallback.** NIED is not FDSN → can't fetch F-net. Need a HinetPy adapter.                                            |
| Preprocess (resp/filter/resamp) | `src/seismo_sbi/data_handling/preprocessing/{daily,processing}.py`                                    | **Fully reusable** once mseed + StationXML are in the standard `{station}/{YYYY.DDD}/` layout.                                           |
| Per-station QA                  | `…/preprocessing/quality.py` (completeness ≥90%, flatness, RMS floor, all-zero/NaN)                   | **Fully reusable**; per-event, drops bad traces individually.                                                                            |
| Catalogue → HDF5                | `…/preprocessing/{catalogue,sbi_export}.py` (`build_event_catalogue`, `export_to_sbi_h5`)             | **Fully reusable.** h5 schema: channel keys `Z/1/2`, length `compute_data_vector_length+1`, `/misc` autocorr. Needs a QuakeML catalogue. |
| CLI catalogue builder           | `scripts/build_catalogue.py`                                                                          | Reusable; point it at local mseed + StationXML + a Japan QuakeML.                                                                        |
| Station list format             | `STA NET lat lon` (`read_stations_file`)                                                              | Network code is used in the FDSN query; for F-net use `BO` (FDSN) / `0103` (NIED win).                                                   |
| Reference-MT overlay (science)  | `src/seismo_sbi/plotting/` (`extra_references` dict → distinct markers; `unified_reference_mts.json`) | **The multi-reference pattern already exists** (Zahradník/Lentas/Fountoulakis). Mirror it for F-net/GCMT/USGS in the web viz.            |

There is **no existing global "pick the best N stations" routine** — QA is per-event. The new task
adds an autonomous station-selection step (§2.2). There is **no NIED/HinetPy/win32 code anywhere**
in the repo (grepped) — the download adapter is genuinely new.

---

## 2. Stations — the target list

### 2.1 F-net (the real target)

- F-net is ~**73 broadband stations** (STS-1/STS-2) across Japan; FDSN network code **`BO`**, NIED
  win network code **`0103`**. It is the network used for the routine F-net MT catalogue → its
  stations are the operationally-reliable set.
- **Access:** **HinetPy** (NIED Hi-net/F-net client; **not installed** — `pip install HinetPy`),
  authenticated with the NIED account; continuous data comes as **WIN32**, converted to SAC/mseed
  with **`win32tools`** (`catwin32`, `win2sac_32`). Request times are **JST (UTC+9)** — convert
  carefully. Batch one request per event over all stations.
- **"Which stations does NIED use for MT?"** — _not_ in the catalogue: the F-net MT record
  (read by `obspy.io.nied.fnetmt`) exposes `variance_reduction` but **no per-event station list**.
  So operational reliability is established by **F-net membership + measured uptime/quality**
  (§2.2), optionally refined by any NIED documentation of the F-net MT station configuration. The
  agent should look for, but not depend on, such a doc.

### 2.2 Autonomous selection criterion (the key step)

Pick **~20** F-net stations maximising, in priority order:

1. **Operational reliability** — high data completeness/uptime over the target month (measured),
   low gaps, clean response metadata. Prefer canonical, long-running F-net broadband sites.
2. **Azimuthal / geographic coverage** — well spread Hokkaido → Tohoku → Honshu → Shikoku →
   Kyushu + the offshore islands, so events anywhere in the region are well-surrounded. (Coverage
   is ultimately _per event_; a geographically even national subset approximates it.)
3. **Redundancy avoidance** — don't pick co-located pairs.

Concretely the agent should: enumerate F-net stations (HinetPy) → measure availability/quality over
the month → run a coverage-greedy (or octant-balanced) selection subject to an availability floor →
emit `scripts/configs/japan/stations.txt` + a QA report (per-station uptime, a coverage map). The
selection must be **reliability-first**, documented, and reproducible.

### 2.3 IRIS fallback / cross-check (NOT the target)

Empirically (IRIS FDSN, Japan bbox, 2024-05 month, BH?/HH?, 2026-06-28):

- **F-net (`BO`) is NOT served by IRIS** — metadata _and_ waveform requests return **HTTP 204
  (no data)**. NIED is not in obspy's FDSN registry. → F-net cannot be reached via the existing
  FDSN downloader.
- IRIS _does_ serve **25 broadband stations** in the bbox: **JP network (16, nationwide)** + GSN
  (`IU MAJO`, `II ERM`, `G INU`, `PS TSK`) + edge (`KS` Korea, `IC MDJ` China, `IM MJAR` array).
  These are downloadable with `custom_download.py` **unchanged** and make a viable **fallback** if
  F-net is ever blocked — but they are **not** the F-net operational set, so use only as a
  cross-check or stopgap. (Full candidate table: `iris_japan_candidates.csv` next to this doc.)

---

## 3. Reference MT catalogues (multiple per event)

Attach **all** that resolve an event; the science plotter already renders many references with
distinct markers (star/square/triangle/pentagon).

| Catalogue                   | Coverage / floor         | Access                                                                                                                                                  |
| --------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **F-net routine MT** (NIED) | Japan regional, ~Mw 3.5+ | `obspy.io.nied.fnetmt` **reads** the format (present). Retrieve from the F-net site (search/grid); verify bulk access + account. THE primary reference. |
| **GCMT**                    | Global, ~M5.0+           | Monthly **NDK** from globalcmt.org (parseable), or **ISC** FDSN.                                                                                        |
| **USGS** (Mww/W-phase)      | Global, ~M4.5+           | USGS **FDSN** event products (reachable; returned Japan events in the probe).                                                                           |
| JMA (optional)              | Japan national           | JMA catalogue — secondary.                                                                                                                              |

→ The data task adds a **multi-reference fetcher** + the contract change in §5.

---

## 4. Prerequisites flagged (separate milestones — NOT this task)

These gate **real** inference (M-D2) and depend on the station geometry chosen above:

- **M-D0a — Japan 1-D velocity-model ensemble + Green's-function databases.** Build perturbed 1-D
  Japan Earth models and AxiSEM→Instaseis GF DBs for the **chosen F-net station geometry** (reuse
  `scripts/axisem/` — see that subsystem's README). **Blocked on the §2 station list** (the GF DBs
  are per-receiver-geometry).
- **M-D0b — NPE training.** Train the F-net neural posterior estimator on the GF-simulated dataset
  for that geometry (reuse `train_NPE.py` + the cluster). Output = the checkpoint M-D2 loads.

Until both land, the worker keeps the **mock** inference; everything else (selection, download,
preprocess, references, contract, viz) can proceed now.

---

## 5. Contract change: multiple references (v2.1)

The current per-event record has a single `reference`. Change to a **list** so every catalogue
solution is shown:

```jsonc
// events/<id>.json (added/changed fields)
"references": [
  { "source": "F-net", "gamma": …, "delta": …,
    "strike": …, "dip": …, "rake": …, "mt6": [Mrr,Mtt,Mpp,Mrt,Mrp,Mtp], "kagan_deg": … },
  { "source": "GCMT",  … },
  { "source": "USGS",  … }
]
```

- **Index** (`events.json`) stays compact: per feature keep `n_references` + a primary source +
  primary `kagan_deg`; the panel lazy-loads the full list.
- **Frontend (deferred to the data task):** `Lune.tsx` scatters **each** reference at its `(γ, δ)`
  with a **distinct marker + label** (mirror the science plotter's star/square/triangle/pentagon);
  `EventPanel` renders the **model beachball + one small labelled beachball per reference**
  (`Beachball.tsx` already takes strike/dip/rake). Keep the model posterior cloud as today.

---

## 6. Proposed task — `personal-page/fnet-data-sourcing` (autonomous milestones)

> A new tracked task. Each step is autonomous + leaves an artifact; reliability-first throughout.

- **S0 — Setup.** `pip install HinetPy`; build/cache `win32tools`; put NIED creds in the worker
  `.env` / GitHub Actions secrets (never committed). **Smoke:** list F-net (`0103`) stations.
- **S1 — F-net inventory.** Pull the F-net station list (codes, coords) via HinetPy; cross-check
  NIED's published F-net station status. → candidate pool (~73). Artifact: `fnet_stations_all.csv`.
- **S2 — Reliability QA over the target month** (autonomous). Measure per-station availability/
  uptime + basic quality (gaps, dead/flat) for the chosen month; rank. Artifact: `station_qa.csv`.
- **S3 — Operational selection** (autonomous, the crux). Choose ~20 maximising reliability (S2)
  then coverage (§2.2), avoiding co-location. Emit `scripts/configs/japan/stations.txt`
  (`STA BO lat lon`) + `station_selection_report.md` (uptime table + coverage map + criteria).
  **Must justify each pick as reliability/coverage-driven, not convenience.**
- **S4 — Download 1 month (F-net).** New `worker/fnet/fetch_fnet.py` (HinetPy): continuous F-net
  data for the 20 stations + StationXML/pole-zeros, WIN32→SAC→mseed into the repo's standard
  `{station}/{YYYY.DDD}/` layout. Then `scripts/build_catalogue.py` runs **unchanged**. _Fallback:_
  `custom_download.py --providers IRIS` for the JP/GSN subset.
- **S5 — Event catalogue.** Build a Japan QuakeML (M≥3.5, the month) from the F-net MT catalogue
  (`obspy.io.nied.fnetmt`) and/or USGS FDSN; feed `build_catalogue.py` → event + noise h5.
- **S6 — Multi-reference fetcher + contract v2.1.** Per event, gather F-net MT + GCMT + USGS →
  `references[]`; implement §5 (worker emit + frontend Lune multi-marker + multiple beachballs);
  regenerate the demo fixtures from real references where available.
- **S7 — Validate.** Reuse the repo QA + a coverage/availability report; sanity-plot a few events
  (model vs all references on the lune).

**Out of scope for this task:** the GF ensemble (M-D0a), NPE training (M-D0b), and real inference
(M-D2) — those follow once the geometry is fixed.

---

## 7. Open questions for the agent to resolve live

1. F-net MT **bulk retrieval** — does the F-net website allow programmatic catalogue download
   (with the account), or is it per-event grid search? (Confirm; `obspy.io.nied.fnetmt` only
   _parses_.)
2. Is there a **NIED-documented F-net MT station configuration** (the canonical subset/weights)? If
   so, prefer it as the reliability prior in S3.
3. Target **month** — pick one with good F-net uptime and a few M≥3.5 events for a lively demo.
4. **GCMT/USGS** convention handling when computing `(γ, δ)` + Kagan vs the model (reuse
   `evaluation/moment_tensor.py` conventions — note the 2026-06-13 no-flip fix).
