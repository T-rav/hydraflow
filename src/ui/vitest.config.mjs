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
    // three pytest processes (Makefile `quality` target), which starves the
    // Node event loop badly enough that even synchronous tests can miss
    // Vitest's 5000ms default per-test timeout (#10515). Bumping a single
    // test's local waitFor timeout doesn't help — it's still bounded by this
    // outer timeout — so raise it globally instead of chasing individual
    // flaky tests one at a time.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
})
