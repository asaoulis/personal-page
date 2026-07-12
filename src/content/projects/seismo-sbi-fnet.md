---
title: 'Live earthquake monitor: Japan'
blurb: 'Machine learning that characterises earthquake sources from their seismic waveforms with calibrated uncertainties, running live on the Japan seismic network.'
summary: 'A live, map-based monitor of the Japan (F-net) region. For each resolvable earthquake, deep-learning models embed the recorded waveforms and infer the source mechanism from them, together with a calibrated estimate of the uncertainty.'
status: 'live'
area: 'seismology'
metric: { value: '<1 s', label: 'to a full source solution with calibrated uncertainty' }
bullets:
  [
    'Standard analysis assumes Gaussian errors and can underestimate uncertainty by up to three times. This model learns the error distribution from the data.',
    'It returns a full posterior distribution over the source parameters, showing what the data does and does not constrain.',
    'A scheduled worker monitors the catalogue, runs the model on each new event, and precomputes the result, so the viewer remains responsive without a model server in the request path.',
  ]
figure: '/figures/earthquake.png'
figureCaption: 'Waves from one earthquake recorded across a network of seismometers.'
tags: ['Simulation-based inference', 'Normalising flows', 'PyTorch', 'Seismology']
links:
  [
    { label: 'Open the live monitor', href: '/demo/' },
    { label: 'Paper (GJI 2025)', href: 'https://arxiv.org/abs/2410.23238' },
    { label: 'Code', href: 'https://github.com/asaoulis/seismo-sbi' },
  ]
order: 1
featured: true
href: '/demo/'
year: '2026'
---

The model is a probabilistic deep learning network: it learns to map recorded waveforms to the
distribution of earthquake sources that could have produced them. Trained once on simulated
earthquakes, it then infers a new event in a fraction of a second.

The live monitor applies this to real data. It follows the F-net catalogue, runs the model on
each resolvable event (around magnitude 3.5 to 6.0), and compares the result with the official
catalogue solution: beachball, source-type lune, and the spread of the posterior. Each result is
served as a small file, so the viewer remains responsive.
