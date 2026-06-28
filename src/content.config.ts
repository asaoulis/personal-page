import { defineCollection } from 'astro:content';
import { z } from 'astro:schema';
import { glob } from 'astro/loaders';

/**
 * `projects` content collection — each Markdown file in src/content/projects/
 * is one project. The Projects index + cards read `data`; the body is available
 * for future per-project detail pages.
 */
const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/projects' }),
  schema: z.object({
    title: z.string(),
    blurb: z.string(),
    status: z.enum(['live', 'in-progress', 'coming-soon', 'planned']),
    tags: z.array(z.string()).default([]),
    order: z.number().default(99),
    /** Internal route or external URL; omit for a non-clickable stub card. */
    href: z.string().optional(),
    featured: z.boolean().default(false),
    year: z.string().optional(),
  }),
});

export const collections = { projects };
