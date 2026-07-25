import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    // Browser scenario specs run under Playwright via `make scenario-browser`,
    // never via vitest. Expanding this glob if we add subdirs is intentional.
    exclude: ['e2e/**/*.spec.js', 'node_modules/**'],
    // `make quality` runs this suite concurrently with pyright, bandit, and
    // three pytest processes — one of them `pytest -n auto`, which saturates
    // every core (Makefile `quality` target). The root cause of the flake
    // (#10508) is CPU contention, not a genuinely slow test: `SystemPanel`
    // passes in ~5s standalone. So the primary fix is to stop Vitest from
    // fighting `pytest -n auto` for cores by capping its own worker pool to
    // half the available CPUs, rather than blanket-inflating the timeout
    // (which masks contention for every test and slows detection of tests
    // that are genuinely hung). `maxWorkers` accepts a percentage string in
    // Vitest 4 and maps to whichever `pool` is active. (Vitest 4 has no
    // top-level `minWorkers`, so there's nothing to pin the floor with.)
    maxWorkers: '50%',
    // A modest safety margin over the 5000ms default absorbs residual jitter
    // from the remaining sibling jobs without reverting to the 20000ms mask.
    testTimeout: 10000,
    hookTimeout: 10000,
  },
})
