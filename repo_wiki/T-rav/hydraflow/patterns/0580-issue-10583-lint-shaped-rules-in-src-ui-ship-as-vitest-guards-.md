---
id: 0580
topic: patterns
source_issue: 10583
source_phase: plan
created_at: 2026-07-26T02:28:58.639370+00:00
status: active
corroborations: 1
---

# Lint-shaped rules in src/ui ship as vitest guards, not eslint plugins

Since `src/ui` has no eslint config, repo-wide style rules (like banning `border` shorthand next to a per-side longhand) are enforced as a vitest test that walks the source tree at run time, e.g. `src/ui/src/test/__tests__/borderShorthandScan.test.js`. `make quality` and CI already invoke vitest via `src/ui/scripts/run-vitest.cjs`, so this pattern needs no new tooling wiring — just a new test file.

**Why:** avoids introducing a parallel lint pipeline; keeps enforcement inside the existing `make quality` gate that's already load-bearing per CLAUDE.md.
