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
    // `make quality` runs pyright, bandit, and three pytest invocations
    // alongside this vitest suite, all backgrounded in parallel (Makefile
    // `quality` target). Under that CPU contention, even purely synchronous
    // tests can blow past vitest's 5000ms default as the process gets
    // starved of scheduling time — not an actual hang. Raise the global
    // budget rather than patching one flaky test at a time.
    testTimeout: 20000,
  },
})
