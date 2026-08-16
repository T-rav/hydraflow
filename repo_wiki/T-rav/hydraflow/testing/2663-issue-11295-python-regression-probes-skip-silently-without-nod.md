---
id: 2663
topic: testing
source_issue: 11295
source_phase: plan
created_at: 2026-08-16T02:40:08.127239+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Python regression probes skip silently without node; vitest sibling mandatory

When `tests/regressions/test_*.py` drives a real `src/ui/src/operator/model/*.js` view-model via node + an ESM resolve hook, it calls `shutil.which("node")` and skips silently if absent. A node-less CI lane then reads green with zero coverage.

Always ship a vitest mirror under `src/ui/src/operator/model/__tests__/*.regression.test.js` covering identical behaviors. The vitest layer runs in `UI_TEST_CMD` (`Makefile:525`) regardless of node availability.

**Why:** A silently-skipping python guard produces false-green coverage while the defect stays live in the codebase.
