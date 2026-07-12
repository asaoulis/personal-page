---
title: 'Cosmological inference from few simulations'
blurb: 'Deep-learning data compression and probabilistic modelling to estimate the dark matter and dark energy in the universe, with transfer learning cutting simulation costs by an order of magnitude.'
summary: 'Measuring what the universe is made of means comparing observations against expensive simulations. Here, deep networks compress the data into informative summaries and model the resulting probability distributions, while transfer learning from cheap approximate simulations reduces the accurate simulations, and with them the training cost, by an order of magnitude.'
status: 'in-progress'
area: 'cosmology'
metric: { value: '8–15×', label: 'lower simulation and training cost' }
bullets:
  [
    'Pre-training on cheap, approximate simulations, then fine-tuning on a small number of accurate ones, transfers what the network has learned.',
    'On the CAMELS dataset, this reduced the accurate training simulations required by eight to fifteen times.',
    'Extended to field-level weak-lensing analysis, it produces well-calibrated cosmological posteriors from as few as 60 to 100 accurate simulations, an order of magnitude fewer than usual.',
  ]
figure: '/figures/cosmology-overview.png'
figureCaption: 'Pre-training on around 10,000 cheap approximate simulations, then fine-tuning on fewer than 100 accurate N-body simulations. Figure from the field-level weak-lensing paper.'
tags: ['Transfer learning', 'Simulation-based inference', 'Neural compression', 'Weak lensing']
links:
  [
    { label: 'Transfer learning paper (MNRAS 2025)', href: 'https://arxiv.org/abs/2505.21215' },
    { label: 'Field-level paper (2026)', href: 'https://arxiv.org/abs/2606.23346' },
  ]
order: 2
featured: true
href: '/projects/cosmology-sbi/'
year: '2025'
---

The bottleneck in this analysis is simulation cost. Inferring parameters such as the matter
density requires comparing data against many simulated universes, and the physically accurate
simulations (with gas, stars, and feedback) are expensive to produce.

The approach exploits fidelity. The network is first trained on many cheap, dark-matter-only
simulations to learn the general structure of the problem, then fine-tuned on a few accurate ones.
The same idea extends to field-level analysis, where the network processes a full lensing map
rather than a set of summary statistics, and still recovers well-calibrated posteriors from under
100 accurate simulations.
