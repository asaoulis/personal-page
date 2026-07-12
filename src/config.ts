/**
 * Central site configuration. Every page reads from here, so one edit propagates.
 */

export const SITE = {
  /** Canonical URL — update to the custom domain once added on Vercel. */
  url: 'https://alex-saoulis.vercel.app',
  title: 'Alex Saoulis',
  role: 'Machine learning for science',
  affiliation: 'University College London',
  tagline:
    'Deep learning for Bayesian inference and generative modelling in the physical sciences.',
  description:
    'Alex Saoulis develops machine learning for Bayesian inference and generative modelling, applied to problems in seismology, cosmology, and the climate sciences.',
  locale: 'en',
} as const;

/** Primary navigation (order matters). */
export const NAV: { label: string; href: string }[] = [
  { label: 'Work', href: '/#work' },
  { label: 'Earthquake monitor', href: '/demo/' },
  { label: 'CV', href: '/cv/' },
  { label: 'Contact', href: '/contact/' },
];

/**
 * Email is stored split so it is never emitted as a single plaintext string in
 * the built HTML (basic scraper hygiene). Reassemble at the call site.
 */
export const EMAIL = { user: 'alex.saoulis', domain: 'outlook.com' } as const;

export type Social = {
  label: string;
  href: string;
  icon: 'github' | 'scholar' | 'orcid' | 'linkedin' | 'email';
};

/** Social / professional links. */
export const SOCIALS: Social[] = [
  { label: 'GitHub', href: 'https://github.com/asaoulis', icon: 'github' },
  {
    label: 'Google Scholar',
    href: 'https://scholar.google.com/citations?user=u0kV3TAAAAAJ',
    icon: 'scholar',
  },
  { label: 'LinkedIn', href: 'https://www.linkedin.com/in/alex-saoulis', icon: 'linkedin' },
  { label: 'ORCID', href: 'https://orcid.org/0009-0005-1486-8681', icon: 'orcid' },
];
