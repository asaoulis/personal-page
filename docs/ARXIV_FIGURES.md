# arXiv figure placeholders

Figures pulled from Alex Saoulis's papers for use as portfolio placeholders. Each was extracted
from the arXiv HTML5 rendering (or, where unavailable, the PDF's embedded raster images) via
`curl`, then whitespace-trimmed and downscaled with ImageMagick `convert -trim -resize 1600x`.
All are confirmed clean, single-panel or self-contained multi-panel figures with no broken
rendering or truncated text.

## paper-cosmology.png

- **Paper**: Transfer learning for multifidelity simulation-based inference in cosmology
  (Saoulis, Piras, Jeffrey, Mancini, Ferreira) — arXiv:2505.21215
- **Figure**: Figure 2 (`figures/CNN_NDE_architecture.png`, id `S2.F2`)
- **Caption gist**: The CNN + normalizing-flow (RQ-NSF) neural posterior estimation
  architecture used throughout the paper — panel (a) shows the CNN summary-compression
  network, panel (b) shows the conditional spline-flow density estimator.
- **Why picked**: Clean, colourful, self-contained architecture diagram — no dense
  axis labels/whitespace issues, reads well at thumbnail size.

## paper-lensing.png

- **Paper**: Field-level weak lensing cosmology with <100 simulations using multifidelity
  simulation-based inference (Saoulis, Lin, Jeffrey, von Wietersheim-Kramsta, Piras) —
  arXiv:2606.23346
- **Figure**: Figure 1 (embedded raster image, extracted via `pdfimages` from the arXiv PDF —
  no arXiv HTML5 version exists for this ID)
- **Caption gist**: Graphical abstract of the multifidelity pipeline — cheap log-normal
  random-field sims (~10^4) and expensive N-body sims (<100) both feed the neural
  compression + density estimation network (pre-training vs fine-tuning), producing the
  final Ω_m–σ8 N-body posterior contours.
- **Why picked**: A single clean "graphical abstract" panel that explains the whole paper's
  method at a glance; no HTML5 source was available so this came from extracting embedded
  PDF images directly (`pdfimages -png`) and picking the largest/cleanest full-colour one.

## paper-seismo.png

- **Paper**: Full-waveform earthquake source inversion using simulation-based inference
  (Saoulis, Piras, Mancini, Joachimi, Ferreira) — arXiv:2410.23238
- **Figure**: Figure 3 (`extracted/6438654/Figures/sbi_cartoon.png`, id `S3.F3`)
- **Caption gist**: Diagram of the SBI workflow for earthquake source inversion — training
  (waveform compression + NDE fitting on sampled sources/forward-modelled data) vs inference
  (compress a new observation, evaluate the trained NDE, get posterior samples).
- **Why picked**: The most visually distinctive, self-contained figure in the paper — clean
  colour-coded training/inference workflow, reads well as a thumbnail. The lune/beachball
  posterior figures (e.g. Figure 10/11, `north_inversion_summary.png`,
  `madeira_inversion_summary.png`) were considered but are dense multi-panel corner plots
  with tightly packed sub-panels (lune + corner plot + waveform fits) that don't crop
  cleanly to a single panel without bleeding into neighbours — skipped in favour of the
  cartoon.

## paper-seismo-structure.png

- **Paper**: Improving moment tensor solutions under Earth structure uncertainty with
  simulation-based inference (Saoulis, Pham, Ferreira) — arXiv:2603.18925
- **Figure**: Figure 9 (`2603.18925v1/Figures/shallow_isotropic_lunes_lettered.png`)
- **Caption gist**: Inference results on 10 random artificial shallow-isotropic sources —
  each panel shows the recovered source-type lune (with ISO/CLVD/DC decomposition pie
  charts) comparing the SBI, Gaussian-likelihood and other inversion approaches against
  the true mechanism.
- **Why picked**: A clean, colourful, self-contained 2x5 grid of lune plots with legible
  pie-chart source-type breakdowns — exactly the "moment tensor under uncertainty" story
  the paper tells, and crops/trims to a tidy widescreen panel with no neighbouring bleed.

## Skipped

Nothing was skipped outright — all four target papers yielded a usable figure. Note that
arXiv:2606.23346 has no HTML5 rendering, so its figure came from the PDF's embedded images
rather than a direct `<img>` URL; this is the only one with a slightly different provenance
than the other three.
