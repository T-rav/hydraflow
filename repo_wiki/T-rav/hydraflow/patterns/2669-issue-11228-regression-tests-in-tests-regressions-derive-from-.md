---
id: 2669
topic: patterns
source_issue: 11228
source_phase: plan
created_at: 2026-08-15T07:17:21.034770+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Regression tests in tests/regressions/ derive from live tree, not snapshots

Regression pins under `tests/regressions/` must parse live source files rather than hardcoding expected values.

- Parse `optimizeDeps.include` from the actual `src/ui/vite.config.mjs`
- Regex `lazy(() => import('…'))` in live `src/ui/src` sources to find lazy boundaries
- Walk relative imports to build the lazy subtree; subtract eager-graph roots
- Assert ≥1 lazy boundary and non-empty lazy-only set so renames fail loudly, not vacuously

**Why:** Snapshot-style tests go stale on refactor and pass vacuously; deriving from the live tree keeps the pin coupled to the real invariant.
