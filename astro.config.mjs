// @ts-check
import { defineConfig } from 'astro/config';

import react from '@astrojs/react';

// https://astro.build/config
export default defineConfig({
  site: 'https://alex-saoulis.vercel.app',
  // Prefetch links on hover/viewport for instant navigation.
  prefetch: { prefetchAll: true, defaultStrategy: 'viewport' },
  integrations: [react()],
});
