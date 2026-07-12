---
title: 'Machine learning on a live particle accelerator'
blurb: 'Time-series anomaly detection and Bayesian-optimisation beam tuning on a live particle accelerator, deployed to production with CI/CD.'
summary: 'Before the PhD, two years developing machine learning in production at a national particle-accelerator facility: detecting anomalies in live signals and supporting beam tuning.'
status: 'in-progress'
area: 'timeseries'
metric: { value: '2 years', label: 'of ML in production at a national facility' }
bullets:
  [
    'Real-time anomaly detection on the continuous signals of the ISIS 800 MeV proton synchrotron.',
    'Surrogate models and Bayesian optimisation to support faster tuning of the accelerator.',
    'Developed and maintained as production software: Docker, CI/CD, C++ and Python, running against a live control system.',
  ]
figure: '/figures/accelerator-surrogate.png'
figureCaption: 'Measured accelerator beam signals (left) against generative surrogate-model reconstructions (cVAE and GAN). From the ISIS surrogate-modelling paper.'
tags: ['Anomaly detection', 'Bayesian optimisation', 'Surrogate models', 'Production ML']
links:
  [
    {
      label: 'Paper (ICALEPCS 2021)',
      href: 'https://proceedings.jacow.org/icalepcs2021/papers/frbl01.pdf',
    },
    {
      label: 'Paper (IPAC 2022)',
      href: 'https://proceedings.jacow.org/ipac2022/papers/tupopt057.pdf',
    },
  ]
order: 5
featured: true
href: '/projects/timeseries-anomaly/'
year: '2022'
---

A particle accelerator is a large, complex machine that must stay within specification around the
clock. Two years at ISIS/STFC went into machine learning to support that.

One strand monitored the accelerator’s live signals and detected anomalies as they appeared.
Another developed surrogate models and Bayesian optimisation for beam tuning, standing in for slow
physics simulations so that operators could search settings quickly. All of it ran in production
against a live control system.
