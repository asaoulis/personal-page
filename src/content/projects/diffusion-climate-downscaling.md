---
title: 'Downscaling climate projections to local rainfall'
blurb: 'Generative diffusion models that turn coarse climate projections into high-resolution local rainfall fields, with uncertainty.'
summary: 'Global climate models run on a coarse grid, too coarse to resolve local extremes. Diffusion models learn to add the fine-scale detail, generating an ensemble of plausible high-resolution rainfall fields rather than a single smoothed average.'
status: 'in-progress'
area: 'climate'
metric: { value: 'Continental US', label: 'delivered in six months' }
bullets:
  [
    'Diffusion models outperform conventional statistical downscaling on climate variables, giving a stronger baseline for probabilistic downscaling.',
    'Because the model is generative, it produces a distribution of possible local outcomes, which is what flood-risk assessment requires.',
    'Developed during consulting work at Fathom on ERA5 and MSWEP data, and delivered at continental-US scale within a six-month timeline. The underlying paper is under review at JGR.',
  ]
figure: '/figures/downscaling-precip.png'
figureCaption: 'Observed rainfall (top) against independent samples from the diffusion model.'
tags: ['Diffusion models', 'Super-resolution', 'Generative ML', 'Climate']
links:
  [
    {
      label: 'Preprint (JGR under review)',
      href: 'https://essopenarchive.org/doi/full/10.22541/essoar.173869444.40681416/v1',
    },
    { label: 'Code', href: 'https://github.com/asaoulis/diffusion-downscaling' },
  ]
order: 3
featured: true
href: '/projects/diffusion-climate-downscaling/'
year: '2025'
---

Climate projections are inherently coarse. A single grid cell can span tens of kilometres, which
smooths out the local extremes that matter most for flooding.

A conditional diffusion model learns the statistics of high-resolution rainfall and, given a
coarse input, generates fine-scale fields consistent with it. Repeated sampling produces an
ensemble, giving a calibrated range of local outcomes rather than a single estimate. The system
ran at continental scale on reanalysis data during a six-month consulting engagement.
