import { defineConfig, mergeConfig } from 'vitest/config';

import viteConfig from './vite.config';

/**
 * The checks that need a running service.
 *
 * They are excluded from the default run because a check that skips when its
 * dependency is absent passes in CI without running — a green tick for
 * nothing, which reads as coverage and is worse than an honest gap. This
 * config is how they are asked for: `pnpm test:live`, with a service on
 * 127.0.0.1:8000.
 *
 * Built from `vite.config` rather than by merging `vitest.config`, because
 * `mergeConfig` concatenates `exclude` rather than replacing it — merging
 * would inherit the very exclusion this exists to lift.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/testSetup.ts'],
      include: ['**/*.live.test.ts'],
      exclude: ['**/node_modules/**', '**/dist/**'],
    },
  }),
);
