---
title: 'Real-time earthquake source inference'
blurb: "A live, map-based demo that monitors the Japan (F-net) region, runs simulation-based inference on resolvable events (~M≥3.5), and shows the model's moment-tensor posterior against catalogue solutions — beachballs, source-type lune, and uncertainty, all in the browser."
status: 'coming-soon'
tags: ['Simulation-based inference', 'Seismology', 'Moment tensors', 'PyTorch']
order: 1
featured: true
href: '/demo/'
year: '2026'
---

The cornerstone of this site: a neural posterior estimator trained to infer earthquake
moment tensors directly from waveforms, deployed as a continuously-updating regional monitor.
A scheduled worker watches the catalogue, runs CPU inference on each new resolvable event, and
publishes a compact, precomputed result — so the interactive viewer (map + diagnostic panels +
month-long time-slider) stays fast without a model server in the request path.

See `docs/ARCHITECTURE.md` for the full design. The live data pipeline is the next milestone;
the current `/demo` page previews the interface with representative mock data.
