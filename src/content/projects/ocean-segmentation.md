---
title: 'Semantic segmentation for whale calls and ocean currents'
blurb: 'Semantic segmentation that detects whale calls and ocean signals across an ocean seismic array, enabling automated whale tracking and measurement of tidal currents from the seafloor.'
summary: 'Ocean-bottom seismometers record a mixture of signals: instrument resonances, tidal currents, storms, and the calls of blue whales. This work treats their spectrograms as images and trains a semantic-segmentation model to label each signal, enabling automated tracking of individual whales and measurement of tidal currents from the seafloor.'
status: 'in-progress'
area: 'ocean'
metric: { value: '>90%', label: 'better detection of rare signals' }
bullets:
  [
    'A U-Net processes each spectrogram as an image and labels every pixel: whale call, instrument resonance, tidal signal, or noise.',
    'With only 500 manually annotated spectrograms, a synthetic pre-training step improved rare-feature detection by over 90 percent.',
    'The trained model enables automated tracking of individual blue whales from their calls, and measurement of tidal currents from the seafloor.',
  ]
figure: '/figures/whale-tracking.png'
figureCaption: 'A blue whale’s path reconstructed from its calls across an ocean-bottom array. From the segmentation paper.'
tags: ['Semantic segmentation', 'U-Net', 'Synthetic pre-training', 'Bioacoustics']
links: [{ label: 'Paper (Seismica 2026)', href: 'https://doi.org/10.26443/seismica.v5i1.1821' }]
order: 4
featured: true
href: '/projects/ocean-segmentation/'
year: '2026'
---

Ocean-bottom seismometers remain on the seafloor for months and record continuously. The signals
of interest, whale calls in particular, are rare and easily lost among everything else.

Converting each recording into a spectrogram turns this into an image-segmentation problem: the
network labels every pixel by its source. The main constraint is data, since manual annotation is
slow and rare features seldom appear. Pre-training on synthetic spectrograms first improved
rare-class detection by over 90 percent, enough to track individual whales from their calls and
to measure tidal currents directly from the seafloor recordings.
