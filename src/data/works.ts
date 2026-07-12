/**
 * The homepage "body of work" — each strand written for a technical layperson,
 * with numbered citation chips that link out to the real papers. The chips and
 * the references list below mirror how a paper reads: plain claims up top,
 * sources at the bottom. Numbers are assigned from the `references` order.
 */

export type Reference = {
  id: number;
  /** Short human label for the chip's title / references list. */
  label: string;
  /** Venue + year, shown in the references list. */
  venue: string;
  href: string;
};

/** Numbered once, reused by the chips. Order here = citation number. */
export const references: Reference[] = [
  {
    id: 1,
    label: 'Full-waveform earthquake source inversion with SBI',
    venue: 'Geophysical Journal International, 2025',
    href: 'https://arxiv.org/abs/2410.23238',
  },
  {
    id: 2,
    label: 'Moment tensors under Earth-structure uncertainty',
    venue: 'preprint, 2026',
    href: 'https://arxiv.org/abs/2603.18925',
  },
  {
    id: 3,
    label: 'Transfer learning for multifidelity SBI in cosmology',
    venue: 'MNRAS, 2025',
    href: 'https://arxiv.org/abs/2505.21215',
  },
  {
    id: 4,
    label: 'Field-level weak lensing with <100 simulations',
    venue: 'preprint, 2026',
    href: 'https://arxiv.org/abs/2606.23346',
  },
  {
    id: 5,
    label: 'Diffusion models for climate downscaling',
    venue: 'preprint, 2025 (JGR under review)',
    href: 'https://essopenarchive.org/doi/full/10.22541/essoar.173869444.40681416/v1',
  },
  {
    id: 6,
    label: 'Semantic segmentation for ocean-bottom seismometer data',
    venue: 'Seismica, 2026',
    href: 'https://doi.org/10.26443/seismica.v5i1.1821',
  },
  {
    id: 7,
    label: 'FathomDEM: an improved global terrain map using a hybrid vision transformer model',
    venue: 'Environmental Research Letters, 2025',
    href: 'https://doi.org/10.1088/1748-9326/ada972',
  },
];

export type Work = {
  /** One sentence leading with the ML method, layperson-readable. */
  text: string;
  /** Citation numbers (into `references`). */
  cite: number[];
  /** Link to the matching project page or demo; omitted for strands without a page. */
  project?: string;
};

export const works: Work[] = [
  {
    text: 'Machine learning for more accurate characterisation of earthquake sources from their seismic waveforms, with calibrated uncertainties, running live on the Japan seismic network.',
    cite: [1, 2],
    project: '/demo/',
  },
  {
    text: 'Deep-learning data compression and probabilistic modelling to estimate the dark matter and dark energy content of the universe, with transfer learning reducing training costs by an order of magnitude.',
    cite: [3, 4],
    project: '/projects/cosmology-sbi/',
  },
  {
    text: 'Generative diffusion models that turn coarse climate projections into high-resolution local rainfall fields, at continental scale.',
    cite: [5],
    project: '/projects/diffusion-climate-downscaling/',
  },
  {
    text: 'Semantic segmentation for tracking ocean currents and detecting whale calls across an ocean seismic array, enabling automated tracking of individual whales and measurement of tidal currents from the seafloor.',
    cite: [6],
    project: '/projects/ocean-segmentation/',
  },
  {
    text: 'Time-series anomaly detection and Bayesian-optimisation beam tuning on a live particle accelerator, deployed to production with CI/CD at a national research facility.',
    cite: [],
    project: '/projects/timeseries-anomaly/',
  },
  {
    text: 'Time-series forecasting and imputation with diffusion models on athlete health and performance data, and classification with deep-learning ensembles.',
    cite: [],
  },
  {
    text: 'Further applications: correcting the global terrain map with a hybrid CNN and vision-transformer model, and generative modelling of Earth-systems observations, super-resolving satellite imagery of Arctic sea ice.',
    cite: [7],
  },
];
