/**
 * Central site configuration.
 *
 * NOTE: Several fields below are realistic PLACEHOLDERS (marked `TODO`). Swap in
 * real content when ready — every page reads from here, so one edit propagates.
 */

export const SITE = {
  /** Canonical URL — TODO: update to the custom domain once added on Vercel. */
  url: 'https://personal-page.vercel.app',
  title: 'Alex Saoulis',
  /** TODO: confirm exact title/affiliation. */
  role: 'Computational Seismologist · Machine-Learning Researcher',
  affiliation: 'University College London',
  tagline:
    'Simulation-based inference for fast, well-calibrated earthquake source characterisation.',
  description:
    'Alex Saoulis — computational seismologist and ML researcher building simulation-based inference for earthquake source characterisation, with applications across cosmology and climate.',
  locale: 'en',
} as const;

/** Primary navigation (order matters). */
export const NAV: { label: string; href: string }[] = [
  { label: 'About', href: '/about/' },
  { label: 'Projects', href: '/projects/' },
  { label: 'Live Demo', href: '/demo/' },
  { label: 'CV', href: '/cv/' },
  { label: 'Contact', href: '/contact/' },
];

/**
 * Email is stored split so it is never emitted as a single plaintext string in
 * the built HTML (basic scraper hygiene). Reassemble at the call site.
 */
export const EMAIL = { user: 'a.saoulis', domain: 'ucl.ac.uk' } as const;

export type Social = {
  label: string;
  href: string;
  icon: 'github' | 'scholar' | 'orcid' | 'linkedin' | 'email';
};

/** Social / professional links. TODO: fill in real Scholar / ORCID / LinkedIn URLs. */
export const SOCIALS: Social[] = [
  { label: 'GitHub', href: 'https://github.com/asaoulis', icon: 'github' },
  { label: 'Google Scholar', href: 'https://scholar.google.com/', icon: 'scholar' }, // TODO
  { label: 'ORCID', href: 'https://orcid.org/', icon: 'orcid' }, // TODO
  { label: 'LinkedIn', href: 'https://www.linkedin.com/', icon: 'linkedin' }, // TODO
];
