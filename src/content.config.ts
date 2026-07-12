import { defineCollection } from 'astro:content';
import { z } from 'astro:schema';
import { glob } from 'astro/loaders';

/**
 * `projects` content collection — each Markdown file in src/content/projects/
 * is one project. The homepage gallery + project detail pages read `data`; the
 * Markdown body renders as the "how it works" prose on the detail page.
 */
const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/projects' }),
  schema: z.object({
    title: z.string(),
    /** Plain one-liner for the gallery tile. */
    blurb: z.string(),
    /** 1-2 sentence plain-language summary for the top of the detail page. */
    summary: z.string().optional(),
    status: z.enum(['live', 'in-progress', 'coming-soon', 'planned']),
    /** Which strand of work — drives the accent tint. */
    area: z
      .enum(['seismology', 'cosmology', 'climate', 'ocean', 'timeseries'])
      .default('seismology'),
    /** One honest headline number, quoted from a paper. */
    metric: z.object({ value: z.string(), label: z.string() }).optional(),
    /** Plain-language bullets (what the ML does + why it matters). */
    bullets: z.array(z.string()).default([]),
    /** Public path to the hero figure, e.g. /figures/earthquake.png */
    figure: z.string().optional(),
    figureCaption: z.string().optional(),
    /** Method tags shown lower down (the precise terms live here). */
    tags: z.array(z.string()).default([]),
    /** Outbound links: papers, code, demo. */
    links: z.array(z.object({ label: z.string(), href: z.string() })).default([]),
    order: z.number().default(99),
    /** Internal route or external URL; omit for a non-clickable stub card. */
    href: z.string().optional(),
    featured: z.boolean().default(false),
    year: z.string().optional(),
  }),
});

export const collections = { projects };
