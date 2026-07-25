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
    // three pytest processes (see Makefile `quality` target), so individual
    // tests can be starved well past vitest's 5000ms default even though
    // they run in ~50ms standalone. Raise the default so CPU contention from
    // sibling quality-gate jobs doesn't flake whichever test happens to be
    // running when the machine is busiest (#10489).
    testTimeout: 20000,
  },
})
