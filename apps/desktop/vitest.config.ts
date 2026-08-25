import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/testSetup.ts'],
      // `*.live.test.ts` needs a running service and is excluded from the
      // default run, which is what CI does. Included, it would pass in CI by
      // skipping — a green tick for a check that never ran, which is worse
      // than no check because it reads as coverage. Run it with
      // `pnpm test:live` against a service on 127.0.0.1:8000.
      exclude: ['**/node_modules/**', '**/dist/**', '**/*.live.test.ts'],
    },
  }),
);
